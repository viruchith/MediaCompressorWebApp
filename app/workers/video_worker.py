import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.config import config
from app.utils.hashing import compute_file_hash

logger = logging.getLogger(__name__)

TIME_RE = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)")

# HW codecs that use quality-based encoding (no -crf / -preset in standard sense)
_HW_CODECS = frozenset({
    "hevc_videotoolbox", "h264_videotoolbox",
    "hevc_nvenc", "h264_nvenc",
    "hevc_qsv", "h264_qsv",
    "hevc_amf", "h264_amf",
})


def is_video_file(file_path: str) -> bool:
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_path)
    return bool(mime_type and mime_type.startswith("video/"))


def _parse_duration(stderr_line: str) -> Optional[float]:
    m = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", stderr_line)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s
    return None


def _parse_time(stderr_line: str) -> Optional[float]:
    m = TIME_RE.search(stderr_line)
    if m:
        h, mi, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return h * 3600 + mi * 60 + s
    return None


def _resolution_scale(resolution: str) -> Optional[str]:
    mapping = {
        "1080p": "1920:-2",
        "720p": "1280:-2",
        "480p": "854:-2",
        "360p": "640:-2",
    }
    return mapping.get(resolution)


def get_output_path(base_output: str, settings: Dict[str, Any]) -> str:
    container = settings.get("container", "mkv")
    return os.path.splitext(base_output)[0] + f".{container}"


def _build_ffmpeg_cmd(
    input_path: str,
    output_path: str,
    settings: Dict[str, Any],
) -> List[str]:
    """Build FFmpeg command with platform-aware HW encoder selection.

    When a hardware codec is specified (e.g. hevc_videotoolbox, hevc_nvenc),
    uses the appropriate quality flags and hwaccel decode method instead of
    the standard -crf/-preset flags used by software codecs.
    """
    from app.hardware import get_hw_encoder_flags, get_hwaccel_input_flags

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    codec = settings.get("codec", "libx265")
    is_hw_codec = codec in _HW_CODECS

    # Start building command — hwaccel flags go BEFORE -i
    cmd = [ffmpeg_bin, "-y", "-hide_banner"]

    if is_hw_codec:
        # Use codec-specific hwaccel for decode acceleration
        hwaccel_flags = get_hwaccel_input_flags(codec)
        if hwaccel_flags:
            cmd.extend(hwaccel_flags)
    elif settings.get("hw_accel"):
        # Legacy fallback: generic auto hwaccel
        cmd.extend(["-hwaccel", "auto"])

    cmd.extend(["-i", input_path])

    # Video filter (scaling)
    scale = _resolution_scale(settings.get("resolution", "original"))
    if scale:
        cmd.extend(["-vf", f"scale={scale}"])

    # Codec and quality settings
    cmd.extend(["-c:v", codec])

    if is_hw_codec:
        # Use platform-specific quality flags from hardware module
        hw_flags = get_hw_encoder_flags(codec)
        if hw_flags:
            cmd.extend(hw_flags)
        else:
            # Fallback quality flag for unknown HW codecs
            cmd.extend(["-b:v", "5M"])
    else:
        # Software codec: use standard CRF + preset
        preset = settings.get("preset", "slow")
        crf = str(settings.get("crf", 28))
        cmd.extend(["-preset", preset, "-crf", crf])

    # Audio settings
    audio_codec = settings.get("audio_codec", "aac")
    if audio_codec == "copy":
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(["-c:a", audio_codec, "-b:a", settings.get("audio_bitrate", "128k")])

    if settings.get("preserve_metadata", True):
        cmd.extend(["-map_metadata", "0"])

    cmd.append(output_path)
    return cmd


def _run_ffmpeg(
    cmd: List[str],
    should_cancel: Optional[Callable[[], bool]],
    progress_callback: Optional[Callable[[int, str], None]],
    on_process: Optional[Callable[[subprocess.Popen], None]],
) -> None:
    """Execute an FFmpeg command with progress tracking and cancellation support."""
    duration: Optional[float] = None
    proc = subprocess.Popen(
        cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    if on_process:
        on_process(proc)

    try:
        assert proc.stderr is not None
        for line in proc.stderr:
            if should_cancel and should_cancel():
                proc.terminate()
                proc.wait(timeout=5)
                raise InterruptedError("Video compression cancelled")

            if duration is None:
                duration = _parse_duration(line)
            current = _parse_time(line)
            if current is not None and duration and duration > 0 and progress_callback:
                pct = min(99, int((current / duration) * 100))
                progress_callback(pct, f"Encoding {pct}%")

        proc.wait()
        if proc.returncode != 0:
            if should_cancel and should_cancel():
                raise InterruptedError("Video compression cancelled")
            raise RuntimeError(f"FFmpeg failed with code {proc.returncode}")
    except Exception:
        proc.kill()
        raise


def compress_video(
    input_path: str,
    output_path: str,
    settings: Dict[str, Any],
    progress_callback: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> Tuple[str, str, str, int, int, float]:
    """Compress a video atomically with automatic HW-to-SW fallback.

    If a hardware encoder fails at runtime (driver issue, unsupported input),
    automatically retries with libx265 software encoding.
    Returns (out_path, input_hash, output_hash, input_size, output_size, ratio).
    """
    if not is_video_file(input_path):
        raise ValueError(f"Not a valid video file: {input_path}")

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not in PATH")

    out_path = get_output_path(output_path, settings)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if progress_callback:
        progress_callback(5, "Computing input hash")

    # Pass cancellation callback to hash computation so large file
    # hashing can be interrupted without waiting for full file read.
    input_hash = compute_file_hash(input_path, should_cancel=should_cancel)
    input_size = os.path.getsize(input_path)

    fd, tmp_path = tempfile.mkstemp(
        suffix=os.path.splitext(out_path)[1],
        dir=os.path.dirname(out_path) or ".",
    )
    os.close(fd)

    codec = settings.get("codec", "libx265")
    is_hw = codec in _HW_CODECS

    try:
        cmd = _build_ffmpeg_cmd(input_path, tmp_path, settings)
        logger.info("FFmpeg command: %s", " ".join(cmd))
        _run_ffmpeg(cmd, should_cancel, progress_callback, on_process)
    except (RuntimeError, OSError) as e:
        # If HW encoder failed, retry with software fallback
        if is_hw and not (should_cancel and should_cancel()):
            logger.warning(
                "HW encoder %s failed (%s), falling back to libx265", codec, e
            )
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            # Rebuild tmp file
            fd, tmp_path = tempfile.mkstemp(
                suffix=os.path.splitext(out_path)[1],
                dir=os.path.dirname(out_path) or ".",
            )
            os.close(fd)
            # Retry with software settings
            sw_settings = dict(settings, codec="libx265", hw_accel=False, preset="slow")
            cmd = _build_ffmpeg_cmd(input_path, tmp_path, sw_settings)
            logger.info("Fallback FFmpeg command: %s", " ".join(cmd))
            if progress_callback:
                progress_callback(10, "Retrying with software encoder")
            _run_ffmpeg(cmd, should_cancel, progress_callback, on_process)
        else:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    try:
        if progress_callback:
            progress_callback(99, "Finalizing")
        os.replace(tmp_path, out_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    output_size = os.path.getsize(out_path)
    output_hash = compute_file_hash(out_path)
    ratio = output_size / input_size if input_size > 0 else 0

    if progress_callback:
        progress_callback(100, "Complete")

    return out_path, input_hash, output_hash, input_size, output_size, ratio
