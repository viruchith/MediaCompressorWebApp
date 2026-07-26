"""Unit tests for utility modules."""

import os
import tempfile

from app.utils.hashing import compute_file_hash
from app.workers.image_worker import is_image_file, get_output_path
from app.workers.video_worker import is_video_file
from app.workers.process_registry import ProcessRegistry


class TestHashing:
    def test_compute_hash(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        h = compute_file_hash(str(f))
        # Known SHA-256 of "hello world"
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_hash_cancellation(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"x" * 10000)
        try:
            compute_file_hash(str(f), should_cancel=lambda: True)
            assert False, "Should have raised InterruptedError"
        except InterruptedError:
            pass

    def test_hash_no_cancellation(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"data")
        h = compute_file_hash(str(f), should_cancel=lambda: False)
        assert len(h) == 64  # SHA-256 hex length


class TestImageWorker:
    def test_is_image_file(self):
        assert is_image_file("photo.jpg") is True
        assert is_image_file("photo.png") is True
        assert is_image_file("photo.webp") is True
        assert is_image_file("video.mp4") is False
        assert is_image_file("readme.txt") is False

    def test_get_output_path_webp(self):
        result = get_output_path("/out/photo.png", {"output_format": "webp"})
        assert result == "/out/photo.webp"

    def test_get_output_path_jpeg(self):
        result = get_output_path("/out/photo.png", {"output_format": "jpeg"})
        assert result == "/out/photo.jpg"


class TestVideoWorker:
    def test_is_video_file(self):
        assert is_video_file("clip.mp4") is True
        assert is_video_file("clip.mkv") is True
        assert is_video_file("photo.png") is False


class TestProcessRegistry:
    def test_register_and_terminate_by_id(self):
        import subprocess
        reg = ProcessRegistry()

        # terminate_by_id on nonexistent returns False
        assert reg.terminate_by_id(999) is False

    def test_terminate_all_empty(self):
        reg = ProcessRegistry()
        assert reg.terminate_all() == 0
