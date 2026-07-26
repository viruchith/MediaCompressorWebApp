"""Track active compression subprocesses for cancellation."""

import subprocess
import threading
from typing import Dict


class ProcessRegistry:
    """Track active compression subprocesses for cancellation and timeout recovery."""

    def __init__(self):
        self._lock = threading.Lock()
        self._processes: Dict[int, subprocess.Popen] = {}

    def register(self, file_id: int, proc: subprocess.Popen):
        with self._lock:
            self._processes[file_id] = proc

    def unregister(self, file_id: int):
        with self._lock:
            self._processes.pop(file_id, None)

    def terminate_by_id(self, file_id: int) -> bool:
        """Terminate the subprocess for a specific file_id.

        Used by the timeout watchdog to kill hung ffmpeg processes.
        Returns True if a process was found and terminated.
        """
        with self._lock:
            proc = self._processes.pop(file_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            return True
        return False

    def terminate_all(self) -> int:
        terminated = 0
        with self._lock:
            for proc in self._processes.values():
                if proc.poll() is None:
                    proc.terminate()
                    terminated += 1
            self._processes.clear()
        return terminated
