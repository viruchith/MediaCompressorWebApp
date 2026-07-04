import logging
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Optional, Set

from app import db
from app.config import config
from app.models import FileRecord
from app.utils.manifest import save_manifest_to_output_folder
from app.workers.image_worker import compress_image
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

    def start(self):
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
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

    def _dispatcher_loop(self):
        while self._running:
            try:
                self._dispatch_pending()
                self._emit_queue_counts()
            except Exception as e:
                logger.error("Dispatcher error: %s", e)
            self._shutdown_event.wait(2)

    def _dispatch_pending(self):
        with self._lock:
            active_count = len(self._active)
        max_fetch = (
            config.WORKER_COUNT_IMAGES + config.WORKER_COUNT_VIDEOS - active_count
        )
        if max_fetch <= 0:
            return

        pending = db.get_pending_files(limit=max_fetch)
        for file_rec in pending:
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
            file_rec = db.get_file(file_id)
            if not file_rec:
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
                db.mark_file_failed(file_id, "Input file not found")
                self._emit_progress(file_id, "error", "File not found", 100)
                return

            def progress_cb(pct: int, msg: str):
                self._emit_progress(file_id, "processing", msg, pct)

            output_path = file_rec.output_file_path or file_rec.input_file_path

            if file_rec.file_type == "image":
                result = compress_image(
                    file_rec.input_file_path,
                    output_path,
                    settings,
                    progress_callback=progress_cb,
                )
            else:
                result = compress_video(
                    file_rec.input_file_path,
                    output_path,
                    settings,
                    progress_callback=progress_cb,
                )

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
                    logger.warning("Failed to save manifest for job %d: %s", file_rec.job_id, e)

        except Exception as e:
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
