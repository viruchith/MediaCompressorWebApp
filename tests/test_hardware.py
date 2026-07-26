"""Comprehensive tests for app/hardware.py — hardware detection and adaptive scaling.

Tests cover:
  - CPU detection (macOS/Linux/Windows paths)
  - RAM detection (all platforms)
  - GPU detection (all platforms)
  - FFmpeg probing
  - Recommendation algorithm (various hardware profiles)
  - Edge cases: no GPU, low RAM, single core, missing tools
  - HW encoder flag generation
  - Profile caching and initialization
"""

import platform
import subprocess
from dataclasses import asdict
from unittest.mock import MagicMock, patch, mock_open

import pytest

from app.hardware import (
    HardwareProfile,
    _clamp,
    _compute_recommendations,
    _detect_cpu,
    _detect_gpu,
    _detect_ram,
    _probe_ffmpeg,
    detect_hardware,
    get_hardware_profile,
    get_hw_encoder_flags,
    get_hwaccel_input_flags,
    initialize,
    HW_ENCODER_CONFIG,
    CODEC_PRIORITY,
    MIN_IMAGE_WORKERS,
    MAX_IMAGE_WORKERS,
    MIN_VIDEO_WORKERS,
    MAX_VIDEO_WORKERS,
)


# --- Helper fixtures ---


@pytest.fixture
def mock_subprocess_run():
    """Fixture to mock subprocess.run with configurable return values."""
    with patch("app.hardware.subprocess.run") as mock_run:
        yield mock_run


@pytest.fixture
def reset_cached_profile():
    """Reset the module-level cached profile before/after tests."""
    import app.hardware as hw_mod
    original = hw_mod._cached_profile
    hw_mod._cached_profile = None
    yield
    hw_mod._cached_profile = original


# --- _clamp tests ---


class TestClamp:
    def test_value_within_range(self):
        assert _clamp(5, 1, 10) == 5

    def test_value_below_min(self):
        assert _clamp(-3, 1, 10) == 1

    def test_value_above_max(self):
        assert _clamp(15, 1, 10) == 10

    def test_value_equals_min(self):
        assert _clamp(1, 1, 10) == 1

    def test_value_equals_max(self):
        assert _clamp(10, 1, 10) == 10


# --- HardwareProfile tests ---


class TestHardwareProfile:
    def test_default_values(self):
        profile = HardwareProfile()
        assert profile.os_name == ""
        assert profile.cpu_cores_logical == 1
        assert profile.ram_total_gb == 0.0
        assert profile.gpu_name is None
        assert profile.ffmpeg_available is False
        assert profile.recommended_image_workers == 2
        assert profile.recommended_video_codec == "libx265"

    def test_to_dict(self):
        profile = HardwareProfile(os_name="linux", cpu_name="Test CPU")
        d = profile.to_dict()
        assert isinstance(d, dict)
        assert d["os_name"] == "linux"
        assert d["cpu_name"] == "Test CPU"
        assert "recommended_image_workers" in d

    def test_to_dict_serializable(self):
        """Ensure to_dict output is JSON-serializable."""
        import json
        profile = HardwareProfile(
            os_name="darwin",
            hw_encoders={"hevc": "hevc_videotoolbox"},
            hw_accel_methods=["videotoolbox"],
        )
        json_str = json.dumps(profile.to_dict())
        assert "darwin" in json_str


# --- CPU Detection tests ---


