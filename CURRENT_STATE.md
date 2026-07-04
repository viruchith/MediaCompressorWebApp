# MediaCompressorWebApp — Current State

## Last Updated
2026-07-04T09:30:00+05:30

## Completed Tasks
- [x] Phase 1: Project structure & configuration (modular `app/` package, `run.py`, `requirements.txt`, `config.env.example`)
- [x] Phase 2: Database schema upgrade & crash recovery (WAL mode, migration from legacy schema, graceful shutdown)
- [x] Phase 3: Worker pool & parallel processing (separate image/video ThreadPoolExecutors, dispatcher loop)
- [x] Phase 4: User-configurable encoding & profiles (6 presets, settings validation/merge)
- [x] Phase 5: Enhanced API (`/api/v1/*` endpoints + deprecated legacy aliases)
- [x] Phase 6: Archival features (SHA-256 checksums, JSON manifests, metadata preservation)
- [x] Phase 7: Enhanced UI (profiles, advanced settings, jobs section, pagination, real progress %)
- [x] Phase 8: Final polish (structured logging option, error handlers, README update)

## Current Architecture

Flask application factory (`app/factory.py`) creates the app, registers blueprints (`app/routes.py`), Socket.IO handlers (`app/sockets.py`), and starts a `WorkerManager` (`app/workers/manager.py`).

**Flow:**
1. User submits a job via UI or `POST /api/v1/jobs`
2. Route handler validates settings via `app/compression/settings.py`, creates a `jobs` row and batch-inserts `files` rows
3. `WorkerManager` dispatcher polls every 2s for pending files from active jobs
4. Files are claimed atomically and dispatched to image (`image_worker.py`) or video (`video_worker.py`) thread pools
5. Workers compress atomically (temp file + rename), compute checksums, update DB, emit WebSocket events
6. On job completion, manifest JSON is auto-saved to the output folder

**Crash recovery:** On startup, processing files are reset to pending with incremented retry count; files exceeding `max_retries` are marked permanent failures (-2). SIGTERM/SIGINT handlers reset in-flight files before exit.

## File Map

| File | Description |
|------|-------------|
| `run.py` | Application entry point |
| `main.py` | Legacy entry point (delegates to `run.py`) |
| `app/factory.py` | Flask app factory, logging, signal handlers |
| `app/config.py` | Environment-based configuration |
| `app/db.py` | SQLite schema, migrations, crash recovery, queries |
| `app/models.py` | Job/FileRecord dataclasses |
| `app/routes.py` | Web + API v1 routes, legacy aliases |
| `app/sockets.py` | Socket.IO event handlers |
| `app/workers/manager.py` | Thread pool dispatcher |
| `app/workers/image_worker.py` | PIL-based image compression |
| `app/workers/video_worker.py` | FFmpeg video compression with progress |
| `app/compression/profiles.py` | Encoding preset definitions |
| `app/compression/settings.py` | Settings validation and merge |
| `app/utils/hashing.py` | SHA-256 file checksums |
| `app/utils/manifest.py` | Job manifest generation |
| `templates/index.html` | Main UI with profiles & advanced settings |
| `templates/settings.html` | Encoding settings reference page |
| `templates/job_detail.html` | Per-job detail view with checksums |
| `static/css/style.css` | Application styles |
| `static/js/app.js` | Client-side logic & Socket.IO |
| `requirements.txt` | Python dependencies |
| `config.env.example` | Example environment configuration |

## Database Schema (Current)

```sql
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
    failed_files INTEGER DEFAULT 0
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
```

**Status codes:** `0`=pending, `1`=completed, `2`=processing, `-1`=error, `-2`=permanent fail

## API Endpoints (Current)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main UI |
| GET | `/settings` | Settings reference page |
| GET | `/jobs/<id>` | Job detail page |
| GET | `/api/v1/jobs` | List jobs (paginated) |
| GET | `/api/v1/jobs/<id>` | Job details |
| POST | `/api/v1/jobs` | Create compression job |
| PUT | `/api/v1/jobs/<id>/pause` | Pause job |
| PUT | `/api/v1/jobs/<id>/resume` | Resume job |
| DELETE | `/api/v1/jobs/<id>` | Delete job |
| GET | `/api/v1/jobs/<id>/files` | List job files (paginated, filterable) |
| POST | `/api/v1/jobs/<id>/retry_failed` | Retry failed files |
| GET | `/api/v1/jobs/<id>/manifest` | Download compression manifest |
| GET | `/api/v1/files` | List all files (paginated) |
| GET | `/api/v1/files/<id>` | File details |
| GET | `/api/v1/profiles` | List compression profiles |
| GET | `/api/v1/profiles/<name>` | Profile details |
| GET | `/api/v1/stats` | Global statistics |
| POST | `/api/v1/clear_completed` | Clear completed records |
| GET | `/files` | *(deprecated)* Legacy file list |
| GET | `/queue_counts` | *(deprecated)* Queue counts |
| POST | `/folder` | *(deprecated)* Create job via form |
| POST | `/clear_completed` | *(deprecated)* Clear completed |

**WebSocket events:** `progress_update`, `queue_counts`, `connection_status`, `request_queue_counts`

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-key-change-in-production` | Flask secret |
| `DB_PATH` | `file_db.db` | SQLite database path |
| `WORKER_COUNT_IMAGES` | `4` | Image worker threads |
| `WORKER_COUNT_VIDEOS` | `2` | Video worker threads |
| `MAX_RETRIES` | `3` | Max retries per file |
| `PROCESSING_TIMEOUT_MINUTES` | `30` | Stale processing timeout |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_JSON` | `false` | JSON log format |
| `HOST` | `0.0.0.0` | Bind host |
| `PORT` | `5000` | Bind port |

## Known Issues / TODOs

- Eventlet shows a deprecation warning with Python 3.14; consider migrating to `threading` async mode
- AVIF output requires Pillow built with AVIF support; falls back gracefully on unsupported builds
- Hardware acceleration (`hw_accel`) passes `-hwaccel auto` to FFmpeg but is not exposed in UI yet
- Log rotation is documented in README but not built-in; use external logrotate

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Optional: copy and edit environment config
cp config.env.example .env

# Ensure FFmpeg is in PATH (required for video compression)
ffmpeg -version

# Start the server
python run.py
```

Open http://localhost:5000 in your browser.
