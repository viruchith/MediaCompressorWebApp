# MediaCompressorWebApp — Current State

## Last Updated
2026-07-23T17:30:00+05:30

## Version
**2.3.0** (see [`VERSION`](VERSION) and [`CHANGELOG.md`](CHANGELOG.md))

## Completed Changes (v2.3.0)
- [x] Processing timeout watchdog — enforces `PROCESSING_TIMEOUT_MINUTES` at runtime
- [x] Disk space pre-check (`MIN_FREE_DISK_MB`) before starting compression
- [x] Event-driven dispatcher wake via `notify_new_files()`
- [x] Per-job fair scheduling with ROW_NUMBER() round-robin
- [x] Image compression moved to ProcessPoolExecutor (bypasses GIL)
- [x] Background file scanning — job creation returns instantly
- [x] Dead letter / poison file detection (`is_poison_file()`)
- [x] Optimized `get_queue_counts` — single GROUP BY query
- [x] Hash computation: 1 MB chunks with cancellation support
- [x] `ProcessRegistry.terminate_by_id()` for targeted timeout recovery

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
| `VERSION` | Bumped to 2.3.0 |
| `app/config.py` | Added `MIN_FREE_DISK_MB` setting |
| `app/db.py` | Optimized `get_queue_counts`, fair scheduling, timeout/poison helpers |
| `app/routes.py` | Background file scanning thread |
| `app/workers/manager.py` | ProcessPoolExecutor, watchdog, disk check, event-driven dispatch |
| `app/workers/process_registry.py` | Added `terminate_by_id()` |
| `app/utils/hashing.py` | 1 MB chunks, cancellation callback |
| `app/workers/image_worker.py` | Cancellable hash |
| `app/workers/video_worker.py` | Cancellable hash |
| `config.env.example` | `MIN_FREE_DISK_MB` |
| `CHANGELOG.md` | v2.3.0 entry |
| `README.md` | Updated features, config, version |

## API Endpoints (Current)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main UI |
| GET | `/settings` | Settings reference |
| GET | `/jobs/<id>` | Job detail page |
| GET | `/version` | Version info (legacy) |
| GET | `/api/v1/version` | Version info |
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
- Hardware acceleration toggle not yet exposed in UI

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