class TestDetectCPU:
    @patch("app.hardware.platform.system", return_value="Darwin")
    @patch("app.hardware.platform.processor", return_value="arm")
    @patch("os.cpu_count", return_value=10)
    @patch("app.hardware.subprocess.run")
    def test_macos_detection(self, mock_run, mock_count, mock_proc, mock_sys):
        """Test macOS CPU detection via sysctl."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Apple M4\n"),        # brand_string
            MagicMock(returncode=0, stdout="10\n"),              # physicalcpu
            MagicMock(returncode=0, stdout="10\n"),              # logicalcpu
            MagicMock(returncode=0, stdout="4\n"),               # perflevel0
            MagicMock(returncode=0, stdout="6\n"),               # perflevel1
        ]

        name, phys, logical, perf, eff = _detect_cpu()
        assert name == "Apple M4"
        assert phys == 10
        assert logical == 10
        assert perf == 4
        assert eff == 6

    @patch("app.hardware.platform.system", return_value="Linux")
    @patch("app.hardware.platform.processor", return_value="x86_64")
    @patch("os.cpu_count", return_value=16)
    def test_linux_detection(self, mock_cpu_count, mock_proc, mock_sys):
        """Test Linux CPU detection via /proc/cpuinfo."""
        cpuinfo = (
            "processor\t: 0\n"
            "model name\t: Intel(R) Core(TM) i7-13700K\n"
            "physical id\t: 0\n"
            "core id\t\t: 0\n\n"
            "processor\t: 1\n"
            "model name\t: Intel(R) Core(TM) i7-13700K\n"
            "physical id\t: 0\n"
            "core id\t\t: 1\n\n"
        )
        with patch("builtins.open", mock_open(read_data=cpuinfo)):
            name, phys, logical, perf, eff = _detect_cpu()

        assert "i7-13700K" in name
        assert phys == 2  # 2 unique core ids
        assert logical == 16

    @patch("app.hardware.platform.system", return_value="Windows")
    @patch("app.hardware.platform.processor", return_value="Intel64")
    @patch("os.cpu_count", return_value=8)
    def test_windows_detection(self, mock_count, mock_proc, mock_sys, mock_subprocess_run):
        """Test Windows CPU detection via wmic."""
        mock_subprocess_run.side_effect = [
            MagicMock(returncode=0, stdout="Name=AMD Ryzen 7 5800X\n"),
            MagicMock(returncode=0, stdout="NumberOfCores=8\n"),
        ]

        name, phys, logical, perf, eff = _detect_cpu()
        assert "Ryzen 7" in name
        assert phys == 8

    @patch("app.hardware.platform.system", return_value="Darwin")
    @patch("app.hardware.platform.processor", return_value="arm")
    @patch("os.cpu_count", return_value=4)
    def test_timeout_graceful_fallback(self, mock_count, mock_proc, mock_sys, mock_subprocess_run):
        """Test that subprocess timeout doesn't crash detection."""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("sysctl", 5)

        name, phys, logical, perf, eff = _detect_cpu()
        # Should return fallback values without raising
        assert logical >= 1


# --- RAM Detection tests ---


class TestDetectRAM:
    @patch("app.hardware.platform.system", return_value="Darwin")
    def test_macos_ram(self, mock_sys, mock_subprocess_run):
        """Test macOS RAM detection via sysctl + vm_stat."""
        # 24 GB = 25769803776 bytes
        mock_subprocess_run.side_effect = [
            MagicMock(returncode=0, stdout="25769803776\n"),  # hw.memsize
            MagicMock(returncode=0, stdout=(
                "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free:                    200000.\n"
                "Pages inactive:                300000.\n"
            )),
        ]

        total, available = _detect_ram()
        assert abs(total - 24.0) < 0.1
        assert available > 0

    @patch("app.hardware.platform.system", return_value="Linux")
    def test_linux_ram(self, mock_sys, mock_subprocess_run):
        """Test Linux RAM detection via /proc/meminfo."""
        meminfo = (
            "MemTotal:       32768000 kB\n"
            "MemFree:         8192000 kB\n"
            "MemAvailable:   16384000 kB\n"
        )
        with patch("builtins.open", mock_open(read_data=meminfo)):
            total, available = _detect_ram()

        assert abs(total - 31.25) < 0.5  # 32768000 kB ≈ 31.25 GB
        assert abs(available - 15.625) < 0.5

    @patch("app.hardware.platform.system", return_value="Linux")
    def test_linux_no_memavailable(self, mock_sys, mock_subprocess_run):
        """Test fallback when MemAvailable is missing (older kernels)."""
        meminfo = "MemTotal:       16384000 kB\nMemFree:  4096000 kB\n"
        with patch("builtins.open", mock_open(read_data=meminfo)):
            total, available = _detect_ram()

        assert total > 0
        # Fallback: 60% of total
        assert abs(available - total * 0.6) < 0.1

    @patch("app.hardware.platform.system", return_value="Unknown")
    def test_fallback_values(self, mock_sys, mock_subprocess_run):
        """Test that unknown OS gets conservative fallback."""
        total, available = _detect_ram()
        assert total == 4.0  # Conservative fallback
        assert available == 2.0  # Fallback available


