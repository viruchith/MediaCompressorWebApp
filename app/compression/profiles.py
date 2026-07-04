"""Compression preset profiles."""

PROFILES = {
    "archival_lossless": {
        "description": "Lossless compression for long-term archival",
        "image": {
            "quality": 100,
            "lossless": True,
            "output_format": "png",
            "strip_metadata": False,
        },
        "video": {
            "codec": "libx265",
            "crf": 0,
            "preset": "veryslow",
            "audio_codec": "copy",
            "container": "mkv",
        },
    },
    "archival_visually_lossless": {
        "description": "Near-lossless with significant size reduction",
        "image": {
            "quality": 95,
            "output_format": "webp",
            "strip_metadata": False,
        },
        "video": {
            "codec": "libx265",
            "crf": 18,
            "preset": "slow",
            "audio_codec": "aac",
            "audio_bitrate": "192k",
            "container": "mkv",
        },
    },
    "balanced": {
        "description": "Good balance of quality and file size",
        "image": {
            "quality": 75,
            "output_format": "webp",
            "strip_metadata": False,
        },
        "video": {
            "codec": "libx265",
            "crf": 28,
            "preset": "slow",
            "audio_codec": "aac",
            "audio_bitrate": "128k",
            "container": "mkv",
        },
    },
    "web_optimized": {
        "description": "Optimized for web delivery",
        "image": {
            "quality": 60,
            "output_format": "webp",
            "max_dimension": 1920,
            "strip_metadata": True,
        },
        "video": {
            "codec": "libx264",
            "crf": 23,
            "preset": "medium",
            "audio_codec": "aac",
            "audio_bitrate": "128k",
            "container": "mp4",
        },
    },
    "mobile_friendly": {
        "description": "Small files for mobile devices",
        "image": {
            "quality": 70,
            "output_format": "webp",
            "max_dimension": 1080,
            "strip_metadata": True,
        },
        "video": {
            "codec": "libx264",
            "crf": 28,
            "preset": "medium",
            "audio_codec": "aac",
            "audio_bitrate": "96k",
            "resolution": "720p",
            "container": "mp4",
        },
    },
    "maximum_compression": {
        "description": "Smallest possible files (lower quality)",
        "image": {
            "quality": 40,
            "output_format": "webp",
            "max_dimension": 1920,
            "strip_metadata": True,
        },
        "video": {
            "codec": "libx265",
            "crf": 35,
            "preset": "veryslow",
            "audio_codec": "opus",
            "audio_bitrate": "64k",
            "resolution": "720p",
            "container": "mkv",
        },
    },
}
