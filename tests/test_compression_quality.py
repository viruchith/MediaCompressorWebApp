"""Unit tests for professional compression quality standards and improvements."""

import os
from unittest.mock import MagicMock, patch
from PIL import Image

from app.compression.profiles import PROFILES
from app.compression.settings import get_effective_settings, validate_video_settings
from app.workers.image_worker import compress_image
from app.workers.video_worker import _build_ffmpeg_cmd


class TestImageWorkerQuality:
    def test_webp_preserves_alpha_channel(self, tmp_path):
        # Create an RGBA image with transparent corner
        src_path = str(tmp_path / "transparent_source.png")
        img = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
        img.putpixel((25, 25), (0, 255, 0, 255))
        img.save(src_path, "PNG")

        out_base = str(tmp_path / "out_transparent")
        settings = {"output_format": "webp", "quality": 85}
        out_path, _, _, _, _, _ = compress_image(src_path, out_base, settings)

        with Image.open(out_path) as res:
            assert res.mode in ("RGBA", "LA")
            # Pixel (0, 0) should remain fully transparent
            assert res.getpixel((0, 0))[3] == 0
            # Center pixel should remain fully opaque
            assert res.getpixel((25, 25))[3] == 255

    def test_jpeg_flattens_alpha_to_white(self, tmp_path):
        src_path = str(tmp_path / "transparent_source.png")
        img = Image.new("RGBA", (50, 50), (255, 0, 0, 0))  # Fully transparent
        img.save(src_path, "PNG")

        out_base = str(tmp_path / "out_jpeg")
        settings = {"output_format": "jpeg", "quality": 85}
        out_path, _, _, _, _, _ = compress_image(src_path, out_base, settings)

        with Image.open(out_path) as res:
            assert res.mode == "RGB"
            # Fully transparent region should flatten to white (255, 255, 255)
            r, g, b = res.getpixel((0, 0))
            assert r >= 250 and g >= 250 and b >= 250

    def test_exif_orientation_normalised(self, tmp_path):
        # Create an image with orientation tag in EXIF
        src_path = str(tmp_path / "oriented.jpg")
        img = Image.new("RGB", (60, 30), color="blue")
        exif = img.getexif()
        # Tag 274 is Orientation. 6 = Rotate 90 CW
        exif[274] = 6
        img.save(src_path, "JPEG", exif=exif)

        out_base = str(tmp_path / "out_oriented")
        settings = {"output_format": "webp", "quality": 80}
        out_path, _, _, _, _, _ = compress_image(src_path, out_base, settings)

        with Image.open(out_path) as res:
            # When transposed from 60x30 with rotation 6, dimensions become 30x60
            assert res.size == (30, 60)

    def test_webp_method_6_in_save_kwargs(self, tmp_path):
        src_path = str(tmp_path / "dummy.png")
        Image.new("RGB", (20, 20), color="red").save(src_path, "PNG")

        out_base = str(tmp_path / "out_dummy")
        settings = {"output_format": "webp", "quality": 80}
        with patch("PIL.Image.Image.save") as mock_save:
            compress_image(src_path, out_base, settings)
            mock_save.assert_called()
            _, kwargs = mock_save.call_args
            assert kwargs.get("method") == 6

    def test_png_compress_level_9(self, tmp_path):
        src_path = str(tmp_path / "dummy.png")
        Image.new("RGB", (20, 20), color="green").save(src_path, "PNG")

        out_base = str(tmp_path / "out_dummy")
        settings = {"output_format": "png", "lossless": True}
        with patch("PIL.Image.Image.save") as mock_save:
            compress_image(src_path, out_base, settings)
            mock_save.assert_called()
            _, kwargs = mock_save.call_args
            assert kwargs.get("compress_level") == 9


class TestVideoWorkerQuality:
    def test_ffmpeg_faststart_for_mp4(self):
        settings = {
            "codec": "libx264",
            "container": "mp4",
            "crf": 20,
            "preset": "slow",
        }
        cmd = _build_ffmpeg_cmd("input.mp4", "output.mp4", settings)
        assert "-movflags" in cmd
        idx = cmd.index("-movflags")
        assert cmd[idx + 1] == "+faststart"

    def test_ffmpeg_no_faststart_for_mkv(self):
        settings = {
            "codec": "libx265",
            "container": "mkv",
            "crf": 22,
            "preset": "slow",
        }
        cmd = _build_ffmpeg_cmd("input.mkv", "output.mkv", settings)
        assert "-movflags" not in cmd

    def test_ffmpeg_pix_fmt_x265_default(self):
        settings = {
            "codec": "libx265",
            "container": "mkv",
            "crf": 22,
        }
        cmd = _build_ffmpeg_cmd("input.mkv", "output.mkv", settings)
        assert "-pix_fmt" in cmd
        idx = cmd.index("-pix_fmt")
        assert cmd[idx + 1] == "yuv420p10le"

    def test_ffmpeg_pix_fmt_x264_default(self):
        settings = {
            "codec": "libx264",
            "container": "mp4",
            "crf": 20,
        }
        cmd = _build_ffmpeg_cmd("input.mp4", "output.mp4", settings)
        assert "-pix_fmt" in cmd
        idx = cmd.index("-pix_fmt")
        assert cmd[idx + 1] == "yuv420p"

    def test_ffmpeg_pix_fmt_explicit_override(self):
        settings = {
            "codec": "libx265",
            "container": "mkv",
            "pix_fmt": "yuv444p10le",
        }
        cmd = _build_ffmpeg_cmd("input.mkv", "output.mkv", settings)
        assert "-pix_fmt" in cmd
        idx = cmd.index("-pix_fmt")
        assert cmd[idx + 1] == "yuv444p10le"


class TestProfilesAndSettings:
    def test_balanced_profile_retuning(self):
        balanced = PROFILES["balanced"]
        assert balanced["video"]["crf"] == 22
        assert balanced["video"]["pix_fmt"] == "yuv420p10le"
        assert balanced["image"]["quality"] == 80

    def test_maximum_compression_crf_cap(self):
        max_c = PROFILES["maximum_compression"]
        assert max_c["video"]["crf"] == 30
        assert max_c["video"]["pix_fmt"] == "yuv420p10le"

    def test_photo_print_profile_registered(self):
        assert "photo_print" in PROFILES
        pp = PROFILES["photo_print"]
        assert pp["image"]["lossless"] is True
        assert pp["image"]["output_format"] == "webp"
        assert pp["video"]["codec"] == "libx265"
        assert pp["video"]["pix_fmt"] == "yuv420p10le"

    def test_pix_fmt_validator_valid(self):
        res, errors = validate_video_settings({"pix_fmt": "yuv420p10le"})
        assert not errors
        assert res["pix_fmt"] == "yuv420p10le"

    def test_pix_fmt_validator_invalid(self):
        res, errors = validate_video_settings({"pix_fmt": "invalid_fmt"})
        assert len(errors) == 1
        assert "video.pix_fmt must be one of" in errors[0]
