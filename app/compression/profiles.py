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
            "quality": 88,
            "output_format": "webp",
            "strip_metadata": False,
        },
        "video": {
            "codec": "libx265",
            "crf": 18,
            "preset": "slow",
            "pix_fmt": "yuv420p10le",
            "audio_codec": "aac",
            "audio_bitrate": "256k",
            "container": "mkv",
        },
    },
    "balanced": {
        "description": "Good balance of quality and file size",
        "image": {
            "quality": 80,
            "output_format": "webp",
            "strip_metadata": False,
        },
        "video": {
            "codec": "libx265",
            "crf": 22,
            "preset": "slow",
            "pix_fmt": "yuv420p10le",
            "audio_codec": "aac",
            "audio_bitrate": "128k",
            "container": "mkv",
        },
    },
    "web_optimized": {
        "description": "Optimized for web delivery",
        "image": {
            "quality": 72,
            "output_format": "webp",
            "max_dimension": 1920,
            "strip_metadata": True,
        },
        "video": {
            "codec": "libx264",
            "crf": 20,
            "preset": "slow",
            "pix_fmt": "yuv420p",
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
            "crf": 24,
            "preset": "medium",
            "pix_fmt": "yuv420p",
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
            "crf": 30,
            "preset": "veryslow",
            "pix_fmt": "yuv420p10le",
            "audio_codec": "opus",
            "audio_bitrate": "64k",
            "resolution": "720p",
            "container": "mkv",
        },
    },
    "photo_print": {
        "description": "Maximum fidelity for print-quality photo archival (lossless WebP, full metadata)",
        "image": {
            "quality": 100,
            "lossless": True,
            "output_format": "webp",
            "strip_metadata": False,
        },
        "video": {
            "codec": "libx265",
            "crf": 16,
            "preset": "slow",
            "pix_fmt": "yuv420p10le",
            "audio_codec": "copy",
            "container": "mkv",
        },
    },
}