# --- GPU Detection tests ---


class TestDetectGPU:
    @patch("app.hardware.platform.system", return_value="Darwin")
    def test_macos_apple_silicon(self, mock_sys, mock_subprocess_run):
        """Test macOS Apple GPU detection via system_profiler."""
        json_output = '{"SPDisplaysDataType": [{"sppci_model": "Apple M4 Pro GPU"}]}'
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout=json_output
        )

        name, vram, vendor = _detect_gpu()
        assert "M4" in name
        assert vendor == "apple"
        assert vram is None  # Apple Silicon uses unified memory

    @patch("app.hardware.platform.system", return_value="Linux")
    @patch("app.hardware.shutil.which")
    def test_linux_nvidia(self, mock_which, mock_sys, mock_subprocess_run):
        """Test Linux NVIDIA GPU detection via nvidia-smi."""
        mock_which.return_value = "/usr/bin/nvidia-smi"
        mock_subprocess_run.return_value = MagicMock(
            returncode=0, stdout="NVIDIA GeForce RTX 4090, 24564\n"
        )

        name, vram, vendor = _detect_gpu()
        assert "RTX 4090" in name
        assert vendor == "nvidia"
        assert abs(vram - 23.98) < 0.1  # 24564 MiB ≈ 23.98 GB

    @patch("app.hardware.platform.system", return_value="Linux")
    @patch("app.hardware.shutil.which")
    def test_linux_no_gpu(self, mock_which, mock_sys, mock_subprocess_run):
        """Test graceful handling when no GPU tools are available."""
        mock_which.return_value = None
        mock_subprocess_run.return_value = MagicMock(returncode=1, stdout="")

        name, vram, vendor = _detect_gpu()
        assert name is None
        assert vendor is None

    @patch("app.hardware.platform.system", return_value="Darwin")
    def test_macos_system_profiler_timeout(self, mock_sys, mock_subprocess_run):
        """Test graceful timeout handling."""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("system_profiler", 15)

        name, vram, vendor = _detect_gpu()
        assert name is None
        assert vendor is None


# --- FFmpeg Probe tests ---


