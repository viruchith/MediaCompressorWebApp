# MediaCompressorWebApp — Current State

## Last Updated
2026-07-04T09:52:00+05:30

## Completed Changes
- [x] `STATUS_CANCELLED` (-3) added for cancelled files (distinct from permanent fail -2)
- [x] `POST /api/v1/cancel_queue` — cancels pending/processing files, terminates active FFmpeg processes
- [x] `POST /api/v1/clear_history` — cancels active work then flushes all jobs and files
- [x] Legacy aliases `POST /cancel_queue` and `POST /clear_history`
- [x] WorkerManager cancellation via `threading.Event` + `ProcessRegistry`
- [x] Queue stats include `cancelled` count
- [x] UI: Cancel Queue (orange) and Clear All History (dark red) buttons with confirmations
- [x] WebSocket events `queue_cancelled` and `history_cleared`
- [x] Cancelled file styling in file list and status filter

## Modified Files

| File | Change |
|------|--------|
| `app/config.py` | Added `STATUS_CANCELLED = -3` |
| `app/models.py` | Added `cancelled` status label |
| `app/db.py` | `cancel_queue_files()`, `flush_database()`, `mark_file_cancelled()`, cancelled in queue counts |
| `app/workers/process_registry.py` | **New** — tracks/terminates active subprocesses |
| `app/workers/manager.py` | Cancel event, `cancel_queue()`, `clear_history()`, dispatch guards |
| `app/workers/video_worker.py` | `should_cancel` + `on_process` hooks for FFmpeg termination |
| `app/workers/image_worker.py` | `should_cancel` checks during compression |
| `app/factory.py` | Exported `get_worker_manager()` |
| `app/routes.py` | Cancel/clear API + legacy routes |
| `templates/index.html` | Cancelled stat, Cancel Queue + Clear All History buttons |
| `static/js/app.js` | Button handlers, socket events, cancelled status UI |
| `static/css/style.css` | `.cancel-btn`, `.danger-btn`, `.status-cancelled`, `.warning` |

## API Endpoints (Current)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Main UI |
| GET | `/settings` | Settings reference |
| GET | `/jobs/<id>` | Job detail page |
| GET | `/version` | Version info (legacy) |
| GET | `/api/v1/version` | Version info |
| GET | `/api/v1/jobs` | List jobs |
| POST | `/api/v1/jobs` | Create job |
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
| **POST** | **`/api/v1/cancel_queue`** | **Cancel pending + processing files** |
| **POST** | **`/api/v1/clear_history`** | **Flush entire database** |
| GET | `/files` | Legacy file list |
| GET | `/queue_counts` | Legacy queue counts |
| POST | `/folder` | Legacy create job |
| POST | `/clear_completed` | Legacy clear completed |
| POST | `/cancel_queue` | Legacy cancel queue |
| POST | `/clear_history` | Legacy clear history |

**WebSocket:** `progress_update`, `queue_counts`, `queue_cancelled`, `history_cleared`, `connection_status`

## Database Schema (Current)

Unchanged table structure. File status values:

| Code | Meaning |
|------|---------|
| `0` | Pending |
| `1` | Completed |
| `2` | Processing |
| `-1` | Error |
| `-2` | Permanent fail (max retries) |
| `-3` | **Cancelled** |

## New UI Elements

- **Cancel Queue** — orange button in Queue Statistics card; confirms then calls `POST /api/v1/cancel_queue`
- **Clear All History** — dark red button; warns then flushes entire DB via `POST /api/v1/clear_history`
- **Cancelled** stat counter in queue statistics
- **Cancelled** filter option in file list dropdown
- Orange styling for cancelled files in the queue list

## Known Issues / TODOs

- Image compression cannot be interrupted mid-PIL-save (short window); video FFmpeg processes are terminated immediately
- `clear_history` counts both jobs and files in the removed total
- Status `-3` used instead of `-2` for cancelled ( `-2` reserved for permanent fail in refactored schema)

## How to Test

```bash
python run.py
```

1. **Cancel Queue**
   - Submit a folder with several files
   - Click **Cancel Queue** → confirm
   - Verify pending files show as Cancelled (orange), stats update, `cancelled` count increases
   - Submit a new folder → processing should resume normally

2. **Clear History**
   - With files in various states, click **Clear All History** → confirm
   - Verify file list is empty, all queue stats are zero
   - Submit a new job → should work from clean state

3. **API**
   ```bash
   curl -X POST http://localhost:5000/api/v1/cancel_queue
   curl -X POST http://localhost:5000/api/v1/clear_history
   ```

4. **Active video cancel** — start a large video encode, click Cancel Queue, verify FFmpeg stops and file is marked cancelled
