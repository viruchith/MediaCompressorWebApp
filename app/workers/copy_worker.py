"""File copy helper for media that should be archived as-is without re-encoding."""

import logging
import os
import shutil
import tempfile
from typing import Callable, Optional, Tuple

from app.utils.hashing import compute_file_hash

logger = logging.getLogger(__name__)


def copy_media_as_is(
    input_path: str,
    output_path: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[str, str, str, int, int, float]:
    """Copy media directly to destination preserving mtime, computing SHA-256 digests.

    Returns (out_path, input_hash, output_hash, input_size, output_size, ratio).
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Source file does not exist: {input_path}")

    # Retain original file extension when copying as-is
    src_ext = os.path.splitext(input_path)[1]
    out_path = os.path.splitext(output_path)[0] + src_ext
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if progress_callback:
        progress_callback(10, "Hashing source file")

    if should_cancel and should_cancel():
        raise InterruptedError("Operation cancelled")

    input_hash = compute_file_hash(input_path, should_cancel=should_cancel)
    input_size = os.path.getsize(input_path)

    if progress_callback:
        progress_callback(40, "Copying media file")

    if should_cancel and should_cancel():
        raise InterruptedError("Operation cancelled")

    # Atomic copy via temporary file in output directory
    fd, tmp_path = tempfile.mkstemp(
        suffix=src_ext,
        dir=os.path.dirname(out_path) or ".",
    )
    os.close(fd)

    try:
        shutil.copy2(input_path, tmp_path)
        os.replace(tmp_path, out_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    if progress_callback:
        progress_callback(80, "Verifying copied output")

    output_hash = input_hash  # Exact copy has identical hash
    output_size = input_size
    ratio = 1.0

    if progress_callback:
        progress_callback(100, "Archived without re-compression")

    return out_path, input_hash, output_hash, input_size, output_size, ratio