class TestProbeFFmpeg:
    @patch("app.hardware.shutil.which", return_value=None)
    def test_no_ffmpeg(self, mock_which):
        """Test when FFmpeg is not installed."""
        available, methods, encoders, decoders = _probe_ffmpeg()
        assert available is False
        assert methods == []
        assert encoders == {}

    @patch("app.hardware.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ffmpeg_with_videotoolbox(self, mock_which, mock_subprocess_run):
        """Test FFmpeg probe finding VideoToolbox encoders."""
        mock_subprocess_run.side_effect = [
            # -hwaccels
            MagicMock(returncode=0, stdout="Hardware acceleration methods:\nvideotoolbox\n"),
            # -encoders
            MagicMock(returncode=0, stdout=(
                "Encoders:\n"
                " V..... hevc_videotoolbox    VideoToolbox H.265 Encoder\n"
                " V..... h264_videotoolbox    VideoToolbox H.264 Encoder\n"
                " V..... libx265             libx265 H.265\n"
            )),
            # -decoders
            MagicMock(returncode=0, stdout=(
                "Decoders:\n"
                " V..... hevc_videotoolbox    VideoToolbox HEVC Decoder\n"
            )),
        ]

        available, methods, encoders, decoders = _probe_ffmpeg()
        assert available is True
        assert "videotoolbox" in methods
        assert encoders["hevc"] == "hevc_videotoolbox"
        assert encoders["h264"] == "h264_videotoolbox"
        assert "hevc_videotoolbox" in decoders

    @patch("app.hardware.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ffmpeg_with_nvenc(self, mock_which, mock_subprocess_run):
        """Test FFmpeg probe finding NVENC encoders."""
        mock_subprocess_run.side_effect = [
            MagicMock(returncode=0, stdout="Hardware acceleration methods:\ncuda\nnvdec\n"),
            MagicMock(returncode=0, stdout=(
                "Encoders:\n"
                " V..... hevc_nvenc           NVIDIA NVENC HEVC encoder\n"
                " V..... h264_nvenc           NVIDIA NVENC H.264 encoder\n"
            )),
            MagicMock(returncode=0, stdout="Decoders:\n V..... h264_cuvid NVIDIA CUVID\n"),
        ]

        available, methods, encoders, decoders = _probe_ffmpeg()
        assert available is True
        assert encoders["hevc"] == "hevc_nvenc"
        assert encoders["h264"] == "h264_nvenc"
        assert "h264_cuvid" in decoders

    @patch("app.hardware.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ffmpeg_sw_only(self, mock_which, mock_subprocess_run):
        """Test FFmpeg with no HW encoders available."""
        mock_subprocess_run.side_effect = [
            MagicMock(returncode=0, stdout="Hardware acceleration methods:\n"),
            MagicMock(returncode=0, stdout="Encoders:\n V..... libx265  libx265\n"),
            MagicMock(returncode=0, stdout="Decoders:\n"),
        ]

        available, methods, encoders, decoders = _probe_ffmpeg()
        assert available is True
        assert encoders == {}
        assert decoders == []

    @patch("app.hardware.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_ffmpeg_probe_timeout(self, mock_which, mock_subprocess_run):
        """Test graceful handling of FFmpeg timeout."""
        mock_subprocess_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 10)

        available, methods, encoders, decoders = _probe_ffmpeg()
        assert available is True  # FFmpeg exists but probe failed
        assert methods == []


# --- Recommendation Algorithm tests ---


class TestComputeRecommendations:
    def test_high_end_with_hw_accel(self):
        """Test recommendations for a high-end machine with HW encoder."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=16,
            ram_total_gb=32.0,
            ram_available_gb=24.0,
            gpu_vendor="nvidia",
            hw_encoders={"hevc": "hevc_nvenc", "h264": "h264_nvenc"},
        )
        assert img_w == 12  # Capped at max
        assert vid_w >= 2
        assert codec == "hevc_nvenc"
        assert hw is True
        assert device == "cuda"
        assert preset == "medium"

    def test_apple_silicon(self):
        """Test recommendations for Apple Silicon Mac."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=10,
            ram_total_gb=24.0,
            ram_available_gb=16.0,
            gpu_vendor="apple",
            hw_encoders={"hevc": "hevc_videotoolbox", "h264": "h264_videotoolbox"},
        )
        assert img_w == 8  # min(16*0.7*1024/500, 10-2) = min(22, 8) = 8
        assert vid_w == 3  # 10 // 3 = 3
        assert codec == "hevc_videotoolbox"
        assert hw is True
        assert device == "videotoolbox"

    def test_software_only(self):
        """Test recommendations with no HW acceleration."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=8,
            ram_total_gb=16.0,
            ram_available_gb=10.0,
            gpu_vendor=None,
            hw_encoders={},
        )
        assert img_w >= MIN_IMAGE_WORKERS
        assert img_w <= MAX_IMAGE_WORKERS
        assert vid_w >= MIN_VIDEO_WORKERS
        assert codec == "libx265"
        assert hw is False
        assert preset == "slow"

    def test_low_ram_system(self):
        """Test that low-RAM systems get minimum workers."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=4,
            ram_total_gb=3.0,
            ram_available_gb=2.0,
            gpu_vendor=None,
            hw_encoders={},
        )
        assert img_w == MIN_IMAGE_WORKERS
        assert vid_w == MIN_VIDEO_WORKERS

    def test_single_core_system(self):
        """Test minimum worker counts on single-core systems."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=1,
            ram_total_gb=8.0,
            ram_available_gb=4.0,
            gpu_vendor=None,
            hw_encoders={},
        )
        assert img_w == MIN_IMAGE_WORKERS  # Clamped to minimum
        assert vid_w == MIN_VIDEO_WORKERS

    def test_intel_qsv(self):
        """Test Intel QSV selection when NVIDIA is not available."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=12,
            ram_total_gb=16.0,
            ram_available_gb=10.0,
            gpu_vendor="intel",
            hw_encoders={"hevc": "hevc_qsv", "h264": "h264_qsv"},
        )
        assert codec == "hevc_qsv"
        assert hw is True
        assert device == "qsv"

    def test_amd_amf(self):
        """Test AMD AMF selection."""
        img_w, vid_w, codec, hw, device, preset = _compute_recommendations(
            cpu_cores_logical=16,
            ram_total_gb=32.0,
            ram_available_gb=20.0,
            gpu_vendor="amd",
            hw_encoders={"hevc": "hevc_amf"},
        )
        assert codec == "hevc_amf"
        assert hw is True
        assert device == "d3d11va"

    def test_codec_priority_order(self):
        """Test that VideoToolbox is preferred over NVENC when both available."""
        _, _, codec, _, _, _ = _compute_recommendations(
            cpu_cores_logical=10,
            ram_total_gb=24.0,
            ram_available_gb=16.0,
            gpu_vendor="apple",
            hw_encoders={"hevc": "hevc_videotoolbox"},
        )
        assert codec == "hevc_videotoolbox"


