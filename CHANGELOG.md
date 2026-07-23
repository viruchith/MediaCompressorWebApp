# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Health check endpoint** — `GET /healthz` and `GET /api/v1/health` for monitoring and load balancers
- **Dockerfile** with multi-stage build, non-root user, and built-in health check
- **`.dockerignore`** for lean container builds
- **GitHub Actions CI** workflow — lint (flake8), test (pytest), and Docker build verification
- **Test suite** — 30 unit/integration tests covering DB, API, utilities, and workers
- **`requirements-dev.txt`** for development dependencies (pytest, flake8)
- **WebSocket `job_updated` event** — pushes job state changes to clients in real time
- **WebSocket `job_scan_complete` event** — notifies UI when background file scanning finishes
- **XSS protection** — `safeBadgeClass()` whitelist prevents injection via job status badges
- **Accessibility** — progress bars now include `role="progressbar"`, `aria-valuenow`, `aria-valuemin`, `aria-valuemax`
- **Scanning status UI** — shows "scanning files in background…" message after job creation

### Changed
- Replaced deprecated `datetime.utcnow()` with `datetime.now(timezone.utc)` (Python 3.12+ compatible)
- `ProcessPoolExecutor` now uses `spawn` multiprocessing context to prevent inheriting parent DB connections
- Background file scanner wrapped in `try/except` — errors are logged and job marked `scan_failed`
- Graceful shutdown now waits for emit queue to drain (prevents lost progress events)
- Frontend job polling reduced from 30s to 120s fallback (primary updates via WebSocket push)

### Planned
- Hardware acceleration toggle in the web UI

## [2.3.0] - 2026-07-23

### Added
- **Processing timeout watchdog** — enforces `PROCESSING_TIMEOUT_MINUTES` at runtime; stuck workers are automatically reaped, their ffmpeg processes terminated, and files retried or permanently failed
- **Disk space pre-check** — workers verify sufficient free disk space (`MIN_FREE_DISK_MB`, default 100 MB) before starting compression; files fail early with a clear error instead of crashing mid-write
- **Event-driven dispatcher wake** — new files trigger the dispatcher immediately via `notify_new_files()` instead of waiting for the 2-second poll interval
- **Per-job fair scheduling** — `get_pending_files` uses `ROW_NUMBER()` round-robin across active jobs so a single large job cannot monopolize all worker slots
- **Dead letter / poison file detection** — `is_poison_file()` helper identifies files that repeatedly fail with the same error, enabling faster skip of known-bad media
- **`ProcessRegistry.terminate_by_id()`** — targeted subprocess termination for timeout recovery without killing all active processes
- **`MIN_FREE_DISK_MB`** environment variable for configurable disk space threshold
- **`db.get_timed_out_files()`** and **`db.mark_file_timed_out()`** for timeout-based crash recovery

### Changed
- **Image compression uses `ProcessPoolExecutor`** — Pillow work now runs in separate processes to bypass GIL contention, improving throughput on multi-core systems
- **`get_queue_counts` optimized** — replaced 5 separate `COUNT(*)` queries with a single `GROUP BY status` query to reduce SQLite write-lock contention
- **Hash computation uses 1 MB chunks** (up from 8 KB) for significantly better I/O throughput on large video files
- **Hash computation supports cancellation** — `compute_file_hash()` accepts an optional `should_cancel` callback to abort mid-stream
- **File scanning runs in background thread** — `os.walk` + `add_files_batch` no longer blocks the HTTP response; job creation returns immediately with `"status": "scanning"`
- Worker manager logs now distinguish process pool (images) from thread pool (videos)

### Fixed
- `PROCESSING_TIMEOUT_MINUTES` is now enforced at runtime (was previously defined but never checked)
- Dispatcher no longer uses `_shutdown_event.wait()` for its sleep — uses a dedicated `_wake_event` that can be signalled independently

## [2.2.0] - 2026-07-04

