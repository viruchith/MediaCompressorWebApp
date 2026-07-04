"""Compression settings validation and merging."""

from copy import deepcopy
from typing import Any, Dict, Optional, Tuple

from app.compression.profiles import PROFILES

IMAGE_FORMATS = frozenset({"webp", "jpeg", "jpg", "png", "avif"})
VIDEO_CODECS = frozenset({"libx265", "libx264", "libsvtav1", "libvpx-vp9"})
VIDEO_CONTAINERS = frozenset({"mkv", "mp4", "webm"})
VIDEO_PRESETS = frozenset({
    "ultrafast", "superfast", "veryfast", "faster", "fast",
    "medium", "slow", "slower", "veryslow",
})
AUDIO_CODECS = frozenset({"aac", "opus", "copy"})
VIDEO_RESOLUTIONS = frozenset({"original", "1080p", "720p", "480p", "360p"})

DEFAULT_IMAGE_SETTINGS: Dict[str, Any] = {
    "quality": 75,
    "output_format": "webp",
    "max_dimension": None,
    "strip_metadata": False,
    "lossless": False,
}

DEFAULT_VIDEO_SETTINGS: Dict[str, Any] = {
    "codec": "libx265",
    "container": "mkv",
    "crf": 28,
    "preset": "slow",
    "audio_codec": "aac",
    "audio_bitrate": "128k",
    "resolution": "original",
    "hw_accel": False,
    "preserve_metadata": True,
}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def validate_image_settings(settings: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
    errors = []
    result = deepcopy(DEFAULT_IMAGE_SETTINGS)

    if "quality" in settings:
        try:
            result["quality"] = _clamp(int(settings["quality"]), 1, 100)
        except (TypeError, ValueError):
            errors.append("image.quality must be an integer 1-100")

    if "output_format" in settings:
        fmt = str(settings["output_format"]).lower()
        if fmt == "jpg":
            fmt = "jpeg"
        if fmt not in IMAGE_FORMATS:
            errors.append(f"image.output_format must be one of {sorted(IMAGE_FORMATS)}")
        else:
            result["output_format"] = fmt

    if "max_dimension" in settings and settings["max_dimension"] is not None:
        try:
            dim = int(settings["max_dimension"])
            if dim < 1:
                errors.append("image.max_dimension must be positive")
            else:
                result["max_dimension"] = dim
        except (TypeError, ValueError):
            errors.append("image.max_dimension must be an integer")

    if "strip_metadata" in settings:
        result["strip_metadata"] = bool(settings["strip_metadata"])

    if "lossless" in settings:
        result["lossless"] = bool(settings["lossless"])

    return result, errors


def validate_video_settings(settings: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
    errors = []
    result = deepcopy(DEFAULT_VIDEO_SETTINGS)

    if "codec" in settings:
        codec = str(settings["codec"])
        if codec not in VIDEO_CODECS:
            errors.append(f"video.codec must be one of {sorted(VIDEO_CODECS)}")
        else:
            result["codec"] = codec

    if "container" in settings:
        container = str(settings["container"]).lower()
        if container not in VIDEO_CONTAINERS:
            errors.append(f"video.container must be one of {sorted(VIDEO_CONTAINERS)}")
        else:
            result["container"] = container

    if "crf" in settings:
        try:
            result["crf"] = _clamp(int(settings["crf"]), 0, 51)
        except (TypeError, ValueError):
            errors.append("video.crf must be an integer 0-51")

    if "preset" in settings:
        preset = str(settings["preset"])
        if preset not in VIDEO_PRESETS:
            errors.append(f"video.preset must be one of {sorted(VIDEO_PRESETS)}")
        else:
            result["preset"] = preset

    if "audio_codec" in settings:
        ac = str(settings["audio_codec"])
        if ac not in AUDIO_CODECS:
            errors.append(f"video.audio_codec must be one of {sorted(AUDIO_CODECS)}")
        else:
            result["audio_codec"] = ac

    if "audio_bitrate" in settings:
        result["audio_bitrate"] = str(settings["audio_bitrate"])

    if "resolution" in settings:
        res = str(settings["resolution"]).lower()
        if res not in VIDEO_RESOLUTIONS:
            errors.append(f"video.resolution must be one of {sorted(VIDEO_RESOLUTIONS)}")
        else:
            result["resolution"] = res

    if "hw_accel" in settings:
        result["hw_accel"] = bool(settings["hw_accel"])

    if "preserve_metadata" in settings:
        result["preserve_metadata"] = bool(settings["preserve_metadata"])

    return result, errors


def get_effective_settings(
    profile_name: Optional[str] = None,
    user_image_overrides: Optional[Dict[str, Any]] = None,
    user_video_overrides: Optional[Dict[str, Any]] = None,
    preserve_metadata: bool = True,
) -> Tuple[Dict[str, Any], Dict[str, Any], list]:
    """Merge profile defaults with user overrides. Returns (image, video, errors)."""
    image_base = deepcopy(DEFAULT_IMAGE_SETTINGS)
    video_base = deepcopy(DEFAULT_VIDEO_SETTINGS)
    video_base["preserve_metadata"] = preserve_metadata

    if profile_name:
        profile = PROFILES.get(profile_name)
        if not profile:
            return image_base, video_base, [f"Unknown profile: {profile_name}"]
        image_base.update(deepcopy(profile.get("image", {})))
        video_base.update(deepcopy(profile.get("video", {})))

    image_overrides = user_image_overrides or {}
    video_overrides = user_video_overrides or {}

    image_settings, img_errors = validate_image_settings({**image_base, **image_overrides})
    video_settings, vid_errors = validate_video_settings({**video_base, **video_overrides})

    if not preserve_metadata:
        image_settings["strip_metadata"] = True
    else:
        image_settings["strip_metadata"] = False

    video_settings["preserve_metadata"] = preserve_metadata

    return image_settings, video_settings, img_errors + vid_errors
