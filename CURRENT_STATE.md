# MediaCompressorWebApp — Current State

## Last Updated
2026-07-26T17:00:00+05:30

## Version
**2.4.0** (see [`VERSION`](VERSION) and [`CHANGELOG.md`](CHANGELOG.md))

## Completed Changes (v2.4.0)
- [x] Universal hardware auto-detection module (`app/hardware.py`)
- [x] Cross-platform CPU detection (macOS sysctl / Linux /proc/cpuinfo / Windows wmic)
- [x] RAM detection with fallback (macOS vm_stat / Linux /proc/meminfo / Windows wmic)
- [x] GPU detection with vendor identification (Apple/NVIDIA/Intel/AMD)
- [x] FFmpeg HW encoder/decoder probing at startup
- [x] Adaptive worker scaling based on hardware profile (`AUTO_SCALE=true`)
- [x] Platform-aware video encoding (VideoToolbox/NVENC/QSV/AMF with correct quality flags)
- [x] HW-to-SW runtime fallback (automatic retry with libx265 if HW encoder fails)
- [x] `/api/v1/system` endpoint exposing hardware profile
- [x] HW codec validation in compression settings
- [x] 49 unit tests for hardware module (79 total tests pass)

## Completed Changes (v2.2.0)
- [x] SVG icons on buttons, labels, headings, stats, and dynamic job actions
- [x] Dark theme — System (auto) / Light / Dark with header toggle
- [x] `prefers-color-scheme` detection and live OS theme sync
- [x] Rotating file logging (`logs/app.log`, `LOG_FILE`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT`)
- [x] CSS custom properties for full light/dark UI theming
- [x] Shared `_head_common.html` and `_theme_init.html` partials

## Completed Changes (v2.1.0)
- [x] Separate `image_profile` and `video_profile` per job (UI, API, DB, manifest)
- [x] Queue cancel/clear history, cancelled status, connection indicator
- [x] Socket.IO threading + thread-safe emits, job size summaries

## Modified Files (recent)

| File | Change |
|------|--------|
| `VERSION` | Bumped to 2.4.0 |
| `app/hardware.py` | **New** — hardware detection + recommendation engine |
| `app/config.py` | Added `AUTO_SCALE`, `HW_ACCEL_MODE` settings |
| `app/compression/settings.py` | Added HW codecs, NVENC presets, per-codec validation |
| `app/workers/video_worker.py` | Platform-aware `_build_ffmpeg_cmd`, HW fallback, `_run_ffmpeg` |
| `app/workers/manager.py` | Auto-scaling pool sizes from HardwareProfile |
| `app/factory.py` | Calls `hardware.initialize()` at startup |
| `app/routes.py` | Added `/api/v1/system` endpoint |
| `tests/test_hardware.py` | **New** — 49 unit tests |
| `CHANGELOG.md` | v2.4.0 entry |

## API Endpoints (Current)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main UI |
| GET | `/settings` | Settings reference |
| GET | `/jobs/<id>` | Job detail page |
| GET | `/version` | Version info (legacy) |
| GET | `/api/v1/version` | Version info |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/system` | Hardware profile & recommendations |
| GET | `/api/v1/jobs` | List jobs |
| POST | `/api/v1/jobs` | Create job (`image_profile`, `video_profile`) |
| GET | `/api/v1/jobs/<id>` | Job details |
| PUT | `/api/v1/jobs/<id>/pause` | Pause job |
| PUT | `/api/v1/jobs/<id>/resume` | Resume job |
| DELETE | `/api/v1/jobs/<id>` | Delete job |
| GET | `/api/v1/jobs/<id>/files` | List job files |
| POST | `/api/v1/jobs/<id>/retry_failed` | Retry failed files |
| GET | `/api/v1/jobs/<id>/manifest` | Job manifest JSON |
| GET | `/api/v1/files` | List all files |
| GET | `/api/v1/files/<id>` | File details |
| GET | `/api/v1/profiles` | Compression profiles |
| GET | `/api/v1/profiles/<name>` | Profile details |
| GET | `/api/v1/stats` | Global statistics |
| POST | `/api/v1/clear_completed` | Delete completed files only |
| POST | `/api/v1/cancel_queue` | Cancel pending + processing files |
| POST | `/api/v1/clear_history` | Flush entire database |
| GET | `/files` | Legacy file list |
| GET | `/queue_counts` | Legacy queue counts |
| POST | `/folder` | Legacy create job |
| POST | `/clear_completed` | Legacy clear completed |
| POST | `/cancel_queue` | Legacy cancel queue |
| POST | `/clear_history` | Legacy clear history |

**WebSocket:** `progress_update`, `queue_counts`, `queue_cancelled`, `history_cleared`, `connection_status`

## UI Elements

- **Theme toggle** — System / Light / Dark (header, all main pages)
- **Icons** — buttons, labels, stats, job actions, connection indicator
- **Image Profile** / **Video Profile** — separate dropdowns on new job form
- **Connection indicator** — Online / Offline / Connecting (main page)
- **Cancel Queue** / **Clear All History** — queue management buttons
- Job cards with stacked profiles and size-change summary

## Configuration (worker/resiliency)

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_COUNT_IMAGES` | `4` | Parallel image worker processes (ProcessPool) |
| `WORKER_COUNT_VIDEOS` | `2` | Parallel video worker threads |
| `AUTO_SCALE` | `true` | Override static worker counts with hardware-detected recommendations |
| `HW_ACCEL_MODE` | `auto` | Hardware acceleration: `auto`, `force`, or `off` |
| `MAX_RETRIES` | `3` | Per-file retry limit before permanent failure |
| `PROCESSING_TIMEOUT_MINUTES` | `30` | Watchdog terminates stuck workers after N minutes |
| `MIN_FREE_DISK_MB` | `100` | Minimum free disk space before starting compression |

## Configuration (logging)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_FILE` | `logs/app.log` | Rotating log path (empty = console only) |
| `LOG_MAX_BYTES` | `10485760` | Max size before rotation (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Rotated files to keep |

## Known Issues / TODOs

- Image compression in process pool lacks granular progress callbacks (shows 0% → 100%)
- `clear_history` removed count includes both jobs and files
- Hardware acceleration settings UI page not yet implemented (profile visible via `/api/v1/system`)

## How to Test

```bash
python run.py
```

1. **Theme** — click header toggle; cycle System → Light → Dark; verify UI colors.
2. **Icons** — confirm buttons and section headings show icons.
3. **Logging** — check `logs/app.log` for startup and job messages.
4. **Connection indicator** — Online when connected; Offline when server stopped.
5. **Version** — `curl http://localhost:5000/api/v1/version` → `2.3.0`
6. **Timeout watchdog** — set `PROCESSING_TIMEOUT_MINUTES=1`, submit a job, kill ffmpeg manually; verify file requeues.
7. **Disk space** — set `MIN_FREE_DISK_MB=999999` and submit a job; verify instant "Insufficient disk space" error.
8. **Fair scheduling** — create two jobs simultaneously; verify files interleave from both jobs.