# --- HW Encoder Flags tests ---


class TestGetHWEncoderFlags:
    def test_videotoolbox_flags(self):
        flags = get_hw_encoder_flags("hevc_videotoolbox")
        assert "-q:v" in flags
        assert "50" in flags

    def test_nvenc_flags(self):
        flags = get_hw_encoder_flags("hevc_nvenc")
        assert "-cq:v" in flags
        assert "28" in flags
        assert "-preset" in flags
        assert "p5" in flags

    def test_qsv_flags(self):
        flags = get_hw_encoder_flags("hevc_qsv")
        assert "-global_quality" in flags
        assert "28" in flags

    def test_amf_flags(self):
        flags = get_hw_encoder_flags("hevc_amf")
        assert "-rc" in flags
        assert "cqp" in flags
        assert "-qp_i" in flags

    def test_unknown_codec(self):
        flags = get_hw_encoder_flags("libx265")
        assert flags == []

    def test_h264_variants(self):
        flags = get_hw_encoder_flags("h264_nvenc")
        assert "-cq:v" in flags
        assert "23" in flags  # h264 uses quality 23


class TestGetHWAccelInputFlags:
    def test_videotoolbox(self):
        flags = get_hwaccel_input_flags("hevc_videotoolbox")
        assert flags == ["-hwaccel", "videotoolbox"]

    def test_cuda(self):
        flags = get_hwaccel_input_flags("hevc_nvenc")
        assert flags == ["-hwaccel", "cuda"]

    def test_unknown_codec(self):
        flags = get_hwaccel_input_flags("libx265")
        assert flags == []


# --- Full detect_hardware integration tests ---


