import os
import shutil
import tempfile
import time
from PIL import Image
import pytest

from app.utils.scanner import (
    verify_file_integrity,
    is_destination_up_to_date,
    is_precompressed_social_media,
    is_whatsapp_document,
)
from app.workers.copy_worker import copy_media_as_is


@pytest.fixture
def temp_dirs():
    tmp_in = tempfile.mkdtemp(prefix="test_inc_in_")
    tmp_out = tempfile.mkdtemp(prefix="test_inc_out_")
    yield tmp_in, tmp_out
    shutil.rmtree(tmp_in, ignore_errors=True)
    shutil.rmtree(tmp_out, ignore_errors=True)


def test_verify_file_integrity_image():
    with tempfile.TemporaryDirectory() as td:
        good_img = os.path.join(td, "good.jpg")
        img = Image.new("RGB", (50, 50), color=(255, 0, 0))
        img.save(good_img)
        assert verify_file_integrity(good_img, "image") is True

        # Truncated corrupt image
        bad_img = os.path.join(td, "corrupt.jpg")
        with open(bad_img, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
        assert verify_file_integrity(bad_img, "image") is False

        # 0-byte file
        zero_img = os.path.join(td, "zero.png")
        open(zero_img, "wb").close()
        assert verify_file_integrity(zero_img, "image") is False


def test_is_destination_up_to_date_and_corrupt_cleanup(temp_dirs):
    tmp_in, tmp_out = temp_dirs

    src = os.path.join(tmp_in, "photo.jpg")
    dst = os.path.join(tmp_out, "photo.webp")

    # Create source
    img = Image.new("RGB", (50, 50), color=(100, 100, 100))
    img.save(src)

    # 1. Output doesn't exist
    assert is_destination_up_to_date(src, dst, "image") is False

    # 2. Output exists but is corrupt (e.g. killed process)
    with open(dst, "wb") as f:
        f.write(b"corrupt partial webp data")
    assert is_destination_up_to_date(src, dst, "image") is False
    # Corrupt file must be cleaned up automatically
    assert not os.path.exists(dst)

    # 3. Output exists and is valid
    img_out = Image.new("RGB", (50, 50), color=(100, 100, 100))
    img_out.save(dst, "WEBP")
    assert is_destination_up_to_date(src, dst, "image") is True

    # 4. Source was modified after output was generated
    time.sleep(1.1)
    with open(src, "ab") as f:
        f.write(b"\x00")
    # Touch source with future mtime
    os.utime(src, (time.time() + 10, time.time() + 10))
    assert is_destination_up_to_date(src, dst, "image") is False


def test_is_precompressed_social_media():
    # WhatsApp standard photo name
    assert is_precompressed_social_media("IMG-20260714-WA0001.jpg", "image") is True
    # WhatsApp standard video name
    assert is_precompressed_social_media("VID-20260714-WA0002.mp4", "video") is True
    # In standard WhatsApp directory
    assert is_precompressed_social_media("/media/WhatsApp Images/photo.jpg", "image") is True
    assert is_precompressed_social_media("/media/Snapchat/video.mp4", "video") is True

    # High-quality camera media
    assert is_precompressed_social_media("/media/DCIM/Camera/IMG_2026.jpg", "image") is False
    assert is_precompressed_social_media("/media/DCIM/Camera/VID_2026.mp4", "video") is False

    # WhatsApp Documents (sent uncompressed for quality)
    assert is_whatsapp_document("/media/WhatsApp Documents/document_photo.jpg") is True
    assert is_precompressed_social_media("/media/WhatsApp Documents/document_photo.jpg", "image") is False
    assert is_precompressed_social_media("/media/WhatsApp/WhatsApp Documents/VID_camera.mp4", "video") is False


def test_copy_media_as_is(temp_dirs):
    tmp_in, tmp_out = temp_dirs
    src = os.path.join(tmp_in, "whatsapp_photo.jpg")
    img = Image.new("RGB", (100, 100), color=(0, 255, 0))
    img.save(src)
    src_size = os.path.getsize(src)

    out_base = os.path.join(tmp_out, "whatsapp_photo")
    out_path, in_h, out_h, in_sz, out_sz, ratio = copy_media_as_is(src, out_base)

    assert os.path.exists(out_path)
    assert out_path.endswith(".jpg")
    assert in_sz == src_size
    assert out_sz == src_size
    assert in_h == out_h
    assert ratio == 1.0
