"""Hardware auto-detection and adaptive scaling module.

Probes the system at startup and produces a HardwareProfile describing
CPU, RAM, GPU, and available FFmpeg HW encoders. The profile drives:
  1. Auto-tuned worker pool sizes (image processes + video threads)
  2. Auto-selected video encoder (HW when available, software fallback)
  3. A /api/v1/system endpoint exposing detected capabilities to the UI

Works universally on macOS (Apple Silicon + Intel), Linux (NVIDIA/Intel/AMD),
and Windows (NVENC/QSV/AMF) with graceful fallback when no GPU is available.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Constants ---

# Worker count limits to prevent over-allocation
MIN_IMAGE_WORKERS = 2
MAX_IMAGE_WORKERS = 12
MIN_VIDEO_WORKERS = 1
MAX_VIDEO_WORKERS = 6

# Memory budget: reserve 30% for OS and other processes
RAM_RESERVE_FRACTION = 0.3
# Estimated memory per image worker process (MB)
IMAGE_WORKER_RAM_MB = 500

# HW encoder quality flags by platform/vendor
HW_ENCODER_CONFIG: Dict[str, Dict[str, str]] = {
    "hevc_videotoolbox": {
        "quality_flag": "-q:v",
        "quality_value": "50",
        "hwaccel": "videotoolbox",
    },
    "hevc_nvenc": {
        "quality_flag": "-cq:v",
        "quality_value": "28",
        "preset_flag": "-preset",
        "preset_value": "p5",
        "hwaccel": "cuda",
    },
    "hevc_qsv": {
        "quality_flag": "-global_quality",
        "quality_value": "28",
        "hwaccel": "qsv",
    },
    "hevc_amf": {
        "quality_flag": "-rc",
        "quality_value": "cqp",
        "extra_flags": ["-qp_i", "28", "-qp_p", "28"],
        "hwaccel": "d3d11va",
    },
    "h264_videotoolbox": {
        "quality_flag": "-q:v",
        "quality_value": "50",
        "hwaccel": "videotoolbox",
    },
    "h264_nvenc": {
        "quality_flag": "-cq:v",
        "quality_value": "23",
        "preset_flag": "-preset",
        "preset_value": "p5",
        "hwaccel": "cuda",
    },
    "h264_qsv": {
        "quality_flag": "-global_quality",
        "quality_value": "23",
        "hwaccel": "qsv",
    },
    "h264_amf": {
        "quality_flag": "-rc",
        "quality_value": "cqp",
        "extra_flags": ["-qp_i", "23", "-qp_p", "23"],
        "hwaccel": "d3d11va",
    },
}

# Codec selection priority order
CODEC_PRIORITY = [
    "hevc_videotoolbox",
    "hevc_nvenc",
    "hevc_qsv",
    "hevc_amf",
]


def _clamp(value: int, low: int, high: int) -> int:
    """Clamp an integer to [low, high] range."""
    return max(low, min(high, value))


# --- Data Classes ---


@dataclass
class HardwareProfile:
    """Complete hardware profile with detection results and recommendations."""

    # Operating system and architecture
    os_name: str = ""            # "darwin", "linux", "windows"
    arch: str = ""               # "arm64", "x86_64", "aarch64"

    # CPU information
    cpu_name: str = "Unknown"
    cpu_cores_physical: int = 1
    cpu_cores_logical: int = 1
    cpu_perf_cores: Optional[int] = None      # P-cores (hybrid architectures)
    cpu_efficiency_cores: Optional[int] = None  # E-cores (hybrid architectures)

    # Memory
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0

    # GPU
    gpu_name: Optional[str] = None
    gpu_vram_gb: Optional[float] = None
    gpu_vendor: Optional[str] = None  # "apple", "nvidia", "intel", "amd", None

    # FFmpeg capabilities
    ffmpeg_available: bool = False
    hw_accel_methods: List[str] = field(default_factory=list)
    hw_encoders: Dict[str, str] = field(default_factory=dict)  # {"hevc": "hevc_nvenc"}
    hw_decoders: List[str] = field(default_factory=list)

    # Recommendations (computed from above)
    recommended_image_workers: int = 2
    recommended_video_workers: int = 1
    recommended_video_codec: str = "libx265"
    recommended_hw_accel: bool = False
    recommended_hwaccel_device: str = ""  # e.g. "videotoolbox", "cuda"
    recommended_preset: str = "slow"

    def to_dict(self) -> dict:
        """Serialize profile to JSON-safe dictionary."""
        return asdict(self)


# --- Detection Functions ---


def _detect_cpu() -> Tuple[str, int, int, Optional[int], Optional[int]]:
    """Detect CPU name, physical cores, logical cores, and P/E core split.

    Returns:
        (cpu_name, physical_cores, logical_cores, perf_cores, efficiency_cores)
    """
    system = platform.system().lower()
    cpu_name = platform.processor() or "Unknown"
    logical_cores = os.cpu_count() or 1
    physical_cores = logical_cores
    perf_cores: Optional[int] = None
    efficiency_cores: Optional[int] = None

    try:
        if system == "darwin":
            # macOS: use sysctl for detailed info
            result = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                cpu_name = result.stdout.strip()

            # Physical core count
            result = subprocess.run(
                ["sysctl", "-n", "hw.physicalcpu"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                physical_cores = int(result.stdout.strip())

            # Logical core count
            result = subprocess.run(
                ["sysctl", "-n", "hw.logicalcpu"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                logical_cores = int(result.stdout.strip())

            # P/E cores on Apple Silicon
            result = subprocess.run(
                ["sysctl", "-n", "hw.perflevel0.logicalcpu"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                perf_cores = int(result.stdout.strip())

            result = subprocess.run(
                ["sysctl", "-n", "hw.perflevel1.logicalcpu"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                efficiency_cores = int(result.stdout.strip())

        elif system == "linux":
            # Linux: parse /proc/cpuinfo
            try:
                with open("/proc/cpuinfo", "r") as f:
                    cpuinfo = f.read()
                # Get model name from first processor entry
                m = re.search(r"model name\s*:\s*(.+)", cpuinfo)
                if m:
                    cpu_name = m.group(1).strip()
                # Count physical cores (unique core id per physical id)
                core_ids = set()
                for block in cpuinfo.split("\n\n"):
                    phys_id = re.search(r"physical id\s*:\s*(\d+)", block)
                    core_id = re.search(r"core id\s*:\s*(\d+)", block)
                    if phys_id and core_id:
                        core_ids.add((phys_id.group(1), core_id.group(1)))
                if core_ids:
                    physical_cores = len(core_ids)
            except (IOError, OSError):
                pass

            # Detect Intel hybrid (P/E cores) via sysfs
            try:
                import glob as _glob
                cpu_types = _glob.glob("/sys/devices/cpu_core/core_type*")
                if not cpu_types:
                    # Alternative: check for different max frequencies
                    pass
            except (IOError, OSError):
                pass

        elif system == "windows":
            # Windows: use wmic or platform
            try:
                result = subprocess.run(
                    ["wmic", "cpu", "get", "Name", "/value"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    m = re.search(r"Name=(.+)", result.stdout)
                    if m:
                        cpu_name = m.group(1).strip()

                result = subprocess.run(
                    ["wmic", "cpu", "get", "NumberOfCores", "/value"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    m = re.search(r"NumberOfCores=(\d+)", result.stdout)
                    if m:
                        physical_cores = int(m.group(1))
            except (FileNotFoundError, OSError):
                pass

    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        logger.warning("CPU detection error: %s", e)

    return cpu_name, physical_cores, logical_cores, perf_cores, efficiency_cores


def _detect_ram() -> Tuple[float, float]:
    """Detect total and available RAM in GB.

    Returns:
        (total_gb, available_gb)
    """
    system = platform.system().lower()
    total_gb = 0.0
    available_gb = 0.0

    try:
        if system == "darwin":
            # macOS: sysctl for total, vm_stat for available
            result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                total_gb = int(result.stdout.strip()) / (1024 ** 3)

            # Estimate available from vm_stat (pages free + inactive)
            result = subprocess.run(
                ["vm_stat"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                page_size = 16384  # Default on Apple Silicon
                ps_match = re.search(r"page size of (\d+) bytes", result.stdout)
                if ps_match:
                    page_size = int(ps_match.group(1))
                free_m = re.search(r"Pages free:\s+(\d+)", result.stdout)
                inactive_m = re.search(r"Pages inactive:\s+(\d+)", result.stdout)
                free_pages = int(free_m.group(1)) if free_m else 0
                inactive_pages = int(inactive_m.group(1)) if inactive_m else 0
                available_gb = (free_pages + inactive_pages) * page_size / (1024 ** 3)

        elif system == "linux":
            # Linux: parse /proc/meminfo
            try:
                with open("/proc/meminfo", "r") as f:
                    meminfo = f.read()
                total_m = re.search(r"MemTotal:\s+(\d+)\s+kB", meminfo)
                avail_m = re.search(r"MemAvailable:\s+(\d+)\s+kB", meminfo)
                if total_m:
                    total_gb = int(total_m.group(1)) / (1024 ** 2)
                if avail_m:
                    available_gb = int(avail_m.group(1)) / (1024 ** 2)
                elif total_m:
                    # Fallback: estimate available as 60% of total
                    available_gb = total_gb * 0.6
            except (IOError, OSError):
                pass

        elif system == "windows":
            # Windows: use wmic
            try:
                result = subprocess.run(
                    ["wmic", "OS", "get", "TotalVisibleMemorySize", "/value"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    m = re.search(r"TotalVisibleMemorySize=(\d+)", result.stdout)
                    if m:
                        total_gb = int(m.group(1)) / (1024 ** 2)

                result = subprocess.run(
                    ["wmic", "OS", "get", "FreePhysicalMemory", "/value"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    m = re.search(r"FreePhysicalMemory=(\d+)", result.stdout)
                    if m:
                        available_gb = int(m.group(1)) / (1024 ** 2)
            except (FileNotFoundError, OSError):
                pass

    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        logger.warning("RAM detection error: %s", e)

    # Fallback: at least report os.cpu_count-based estimate
    if total_gb == 0.0:
        total_gb = 4.0  # Conservative fallback
        available_gb = 2.0

    if available_gb == 0.0:
        available_gb = total_gb * 0.6

    return total_gb, available_gb


def _detect_gpu() -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """Detect GPU name, VRAM, and vendor.

    Returns:
        (gpu_name, vram_gb, vendor)  where vendor is "apple", "nvidia", "intel", "amd", or None
    """
    system = platform.system().lower()
    gpu_name: Optional[str] = None
    vram_gb: Optional[float] = None
    vendor: Optional[str] = None

    try:
        if system == "darwin":
            # macOS: system_profiler for GPU info
            result = subprocess.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                import json
                try:
                    data = json.loads(result.stdout)
                    displays = data.get("SPDisplaysDataType", [])
                    for gpu in displays:
                        gpu_name = gpu.get("sppci_model", gpu.get("_name", "Unknown GPU"))
                        # Determine vendor from chip name
                        name_lower = gpu_name.lower()
                        if "apple" in name_lower or "m1" in name_lower or "m2" in name_lower \
                                or "m3" in name_lower or "m4" in name_lower:
                            vendor = "apple"
                        elif "nvidia" in name_lower or "geforce" in name_lower:
                            vendor = "nvidia"
                        elif "intel" in name_lower:
                            vendor = "intel"
                        elif "amd" in name_lower or "radeon" in name_lower:
                            vendor = "amd"
                        # Apple Silicon shares unified memory
                        if vendor == "apple":
                            vram_gb = None  # Shared with system RAM
                        else:
                            vram_str = gpu.get("spdisplays_vram", "")
                            vram_m = re.search(r"(\d+)", str(vram_str))
                            if vram_m:
                                vram_gb = float(vram_m.group(1)) / 1024
                        break  # Use first GPU
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

        elif system == "linux":
            # Try nvidia-smi first for NVIDIA GPUs
            if shutil.which("nvidia-smi"):
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    parts = result.stdout.strip().split(",")
                    gpu_name = parts[0].strip()
                    vendor = "nvidia"
                    if len(parts) > 1:
                        try:
                            vram_gb = float(parts[1].strip()) / 1024
                        except ValueError:
                            pass

            # Fallback to lspci for any GPU
            if not gpu_name and shutil.which("lspci"):
                result = subprocess.run(
                    ["lspci"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        if "VGA" in line or "3D" in line or "Display" in line:
                            gpu_name = line.split(":", 2)[-1].strip() if ":" in line else line
                            name_lower = gpu_name.lower()
                            if "nvidia" in name_lower:
                                vendor = "nvidia"
                            elif "intel" in name_lower:
                                vendor = "intel"
                            elif "amd" in name_lower or "radeon" in name_lower:
                                vendor = "amd"
                            break

        elif system == "windows":
            # Windows: wmic path win32_VideoController
            try:
                result = subprocess.run(
                    ["wmic", "path", "win32_VideoController", "get", "Name,AdapterRAM", "/value"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    name_m = re.search(r"Name=(.+)", result.stdout)
                    ram_m = re.search(r"AdapterRAM=(\d+)", result.stdout)
                    if name_m:
                        gpu_name = name_m.group(1).strip()
                        name_lower = gpu_name.lower()
                        if "nvidia" in name_lower or "geforce" in name_lower or "rtx" in name_lower:
                            vendor = "nvidia"
                        elif "intel" in name_lower:
                            vendor = "intel"
                        elif "amd" in name_lower or "radeon" in name_lower:
                            vendor = "amd"
                    if ram_m:
                        vram_gb = int(ram_m.group(1)) / (1024 ** 3)
            except (FileNotFoundError, OSError):
                pass

    except (subprocess.TimeoutExpired, ValueError, OSError) as e:
        logger.warning("GPU detection error: %s", e)

    return gpu_name, vram_gb, vendor


def _probe_ffmpeg() -> Tuple[bool, List[str], Dict[str, str], List[str]]:
    """Probe FFmpeg for available HW acceleration methods, encoders, and decoders.

    Returns:
        (ffmpeg_available, hw_accel_methods, hw_encoders, hw_decoders)
        hw_encoders maps codec family to best encoder: {"hevc": "hevc_nvenc", "h264": "h264_nvenc"}
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        return False, [], {}, []

    hw_accel_methods: List[str] = []
    hw_encoders: Dict[str, str] = {}
    hw_decoders: List[str] = []

    try:
        # Get available hardware acceleration methods
        result = subprocess.run(
            [ffmpeg_bin, "-hwaccels"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().splitlines()
            # Skip header line "Hardware acceleration methods:"
            for line in lines[1:]:
                method = line.strip()
                if method:
                    hw_accel_methods.append(method)

        # Get available encoders and find HW-accelerated ones
        result = subprocess.run(
            [ffmpeg_bin, "-encoders"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            # Match lines like " V..... hevc_videotoolbox ..."
            encoder_re = re.compile(r"^\s*V[.\w]+\s+([\w_]+)\s+(.*)$")
            for line in result.stdout.splitlines():
                m = encoder_re.match(line)
                if m:
                    encoder_name = m.group(1)
                    # Check if it's a known HW encoder
                    if encoder_name in HW_ENCODER_CONFIG:
                        # Determine codec family (hevc or h264)
                        if "hevc" in encoder_name or "h265" in encoder_name:
                            family = "hevc"
                        elif "h264" in encoder_name:
                            family = "h264"
                        else:
                            continue
                        # Only store if not already set (priority is by iteration order)
                        if family not in hw_encoders:
                            hw_encoders[family] = encoder_name

        # Get available decoders (HW-accelerated)
        result = subprocess.run(
            [ffmpeg_bin, "-decoders"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            decoder_re = re.compile(r"^\s*V[.\w]+\s+([\w_]+)\s+(.*)$")
            hw_keywords = ("cuvid", "qsv", "videotoolbox", "vaapi", "d3d11va", "dxva2", "amf")
            for line in result.stdout.splitlines():
                m = decoder_re.match(line)
                if m:
                    decoder_name = m.group(1)
                    if any(kw in decoder_name for kw in hw_keywords):
                        hw_decoders.append(decoder_name)

    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("FFmpeg probe error: %s", e)
        return True, [], {}, []  # FFmpeg exists but probe failed

    return True, hw_accel_methods, hw_encoders, hw_decoders


def _compute_recommendations(
    cpu_cores_logical: int,
    ram_total_gb: float,
    ram_available_gb: float,
    gpu_vendor: Optional[str],
    hw_encoders: Dict[str, str],
) -> Tuple[int, int, str, bool, str, str]:
    """Compute optimal worker counts and codec selection.

    Returns:
        (image_workers, video_workers, video_codec, hw_accel, hwaccel_device, preset)
    """
    # --- Image workers ---
    # Each process uses ~500MB; leave 30% RAM for OS
    ram_budget_gb = ram_available_gb * (1 - RAM_RESERVE_FRACTION)
    max_by_ram = int((ram_budget_gb * 1024) / IMAGE_WORKER_RAM_MB)
    max_by_cpu = cpu_cores_logical - 2  # Reserve 2 cores for dispatcher + system
    image_workers = _clamp(min(max_by_ram, max_by_cpu), MIN_IMAGE_WORKERS, MAX_IMAGE_WORKERS)

    # --- Video codec selection (priority order) ---
    video_codec = "libx265"
    hw_accel = False
    hwaccel_device = ""
    preset = "slow"

    for codec in CODEC_PRIORITY:
        codec_family = "hevc" if "hevc" in codec else "h264"
        if hw_encoders.get(codec_family) == codec:
            video_codec = codec
            hw_accel = True
            encoder_config = HW_ENCODER_CONFIG.get(codec, {})
            hwaccel_device = encoder_config.get("hwaccel", "")
            preset = "medium"  # HW encoders don't benefit from slow presets
            break

    # --- Video workers ---
    if hw_accel:
        # HW encoding uses minimal CPU; limited mainly by encoder sessions
        video_workers = _clamp(cpu_cores_logical // 3, 2, MAX_VIDEO_WORKERS)
    else:
        # Software x265 uses ~4 threads internally per ffmpeg process
        video_workers = _clamp(cpu_cores_logical // 4, MIN_VIDEO_WORKERS, 4)

    # Low-RAM override: reduce workers to prevent OOM
    if ram_total_gb < 4.0:
        image_workers = MIN_IMAGE_WORKERS
        video_workers = MIN_VIDEO_WORKERS

    return image_workers, video_workers, video_codec, hw_accel, hwaccel_device, preset


def detect_hardware() -> HardwareProfile:
    """Run full hardware detection and return a populated HardwareProfile.

    This is the main entry point — call once at application startup.
    All detection functions are wrapped in try/except to ensure graceful
    fallback if any system command is unavailable.
    """
    profile = HardwareProfile()
    profile.os_name = platform.system().lower()
    profile.arch = platform.machine().lower()

    # Detect CPU
    cpu_name, phys, logical, perf, eff = _detect_cpu()
    profile.cpu_name = cpu_name
    profile.cpu_cores_physical = phys
    profile.cpu_cores_logical = logical
    profile.cpu_perf_cores = perf
    profile.cpu_efficiency_cores = eff

    # Detect RAM
    total_gb, available_gb = _detect_ram()
    profile.ram_total_gb = round(total_gb, 2)
    profile.ram_available_gb = round(available_gb, 2)

    # Detect GPU
    gpu_name, vram_gb, gpu_vendor = _detect_gpu()
    profile.gpu_name = gpu_name
    profile.gpu_vram_gb = round(vram_gb, 2) if vram_gb is not None else None
    profile.gpu_vendor = gpu_vendor

    # Probe FFmpeg
    ffmpeg_avail, accel_methods, encoders, decoders = _probe_ffmpeg()
    profile.ffmpeg_available = ffmpeg_avail
    profile.hw_accel_methods = accel_methods
    profile.hw_encoders = encoders
    profile.hw_decoders = decoders

    # Compute recommendations
    img_w, vid_w, codec, hw_accel, hwaccel_dev, preset = _compute_recommendations(
        profile.cpu_cores_logical,
        profile.ram_total_gb,
        profile.ram_available_gb,
        profile.gpu_vendor,
        profile.hw_encoders,
    )
    profile.recommended_image_workers = img_w
    profile.recommended_video_workers = vid_w
    profile.recommended_video_codec = codec
    profile.recommended_hw_accel = hw_accel
    profile.recommended_hwaccel_device = hwaccel_dev
    profile.recommended_preset = preset

    logger.info(
        "Hardware detected: %s %s | CPU: %s (%d/%d cores) | RAM: %.1f GB | GPU: %s (%s)",
        profile.os_name, profile.arch, profile.cpu_name,
        profile.cpu_cores_physical, profile.cpu_cores_logical,
        profile.ram_total_gb, profile.gpu_name or "None", profile.gpu_vendor or "none",
    )
    logger.info(
        "Recommendations: image_workers=%d, video_workers=%d, codec=%s, hw_accel=%s",
        img_w, vid_w, codec, hw_accel,
    )

    return profile


def get_hw_encoder_flags(codec: str) -> List[str]:
    """Get the FFmpeg quality/preset flags for a hardware encoder.

    Returns a list of CLI arguments to insert after -c:v <codec> in ffmpeg command.
    Returns empty list for unknown codecs (caller should use default -crf).
    """
    encoder_config = HW_ENCODER_CONFIG.get(codec)
    if not encoder_config:
        return []

    flags = []
    # Quality flag (e.g. -q:v 50, -cq:v 28, -global_quality 28)
    quality_flag = encoder_config.get("quality_flag")
    quality_value = encoder_config.get("quality_value")
    if quality_flag and quality_value:
        flags.extend([quality_flag, quality_value])

    # Preset (e.g. -preset p5 for NVENC)
    preset_flag = encoder_config.get("preset_flag")
    preset_value = encoder_config.get("preset_value")
    if preset_flag and preset_value:
        flags.extend([preset_flag, preset_value])

    # Extra flags (e.g. -qp_i 28 -qp_p 28 for AMF)
    extra = encoder_config.get("extra_flags", [])
    flags.extend(extra)

    return flags


def get_hwaccel_input_flags(codec: str) -> List[str]:
    """Get the FFmpeg -hwaccel flags to add before -i for decode acceleration.

    Returns empty list if codec has no associated hwaccel method.
    """
    encoder_config = HW_ENCODER_CONFIG.get(codec)
    if not encoder_config:
        return []

    hwaccel = encoder_config.get("hwaccel")
    if hwaccel:
        return ["-hwaccel", hwaccel]
    return []


# Module-level cached profile (populated by detect_hardware() at startup)
_cached_profile: Optional[HardwareProfile] = None


def get_hardware_profile() -> Optional[HardwareProfile]:
    """Return the cached hardware profile (None if not yet detected)."""
    return _cached_profile


def initialize() -> HardwareProfile:
    """Detect hardware and cache the profile. Call once at app startup."""
    global _cached_profile
    _cached_profile = detect_hardware()
    return _cached_profile
