import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db import get_job, list_files_for_job
from app.models import status_label


def _format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 ** 2:
        return f"{size / 1024:.1f} KB"
    if size < 1024 ** 3:
        return f"{size / (1024 ** 2):.1f} MB"
    return f"{size / (1024 ** 3):.2f} GB"


def build_job_manifest(job_id: int) -> Optional[Dict[str, Any]]:
    job = get_job(job_id)
    if not job:
        return None

    files = list_files_for_job(job_id, page=1, limit=1_000_000)
    file_entries = []
    total_input = 0
    total_output = 0
    completed = 0
    failed = 0

    for f in files.items:
        inp = f.input_size or 0
        out = f.output_size or 0
        total_input += inp
        total_output += out
        if f.status == 1:
            completed += 1
        elif f.status in (-1, -2):
            failed += 1

        file_entries.append({
            "input_path": f.input_file_path,
            "output_path": f.output_file_path,
            "input_size_bytes": f.input_size,
            "output_size_bytes": f.output_size,
            "compression_ratio": f.compression_ratio,
            "input_sha256": f.input_hash,
            "output_sha256": f.output_hash,
            "status": status_label(f.status),
            "error_message": f.error_message,
            "completed_at": f.completed_at,
        })

    overall_ratio = (total_output / total_input) if total_input > 0 else None

    return {
        "job_id": job.id,
        "created_at": job.created_at,
        "profile": job.profile,
        "settings": {
            "image": json.loads(job.image_settings) if job.image_settings else {},
            "video": json.loads(job.video_settings) if job.video_settings else {},
        },
        "files": file_entries,
        "summary": {
            "total_files": job.total_files,
            "completed": completed,
            "failed": failed,
            "total_input_size": _format_bytes(total_input),
            "total_output_size": _format_bytes(total_output),
            "total_input_bytes": total_input,
            "total_output_bytes": total_output,
            "overall_compression_ratio": round(overall_ratio, 4) if overall_ratio else None,
        },
    }


def save_manifest_to_output_folder(job_id: int) -> Optional[str]:
    manifest = build_job_manifest(job_id)
    if not manifest:
        return None

    job = get_job(job_id)
    if not job:
        return None

    os.makedirs(job.output_folder, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(job.output_folder, f"compression_manifest_{job_id}_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return path
