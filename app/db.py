import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.config import config
from app.models import FileRecord, Job, PaginatedResult

logger = logging.getLogger(__name__)

local = threading.local()
CURRENT_SCHEMA_VERSION = 1

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_folder TEXT NOT NULL,
    output_folder TEXT NOT NULL,
    image_settings TEXT NOT NULL DEFAULT '{}',
    video_settings TEXT NOT NULL DEFAULT '{}',
    profile TEXT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    total_files INTEGER DEFAULT 0,
    completed_files INTEGER DEFAULT 0,
    failed_files INTEGER DEFAULT 0,
    cancelled_files INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    input_file_path TEXT NOT NULL UNIQUE,
    output_file_path TEXT NULL,
    file_type TEXT NOT NULL,
    status INTEGER NOT NULL DEFAULT 0,
    priority INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_message TEXT NULL,
    input_size INTEGER NULL,
    output_size INTEGER NULL,
    input_hash TEXT NULL,
    output_hash TEXT NULL,
    compression_ratio REAL NULL,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
CREATE INDEX IF NOT EXISTS idx_files_job_id ON files(job_id);
CREATE INDEX IF NOT EXISTS idx_files_priority ON files(priority DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def get_db() -> sqlite3.Connection:
    if not hasattr(local, "conn") or local.conn is None:
        local.conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        local.conn.row_factory = sqlite3.Row
        local.conn.execute("PRAGMA journal_mode=WAL;")
        local.conn.execute("PRAGMA foreign_keys=ON;")
    return local.conn


def close_db():
    if hasattr(local, "conn") and local.conn is not None:
        local.conn.close()
        local.conn = None


def _table_columns(conn: sqlite3.Connection, table: str) -> set:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row[1] for row in rows}


def _get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        return row[0] if row and row[0] is not None else 0
    except sqlite3.OperationalError:
        return 0


def _infer_file_type(path: str) -> str:
    ext = os.path.splitext(path)[1][1:].lower()
    if ext in config.SUPPORTED_VIDEO_EXTENSIONS:
        return "video"
    return "image"


def _migrate_v0_to_v1(conn: sqlite3.Connection):
    """Migrate legacy single-table schema to jobs + files."""
    logger.info("Migrating database from v0 to v1...")

    conn.execute("ALTER TABLE files RENAME TO files_legacy")

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        input_folder TEXT NOT NULL,
        output_folder TEXT NOT NULL,
        image_settings TEXT NOT NULL DEFAULT '{}',
        video_settings TEXT NOT NULL DEFAULT '{}',
        profile TEXT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP NULL,
        total_files INTEGER DEFAULT 0,
        completed_files INTEGER DEFAULT 0,
        failed_files INTEGER DEFAULT 0,
        cancelled_files INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL REFERENCES jobs(id),
        input_file_path TEXT NOT NULL UNIQUE,
        output_file_path TEXT NULL,
        file_type TEXT NOT NULL,
        status INTEGER NOT NULL DEFAULT 0,
        priority INTEGER DEFAULT 0,
        retry_count INTEGER DEFAULT 0,
        max_retries INTEGER DEFAULT 3,
        error_message TEXT NULL,
        input_size INTEGER NULL,
        output_size INTEGER NULL,
        input_hash TEXT NULL,
        output_hash TEXT NULL,
        compression_ratio REAL NULL,
        started_at TIMESTAMP NULL,
        completed_at TIMESTAMP NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);
    CREATE INDEX IF NOT EXISTS idx_files_job_id ON files(job_id);
    CREATE INDEX IF NOT EXISTS idx_files_priority ON files(priority DESC, created_at ASC);
    """)

    cursor = conn.execute(
        "SELECT id, input_file_path, output_file_path, compressed FROM files_legacy"
    )
    legacy_rows = cursor.fetchall()

    if legacy_rows:
        conn.execute(
            """INSERT INTO jobs (input_folder, output_folder, image_settings, video_settings,
               profile, status, total_files)
               VALUES (?, ?, '{}', '{}', 'balanced', 'active', ?)""",
            ("migrated", "migrated", len(legacy_rows)),
        )
        job_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        for row in legacy_rows:
            inp = row["input_file_path"]
            out = row["output_file_path"]
            status = row["compressed"]
            conn.execute(
                """INSERT INTO files
                   (job_id, input_file_path, output_file_path, file_type, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (job_id, inp, out, _infer_file_type(inp), status),
            )

    conn.execute("DROP TABLE files_legacy")
    conn.execute("INSERT OR IGNORE INTO schema_version (version) VALUES (1)")
    conn.commit()
    logger.info("Migration v0 -> v1 complete (%d legacy files)", len(legacy_rows))


