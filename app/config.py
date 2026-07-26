import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DB_PATH: str = os.getenv("DB_PATH", "file_db.db")
    WORKER_COUNT_IMAGES: int = int(os.getenv("WORKER_COUNT_IMAGES", "4"))
    WORKER_COUNT_VIDEOS: int = int(os.getenv("WORKER_COUNT_VIDEOS", "2"))
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    PROCESSING_TIMEOUT_MINUTES: int = int(os.getenv("PROCESSING_TIMEOUT_MINUTES", "30"))
    # Minimum free disk space (in MB) required before starting a compression task.
    # Workers will fail files early if available space drops below this threshold.
    MIN_FREE_DISK_MB: int = int(os.getenv("MIN_FREE_DISK_MB", "100"))
    # When True, override static WORKER_COUNT_* with hardware-detected recommendations.
    AUTO_SCALE: bool = os.getenv("AUTO_SCALE", "true").lower() in ("1", "true", "yes")
    # Hardware acceleration mode: "auto" (detect), "force" (always use HW), "off" (SW only)
    HW_ACCEL_MODE: str = os.getenv("HW_ACCEL_MODE", "auto")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON: bool = os.getenv("LOG_JSON", "false").lower() in ("1", "true", "yes")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/app.log")
    LOG_MAX_BYTES: int = int(os.getenv("LOG_MAX_BYTES", str(10 * 1024 * 1024)))
    LOG_BACKUP_COUNT: int = int(os.getenv("LOG_BACKUP_COUNT", "5"))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))

    # File status constants
    STATUS_PENDING = 0
    STATUS_COMPLETED = 1
    STATUS_ERROR = -1
    STATUS_PROCESSING = 2
    STATUS_PERMANENT_FAIL = -2
    STATUS_CANCELLED = -3

    SUPPORTED_IMAGE_EXTENSIONS = frozenset({
        "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "dng", "raw",
        "cr2", "nef", "arw", "orf", "sr2", "raf", "rw2", "pef", "srw", "heic", "avif",
    })
    SUPPORTED_VIDEO_EXTENSIONS = frozenset({
        "mp4", "mov", "avi", "mkv", "webm", "flv", "wmv", "m4v", "3gp", "mpeg", "mpg",
    })


config = Config()
