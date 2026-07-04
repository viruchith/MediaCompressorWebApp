# MediaCompressorWebApp

[![Version](https://img.shields.io/badge/version-2.2.0-blue.svg)](VERSION)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0%2B-green.svg)](https://flask.palletsprojects.com/)

> **Batch compress images and videos** with a production-grade Flask web app — parallel workers, crash recovery, encoding profiles, SHA-256 checksums, and real-time progress.

**Author:** [Viruchith Ganesan](https://github.com/viruchith) · **Version:** 2.2.0 · **License:** [GPL-3.0](LICENSE)

---

## Table of Contents

- [Overview](#overview)
- [Screenshots](#screenshots)
- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Compression Profiles](#compression-profiles)
- [API Reference](#api-reference)
- [Architecture](#architecture)
- [Versioning](#versioning)
- [Contributing](#contributing)
- [License](#license)
- [Acknowledgements](#acknowledgements)

---

## Overview

**MediaCompressorWebApp** is a self-hosted web application for batch-compressing image and video collections. Point it at an input folder, choose encoding profiles for images and videos independently, and monitor progress in real time while parallel workers process your files.

Ideal for photographers, archivists, content creators, and anyone who needs repeatable, auditable media compression without cloud uploads.

| | |
|---|---|
| **Repository** | https://github.com/viruchith/MediaCompressorWebApp |
| **Language** | Python 3.9+ |
| **Database** | SQLite (embedded, no external server) |
| **Image engine** | Pillow (+ optional ImageMagick) |
| **Video engine** | FFmpeg |

---

## Screenshots

> Placeholder — add screenshots to `docs/images/` and update links below.

| Main dashboard | Job detail |
|:---:|:---:|
| ![Main dashboard](docs/images/screenshot-dashboard.png) | ![Job detail](docs/images/screenshot-job-detail.png) |

| Compression profiles | Real-time progress |
|:---:|:---:|
| ![Profiles](docs/images/screenshot-profiles.png) | ![Progress](docs/images/screenshot-progress.png) |

---

## Features

| Feature | Description |
|---------|-------------|
| **Parallel processing** | Separate thread pools for images (default 4) and videos (default 2) |
| **Crash recovery** | Stale in-flight files resume on restart; graceful SIGTERM/SIGINT shutdown |
| **Encoding profiles** | Archival, balanced, web-optimized, mobile-friendly, and more |
| **Split profiles** | Independent image and video preset per job (`image_profile`, `video_profile`) |
| **Advanced settings** | Per-job image/video overrides via UI or REST API |
| **Queue control** | Cancel pending work, clear completed history, or flush entire database |
| **Archival-grade** | SHA-256 checksums, JSON manifests, metadata preservation |
| **Real-time progress** | WebSocket updates with FFmpeg encoding percentage and live file status |
| **Connection status** | Online/offline indicator on the main dashboard |
| **Dark theme** | Light, dark, or system-auto theme with header toggle |
| **Icon UI** | Self-hosted SVG icons on buttons, labels, stats, and actions |
| **File logging** | Rotating log file (`logs/app.log`) alongside console output |
| **Job management** | Pause, resume, retry failed, download manifest, size-change summaries |
| **Backward compatible** | Legacy routes and automatic DB migration from v1 schema |

---

## Requirements

- **Python** 3.9 or newer
- **FFmpeg** in `PATH` (required for video compression)
- **Pillow** (installed via `requirements.txt`; handles images on all platforms)

### Optional

- **ImageMagick** (`magick`) — alternative image backend (not required)
- **Copy `.env`** from `config.env.example` for custom configuration

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/viruchith/MediaCompressorWebApp.git
cd MediaCompressorWebApp
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Install FFmpeg

| Platform | Command |
|----------|---------|
| **Ubuntu / Debian** | `sudo apt install ffmpeg` |
| **macOS** | `brew install ffmpeg` |
| **Windows** | Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to `PATH` |

Verify:

```bash
ffmpeg -version
```

### 4. Configure (optional)

```bash
cp config.env.example .env
# Edit .env — set SECRET_KEY, worker counts, etc.
```

---

## Quick Start

```bash
python run.py
```

Open **http://localhost:5000** in your browser.

1. Enter **input** and **output** folder paths
2. Select **Image Profile** and **Video Profile** (or expand Advanced Settings for fine-tuning)
3. Click **Start Compression Job**
4. Watch real-time progress (connection indicator shows **Online** when WebSocket is live)
5. Use the header **theme toggle** (System / Light / Dark) as needed
6. Download the manifest when the job completes

Server logs are written to **`logs/app.log`** by default (configurable via `LOG_FILE`).

Check the running version:

```bash
curl http://localhost:5000/api/v1/version
```

---

## Configuration

Environment variables (see [`config.env.example`](config.env.example)):

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(dev default)* | Flask session secret — **change in production** |
| `DB_PATH` | `file_db.db` | SQLite database file path |
| `WORKER_COUNT_IMAGES` | `4` | Parallel image worker threads |
| `WORKER_COUNT_VIDEOS` | `2` | Parallel video worker threads |
| `MAX_RETRIES` | `3` | Per-file retry limit before permanent failure |
| `PROCESSING_TIMEOUT_MINUTES` | `30` | Reset stale in-flight files after N minutes |
| `LOG_LEVEL` | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, …) |
| `LOG_FILE` | `logs/app.log` | Rotating log file path (set empty to disable file logging) |
| `LOG_MAX_BYTES` | `10485760` | Max log file size before rotation (10 MB) |
| `LOG_BACKUP_COUNT` | `5` | Number of rotated log files to retain |
| `LOG_JSON` | `false` | Emit structured JSON logs |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Server port |

---

## Compression Profiles

| Profile | Best for | Image | Video |
|---------|----------|-------|-------|
| `archival_lossless` | Long-term archival | PNG lossless | H.265 CRF 0 |
| `archival_visually_lossless` | Near-lossless archive | WebP q95 | H.265 CRF 18 |
| `balanced` | **Default** — quality/size balance | WebP q75 | H.265 CRF 28 |
| `web_optimized` | Web delivery | WebP q60, max 1920px | H.264 MP4 |
| `mobile_friendly` | Mobile devices | WebP q70, max 1080px | H.264 720p |
| `maximum_compression` | Smallest files | WebP q40 | H.265 CRF 35 |

List profiles via API:

```bash
curl http://localhost:5000/api/v1/profiles
```

---

## API Reference

All v1 endpoints are prefixed with `/api/v1/`. Errors return:

```json
{"error": "Human-readable message", "code": "ERROR_CODE"}
```

### Version

```bash
GET /api/v1/version
GET /version          # legacy alias
```

### Jobs

```bash
GET    /api/v1/jobs                         # List jobs (paginated)
POST   /api/v1/jobs                         # Create job
GET    /api/v1/jobs/<id>                    # Job details
PUT    /api/v1/jobs/<id>/pause              # Pause job
PUT    /api/v1/jobs/<id>/resume             # Resume job
DELETE /api/v1/jobs/<id>                    # Delete job
GET    /api/v1/jobs/<id>/files              # List files in job
POST   /api/v1/jobs/<id>/retry_failed       # Retry failed files
GET    /api/v1/jobs/<id>/manifest           # Download JSON manifest
```

### Create a job

```bash
curl -X POST http://localhost:5000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "input_folder": "/path/to/input",
    "output_folder": "/path/to/output",
    "image_profile": "balanced",
    "video_profile": "web_optimized",
    "priority": 5,
    "preserve_metadata": true
  }'
```

The legacy `profile` field still works and applies to both image and video when `image_profile` / `video_profile` are omitted.

### Queue management

```bash
POST /api/v1/clear_completed    # Remove completed files from DB
POST /api/v1/cancel_queue       # Cancel pending/processing files
POST /api/v1/clear_history      # Flush all jobs and files
```

### WebSocket events

| Event | Direction | Payload |
|-------|-----------|---------|
| `progress_update` | Server → Client | `file_id`, `job_id`, `status`, `message`, `percent` |
| `queue_counts` | Server → Client | `total`, `pending`, `processing`, `completed`, `errors`, `cancelled` |
| `queue_cancelled` | Server → Client | `message`, counts |
| `history_cleared` | Server → Client | `message` |
| `connection_status` | Server → Client | `status` (`connected`) |
| `request_queue_counts` | Client → Server | — |

The main UI shows an **Online** / **Offline** badge driven by Socket.IO `connect`, `disconnect`, and `connection_status` events.

See [`CURRENT_STATE.md`](CURRENT_STATE.md) for the complete endpoint list and schema.

---

## Architecture

```
MediaCompressorWebApp/
├── run.py                  # Entry point
├── VERSION                 # Canonical version string (read by app/version.py)
├── app/
│   ├── factory.py          # Flask app factory, logging, signals
│   ├── version.py          # VERSION, author, copyright metadata
│   ├── config.py           # Environment configuration
│   ├── db.py               # SQLite, migrations, crash recovery
│   ├── routes.py           # HTTP routes (web + API v1)
│   ├── sockets.py          # WebSocket handlers
│   ├── workers/            # Parallel compression workers
│   ├── compression/        # Profiles and settings validation
│   └── utils/              # Hashing and manifests
├── templates/              # Jinja2 HTML templates
├── static/                 # CSS, JavaScript, vendor assets
│   ├── js/icons.js         # SVG icon helpers
│   ├── js/theme.js         # Dark/light/system theme
│   └── vendor/             # Bundled Socket.IO client
├── logs/                   # Rotating app log (gitignored, auto-created)
├── CHANGELOG.md            # Release history
└── LICENSE                 # GNU GPL v3.0
```

---

## Versioning

This project follows [Semantic Versioning](https://semver.org/). The canonical version is stored in the [`VERSION`](VERSION) file and loaded by [`app/version.py`](app/version.py).

| Release | Date | Highlights |
|---------|------|------------|
| **2.2.0** | 2026-07-04 | SVG icon UI, dark/system theme toggle, rotating file logging |
| **2.1.0** | 2026-07-04 | Split image/video profiles, queue cancel/clear, live connection indicator, progress fixes |
| **2.0.0** | 2026-07-04 | Major refactor — modular architecture, worker pools, API v1 |
| **1.0.0** | 2025-01-01 | Initial monolithic Flask release |

See [`CHANGELOG.md`](CHANGELOG.md) for full release notes.

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes with clear messages
4. Open a Pull Request against `main`

By contributing, you agree that your contributions will be licensed under the **GPL-3.0** license.

---

## License

Copyright © 2025–2026 **Viruchith Ganesan**

This program is free software: you can redistribute it and/or modify it under the terms of the **GNU General Public License v3.0** as published by the Free Software Foundation.

See the [LICENSE](LICENSE) file for the full license text.

---

## Acknowledgements

- [FFmpeg](https://ffmpeg.org/) — video transcoding
- [Pillow](https://python-pillow.org/) — image processing
- [Flask](https://flask.palletsprojects.com/) — web framework
- [Flask-SocketIO](https://flask-socketio.readthedocs.io/) — real-time updates