def _ensure_schema_updates(conn: sqlite3.Connection):
    """Apply incremental schema updates without full version bump."""
    job_cols = _table_columns(conn, "jobs")
    if "cancelled_files" not in job_cols:
        conn.execute(
            "ALTER TABLE jobs ADD COLUMN cancelled_files INTEGER DEFAULT 0"
        )
        conn.commit()
        logger.info("Added jobs.cancelled_files column")


def init_db():
    conn = get_db()
    version = _get_schema_version(conn)

    if version == 0:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "files" in tables:
            old_cols = _table_columns(conn, "files")
            if "compressed" in old_cols and "job_id" not in old_cols:
                _migrate_v0_to_v1(conn)
                _ensure_schema_updates(conn)
                crash_recovery(conn)
                return
        conn.executescript(SCHEMA_V1)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (CURRENT_SCHEMA_VERSION,),
        )
        conn.commit()
    elif version < CURRENT_SCHEMA_VERSION:
        conn.executescript(SCHEMA_V1)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version) VALUES (?)",
            (CURRENT_SCHEMA_VERSION,),
        )
        conn.commit()

    _ensure_schema_updates(conn)
    crash_recovery(conn)


def crash_recovery(conn: Optional[sqlite3.Connection] = None):
    """Reset stale processing files on startup."""
    conn = conn or get_db()
    timeout_minutes = config.PROCESSING_TIMEOUT_MINUTES
    cutoff = (datetime.utcnow() - timedelta(minutes=timeout_minutes)).isoformat()

    conn.execute(
        """UPDATE files SET status = ?, started_at = NULL,
           retry_count = retry_count + 1,
           error_message = 'Reset after crash or timeout'
           WHERE status = ?""",
        (config.STATUS_PENDING, config.STATUS_PROCESSING),
    )

    conn.execute(
        """UPDATE files SET status = ?, started_at = NULL,
           retry_count = retry_count + 1,
           error_message = 'Reset after processing timeout'
           WHERE status = ? AND started_at IS NOT NULL AND started_at < ?""",
        (config.STATUS_PENDING, config.STATUS_PROCESSING, cutoff),
    )

    conn.execute(
        """UPDATE files SET status = ?, error_message = 'Max retries exceeded'
           WHERE status = ? AND retry_count >= max_retries""",
        (config.STATUS_PERMANENT_FAIL, config.STATUS_PENDING),
    )

    conn.commit()
    logger.info("Crash recovery completed")


def reset_processing_on_shutdown():
    """Mark all in-flight files back to pending for graceful shutdown."""
    conn = get_db()
    conn.execute(
        "UPDATE files SET status = ?, started_at = NULL WHERE status = ?",
        (config.STATUS_PENDING, config.STATUS_PROCESSING),
    )
    conn.commit()
    logger.info("Graceful shutdown: reset processing files to pending")


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        input_folder=row["input_folder"],
        output_folder=row["output_folder"],
        image_settings=row["image_settings"],
        video_settings=row["video_settings"],
        profile=row["profile"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        total_files=row["total_files"],
        completed_files=row["completed_files"],
        failed_files=row["failed_files"],
        cancelled_files=row["cancelled_files"] if "cancelled_files" in row.keys() else 0,
    )


