# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.5.0] - 2026-11-25

### Added
- **Interactive Directory Browser & Folder Picker**:
  - Added `GET /api/v1/browse` endpoint allowing clients to browse server-side directory structures with path resolution, parent directory navigation, and filtering of hidden/system folders.
  - Added "Browse…" buttons next to the Input Folder and Output Folder inputs on the web UI dashboard with an interactive directory picker modal.
  - Supports keyboard navigation, parent directory jumping ("▲ Up"), and selecting any existing directory to auto-populate form fields.
- **Incremental Destination Verification (Stateless Sync)**:
  - Background scanner checks the actual output directory before enqueueing. If a compressed output exists, is intact, and has not been invalidated by newer source modification timestamps, the file is skipped automatically.
  - Safe against database deletion or job clearing: subsequent runs on the same folders only process newly added or uncompressed media.
  - Corrupted or partial outputs left behind by interrupted jobs are automatically detected via structural integrity verification (Pillow/ffprobe), removed, and cleanly re-compressed.
- **Social Media Direct Archiving (`copy_as_is`)**:
  - Automatically classifies pre-compressed media from WhatsApp and Snapchat (standard lossy streams) and copies them directly (`shutil.copy2`) without generational quality loss or CPU waste.
  - Safeguard for WhatsApp Documents: media sent uncompressed as a Document (retaining full resolution and camera EXIF) is preserved for high-quality compression.
  - Worker pipeline now supports fast-path direct copies with streaming SHA-256 calculation for complete JSON manifests.
- **Android MediaStore & OS Junk Filtering**:
  - Implemented `app/utils/scanner.py` to automatically ignore Android trashed files (`.trashed-*`), AppleDouble files (`._*`), and OS metadata files (`.DS_Store`, `Thumbs.db`, `desktop.ini`, `.nomedia`).
  - Prunes junk directories (`.trashed`, `.Trash`, `.recycle`, `$RECYCLE.BIN`, `.thumbnails`, `.cache`) during background folder walk in `app/routes.py`.
  - Added guards in `image_worker.py` and `video_worker.py` against zero-byte files and `.trashed` filenames.
  - Added unit test suites `tests/test_scanner.py` and `tests/test_incremental_archive.py` (86 total unit tests pass).

### Documentation & Verification Audit (2026-11-25)
- Performed grounded code and runtime audit on macOS Apple Silicon M4 with Python 3.14.10 and FFmpeg 7.x.
- Documented claim-by-claim verification matrix in [`docs/DOC_AUDIT.md`](docs/DOC_AUDIT.md).
- Added [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) cataloging confirmed gaps (e.g., native Opus failure on standard FFmpeg, unauthenticated default network binding).
- Rewrote `README.md` and `TECHNICAL.md` to reflect empirical behavior, exact measured profile outputs, and verified architectural details with Mermaid sequence and flow diagrams.
- Clarified historical notes: removed fictional references to ImageMagick (Pillow is the sole image engine); noted that `HW_ACCEL_MODE` and `is_poison_file()` are defined in code but not yet evaluated during active queue dispatch.

## [2.4.0] - 2026-07-26

### Added
- **Hardware auto-detection module** (`app/hardware.py`) — universal cross-platform detection of CPU (physical/logical/P-E cores), RAM, GPU (vendor + VRAM), and FFmpeg HW encoders
- **Adaptive worker scaling** (`AUTO_SCALE=true`) — dynamically sizes image/video worker pools based on detected hardware instead of static config
- **Platform-aware video encoding** — automatically configures platform-specific HW encoders when requested:
  - macOS: `hevc_videotoolbox` with `-q:v 50`
  - NVIDIA: `hevc_nvenc` with `-cq:v 28 -preset p5` (unverified on physical hardware)
  - Intel: `hevc_qsv` with `-global_quality 28` (unverified on physical hardware)
  - AMD: `hevc_amf` with CQP mode (unverified on physical hardware)
  - Fallback: `libx265 -crf 28 -preset slow`
- **HW encode runtime fallback** — if hardware encoder fails mid-encode, automatically retries with software `libx265`
- **`GET /api/v1/system` endpoint** — exposes full hardware profile and recommendations as JSON
- **49 new unit tests** (`tests/test_hardware.py`) covering all detection paths, recommendations, edge cases, and encoder flag generation
- HW codec support in settings validation — `hevc_videotoolbox`, `hevc_nvenc`, `hevc_qsv`, `hevc_amf` (and h264 variants) are valid codec choices
- NVENC-specific preset validation (`p1`–`p7`)

### Changed
- Worker manager reads `HardwareProfile` at startup for pool sizing when `AUTO_SCALE` is enabled
- `_build_ffmpeg_cmd` in video worker now inserts `-hwaccel <method>` BEFORE `-i` (correct FFmpeg ordering) and uses codec-specific quality flags instead of generic `-crf`
- `app/compression/settings.py` expanded `VIDEO_CODECS` to include HW encoder variants with per-codec preset validation
- Factory calls `hardware.initialize()` before creating worker pools to ensure profile is cached

### Known Limitations in v2.4.0
- `HW_ACCEL_MODE` config variable is defined in `Config` but is not referenced in worker logic.