### Added
- SVG icons on buttons, labels, section headings, queue stats, and dynamic job actions (`static/js/icons.js`)
- Dark theme with header toggle — **System** (auto), **Light**, and **Dark** modes (`static/js/theme.js`)
- System theme follows `prefers-color-scheme` and updates when OS theme changes
- Rotating file logging to `logs/app.log` (`LOG_FILE`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
- Shared template partials: `_head_common.html`, `_theme_init.html` (FOUC prevention)

### Changed
- Full UI restyle via CSS custom properties for light and dark themes
- Connection indicator uses wifi icons; theme toggle on all main pages
- Error pages (404/500) include theme and icon assets

## [2.1.0] - 2026-07-04

### Added
- Separate **image** and **video** compression profile selection per job (`image_profile`, `video_profile`)
- `POST /api/v1/cancel_queue` — cancel pending/processing files and terminate active FFmpeg processes
- `POST /api/v1/clear_history` — cancel active work and flush all jobs and files
- Legacy aliases `POST /cancel_queue` and `POST /clear_history`
- `STATUS_CANCELLED` (-3) for cancelled files (distinct from permanent fail -2)
- Online/offline WebSocket connection indicator on the main dashboard
- Job-level size summaries (`total_input_bytes`, `total_output_bytes`, `overall_size_ratio`)
- Self-hosted Socket.IO client (`static/vendor/socket.io.min.js`) — no CDN dependency
- HTML error pages for 404 and 500 responses
- `jobs.image_profile` and `jobs.video_profile` database columns with automatic migration

### Changed
- Socket.IO async mode migrated from Eventlet to **threading** for reliable worker-thread emits
- Real-time file progress updates without full list reload on every tick
- Job form UI: image and video profile dropdowns stacked vertically
- Job cards and detail page show image/video profiles on separate lines when they differ
- Completed records retained as audit trail; cancelled files tracked in queue statistics

### Fixed
- Priority validation returns `400 INVALID_PRIORITY` for non-numeric values
- Removed invalid `broadcast=True` on Socket.IO emits (Flask-SocketIO 5.x compatibility)
- FFmpeg cancel race no longer marks successful encodes as cancelled
- Crash recovery simplified — single reset of all `PROCESSING` files to `PENDING` on startup
- `clear_history` dispatch race — dispatch stays paused until after database flush

## [2.0.0] - 2026-07-04

### Added
- Modular `app/` package architecture with Flask app factory
- Parallel worker pools for images and videos (`ThreadPoolExecutor`)
- Crash recovery and graceful shutdown (SIGTERM/SIGINT)
- Jobs and files database schema with automatic migration from v1
- Six compression profiles (archival, balanced, web, mobile, etc.)
- User-configurable image and video encoding settings
- REST API under `/api/v1/` with pagination and filtering
- SHA-256 checksums for input and output files
- Per-job JSON compression manifests (download + auto-save)
- Real FFmpeg encoding progress via WebSocket
- Enhanced web UI with profiles, advanced settings, and job management
- `VERSION` file and centralized version metadata (`app/version.py`)
- `/version` and `/api/v1/version` endpoints
- GPL-3.0 license, CHANGELOG, and professional README
- Version badge in header and copyright footer in web UI

### Changed
- Entry point moved from `main.py` to `run.py` (`main.py` retained as legacy shim)
- Image compression uses Pillow on all platforms (ImageMagick optional)
- Completed records are retained as audit trail (no longer deleted on startup)
- License changed from MIT to GNU GPL v3.0

### Deprecated
- Legacy routes `/folder`, `/files`, `/queue_counts` (still functional, proxy to v1 API)

## [1.0.0] - 2025-01-01

### Added
- Initial Flask + Flask-SocketIO web application
- Single-file `main.py` implementation
- Batch folder queueing for image and video compression
- ImageMagick (Linux/macOS) and Pillow (Windows) image compression
- FFmpeg video compression (libx265, CRF 28, MKV output)
- SQLite queue with real-time WebSocket progress updates
- Basic web UI with folder input and queue statistics

[Unreleased]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.3.0...HEAD
[2.3.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/viruchith/MediaCompressorWebApp/releases/tag/v1.0.0