def _row_to_file(row: sqlite3.Row) -> FileRecord:
    return FileRecord(
        id=row["id"],
        job_id=row["job_id"],
        input_file_path=row["input_file_path"],
        output_file_path=row["output_file_path"],
        file_type=row["file_type"],
        status=row["status"],
        priority=row["priority"],
        retry_count=row["retry_count"],
        max_retries=row["max_retries"],
        error_message=row["error_message"],
        input_size=row["input_size"],
        output_size=row["output_size"],
        input_hash=row["input_hash"],
        output_hash=row["output_hash"],
        compression_ratio=row["compression_ratio"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        created_at=row["created_at"],
    )


def get_queue_counts() -> Dict[str, int]:
    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status = ?", (config.STATUS_PENDING,)
        ).fetchone()[0]
        processing = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status = ?", (config.STATUS_PROCESSING,)
        ).fetchone()[0]
        completed = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status = ?", (config.STATUS_COMPLETED,)
        ).fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status IN (?, ?)",
            (config.STATUS_ERROR, config.STATUS_PERMANENT_FAIL),
        ).fetchone()[0]
        cancelled = conn.execute(
            "SELECT COUNT(*) FROM files WHERE status = ?", (config.STATUS_CANCELLED,)
        ).fetchone()[0]
        return {
            "total": total,
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "errors": errors,
            "cancelled": cancelled,
        }
    except Exception as e:
        logger.error("Error getting queue counts: %s", e)
        return {
            "total": 0, "pending": 0, "processing": 0,
            "completed": 0, "errors": 0, "cancelled": 0,
        }


def create_job(
    input_folder: str,
    output_folder: str,
    image_settings: dict,
    video_settings: dict,
    profile: Optional[str],
    priority: int = 0,
) -> int:
    conn = get_db()
    cursor = conn.execute(
        """INSERT INTO jobs (input_folder, output_folder, image_settings, video_settings, profile)
           VALUES (?, ?, ?, ?, ?)""",
        (
            input_folder,
            output_folder,
            json.dumps(image_settings),
            json.dumps(video_settings),
            profile,
        ),
    )
    job_id = cursor.lastrowid
    conn.commit()
    return job_id


def add_files_batch(job_id: int, files: List[Tuple], priority: int = 0, max_retries: int = 3):
    """Batch insert files. Each tuple: (input_path, output_path, file_type)."""
    conn = get_db()
    conn.executemany(
        """INSERT OR IGNORE INTO files
           (job_id, input_file_path, output_file_path, file_type, priority, max_retries)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (job_id, inp, out, ftype, priority, max_retries)
            for inp, out, ftype in files
        ],
    )
    added = conn.execute(
        "SELECT COUNT(*) FROM files WHERE job_id = ?", (job_id,)
    ).fetchone()[0]
    conn.execute(
        "UPDATE jobs SET total_files = ? WHERE id = ?", (added, job_id)
    )
    _maybe_complete_job(conn, job_id)
    conn.commit()
    return added


def get_job(job_id: int) -> Optional[Job]:
    row = get_db().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(page: int = 1, limit: int = 20) -> PaginatedResult:
    conn = get_db()
    offset = (page - 1) * limit
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    pages = max(1, (total + limit - 1) // limit)
    return PaginatedResult(
        items=[_row_to_job(r).to_dict() for r in rows],
        page=page,
        limit=limit,
        total=total,
        pages=pages,
    )


def list_files_for_job(
    job_id: int,
    page: int = 1,
    limit: int = 50,
    status: Optional[int] = None,
    search: Optional[str] = None,
) -> PaginatedResult:
    conn = get_db()
    conditions = ["job_id = ?"]
    params: list = [job_id]

    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    if search:
        conditions.append("input_file_path LIKE ?")
        params.append(f"%{search}%")

    where = " AND ".join(conditions)
    total = conn.execute(f"SELECT COUNT(*) FROM files WHERE {where}", params).fetchone()[0]
    offset = (page - 1) * limit
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM files WHERE {where} ORDER BY id ASC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    pages = max(1, (total + limit - 1) // limit)
    return PaginatedResult(
        items=[_row_to_file(r) for r in rows],
        page=page,
        limit=limit,
        total=total,
        pages=pages,
    )


def list_all_files(
    page: int = 1,
    limit: int = 50,
    status: Optional[int] = None,
) -> PaginatedResult:
    conn = get_db()
    conditions = []
    params: list = []
    if status is not None:
        conditions.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    total = conn.execute(f"SELECT COUNT(*) FROM files {where}", params).fetchone()[0]
    offset = (page - 1) * limit
    params.extend([limit, offset])
    rows = conn.execute(
        f"SELECT * FROM files {where} ORDER BY priority DESC, created_at ASC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    pages = max(1, (total + limit - 1) // limit)
    return PaginatedResult(
        items=[_row_to_file(r) for r in rows],
        page=page,
        limit=limit,
        total=total,
        pages=pages,
    )


def get_file(file_id: int) -> Optional[FileRecord]:
    row = get_db().execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    return _row_to_file(row) if row else None


def get_pending_files(limit: int = 50) -> List[FileRecord]:
    rows = get_db().execute(
        """SELECT f.* FROM files f
           JOIN jobs j ON f.job_id = j.id
           WHERE f.status = ? AND j.status = 'active'
           ORDER BY f.priority DESC, f.created_at ASC
           LIMIT ?""",
        (config.STATUS_PENDING, limit),
    ).fetchall()
    return [_row_to_file(r) for r in rows]


def claim_file(file_id: int) -> bool:
    """Atomically claim a file for processing."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    cursor = conn.execute(
        """UPDATE files SET status = ?, started_at = ?
           WHERE id = ? AND status = ?""",
        (config.STATUS_PROCESSING, now, file_id, config.STATUS_PENDING),
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_file_completed(
    file_id: int,
    output_path: str,
    output_size: int,
    output_hash: str,
    input_size: int,
    input_hash: str,
    compression_ratio: float,
):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """UPDATE files SET status = ?, output_file_path = ?, output_size = ?,
           output_hash = ?, input_size = ?, input_hash = ?,
           compression_ratio = ?, completed_at = ?, error_message = NULL
           WHERE id = ?""",
        (
            config.STATUS_COMPLETED, output_path, output_size, output_hash,
            input_size, input_hash, compression_ratio, now, file_id,
        ),
    )
    file_row = conn.execute("SELECT job_id FROM files WHERE id = ?", (file_id,)).fetchone()
    if file_row:
        job_id = file_row["job_id"]
        conn.execute(
            "UPDATE jobs SET completed_files = completed_files + 1 WHERE id = ?",
            (job_id,),
        )
        _maybe_complete_job(conn, job_id)
    conn.commit()


