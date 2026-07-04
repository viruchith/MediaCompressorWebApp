"""Application metadata — version is read from the VERSION file at project root."""

from pathlib import Path

APP_NAME = "MediaCompressorWebApp"
APP_AUTHOR = "Viruchith Ganesan"
APP_COPYRIGHT_YEAR = "2025-2026"
GITHUB_URL = "https://github.com/viruchith/MediaCompressorWebApp"

_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def _read_version() -> str:
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


VERSION = _read_version()
__version__ = VERSION
