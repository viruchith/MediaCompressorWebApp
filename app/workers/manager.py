import logging
import multiprocessing
import os
import queue
import shutil
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import Optional, Set

from app import db
from app.config import config
from app.utils.manifest import save_manifest_to_output_folder
from app.workers.image_worker import compress_image
from app.workers.process_registry import ProcessRegistry
from app.workers.video_worker import compress_video

logger = logging.getLogger(__name__)

# Minimum free disk space (in bytes) required before starting a compression job.
# Workers will skip files and report an error if available space falls below this.
# Configurable via MIN_FREE_DISK_MB environment variable (default: 100 MB).
MIN_FREE_DISK_BYTES = config.MIN_FREE_DISK_MB * 1024 * 1024

# Use 'spawn' start method for ProcessPoolExecutor to avoid inheriting
# the parent's SQLite connections and threading.local state via fork().
_MP_CONTEXT = multiprocessing.get_context("spawn")


class WorkerManager:
    def __init__(self, socketio, app):
        self.socketio = socketio
        self.app = app
        self._emit_queue: queue.SimpleQueue = queue.SimpleQueue()
        # Use ProcessPoolExecutor for images to bypass the GIL during
        # CPU-bound Pillow operations (each image compresses in its own process).
        # Uses 'spawn' context to avoid inheriting parent's DB connections.
        self._image_pool = ProcessPoolExecutor(
            max_workers=config.WORKER_COUNT_IMAGES,
            mp_context=_MP_CONTEXT,
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
        self._emit_thread: Optional[threading.Thread] = None
        # Event signalled when new files are added to the queue so the
        # dispatcher wakes immediately instead of waiting for the next poll.
        self._wake_event = threading.Event()

    def start(self):
        if self._running:
            return
        self._running = True
        self._shutdown_event.clear()
        self._cancel_event.clear()
        self._wake_event.clear()
        self._emit_thread = threading.Thread(
            target=self._emit_consumer_loop,
            name="socket-emit",
            daemon=True,
        )
        self._emit_thread.start()
        self._dispatcher_thread = threading.Thread(
            target=self._dispatcher_loop,
            name="worker-dispatcher",
            daemon=True,
        )
        self._dispatcher_thread.start()
        logger.info(
            "Worker manager started (images=%d [process pool], videos=%d [thread pool])",
            config.WORKER_COUNT_IMAGES,
            config.WORKER_COUNT_VIDEOS,
        )

    def stop(self, wait: bool = True):
        self._running = False
        self._shutdown_event.set()
        self._wake_event.set()  # Unblock dispatcher so it can exit
        if self._dispatcher_thread:
            self._dispatcher_thread.join(timeout=5)
        self._image_pool.shutdown(wait=wait, cancel_futures=True)
        self._video_pool.shutdown(wait=wait, cancel_futures=False)
        # Drain the emit queue so pending progress events are delivered
        if self._emit_thread and self._emit_thread.is_alive():
            self._emit_thread.join(timeout=3)
        logger.info("Worker manager stopped")

    def cancel_queue(self, resume_dispatch: bool = True) -> dict:
        """Cancel all pending and in-progress work.

        When resume_dispatch is False (used by clear_history), the cancel flag
        stays set so the dispatcher cannot claim new work until the caller clears it.
        """
        self._cancel_event.set()
        terminated = self._process_registry.terminate_all()
        cancelled_count = db.cancel_queue_files()
        time.sleep(0.5)
        if resume_dispatch:
            self._cancel_event.clear()

        message = f"Queue cancelled. {cancelled_count} file(s) cancelled."
        if terminated:
            message += f" {terminated} active process(es) terminated."

        logger.info(message)
        payload = {"message": message, "cancelled": cancelled_count, "terminated": terminated}
        self._emit("queue_cancelled", payload)
        self._emit_queue_counts()
        return payload

    def clear_history(self) -> dict:
        """Stop active work and flush the entire database."""
        self.cancel_queue(resume_dispatch=False)
        removed = db.flush_database()
        self._cancel_event.clear()

        message = (
            f"History cleared. {removed} total record(s) removed. Database flushed."
        )
        logger.info(message)
        payload = {"message": message, "removed": removed}
        self._emit("history_cleared", payload)
        self._emit_queue_counts()
        return payload

    def notify_new_files(self):
        """Signal the dispatcher to wake up and check for new pending files.

        Call this after adding files to the queue so the dispatcher picks
        them up immediately instead of waiting for the next 2-second poll.
        """
        self._wake_event.set()

    def _dispatcher_loop(self):
        while self._running:
            try:
                if not self._cancel_event.is_set():
                    self._dispatch_pending()
                    # Enforce PROCESSING_TIMEOUT_MINUTES on stuck workers
                    self._reap_timed_out_files()
                self._emit_queue_counts()
            except Exception as e:
                logger.error("Dispatcher error: %s", e)
            # Wait up to 2s, but wake immediately if new files arrive
            self._wake_event.wait(timeout=2)
            self._wake_event.clear()

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

            if file_rec.file_type == "image":
                # Images run in a ProcessPoolExecutor (separate processes)
                # to avoid GIL contention from CPU-bound Pillow work.
                # We wrap the call in a thread that submits to the process
                # pool and handles callbacks, since ProcessPoolExecutor
                # futures don't integrate with our emit queue directly.
                self._video_pool.submit(self._process_image_in_pool, file_rec.id)
            else:
                self._video_pool.submit(self._process_file, file_rec.id)

    def _reap_timed_out_files(self):
        """Watchdog: find files stuck in PROCESSING beyond the configured timeout.

        Terminates their associated ffmpeg processes (if any) and marks them
        for retry or permanent failure. Runs every dispatcher cycle.
        """
        timed_out = db.get_timed_out_files(config.PROCESSING_TIMEOUT_MINUTES)
        for file_rec in timed_out:
            logger.warning(
                "File %d timed out after %d minutes (started_at=%s)",
                file_rec.id,
                config.PROCESSING_TIMEOUT_MINUTES,
                file_rec.started_at,
            )
            # Terminate any ffmpeg subprocess associated with this file
            self._process_registry.terminate_by_id(file_rec.id)
            job_id = db.mark_file_timed_out(file_rec.id)

            with self._lock:
                self._active.discard(file_rec.id)

            self._emit_progress(
                file_rec.id,
                "error",
                f"Timed out after {config.PROCESSING_TIMEOUT_MINUTES} minutes",
                100,
                job_id=job_id,
            )

    @staticmethod
    def _check_disk_space(output_path: str) -> bool:
        """Check that there is enough free disk space at the output location.

        Returns True if sufficient space is available, False otherwise.
        Uses shutil.disk_usage on the output directory (or its closest
        existing parent) to determine free bytes.
        """
        check_dir = os.path.dirname(output_path) or "."
        # Walk up to an existing directory if the immediate parent doesn't exist yet
        while not os.path.exists(check_dir):
            parent = os.path.dirname(check_dir)
            if parent == check_dir:
                break
            check_dir = parent
        try:
            usage = shutil.disk_usage(check_dir)
            return usage.free >= MIN_FREE_DISK_BYTES
        except OSError:
            # If we can't determine disk space, allow the attempt
            return True

    def _ensure_terminal_on_cancel(self, file_id: int):
        """Move a stuck processing file to cancelled when cancellation is active."""
        if not self._cancel_event.is_set():
            return
        file_rec = db.get_file(file_id)
        if file_rec and file_rec.status == config.STATUS_PROCESSING:
            db.mark_file_cancelled(file_id)
            self._emit_progress(
                file_id, "cancelled", "Cancelled", 100, job_id=file_rec.job_id,
            )

    def _process_image_in_pool(self, file_id: int):
        """Submit image compression to the ProcessPoolExecutor.

        This wrapper runs in a video-pool thread so we can emit socket
        progress events (which require the main process). The actual
        Pillow work runs in a child process to bypass the GIL.
        """
        start_time = time.monotonic()
        try:
            if self._cancel_event.is_set():
                self._ensure_terminal_on_cancel(file_id)
                return

            file_rec = db.get_file(file_id)
            if not file_rec or file_rec.status == config.STATUS_CANCELLED:
                return

            image_settings, _ = db.get_job_settings(file_rec.job_id)
            job_id = file_rec.job_id
            output_path = file_rec.output_file_path or file_rec.input_file_path

            # Disk space pre-check before starting compression
            if not self._check_disk_space(output_path):
                db.mark_file_failed(file_id, "Insufficient disk space")
                self._emit_progress(
                    file_id, "error", "Insufficient disk space", 100, job_id=job_id,
                )
                return

            self._emit_progress(
                file_id, "processing",
                f"Processing {os.path.basename(file_rec.input_file_path)}",
                0, job_id=job_id,
            )

            if not os.path.exists(file_rec.input_file_path):
                db.mark_file_failed(file_id, "Input file not found")
                self._emit_progress(
                    file_id, "error", "File not found", 100, job_id=job_id,
                )
                return

            # Submit to process pool — no progress callback or cancellation
            # since these cannot cross process boundaries easily.
            future = self._image_pool.submit(
                compress_image,
                file_rec.input_file_path,
                output_path,
                image_settings,
            )
            result = future.result()  # blocks until child process finishes

            out_path, inp_hash, out_hash, inp_size, out_size, ratio = result

            db.mark_file_completed(
                file_id, out_path, out_size, out_hash, inp_size, inp_hash, ratio,
            )

            elapsed = time.monotonic() - start_time
            logger.info(
                "File %d completed in %.1fs (ratio=%.2f) [process pool]",
                file_id, elapsed, ratio,
            )

            self._emit_progress(
                file_id, "completed",
                f"Completed: {os.path.basename(file_rec.input_file_path)}",
                100,
                extra={
                    "input_size": inp_size,
                    "output_size": out_size,
                    "compression_ratio": ratio,
                    "input_hash": inp_hash,
                    "output_hash": out_hash,
                },
                job_id=job_id,
            )

            job = db.get_job(file_rec.job_id)
            if job and job.status == "completed":
                try:
                    save_manifest_to_output_folder(file_rec.job_id)
                except Exception as e:
                    logger.warning(
                        "Failed to save manifest for job %d: %s", file_rec.job_id, e,
                    )
            # Push job state to clients so UI updates without polling
            self._emit_job_update(file_rec.job_id)

        except InterruptedError:
            logger.info("File %d processing interrupted (cancelled)", file_id)
            file_rec = db.get_file(file_id)
            if file_rec and file_rec.status != config.STATUS_CANCELLED:
                db.mark_file_cancelled(file_id)
            jid = file_rec.job_id if file_rec else None
            self._emit_progress(file_id, "cancelled", "Cancelled", 100, job_id=jid)
        except Exception as e:
            if self._cancel_event.is_set():
                self._ensure_terminal_on_cancel(file_id)
                return
            file_rec = db.get_file(file_id)
            if file_rec and file_rec.status == config.STATUS_CANCELLED:
                return
            logger.error("Error processing image file %d: %s", file_id, e)
            file_rec = db.get_file(file_id)
            permanent = False
            if file_rec and file_rec.retry_count + 1 >= file_rec.max_retries:
                permanent = True
            db.mark_file_failed(file_id, str(e), permanent=permanent)
            jid = file_rec.job_id if file_rec else None
            self._emit_progress(file_id, "error", str(e), 100, job_id=jid)
        finally:
            with self._lock:
                self._active.discard(file_id)
            self._emit_queue_counts()

    def _process_file(self, file_id: int):
        start_time = time.monotonic()
        try:
            if self._cancel_event.is_set():
                self._ensure_terminal_on_cancel(file_id)
                return

            file_rec = db.get_file(file_id)
            if not file_rec or file_rec.status == config.STATUS_CANCELLED:
                return

            image_settings, video_settings = db.get_job_settings(file_rec.job_id)
            settings = image_settings if file_rec.file_type == "image" else video_settings
            job_id = file_rec.job_id
            output_path = file_rec.output_file_path or file_rec.input_file_path

            # Disk space pre-check before starting compression
            if not self._check_disk_space(output_path):
                db.mark_file_failed(file_id, "Insufficient disk space")
                self._emit_progress(
                    file_id, "error", "Insufficient disk space", 100, job_id=job_id,
                )
                return

            self._emit_progress(
                file_id,
                "processing",
                f"Processing {os.path.basename(file_rec.input_file_path)}",
                0,
                job_id=job_id,
            )

            if not os.path.exists(file_rec.input_file_path):
                if self._cancel_event.is_set():
                    self._ensure_terminal_on_cancel(file_id)
                    return
                db.mark_file_failed(file_id, "Input file not found")
                self._emit_progress(file_id, "error", "File not found", 100, job_id=job_id)
                return

            def progress_cb(pct: int, msg: str):
                if not self._cancel_event.is_set():
                    self._emit_progress(file_id, "processing", msg, pct, job_id=job_id)

            def should_cancel() -> bool:
                return self._cancel_event.is_set()

            def on_process(proc):
                self._process_registry.register(file_id, proc)

            try:
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

            file_rec = db.get_file(file_id)
            if not file_rec:
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
                f"Completed: {os.path.basename(file_rec.input_file_path)}",
                100,
                extra={
                    "input_size": inp_size,
                    "output_size": out_size,
                    "compression_ratio": ratio,
                    "input_hash": inp_hash,
                    "output_hash": out_hash,
                },
                job_id=job_id,
            )

            job = db.get_job(file_rec.job_id)
            if job and job.status == "completed":
                try:
                    save_manifest_to_output_folder(file_rec.job_id)
                except Exception as e:
                    logger.warning(
                        "Failed to save manifest for job %d: %s", file_rec.job_id, e,
                    )
            # Push job state to clients so UI updates without polling
            self._emit_job_update(file_rec.job_id)

        except InterruptedError:
            logger.info("File %d processing interrupted (cancelled)", file_id)
            file_rec = db.get_file(file_id)
            if file_rec and file_rec.status != config.STATUS_CANCELLED:
                db.mark_file_cancelled(file_id)
            jid = file_rec.job_id if file_rec else None
            self._emit_progress(file_id, "cancelled", "Cancelled", 100, job_id=jid)
        except Exception as e:
            if self._cancel_event.is_set():
                self._ensure_terminal_on_cancel(file_id)
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
            jid = file_rec.job_id if file_rec else None
            self._emit_progress(file_id, "error", str(e), 100, job_id=jid)
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
        job_id: Optional[int] = None,
    ):
        payload = {
            "file_id": file_id,
            "status": status,
            "message": message,
            "percent": percent,
        }
        if job_id is not None:
            payload["job_id"] = job_id
        if extra:
            payload.update(extra)
        self._emit("progress_update", payload)

    def _emit_queue_counts(self):
        counts = db.get_queue_counts()
        self._emit("queue_counts", counts)

    def _emit_job_update(self, job_id: int):
        """Push job status change to connected clients via WebSocket.

        Eliminates the need for 30-second polling on the frontend —
        clients receive immediate notification when a job's state changes.
        """
        job = db.get_job(job_id)
        if job:
            self._emit("job_updated", db.job_to_dict(job))

    def _emit(self, event: str, payload):
        """Queue emit for the dedicated consumer (safe from worker threads)."""
        self._emit_queue.put((event, payload))

    def _emit_consumer_loop(self):
        while self._running or not self._emit_queue.empty():
            try:
                event, payload = self._emit_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                with self.app.app_context():
                    self.socketio.emit(event, payload)
            except Exception as e:
                logger.warning("Socket emit failed (%s): %s", event, e)
