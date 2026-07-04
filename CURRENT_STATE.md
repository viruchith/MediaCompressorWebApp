# MediaCompressorWebApp — Current State

## Last Updated
2026-07-04T13:15:00+05:30

## Version
**2.2.0** (see [`VERSION`](VERSION) and [`CHANGELOG.md`](CHANGELOG.md))

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
| `VERSION` | Bumped to 2.2.0 |
| `app/config.py` | `LOG_FILE`, `LOG_MAX_BYTES`, `LOG_BACKUP_COUNT` |
| `app/factory.py` | `RotatingFileHandler`, themed error pages |
| `static/js/icons.js` | **New** — inline SVG icons + hydration |
| `static/js/theme.js` | **New** — theme preference and toggle |
| `static/css/style.css` | CSS variables, dark theme, icon/button styles |
| `templates/_head_common.html` | **New** — shared CSS/JS includes |
| `templates/_theme_init.html` | **New** — anti-FOUC theme script |
| `templates/index.html` | Icons, theme toggle, header actions |
| `templates/job_detail.html` | Icons, theme toggle |
| `templates/settings.html` | Icons, theme toggle, log config docs |
| `config.env.example` | Log file settings |
| `.gitignore` | `logs/` directory |

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

## Configuration (logging)

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_FILE` | `logs/app.log` | Rotating log path (empty = console only) |
| `LOG_MAX_BYTES` | `10485760` | Max size before rotation (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Rotated files to keep |

## Known Issues / TODOs

- Image compression cannot be interrupted mid-PIL-save (short window)
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
5. **Version** — `curl http://localhost:5000/api/v1/version` → `2.2.0`