def mark_file_failed(file_id: int, error_message: str, permanent: bool = False):
    conn = get_db()
    conn.execute(
        """UPDATE files SET status = ?, error_message = ?,
           retry_count = retry_count + 1 WHERE id = ?""",
        (
            config.STATUS_PERMANENT_FAIL if permanent else config.STATUS_ERROR,
            error_message,
            file_id,
        ),
    )
    file_row = conn.execute("SELECT job_id FROM files WHERE id = ?", (file_id,)).fetchone()
    if file_row:
        conn.execute(
            "UPDATE jobs SET failed_files = failed_files + 1 WHERE id = ?",
            (file_row["job_id"],),
        )
        _maybe_complete_job(conn, file_row["job_id"])
    conn.commit()


def reset_file_for_retry(file_id: int):
    conn = get_db()
    conn.execute(
        """UPDATE files SET status = ?, error_message = NULL, started_at = NULL
           WHERE id = ?""",
        (config.STATUS_PENDING, file_id),
    )
    conn.commit()


def mark_file_cancelled(file_id: int):
    conn = get_db()
    file_row = conn.execute(
        "SELECT job_id, status FROM files WHERE id = ?", (file_id,)
    ).fetchone()
    if not file_row or file_row["status"] == config.STATUS_CANCELLED:
        return

    conn.execute(
        """UPDATE files SET status = ?, error_message = 'Cancelled by user',
           started_at = NULL WHERE id = ?""",
        (config.STATUS_CANCELLED, file_id),
    )
    conn.execute(
        "UPDATE jobs SET cancelled_files = cancelled_files + 1 WHERE id = ?",
        (file_row["job_id"],),
    )
    _maybe_complete_job(conn, file_row["job_id"])
    conn.commit()


def retry_failed_files(job_id: int) -> int:
    conn = get_db()
    cursor = conn.execute(
        """UPDATE files SET status = ?, error_message = NULL, started_at = NULL,
           retry_count = 0
           WHERE job_id = ? AND status IN (?, ?)""",
        (config.STATUS_PENDING, job_id, config.STATUS_ERROR, config.STATUS_PERMANENT_FAIL),
    )
    conn.execute(
        "UPDATE jobs SET failed_files = 0, status = 'active', completed_at = NULL WHERE id = ?",
        (job_id,),
    )
    conn.commit()
    return cursor.rowcount


