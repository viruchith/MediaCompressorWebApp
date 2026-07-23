import hashlib
from typing import Callable, Optional

# 1 MB chunks for better throughput on large video files
_DEFAULT_CHUNK_SIZE = 1024 * 1024


def compute_file_hash(
    file_path: str,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> str:
    """Compute SHA-256 hex digest of a file, streaming in chunks.

    Uses 1 MB chunks (instead of the original 8 KB) for significantly
    better I/O throughput on large video files. Supports an optional
    cancellation callback to abort hashing mid-stream.
    """
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            if should_cancel and should_cancel():
                raise InterruptedError("Hash computation cancelled")
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()
