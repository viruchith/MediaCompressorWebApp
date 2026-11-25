import os
import tempfile
import pytest

from app.utils.scanner import (
    should_ignore_dir,
    is_trashed_or_junk_file,
    is_eligible_media_file,
)
from app.config import config


def test_should_ignore_dir():
    assert should_ignore_dir(".trashed") is True
    assert should_ignore_dir(".TRASHED") is True
    assert should_ignore_dir(".Trash") is True
    assert should_ignore_dir(".thumbnails") is True
    assert should_ignore_dir("__MACOSX") is True
    assert should_ignore_dir(".git") is True
    assert should_ignore_dir("DCIM") is False
    assert should_ignore_dir("Camera") is False
    assert should_ignore_dir("Pictures") is False


def test_is_trashed_or_junk_file():
    # Android MediaStore patterns
    assert is_trashed_or_junk_file(".trashed-1718000000-photo.jpg") is True
    assert is_trashed_or_junk_file(".trashed-1718000000-video.mp4") is True
    assert is_trashed_or_junk_file(".trashed-1718000000") is True
    assert is_trashed_or_junk_file(".TRASHED-IMG_001.JPG") is True

    # OS junk
    assert is_trashed_or_junk_file(".DS_Store") is True
    assert is_trashed_or_junk_file("Thumbs.db") is True
    assert is_trashed_or_junk_file("desktop.ini") is True
    assert is_trashed_or_junk_file(".nomedia") is True
    assert is_trashed_or_junk_file("._IMG_0001.JPG") is True

    # Valid media files
    assert is_trashed_or_junk_file("IMG_2026.jpg") is False
    assert is_trashed_or_junk_file("VID_2026.mp4") is False
    assert is_trashed_or_junk_file("trash_can.jpg") is False


def test_is_eligible_media_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Valid non-empty media file
        valid_img = os.path.join(tmpdir, "valid.jpg")
        with open(valid_img, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

        # Trashed file with image extension
        trashed_img = os.path.join(tmpdir, ".trashed-1718000000-photo.jpg")
        with open(trashed_img, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)

        # 0-byte file
        empty_img = os.path.join(tmpdir, "empty.png")
        open(empty_img, "wb").close()

        # Non-media file
        text_file = os.path.join(tmpdir, "notes.txt")
        with open(text_file, "w") as f:
            f.write("hello")

        supported = config.SUPPORTED_IMAGE_EXTENSIONS | config.SUPPORTED_VIDEO_EXTENSIONS

        assert is_eligible_media_file(valid_img, supported) is True
        assert is_eligible_media_file(trashed_img, supported) is False
        assert is_eligible_media_file(empty_img, supported) is False
        assert is_eligible_media_file(text_file, supported) is False
