"""File scanning and filtering utilities.

Filters out OS metadata files, thumbnails, Android trashed media,
and zero-byte files during directory traversal.
"""

import os
from typing import Set

# Directory names that should never be traversed
IGNORED_DIR_NAMES: Set[str] = {
    ".trashed",
    ".trash",
    ".recycle",
    "$recycle.bin",
    ".thumbnails",
    ".cache",
    "__macosx",
    ".git",
}

# Exact file names to ignore (case-insensitive)
IGNORED_EXACT_NAMES: Set[str] = {
    ".ds_store",
    "thumbs.db",
    "desktop.ini",
    ".nomedia",
}


def should_ignore_dir(dir_name: str) -> bool:
    """Return True if directory should not be walked."""
    return dir_name.lower() in IGNORED_DIR_NAMES


def is_trashed_or_junk_file(filename: str) -> bool:
    """Return True if filename matches Android trashed media or common OS metadata junk."""
    lower_name = filename.lower()

    # Exact matches (e.g. .DS_Store, Thumbs.db)
    if lower_name in IGNORED_EXACT_NAMES:
        return True

    # Android MediaStore trashed files (e.g. .trashed-1718000000-photo.jpg or .trashed-1718000000)
    if lower_name.startswith(".trashed"):
        return True

    # macOS AppleDouble resource fork files (e.g. ._IMG_0001.JPG)
    if lower_name.startswith("._"):
        return True

    return False


def is_eligible_media_file(file_path: str, supported_extensions: Set[str]) -> bool:
    """Check if file exists, is non-empty, and has an eligible media extension."""
    filename = os.path.basename(file_path)

    if is_trashed_or_junk_file(filename):
        return False

    ext = os.path.splitext(filename)[1][1:].lower()
    if ext not in supported_extensions:
        return False

    try:
        # Filter out 0-byte files which crash or fail decoders
        if os.path.getsize(file_path) == 0:
            return False
    except OSError:
        return False

    return True
