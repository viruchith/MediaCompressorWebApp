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
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_JSON: bool = os.getenv("LOG_JSON", "false").lower() in ("1", "true", "yes")
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "5000"))

    # File status constants
    STATUS_PENDING = 0
    STATUS_COMPLETED = 1
    STATUS_ERROR = -1
    STATUS_PROCESSING = 2
    STATUS_PERMANENT_FAIL = -2

    SUPPORTED_IMAGE_EXTENSIONS = frozenset({
        "jpg", "jpeg", "png", "gif", "bmp", "tiff", "tif", "webp", "dng", "raw",
        "cr2", "nef", "arw", "orf", "sr2", "raf", "rw2", "pef", "srw", "heic", "avif",
    })
    SUPPORTED_VIDEO_EXTENSIONS = frozenset({
        "mp4", "mov", "avi", "mkv", "webm", "flv", "wmv", "m4v", "3gp", "mpeg", "mpg",
    })


config = Config()