def update_job_status(job_id: int, status: str):
    conn = get_db()
    now = datetime.utcnow().isoformat() if status == "completed" else None
    if now:
        conn.execute(
            "UPDATE jobs SET status = ?, completed_at = ? WHERE id = ?",
            (status, now, job_id),
        )
    else:
        conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()


def delete_job(job_id: int) -> bool:
    conn = get_db()
    conn.execute("DELETE FROM files WHERE job_id = ?", (job_id,))
    cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    return cursor.rowcount > 0


def clear_completed_files() -> int:
    conn = get_db()
    cursor = conn.execute(
        "DELETE FROM files WHERE status = ?", (config.STATUS_COMPLETED,)
    )
    conn.commit()
    return cursor.rowcount


def cancel_queue_files() -> int:
    """Mark all pending and processing files as cancelled."""
    conn = get_db()
    job_rows = conn.execute(
        """SELECT DISTINCT job_id FROM files
           WHERE status IN (?, ?)""",
        (config.STATUS_PENDING, config.STATUS_PROCESSING),
    ).fetchall()
    cursor = conn.execute(
        """UPDATE files SET status = ?, error_message = 'Cancelled by user',
           started_at = NULL
           WHERE status IN (?, ?)""",
        (config.STATUS_CANCELLED, config.STATUS_PENDING, config.STATUS_PROCESSING),
    )
    for row in job_rows:
        job_id = row["job_id"]
        conn.execute(
            """UPDATE jobs SET cancelled_files = (
               SELECT COUNT(*) FROM files
               WHERE job_id = ? AND status = ?
            ) WHERE id = ?""",
            (job_id, config.STATUS_CANCELLED, job_id),
        )
        _maybe_complete_job(conn, job_id)
    conn.commit()
    return cursor.rowcount


def flush_database() -> int:
    """Delete all jobs and files, resetting auto-increment counters."""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    jobs_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    conn.execute("DELETE FROM files")
    conn.execute("DELETE FROM jobs")
    try:
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('files', 'jobs')")
    except sqlite3.OperationalError:
        pass
    conn.commit()
    return total + jobs_count


def get_global_stats() -> Dict[str, Any]:
    conn = get_db()
    total_jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    total_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    completed = conn.execute(
        "SELECT COUNT(*) FROM files WHERE status = ?", (config.STATUS_COMPLETED,)
    ).fetchone()[0]
    row = conn.execute(
        """SELECT COALESCE(SUM(input_size), 0), COALESCE(SUM(output_size), 0)
           FROM files WHERE status = ?""",
        (config.STATUS_COMPLETED,),
    ).fetchone()
    input_total = row[0] or 0
    output_total = row[1] or 0
    saved = input_total - output_total
    ratio = (output_total / input_total) if input_total > 0 else None
    return {
        "total_jobs": total_jobs,
        "total_files": total_files,
        "completed_files": completed,
        "total_input_bytes": input_total,
        "total_output_bytes": output_total,
        "bytes_saved": saved,
        "overall_compression_ratio": round(ratio, 4) if ratio else None,
    }


def get_job_settings(job_id: int) -> Tuple[dict, dict]:
    job = get_job(job_id)
    if not job:
        return {}, {}
    return (
        json.loads(job.image_settings) if job.image_settings else {},
        json.loads(job.video_settings) if job.video_settings else {},
    )


def _maybe_complete_job(conn: sqlite3.Connection, job_id: int):
    row = conn.execute(
        """SELECT total_files, completed_files, failed_files, cancelled_files
           FROM jobs WHERE id = ?""",
        (job_id,),
    ).fetchone()
    if not row:
        return
    cancelled = row["cancelled_files"] if "cancelled_files" in row.keys() else 0
    done = row["completed_files"] + row["failed_files"] + cancelled
    if done >= row["total_files"]:
        conn.execute(
            "UPDATE jobs SET status = 'completed', completed_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), job_id),
        )


def get_all_files_legacy() -> List[tuple]:
    """Return files in legacy tuple format for backward compatibility."""
    rows = get_db().execute("SELECT * FROM files ORDER BY id").fetchall()
    return [_row_to_file(r).to_legacy_tuple() for r in rows]
