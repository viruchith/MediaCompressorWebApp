"""File scanning, filtering, integrity, and media classification utilities.

Filters out OS metadata files, thumbnails, Android trashed media,
validates existing destination file integrity for incremental sync,
and classifies pre-compressed social media vs high-quality originals.
"""

import logging
import os
import re
import shutil
import subprocess
from typing import Optional, Set, Tuple
from PIL import Image

logger = logging.getLogger(__name__)

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

# Standard WhatsApp media patterns: IMG-YYYYMMDD-WA0001.jpg, VID-YYYYMMDD-WA0001.mp4
WHATSAPP_PATTERN = re.compile(r"^(img|vid)-\d{8}-wa\d+", re.IGNORECASE)

# Standard Snapchat media pattern: Snapchat-123456789.mp4 / jpg
SNAPCHAT_PATTERN = re.compile(r"^snapchat-", re.IGNORECASE)


def should_ignore_dir(dir_name: str) -> bool:
    """Return True if directory should not be walked."""
    return dir_name.lower() in IGNORED_DIR_NAMES


def is_trashed_or_junk_file(filename: str) -> bool:
    """Return True if filename matches Android trashed media or common OS metadata junk."""
    lower_name = filename.lower()

    if lower_name in IGNORED_EXACT_NAMES:
        return True

    if lower_name.startswith(".trashed"):
        return True

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
        if os.path.getsize(file_path) == 0:
            return False
    except OSError:
        return False

    return True


def verify_file_integrity(file_path: str, file_type: str) -> bool:
    """Check if an existing file is non-empty and structurally valid."""
    try:
        if not os.path.exists(file_path):
            return False
        if os.path.getsize(file_path) == 0:
            return False

        if file_type == "image":
            # Fast verification of image structure
            with Image.open(file_path) as img:
                img.verify()
            return True
        elif file_type == "video":
            # Fast probe to verify container and video stream validity
            ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
            cmd = [
                ffprobe_bin,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1",
                file_path,
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
            return res.returncode == 0 and len(res.stdout.strip()) > 0
    except Exception as e:
        logger.debug("Integrity check failed for %s: %s", file_path, e)
        return False
    return False


def is_destination_up_to_date(source_path: str, destination_path: str, file_type: str) -> bool:
    """Check whether a valid, non-corrupted destination file already exists for the source file.

    Returns True if destination exists, is non-empty, passes structural integrity check,
    and has mtime >= source_path mtime.
    If the destination exists but is corrupt or 0-byte (e.g. from an interrupted job),
    it removes the corrupt destination and returns False so it will be re-compressed.
    """
    if not os.path.exists(destination_path):
        return False

    # Check structural integrity
    if not verify_file_integrity(destination_path, file_type):
        logger.warning(
            "Found incomplete/corrupted destination file %s; cleaning up for re-compression",
            destination_path,
        )
        try:
            os.remove(destination_path)
        except OSError:
            pass
        return False

    try:
        src_mtime = os.path.getmtime(source_path)
        dst_mtime = os.path.getmtime(destination_path)
        # If source has been modified after the output was generated, it needs updating
        if src_mtime > dst_mtime + 2:  # 2-second tolerance for filesystem timestamp differences
            return False
    except OSError:
        return False

    return True


def is_whatsapp_document(file_path: str) -> bool:
    """Return True if path indicates it was sent/saved as an uncompressed WhatsApp Document."""
    normalized = file_path.replace("\\", "/").lower()
    return "whatsapp documents" in normalized or "whatsapp document" in normalized


def is_precompressed_social_media(file_path: str, file_type: str) -> bool:
    """Classify if media has already undergone heavy lossy social media compression.

    Standard WhatsApp and Snapchat media is already heavily compressed.
    However, media sent as an uncompressed WhatsApp Document retains original camera
    quality and metadata and should be compressed.
    """
    # If explicitly in WhatsApp Documents folder, treat as original uncompressed media
    if is_whatsapp_document(file_path):
        return False

    filename = os.path.basename(file_path)
    lower_path = file_path.replace("\\", "/").lower()

    # WhatsApp media detection
    is_wa = (
        WHATSAPP_PATTERN.match(filename) is not None
        or "whatsapp/media/whatsapp images" in lower_path
        or "whatsapp/media/whatsapp video" in lower_path
        or "whatsapp images" in lower_path
        or "whatsapp video" in lower_path
    )

    # Snapchat detection
    is_snap = (
        SNAPCHAT_PATTERN.match(filename) is not None
        or "snapchat" in lower_path
    )

    if not (is_wa or is_snap):
        return False

    # Perform content-based confirmation
    try:
        if file_type == "image":
            # Standard WhatsApp/Snapchat images are stripped of camera EXIF (Make/Model)
            # and downscaled. High-quality documents sent via WA keep camera EXIF.
            with Image.open(file_path) as img:
                exif = img.getexif()
                has_camera_make = bool(exif.get(0x010f))  # 0x010f = Make
                has_camera_model = bool(exif.get(0x0110)) # 0x0110 = Model
                w, h = img.size

                # If it has original camera metadata and high resolution, it was sent as full quality
                if (has_camera_make or has_camera_model) and max(w, h) >= 2048:
                    return False  # Compress it

            return True  # Already compressed social media

        elif file_type == "video":
            # Standard WhatsApp videos are 720p/480p and encoded at low bitrates (< 2.2 Mbps)
            # Full quality video documents usually have bitrates > 3.5 Mbps or 1080p60/4K
            ffprobe_bin = shutil.which("ffprobe") or "ffprobe"
            cmd = [
                ffprobe_bin,
                "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=bit_rate,width,height:format=bit_rate",
                "-of", "default=noprint_wrappers=1",
                file_path,
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, text=True)
            if res.returncode == 0:
                out = res.stdout
                bitrate = 0
                for line in out.splitlines():
                    if line.startswith("bit_rate="):
                        val = line.split("=")[1].strip()
                        if val.isdigit():
                            bitrate = max(bitrate, int(val))

                # If bitrate > 3.5 Mbps (3,500,000 bps), it is a high-quality video document
                if bitrate > 3_500_000:
                    return False  # Compress it

            return True  # Already compressed social media

    except Exception as e:
        logger.debug("Failed media probe for %s: %s", file_path, e)

    return is_wa or is_snap