class TestDetectHardware:
    @patch("app.hardware._detect_cpu")
    @patch("app.hardware._detect_ram")
    @patch("app.hardware._detect_gpu")
    @patch("app.hardware._probe_ffmpeg")
    def test_full_detection_flow(self, mock_ffmpeg, mock_gpu, mock_ram, mock_cpu):
        """Test the full detection pipeline assembles profile correctly."""
        mock_cpu.return_value = ("Test CPU", 8, 16, None, None)
        mock_ram.return_value = (32.0, 24.0)
        mock_gpu.return_value = ("NVIDIA RTX 4090", 24.0, "nvidia")
        mock_ffmpeg.return_value = (
            True,
            ["cuda", "nvdec"],
            {"hevc": "hevc_nvenc", "h264": "h264_nvenc"},
            ["h264_cuvid"],
        )

        profile = detect_hardware()
        assert profile.cpu_name == "Test CPU"
        assert profile.cpu_cores_physical == 8
        assert profile.cpu_cores_logical == 16
        assert profile.ram_total_gb == 32.0
        assert profile.gpu_name == "NVIDIA RTX 4090"
        assert profile.gpu_vendor == "nvidia"
        assert profile.ffmpeg_available is True
        assert profile.recommended_video_codec == "hevc_nvenc"
        assert profile.recommended_hw_accel is True
        assert profile.recommended_image_workers >= MIN_IMAGE_WORKERS

    @patch("app.hardware._detect_cpu")
    @patch("app.hardware._detect_ram")
    @patch("app.hardware._detect_gpu")
    @patch("app.hardware._probe_ffmpeg")
    def test_no_gpu_no_ffmpeg(self, mock_ffmpeg, mock_gpu, mock_ram, mock_cpu):
        """Test minimal system: no GPU, no FFmpeg."""
        mock_cpu.return_value = ("Generic CPU", 2, 4, None, None)
        mock_ram.return_value = (8.0, 5.0)
        mock_gpu.return_value = (None, None, None)
        mock_ffmpeg.return_value = (False, [], {}, [])

        profile = detect_hardware()
        assert profile.gpu_vendor is None
        assert profile.ffmpeg_available is False
        assert profile.recommended_video_codec == "libx265"
        assert profile.recommended_hw_accel is False
        assert profile.recommended_preset == "slow"


# --- Module-level caching tests ---


class TestInitializeAndCache:
    def test_initialize_caches_profile(self, reset_cached_profile):
        """Test that initialize() caches the profile."""
        with patch("app.hardware.detect_hardware") as mock_detect:
            mock_profile = HardwareProfile(os_name="test", cpu_name="Cached")
            mock_detect.return_value = mock_profile

            result = initialize()
            assert result.cpu_name == "Cached"
            assert get_hardware_profile() is mock_profile

    def test_get_hardware_profile_before_init(self, reset_cached_profile):
        """Test that get_hardware_profile returns None before initialization."""
        assert get_hardware_profile() is None


# --- Constants validation tests ---


class TestConstants:
    def test_hw_encoder_config_complete(self):
        """Verify all CODEC_PRIORITY entries have config."""
        for codec in CODEC_PRIORITY:
            assert codec in HW_ENCODER_CONFIG, f"Missing config for {codec}"

    def test_encoder_config_has_required_fields(self):
        """Verify each encoder config has quality_flag and hwaccel."""
        for codec, cfg in HW_ENCODER_CONFIG.items():
            assert "quality_flag" in cfg, f"{codec} missing quality_flag"
            assert "quality_value" in cfg, f"{codec} missing quality_value"
            assert "hwaccel" in cfg, f"{codec} missing hwaccel"

    def test_worker_limits_sane(self):
        """Verify min/max worker limits are reasonable."""
        assert MIN_IMAGE_WORKERS >= 1
        assert MAX_IMAGE_WORKERS >= MIN_IMAGE_WORKERS
        assert MIN_VIDEO_WORKERS >= 1
        assert MAX_VIDEO_WORKERS >= MIN_VIDEO_WORKERS
