# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Migrate from Eventlet to threading async mode for Socket.IO
- Hardware acceleration toggle in the web UI
- Built-in log rotation

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

[Unreleased]: https://github.com/viruchith/MediaCompressorWebApp/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/viruchith/MediaCompressorWebApp/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/viruchith/MediaCompressorWebApp/releases/tag/v1.0.0
