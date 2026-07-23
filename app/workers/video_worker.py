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
    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg_bin, "-y", "-hide_banner", "-i", input_path]

    if settings.get("hw_accel"):
        cmd.extend(["-hwaccel", "auto"])

    codec = settings.get("codec", "libx265")
    preset = settings.get("preset", "slow")
    crf = str(settings.get("crf", 28))

    scale = _resolution_scale(settings.get("resolution", "original"))
    if scale:
        cmd.extend(["-vf", f"scale={scale}"])

    cmd.extend(["-c:v", codec, "-preset", preset, "-crf", crf])

    audio_codec = settings.get("audio_codec", "aac")
    if audio_codec == "copy":
        cmd.extend(["-c:a", "copy"])
    else:
        cmd.extend(["-c:a", audio_codec, "-b:a", settings.get("audio_bitrate", "128k")])

    if settings.get("preserve_metadata", True):
        cmd.extend(["-map_metadata", "0"])

    cmd.append(output_path)
    return cmd


def compress_video(
    input_path: str,
    output_path: str,
    settings: Dict[str, Any],
    progress_callback: Optional[Callable[[int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    on_process: Optional[Callable[[subprocess.Popen], None]] = None,
) -> Tuple[str, str, str, int, int, float]:
    """Compress a video atomically. Returns (out_path, input_hash, output_hash, sizes, ratio)."""
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

    cmd = _build_ffmpeg_cmd(input_path, tmp_path, settings)
    logger.info("FFmpeg command: %s", " ".join(cmd))

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

        if progress_callback:
            progress_callback(99, "Finalizing")

        os.replace(tmp_path, out_path)
    except Exception:
        proc.kill()
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    output_size = os.path.getsize(out_path)
    output_hash = compute_file_hash(out_path)
    ratio = output_size / input_size if input_size > 0 else 0

    if progress_callback:
        progress_callback(100, "Complete")

    return out_path, input_hash, output_hash, input_size, output_size, ratio
