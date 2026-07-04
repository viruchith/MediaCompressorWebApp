from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Job:
    id: int
    input_folder: str
    output_folder: str
    image_settings: str
    video_settings: str
    profile: Optional[str]
    status: str
    created_at: str
    completed_at: Optional[str]
    total_files: int
    completed_files: int
    failed_files: int
    cancelled_files: int = 0
    image_profile: Optional[str] = None
    video_profile: Optional[str] = None

    def resolved_image_profile(self) -> str:
        return self.image_profile or self.profile or "balanced"

    def resolved_video_profile(self) -> str:
        return self.video_profile or self.profile or "balanced"

    def to_dict(self) -> Dict[str, Any]:
        image_profile = self.resolved_image_profile()
        video_profile = self.resolved_video_profile()
        return {
            "id": self.id,
            "input_folder": self.input_folder,
            "output_folder": self.output_folder,
            "image_settings": self.image_settings,
            "video_settings": self.video_settings,
            "profile": self.profile,
            "image_profile": image_profile,
            "video_profile": video_profile,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "total_files": self.total_files,
            "completed_files": self.completed_files,
            "failed_files": self.failed_files,
            "cancelled_files": self.cancelled_files,
        }


@dataclass
class FileRecord:
    id: int
    job_id: int
    input_file_path: str
    output_file_path: Optional[str]
    file_type: str
    status: int
    priority: int
    retry_count: int
    max_retries: int
    error_message: Optional[str]
    input_size: Optional[int]
    output_size: Optional[int]
    input_hash: Optional[str]
    output_hash: Optional[str]
    compression_ratio: Optional[float]
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "input_file_path": self.input_file_path,
            "output_file_path": self.output_file_path,
            "file_type": self.file_type,
            "status": self.status,
            "status_label": status_label(self.status),
            "priority": self.priority,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error_message": self.error_message,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "compression_ratio": self.compression_ratio,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
        }

    def to_legacy_tuple(self) -> tuple:
        """Backward-compatible tuple for old /files endpoint."""
        return (self.id, self.input_file_path, self.output_file_path or "", self.status)


def status_label(status: int) -> str:
    labels = {
        0: "pending",
        1: "completed",
        -1: "error",
        2: "processing",
        -2: "permanent_fail",
        -3: "cancelled",
    }
    return labels.get(status, "unknown")


@dataclass
class PaginatedResult:
    items: List[Any]
    page: int
    limit: int
    total: int
    pages: int

    def to_dict(self, item_key: str = "items") -> Dict[str, Any]:
        return {
            item_key: self.items,
            "page": self.page,
            "limit": self.limit,
            "total": self.total,
            "pages": self.pages,
        }
