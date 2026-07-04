# MediaCompressorWebApp — Current State

## Last Updated
2026-07-04T12:45:00+05:30

## Version
**2.1.0** (see [`VERSION`](VERSION) and [`CHANGELOG.md`](CHANGELOG.md))

## Completed Changes (v2.1.0)
- [x] Separate `image_profile` and `video_profile` per job (UI, API, DB, manifest)
- [x] `POST /api/v1/cancel_queue` — cancels pending/processing files, terminates FFmpeg
- [x] `POST /api/v1/clear_history` — cancels active work then flushes all jobs and files
- [x] `STATUS_CANCELLED` (-3) for cancelled files
- [x] Online/offline WebSocket connection indicator on main page
- [x] Socket.IO threading async mode + thread-safe emit queue (reliable real-time progress)
- [x] Job size summaries on job list and detail pages
- [x] Self-hosted Socket.IO client (no CDN)
- [x] HTML 404/500 error pages
- [x] Priority validation, FFmpeg cancel race, crash recovery fixes

## Modified Files (recent)

| File | Change |
|------|--------|
| `VERSION` | Bumped to 2.1.0 |
| `app/compression/settings.py` | Independent image/video profile merging |
| `app/models.py` | `image_profile`, `video_profile` on Job |
| `app/db.py` | Profile columns migration, cancel/flush helpers |
| `app/routes.py` | `image_profile` / `video_profile` on job create |
| `app/factory.py` | Threading Socket.IO, HTML error handlers |
| `app/workers/manager.py` | Thread-safe emits, cancel/clear |
| `app/workers/process_registry.py` | Active subprocess tracking |
| `templates/index.html` | Dual profiles, connection indicator, queue actions |
| `templates/job_detail.html` | Stacked profile display |
| `static/js/app.js` | Profiles, connection status, live progress |
| `static/css/style.css` | Connection indicator, profile stack styles |
| `static/vendor/socket.io.min.js` | Bundled Socket.IO client |

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

## Database Schema (Current)

### `jobs` table (key columns)
| Column | Description |
|--------|-------------|
| `profile` | Legacy single profile (set when image/video profiles match) |
| `image_profile` | Image compression preset name |
| `video_profile` | Video compression preset name |
| `image_settings` | JSON effective image encoding settings |
| `video_settings` | JSON effective video encoding settings |

### File status values
| Code | Meaning |
|------|---------|
| `0` | Pending |
| `1` | Completed |
| `2` | Processing |
| `-1` | Error |
| `-2` | Permanent fail (max retries) |
| `-3` | Cancelled |

## UI Elements

- **Image Profile** / **Video Profile** — separate dropdowns on new job form
- **Connection indicator** — Online / Offline / Connecting (header, main page)
- **Cancel Queue** — orange button; `POST /api/v1/cancel_queue`
- **Clear All History** — dark red button; `POST /api/v1/clear_history`
- **Cancelled** stat counter and file-list filter
- Job cards show stacked profiles and size-change summary when available

## Known Issues / TODOs

- Image compression cannot be interrupted mid-PIL-save (short window)
- `clear_history` removed count includes both jobs and files
- Hardware acceleration toggle not yet exposed in UI
- Built-in log rotation not yet implemented

## How to Test

```bash
python run.py
```

1. **Separate profiles** — set Image Profile to `web_optimized`, Video Profile to `mobile_friendly`, submit a mixed folder; verify settings in job detail and manifest.
2. **Connection indicator** — badge shows Online when connected; stop server → Offline.
3. **Cancel Queue** — queue files, click Cancel Queue, confirm cancelled state and stats.
4. **Clear History** — flush DB, verify empty lists and zero stats.
5. **API**
   ```bash
   curl -X POST http://localhost:5000/api/v1/jobs \
     -H "Content-Type: application/json" \
     -d '{"input_folder":"/path/in","output_folder":"/path/out","image_profile":"balanced","video_profile":"web_optimized"}'
   curl http://localhost:5000/api/v1/version
   ```
