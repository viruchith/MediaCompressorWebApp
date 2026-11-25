# MediaCompressorWebApp — Current Verified State

## Last Verified
2026-11-25

## Version
**2.4.0** (see [`VERSION`](VERSION) and [`CHANGELOG.md`](CHANGELOG.md))

## Verification Status Summary
- **Test Suite**: 79/79 pytest unit tests passing (`tests/test_api.py`, `tests/test_db.py`, `tests/test_hardware.py`, `tests/test_utils.py`). Run with `.venv/bin/pytest -v`.
- **Hardware Probing**: Tested and operational on macOS (Apple Silicon M4). Correctly identifies CPU topology, Unified Memory, and VideoToolbox encoders (`hevc_videotoolbox`, `h264_videotoolbox`). Linux and Windows detection paths are implemented with unit tests, but physical runtime execution on NVENC/QSV/AMF is unverified on this host.
- **Worker Concurrency**: Process pool (using `spawn` context) for Pillow image processing, thread pool for FFmpeg subprocess execution. Auto-scaling actively calculates 8 image workers and 3 video workers on 10-core M4 with 24 GB RAM.
- **Database & Queue**: SQLite in WAL mode with connection-per-thread (`threading.local`). Fair scheduling round-robin verified via SQLite window function `ROW_NUMBER()`. Crash recovery resets in-flight files (`status=2`) back to pending (`status=0`) on startup.
- **Security & Network**: Unauthenticated HTTP REST and WebSocket interface. Binds to `HOST=0.0.0.0` by default; recommended production bind is `127.0.0.1` behind an authenticated reverse proxy.

## Implementation Gaps & Deviations
See [`docs/KNOWN_ISSUES.md`](docs/KNOWN_ISSUES.md) and [`docs/DOC_AUDIT.md`](docs/DOC_AUDIT.md) for full audit records.
1. `maximum_compression` video profile specifies native `opus` audio codec, which fails on standard FFmpeg without `-strict -2`.
2. `input_file_path` is `UNIQUE` in the database; re-running on the same input directory silently ignores existing paths unless history is cleared.
3. `HW_ACCEL_MODE` config variable is parsed but not evaluated in code.
4. `is_poison_file()` exists as a helper in `app/db.py` but is not integrated into `WorkerManager`.
5. ImageMagick is not implemented in any form; Pillow is the sole image engine.
6. File modification timestamps (`mtime`) are not preserved.

## Verified API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/healthz` | Web UI / load balancer health check |
| `GET` | `/api/v1/health` | REST health check (returns worker and queue status) |
| `GET` | `/api/v1/version` | Metadata, version, and repository info |
| `GET` | `/version` | Legacy alias for `/api/v1/version` |
| `GET` | `/api/v1/system` | Detected hardware profile and worker recommendations |
| `GET` | `/api/v1/jobs` | Paginated list of jobs (`page`, `limit`) |
| `POST` | `/api/v1/jobs` | Create compression job (scans input folder in background) |
| `GET` | `/api/v1/jobs/<id>` | Job details and counts |
| `PUT` | `/api/v1/jobs/<id>/pause` | Pause job |
| `PUT` | `/api/v1/jobs/<id>/resume` | Resume job |
| `DELETE` | `/api/v1/jobs/<id>` | Delete job and its file records |
| `GET` | `/api/v1/jobs/<id>/files` | Paginated file records for job |
| `POST` | `/api/v1/jobs/<id>/retry_failed` | Reset failed files to pending |
| `GET` | `/api/v1/jobs/<id>/manifest` | Download JSON manifest |
| `GET` | `/api/v1/files` | Paginated list of all files across all jobs |
| `GET` | `/api/v1/files/<id>` | Individual file record details |
| `GET` | `/api/v1/profiles` | Dictionary of all compression profiles and settings |
| `GET` | `/api/v1/profiles/<name>` | Details for specific named profile |
| `GET` | `/api/v1/stats` | Global processing statistics |
| `GET` | `/api/v1/browse` | Server-side directory browsing for the folder picker modal |
| `POST` | `/api/v1/clear_completed` | Remove completed files from database |
| `POST` | `/api/v1/cancel_queue` | Cancel pending/processing files and kill active subprocesses |
| `POST` | `/api/v1/clear_history` | Flush all records from `jobs` and `files` tables |
