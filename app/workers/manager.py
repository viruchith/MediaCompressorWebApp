import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Set

from app import db
from app.config import config
from app.utils.manifest import save_manifest_to_output_folder
from app.workers.image_worker import compress_image
from app.workers.process_registry import ProcessRegistry
from app.workers.video_worker import compress_video

logger = logging.getLogger(__name__)


class WorkerManager:
    def __init__(self, socketio):
        self.socketio = socketio
        self._image_pool = ThreadPoolExecutor(
            max_workers=config.WORKER_COUNT_IMAGES,
            thread_name_prefix="img-worker",
        )
        self._video_pool = ThreadPoolExecutor(
            max_workers=config.WORKER_COUNT_VIDEOS,
            thread_name_prefix="vid-worker",
        )
        self._active: Set[int] = set()
        self._lock = threading.Lock()
        self._running = False
        self._dispatcher_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._cancel_event = threading.Event()
        self._process_registry = ProcessRegistry()

    def start(self):
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._cancel_event.clear()
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop,
            name="worker-dispatcher",
            daemon=True,
        )
        self._dispatcher_thread.start()
        logger.info(
            "Worker manager started (images=%d, videos=%d)",
            config.WORKER_COUNT_IMAGES,
            config.WORKER_COUNT_VIDEOS,
        )

    def stop(self, wait: bool = True):
        self._running = False
        self._shutdown_event.set()
        if self._dispatcher_thread:
            self._dispatcher_thread.join(timeout=5)
        self._image_pool.shutdown(wait=wait, cancel_futures=False)
        self._video_pool.shutdown(wait=wait, cancel_futures=False)
        logger.info("Worker manager stopped")

    def cancel_queue(self) -> dict:
        """Cancel all pending and in-progress work."""
        self._cancel_event.set()
        terminated = self._process_registry.terminate_all()
        cancelled_count = db.cancel_queue_files()
        time.sleep(0.5)
        self._cancel_event.clear()

        message = f"Queue cancelled. {cancelled_count} file(s) cancelled."
        if terminated:
            message += f" {terminated} active process(es) terminated."

        logger.info(message)
        payload = {"message": message, "cancelled": cancelled_count, "terminated": terminated}
        self.socketio.emit("queue_cancelled", payload)
        self._emit_queue_counts()
        return payload

    def clear_history(self) -> dict:
        """Stop active work and flush the entire database."""
        self.cancel_queue()
        time.sleep(0.3)
        removed = db.flush_database()
        self._cancel_event.clear()

        message = (
            f"History cleared. {removed} total record(s) removed. Database flushed."
        )
        logger.info(message)
        payload = {"message": message, "removed": removed}
        self.socketio.emit("history_cleared", payload)
        self._emit_queue_counts()
        return payload

    def _dispatcher_loop(self):
        while self._running:
            try:
                if not self._cancel_event.is_set():
                    self._dispatch_pending()
                self._emit_queue_counts()
            except Exception as e:
                logger.error("Dispatcher error: %s", e)
            self._shutdown_event.wait(2)

    def _dispatch_pending(self):
        if self._cancel_event.is_set():
            return

        with self._lock:
            active_count = len(self._active)
        max_fetch = (
            config.WORKER_COUNT_IMAGES + config.WORKER_COUNT_VIDEOS - active_count
        )
        if max_fetch <= 0:
            return

        pending = db.get_pending_files(limit=max_fetch)
        for file_rec in pending:
            if self._cancel_event.is_set():
                break

            with self._lock:
                if file_rec.id in self._active:
                    continue
                if not db.claim_file(file_rec.id):
                    continue
                self._active.add(file_rec.id)

            pool = (
                self._image_pool
                if file_rec.file_type == "image"
                else self._video_pool
            )
            pool.submit(self._process_file, file_rec.id)

    def _process_file(self, file_id: int):
        start_time = time.monotonic()
        try:
            if self._cancel_event.is_set():
                return

            file_rec = db.get_file(file_id)
            if not file_rec or file_rec.status == config.STATUS_CANCELLED:
                return

            image_settings, video_settings = db.get_job_settings(file_rec.job_id)
            settings = image_settings if file_rec.file_type == "image" else video_settings

            self._emit_progress(
                file_id,
                "processing",
                f"Processing {os.path.basename(file_rec.input_file_path)}",
                0,
            )

            if not os.path.exists(file_rec.input_file_path):
                if self._cancel_event.is_set():
                    return
                db.mark_file_failed(file_id, "Input file not found")
                self._emit_progress(file_id, "error", "File not found", 100)
                return

            def progress_cb(pct: int, msg: str):
                if not self._cancel_event.is_set():
                    self._emit_progress(file_id, "processing", msg, pct)

            def should_cancel() -> bool:
                return self._cancel_event.is_set()

            def on_process(proc):
                self._process_registry.register(file_id, proc)

            output_path = file_rec.output_file_path or file_rec.input_file_path

            try:
                if file_rec.file_type == "image":
                    result = compress_image(
                        file_rec.input_file_path,
                        output_path,
                        settings,
                        progress_callback=progress_cb,
                        should_cancel=should_cancel,
                    )
                else:
                    result = compress_video(
                        file_rec.input_file_path,
                        output_path,
                        settings,
                        progress_callback=progress_cb,
                        should_cancel=should_cancel,
                        on_process=on_process,
                    )
            finally:
                self._process_registry.unregister(file_id)

            if self._cancel_event.is_set():
                return

            file_rec = db.get_file(file_id)
            if not file_rec or file_rec.status == config.STATUS_CANCELLED:
                return

            out_path, inp_hash, out_hash, inp_size, out_size, ratio = result

            db.mark_file_completed(
                file_id, out_path, out_size, out_hash, inp_size, inp_hash, ratio,
            )

            elapsed = time.monotonic() - start_time
            logger.info(
                "File %d completed in %.1fs (ratio=%.2f)",
                file_id, elapsed, ratio,
            )

            self._emit_progress(
                file_id,
                "completed",
                f"Completed: {os.path.basename(file_rec.input_file_path)} "
                f"({ratio:.0%} of original)",
                100,
                extra={
                    "input_size": inp_size,
                    "output_size": out_size,
                    "compression_ratio": ratio,
                    "input_hash": inp_hash,
                    "output_hash": out_hash,
                },
            )

            job = db.get_job(file_rec.job_id)
            if job and job.status == "completed":
                try:
                    save_manifest_to_output_folder(file_rec.job_id)
                except Exception as e:
                    logger.warning(
                        "Failed to save manifest for job %d: %s", file_rec.job_id, e,
                    )

        except InterruptedError:
            logger.info("File %d processing interrupted (cancelled)", file_id)
            if not self._cancel_event.is_set():
                db.mark_file_cancelled(file_id)
                self._emit_progress(file_id, "cancelled", "Cancelled", 100)
        except Exception as e:
            if self._cancel_event.is_set():
                return
            file_rec = db.get_file(file_id)
            if file_rec and file_rec.status == config.STATUS_CANCELLED:
                return
            logger.error("Error processing file %d: %s", file_id, e)
            file_rec = db.get_file(file_id)
            permanent = False
            if file_rec and file_rec.retry_count + 1 >= file_rec.max_retries:
                permanent = True
            db.mark_file_failed(file_id, str(e), permanent=permanent)
            self._emit_progress(file_id, "error", str(e), 100)
        finally:
            with self._lock:
                self._active.discard(file_id)
            self._emit_queue_counts()

    def _emit_progress(
        self,
        file_id: int,
        status: str,
        message: str,
        percent: int,
        extra: Optional[dict] = None,
    ):
        payload = {
            "file_id": file_id,
            "status": status,
            "message": message,
            "percent": percent,
        }
        if extra:
            payload.update(extra)
        self.socketio.emit("progress_update", payload)

    def _emit_queue_counts(self):
        counts = db.get_queue_counts()
        self.socketio.emit("queue_counts", counts)
