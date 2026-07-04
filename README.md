# MediaCompressorWebApp

A production-grade Flask web application for batch compressing images and videos. Features parallel worker pools, crash recovery, configurable encoding profiles, SHA-256 checksums, and compression manifests.

## Features

- **Parallel processing** — Separate thread pools for images (default 4) and videos (default 2)
- **Crash recovery** — Stale in-flight files resume on restart; graceful shutdown on SIGTERM/SIGINT
- **Encoding profiles** — Archival, balanced, web-optimized, mobile-friendly, and more
- **Advanced settings** — Per-job image/video encoding overrides via UI or API
- **Archival-grade handling** — SHA-256 checksums, JSON manifests, metadata preservation
- **Real-time progress** — WebSocket updates with actual FFmpeg encoding percentage for videos
- **Job management** — Pause, resume, retry failed, download manifest
- **Backward compatible** — Legacy `/folder`, `/files`, `/queue_counts` routes still work; old DB auto-migrates

## Requirements

- Python 3.9+
- [FFmpeg](https://ffmpeg.org/) in PATH (for video compression)
- Pillow handles images on all platforms (ImageMagick optional)

## Installation

```bash
git clone https://github.com/viruchith/MediaCompressorWebApp.git
cd MediaCompressorWebApp
pip install -r requirements.txt
```

Copy `config.env.example` to `.env` and adjust settings as needed.

### FFmpeg

- **Ubuntu/Debian:** `sudo apt install ffmpeg`
- **macOS:** `brew install ffmpeg`
- **Windows:** Download from https://ffmpeg.org/download.html and add to PATH

## Usage

```bash
python run.py
```

Open http://localhost:5000

1. Enter input and output folder paths
2. Select a compression profile (or customize advanced settings)
3. Click **Start Compression Job**
4. Monitor progress in real time; download manifest when complete

## Configuration

Environment variables (see `config.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | (dev default) | Flask session secret |
| `DB_PATH` | `file_db.db` | SQLite database |
| `WORKER_COUNT_IMAGES` | `4` | Image worker threads |
| `WORKER_COUNT_VIDEOS` | `2` | Video worker threads |
| `MAX_RETRIES` | `3` | Per-file retry limit |
| `PROCESSING_TIMEOUT_MINUTES` | `30` | Stale job timeout |
| `LOG_LEVEL` | `INFO` | Log verbosity |
| `LOG_JSON` | `false` | Enable JSON log format |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `5000` | Server port |

## Compression Profiles

| Profile | Use Case |
|---------|----------|
| `archival_lossless` | Lossless PNG + H.265 CRF 0 for long-term archival |
| `archival_visually_lossless` | Near-lossless WebP + H.265 CRF 18 |
| `balanced` | Default — good quality/size tradeoff (WebP q75, H.265 CRF 28) |
| `web_optimized` | H.264 MP4, resized images for web delivery |
| `mobile_friendly` | 720p video, 1080px max images |
| `maximum_compression` | Smallest files, lower quality |

## API

All new endpoints are prefixed with `/api/v1/`. Error responses use `{"error": "...", "code": "ERROR_CODE"}`.

### Create a job

```bash
curl -X POST http://localhost:5000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "input_folder": "/path/to/input",
    "output_folder": "/path/to/output",
    "profile": "balanced",
    "priority": 5,
    "preserve_metadata": true
  }'
```

### List profiles

```bash
curl http://localhost:5000/api/v1/profiles
```

### Download manifest

```bash
curl http://localhost:5000/api/v1/jobs/1/manifest
```

See `CURRENT_STATE.md` for the full endpoint list.

## Architecture

```
app/
├── factory.py          # App factory, logging, signals
├── config.py           # Environment configuration
├── db.py               # SQLite + migrations + crash recovery
├── routes.py           # HTTP routes
├── sockets.py          # WebSocket handlers
├── workers/
│   ├── manager.py      # Thread pool dispatcher
│   ├── image_worker.py # PIL compression
│   └── video_worker.py # FFmpeg compression
├── compression/
│   ├── profiles.py     # Encoding presets
│   └── settings.py     # Validation & merge
└── utils/
    ├── hashing.py      # SHA-256
    └── manifest.py     # JSON manifests
```

## WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `progress_update` | Server → Client | File progress (`file_id`, `status`, `message`, `percent`) |
| `queue_counts` | Server → Client | Queue statistics |
| `request_queue_counts` | Client → Server | Request current counts |

## Logging

Set `LOG_JSON=true` for structured JSON logs. For file-based rotation, redirect output:

```bash
python run.py 2>&1 | rotatelogs access.log 86400
```

Or configure system logrotate on the log file.

## License

MIT License

## Acknowledgements

- [FFmpeg](https://ffmpeg.org/)
- [Pillow](https://python-pillow.org/)
- [Flask](https://flask.palletsprojects.com/)
- [Flask-SocketIO](https://flask-socketio.readthedocs.io/)