## [2.3.0] - 2026-07-23

### Added
- **Processing timeout watchdog** — enforces `PROCESSING_TIMEOUT_MINUTES` at runtime; stuck workers are identified by watchdog, active FFmpeg processes terminated via `ProcessRegistry`, and database rows marked timed out
- **Disk space pre-check** — workers verify sufficient free disk space (`MIN_FREE_DISK_MB`, default 100 MB) before starting compression; files fail early with a clear error
- **Event-driven dispatcher wake** — new files trigger the dispatcher immediately via `notify_new_files()` instead of waiting for the 2-second poll interval
- **Per-job fair scheduling** — `get_pending_files` uses SQLite window function `ROW_NUMBER() OVER (PARTITION BY job_id)` round-robin across active jobs
- **`ProcessRegistry.terminate_by_id()`** — targeted subprocess termination for timeout recovery without killing all active processes
- **`MIN_FREE_DISK_MB`** environment variable for configurable disk space threshold
- **`db.get_timed_out_files()`** and **`db.mark_file_timed_out()`** for timeout-based crash recovery

### Changed
- **Image compression uses `ProcessPoolExecutor`** — Pillow work runs in separate processes using `spawn` context to bypass GIL contention
- **`get_queue_counts` optimized** — replaced separate `COUNT(*)` queries with a single `GROUP BY status` query
- **Hash computation uses 1 MB chunks** (up from 8 KB) for I/O throughput on large video files
- **Hash computation supports cancellation** — `compute_file_hash()` accepts an optional `should_cancel` callback to abort mid-stream
- **File scanning runs in background thread** — `os.walk` + `add_files_batch` runs in a background thread; job creation returns immediately with `"status": "scanning"`
- Worker manager logs distinguish process pool (images) from thread pool (videos)

### Fixed
- `PROCESSING_TIMEOUT_MINUTES` is enforced at runtime via watchdog loop
- Dispatcher uses a dedicated `_wake_event` that can be signalled independently

## [2.2.0] - 2026-07-04

### Added
- SVG icons on buttons, labels, section headings, queue stats, and dynamic job actions (`static/js/icons.js`)
- Dark theme with header toggle — **System** (auto), **Light**, and **Dark** modes (`static/js/theme.js`)
- System theme follows `prefers-color-scheme` and updates when OS theme changes
- Rotating file logging to `logs/app.log` (`LOG_FILE`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
- Shared template partials: `_head_common.html`, `_theme_init.html`

### Changed
- UI styling via CSS custom properties for light and dark themes
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
- Socket.IO async mode migrated from Eventlet to **threading** for worker-thread emits
- Real-time file progress updates without full list reload on every tick
- Job form UI: image and video profile dropdowns stacked vertically
- Job cards and detail page show image/video profiles on separate lines when they differ
- Completed records retained as audit trail; cancelled files tracked in queue statistics

### Fixed
- Priority validation returns `400 INVALID_PRIORITY` for non-numeric values
- Removed invalid `broadcast=True` on Socket.IO emits (Flask-SocketIO 5.x compatibility)
- Crash recovery simplified — single reset of all `PROCESSING` files to `PENDING` on startup
- `clear_history` dispatch race — dispatch stays paused until after database flush

## [2.0.0] - 2026-07-04

### Added
- Modular `app/` package architecture with Flask app factory
- Parallel worker pools for images and videos
- Crash recovery and graceful shutdown (SIGTERM/SIGINT)
- Jobs and files database schema with automatic migration from v1
- Six compression profiles (archival, balanced, web, mobile, etc.)
- User-configurable image and video encoding settings
- REST API under `/api/v1/` with pagination and filtering
- SHA-256 checksums for input and output files
- Per-job JSON compression manifests (download + auto-save)
- FFmpeg encoding progress via WebSocket
- Enhanced web UI with profiles, advanced settings, and job management
- `VERSION` file and centralized version metadata (`app/version.py`)
- `/version` and `/api/v1/version` endpoints
- GPL-3.0 license, CHANGELOG, and README
- Version badge in header and copyright footer in web UI

### Changed
- Entry point moved from `main.py` to `run.py` (`main.py` retained as legacy shim)
- Completed records are retained as audit trail (no longer deleted on startup)
- License changed from MIT to GNU GPL v3.0

### Deprecated
- Legacy routes `/folder`, `/files`, `/queue_counts` (proxy to v1 API)

## [1.0.0] - 2025-01-01

### Added
- Initial Flask + Flask-SocketIO web application
- Single-file `main.py` implementation
- Batch folder queueing for image and video compression
- Pillow image compression (JPEG/WebP)
- FFmpeg video compression (libx265, CRF 28, MKV output)
- SQLite queue with real-time WebSocket progress updates
- Basic web UI with folder input and queue statistics

[Unreleased]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.5.0...HEAD
[2.5.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.4.0...v2.5.0
[2.4.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.3.0...v2.4.0
[2.3.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.2.0...v2.3.0
[2.2.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.1.0...v2.2.0
[2.1.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.0.0...v2.1.0
[2.0.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/viruchith/MediaCompressorWebApp/releases/tag/v1.0.0
