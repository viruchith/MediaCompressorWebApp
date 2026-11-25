# Technical Documentation & System Architecture

> In-depth architectural specification, data model, concurrency topology, and runtime behavior for **MediaCompressorWebApp** v2.4.0.

---

## 1. System Architecture & Module Map

```
MediaCompressorWebApp/
├── run.py                          # Application entry point; initializes DB, app factory, and web server
├── VERSION                         # Version string (2.4.0) loaded by app/version.py
├── app/
│   ├── config.py                   # Dataclass loading environment variables with defaults
│   ├── factory.py                  # Flask app factory, logging configuration, signal handlers
│   ├── hardware.py                 # Cross-platform CPU/RAM/GPU detection and adaptive worker sizing
│   ├── db.py                       # SQLite connection lifecycle, schema migrations, and queue operations
│   ├── routes.py                   # Web routes and REST API v1 endpoints
│   ├── sockets.py                  # WebSocket connection and client-initiated request handlers
│   ├── models.py                   # Data transfer objects: Job, FileRecord, PaginatedResult
│   ├── compression/
│   │   ├── profiles.py             # Predefined image and video compression presets
│   │   └── settings.py             # Validation and parameter merging for image and video codecs
│   ├── workers/
│   │   ├── manager.py              # WorkerManager orchestrator: dispatcher, watchdog, emit queue
│   │   ├── image_worker.py         # Pillow image compression executed in worker process
│   │   ├── video_worker.py         # FFmpeg video compression executed in worker thread
│   │   └── process_registry.py     # Registry tracking running FFmpeg subprocess PIDs
│   └── utils/
│       ├── hashing.py              # Streaming SHA-256 chunked calculation with abort checks
│       └── manifest.py             # Job manifest JSON generator and file export
```

### Verified Module Roles

| Module | Source Reference | Verified Implementation |
|--------|------------------|-------------------------|
| `app/config.py` | [config.py:9-49](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/config.py#L9-L49) | Loads `.env` via `python-dotenv`. Declares all runtime constants and limits. |
| `app/factory.py` | [factory.py:65-156](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/factory.py#L65-L156) | Registers blueprints (`api_bp` at `/api/v1`, `web_bp` at root), initializes hardware caching, attaches signal traps for SIGTERM/SIGINT. |
| `app/hardware.py` | [hardware.py:1-719](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/hardware.py#L1-L719) | Probes sysctl/proc/wmic and `ffmpeg -encoders` at startup. Calculates recommended worker pools. |
| `app/db.py` | [db.py:67-150](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/db.py#L67-L150) | SQLite engine operating in WAL mode with connection-per-thread (`threading.local`). Implements round-robin queue fetching. |
| `app/workers/manager.py` | [manager.py:30-80](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/workers/manager.py#L30-L80) | Manages two distinct executor pools, runs dispatcher polling thread, watchdog loop, and Socket.IO emit bridge. |
| `app/workers/image_worker.py` | [image_worker.py:38-140](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/workers/image_worker.py#L38-L140) | Opens images with Pillow and `pillow-heif`, strips/preserves EXIF/ICC, writes atomic temporary files, and returns output metrics. |
| `app/workers/video_worker.py` | [video_worker.py:62-170](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/workers/video_worker.py#L62-L170) | Builds FFmpeg command lines, invokes `subprocess.Popen`, registers PID, parses stderr progress, and catches failures with fallback. |
| `app/workers/process_registry.py` | [process_registry.py:1-45](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/workers/process_registry.py#L1-L45) | Thread-safe dictionary tracking active FFmpeg subprocesses keyed by file ID for targeted termination. |
| `app/utils/hashing.py` | [hashing.py:8-28](file:///Users/viruchith/Projects/MediaCompressorWebApp/app/utils/hashing.py#L8-L28) | Reads file streams in 1 MB blocks to compute SHA-256 digests. |

---

## 2. Concurrency & Execution Model

The application splits concurrency into two dedicated pools inside `WorkerManager`:

```
                       ┌─────────────────────────┐
                       │  Main Server Process    │
                       │  (Flask + Socket.IO)    │
                       └───────────┬─────────────┘
                                   │
      ┌────────────────────────────┼────────────────────────────┐
      │                            │                            │
      ▼                            ▼                            ▼
┌──────────────────┐      ┌─────────────────┐       ┌──────────────────────┐
│ Dispatcher Loop  │      │ Watchdog Loop   │       │ Socket Emit Thread   │
│ (2s poll / wake) │      │ (10s interval)  │       │ (SimpleQueue reader) │
└─────────┬────────┘      └─────────────────┘       └──────────────────────┘
          │
          ├── [Image Files] ──> ProcessPoolExecutor (spawn context)
          │                     └── N image workers (Pillow in dedicated process)
          │
          └── [Video Files] ──> ThreadPoolExecutor
                                └── N video threads (monitors FFmpeg subprocess)
```

### Why ProcessPool for Images vs ThreadPool for Videos?
1. **Images (ProcessPoolExecutor)**:
   - Image resampling (LANCZOS) and encoding in Pillow are CPU-intensive operations inside Python.
   - Using threads would suffer from Python GIL (Global Interpreter Lock) contention, capping throughput on multi-core CPUs.
   - Processes are started using `multiprocessing.get_context("spawn")` (`manager.py:27`) to prevent child processes from inheriting existing SQLite file descriptors or `threading.local` connections.
2. **Videos (ThreadPoolExecutor)**:
   - Video compression is delegated to an external `ffmpeg` binary running in an OS subprocess.
   - The Python thread simply monitors `stderr` pipes for duration/progress timestamps and waits for process completion. Python CPU usage during video encoding is negligible.

### Adaptive Worker Allocation (`AUTO_SCALE=true`)
When `AUTO_SCALE=true` (default), static `WORKER_COUNT_*` values in `.env` are overridden by `hardware.compute_recommendations()` (`hardware.py:270`):
- **Image Workers**: Clamped between `MIN_IMAGE_WORKERS = 2` and `MAX_IMAGE_WORKERS = 12`. Calculated based on available RAM (allocating ~500 MB per process after reserving 30% for OS) and logical CPU cores.
- **Video Workers**: Clamped between `MIN_VIDEO_WORKERS = 1` and `MAX_VIDEO_WORKERS = 6`. Defaults to 2 for hardware encoders (to avoid overwhelming GPU encoder sessions) or physical cores divided by 4 for software encoding.
- Observed on a 10-core Apple Silicon M4 with 24 GB RAM: **8 image worker processes** and **3 video worker threads**.

---

## 3. Data Model & Database Schema

The database is an embedded SQLite file (`file_db.db`) configured on every thread connection with:
```sql
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
```

### Schema (`SCHEMA_V1`)

#### `jobs` Table
Stores high-level batch job metadata and tracking counters.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique job identifier |
| `input_folder` | `TEXT` | `NOT NULL` | Absolute or relative input folder path |
| `output_folder` | `TEXT` | `NOT NULL` | Absolute or relative output folder path |
| `image_settings` | `TEXT` | `NOT NULL DEFAULT '{}'` | JSON string of effective image compression parameters |
| `video_settings` | `TEXT` | `NOT NULL DEFAULT '{}'` | JSON string of effective video compression parameters |
| `profile` | `TEXT` | `NULL` | Legacy unified profile name if image & video match |
| `image_profile` | `TEXT` | `NULL` | Assigned image profile name |
| `video_profile` | `TEXT` | `NULL` | Assigned video profile name |
| `status` | `TEXT` | `NOT NULL DEFAULT 'active'` | Job lifecycle status (`active`, `paused`, `completed`, `cancelled`, `scan_failed`) |
| `total_files` | `INTEGER` | `DEFAULT 0` | Total files discovered during folder scan |
| `completed_files` | `INTEGER` | `DEFAULT 0` | Files successfully compressed |
| `failed_files` | `INTEGER` | `DEFAULT 0` | Files hitting permanent failure |
| `cancelled_files` | `INTEGER` | `DEFAULT 0` | Files cancelled by queue cancel |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Job creation timestamp (UTC) |
| `completed_at` | `TIMESTAMP` | `NULL` | Timestamp when final file completed |

#### `files` Table
Stores individual file queue records and compression metrics.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | `INTEGER` | `PRIMARY KEY AUTOINCREMENT` | Unique file record identifier |
| `job_id` | `INTEGER` | `NOT NULL REFERENCES jobs(id)` | Foreign key linking to parent job |
| `input_file_path` | `TEXT` | `NOT NULL UNIQUE` | Full path to source media file (**Global unique constraint**) |
| `output_file_path` | `TEXT` | `NULL` | Path where compressed output file is written |
| `file_type` | `TEXT` | `NOT NULL` | `'image'` or `'video'` |
| `status` | `INTEGER` | `NOT NULL DEFAULT 0` | Status code (see status codes table below) |
| `priority` | `INTEGER` | `DEFAULT 0` | Higher values claim first |
| `retry_count` | `INTEGER` | `DEFAULT 0` | Incremented upon error or timeout |
| `max_retries` | `INTEGER` | `DEFAULT 3` | Maximum attempts allowed before permanent fail |
| `error_message` | `TEXT` | `NULL` | Last error string captured from exception/FFmpeg |
| `input_size` | `INTEGER` | `NULL` | Original source size in bytes |
| `output_size` | `INTEGER` | `NULL` | Compressed output size in bytes |
| `input_hash` | `TEXT` | `NULL` | Streaming SHA-256 hex digest of source file |
| `output_hash` | `TEXT` | `NULL` | Streaming SHA-256 hex digest of output file |
| `compression_ratio` | `REAL` | `NULL` | `output_size / input_size` |
| `started_at` | `TIMESTAMP` | `NULL` | Timestamp when worker claimed file |
| `completed_at` | `TIMESTAMP` | `NULL` | Timestamp when worker finalized file |
| `created_at` | `TIMESTAMP` | `DEFAULT CURRENT_TIMESTAMP` | Enqueue timestamp |

#### `schema_version` Table
Tracks migration level (`version INTEGER PRIMARY KEY`, `applied_at TIMESTAMP`). Current version: `1`.

---

## 4. File State Machine & Transitions

File records transition through the following integer statuses (`app/config.py:33-38`):

```
       [ 0: PENDING ] <──────── (Crash Recovery on Startup) ────────┐
             │                                                      │
      (claim_file)                                                  │
             ▼                                                      │
      [ 2: PROCESSING ] ──────────────────────┐                     │
             │                                │ (Watchdog Timeout   │
       (Success)                              │  or Retryable Err)  │
             ▼                                ▼                     │
      [ 1: COMPLETED ]             [ -1: ERROR / RETRYING ] ────────┘
                                              │
                                   (retry_count >= max)
                                              ▼
                                   [ -2: PERMANENT_FAIL ]

      * Cancel Action:
      [ 0: PENDING ] or [ 2: PROCESSING ] ──> [ -3: CANCELLED ]
```

| Code | Constant | Meaning |
|------|----------|---------|
| `0` | `STATUS_PENDING` | File is enqueued and waiting for an available worker slot. |
| `2` | `STATUS_PROCESSING` | File has been atomically claimed by a worker thread/process (`started_at` populated). |
| `1` | `STATUS_COMPLETED` | Successfully compressed, verified, hashed, and swapped into place. |
| `-1` | `STATUS_ERROR` | Failed with a non-permanent error; eligible for retry if `retry_count < max_retries`. |
| `-2` | `STATUS_PERMANENT_FAIL` | Exceeded `max_retries` or permanently rejected. |
| `-3` | `STATUS_CANCELLED` | Aborted by user via `/api/v1/cancel_queue`. |

---

## 5. Scheduling & Queue Dispatch Logic

### Fair Round-Robin Across Jobs
Files are claimed using the SQLite query in `app/db.py:537-558`:
```sql
SELECT f.* FROM (
    SELECT f2.*,
           ROW_NUMBER() OVER (
               PARTITION BY f2.job_id
               ORDER BY f2.priority DESC, f2.created_at ASC
           ) AS rn
    FROM files f2
    JOIN jobs j ON f2.job_id = j.id
    WHERE f2.status = 0 AND j.status = 'active'
) f
ORDER BY f.rn ASC, f.priority DESC, f.created_at ASC
LIMIT ?;
```
**Mechanism**: Every active job gets its highest-priority pending file placed at rank 1 (`rn = 1`), followed by rank 2, etc. Ordering by `f.rn ASC` ensures that workers rotate files across all active jobs, preventing a 10,000-file job from starving a 5-file job submitted later.

---

## 6. Hardware Auto-Detection & Codec Execution

Hardware capabilities are inspected once during app creation (`app/hardware.py:initialize()`).

### Detection Mechanisms by OS
- **macOS**:
  - CPU: Runs `/usr/sbin/sysctl -n machdep.cpu.brand_string`, `hw.physicalcpu`, `hw.logicalcpu`, `hw.perflevel0.logicalcpu`.
  - RAM: Runs `/usr/sbin/sysctl -n hw.memsize` and parses page allocations from `/usr/bin/vm_stat`.
  - GPU: Parses `/usr/sbin/system_profiler SPDisplaysDataType -detailLevel mini`.
- **Linux**:
  - CPU: Parses `/proc/cpuinfo`.
  - RAM: Parses `/proc/meminfo` (`MemTotal`, `MemAvailable`).
  - GPU: Searches for `nvidia-smi`, checks `/sys/class/drm/card*/device/vendor`.
- **Windows**:
  - Runs `wmic cpu`, `wmic computersystem get totalphysicalmemory`, `wmic path win32_VideoController`.

### FFmpeg Hardware Flag Generation
When a hardware codec is specified, `app/hardware.py` maps platform flags:

| Target HW Codec | FFmpeg Input Flag (before `-i`) | Quality Flag | Default Value | Extra Flags |
|-----------------|---------------------------------|--------------|---------------|-------------|
| `hevc_videotoolbox` | `-hwaccel videotoolbox` | `-q:v` | `50` | — |
| `h264_videotoolbox` | `-hwaccel videotoolbox` | `-q:v` | `50` | — |
| `hevc_nvenc` | `-hwaccel cuda` | `-cq:v` | `28` | `-preset p5` |
| `h264_nvenc` | `-hwaccel cuda` | `-cq:v` | `23` | `-preset p5` |
| `hevc_qsv` | `-hwaccel qsv` | `-global_quality` | `28` | — |
| `h264_qsv` | `-hwaccel qsv` | `-global_quality` | `23` | — |
| `hevc_amf` | `-hwaccel d3d11va` | `-rc cqp` | — | `-qp_i 28 -qp_p 28` |
| `h264_amf` | `-hwaccel d3d11va` | `-rc cqp` | — | `-qp_i 23 -qp_p 23` |

### Runtime Fallback Path
In `app/workers/video_worker.py:218-245`, if an FFmpeg execution fails when using a hardware codec (`in _HW_CODECS`), the worker logs a warning, falls back to `libx265` with `-crf 28 -preset slow`, and retries the encode immediately using the CPU encoder.

---

## 7. Resiliency Patterns & Failure Recovery

### 1. Crash Recovery (`db.crash_recovery()`)
- **Trigger**: Called automatically inside `app/db.py:init_db()` upon server startup.
- **Action**: Queries for all records where `status = 2` (`STATUS_PROCESSING`). Resets them to `status = 0` (`STATUS_PENDING`) and clears `started_at`.
- **Limitation**: Any partial temporary files on disk from the previous process are overwritten when re-processed.

### 2. Processing Timeout Watchdog (`WorkerManager._timeout_watchdog()`)
- **Trigger**: Runs every 10 seconds in a background daemon thread (`manager.py:348-385`).
- **Action**: Queries `db.get_timed_out_files(PROCESSING_TIMEOUT_MINUTES)`. Compares `started_at` against UTC clock.
- If a file exceeds the threshold:
  1. The PID is retrieved from `ProcessRegistry` and terminated (`SIGTERM` / `terminate()`).
  2. The file is marked as timed out (`status = -1` or `-2` if max retries exceeded).
  3. The active worker slot is released from `_active`.

### 3. Disk Space Pre-Checks
- Before dispatching a file, `WorkerManager._has_disk_space()` inspects the free space on the destination drive using `shutil.disk_usage(output_folder).free`.
- If free space is below `MIN_FREE_DISK_MB` (default 100 MB), the file is failed early (`status = -1`) with error `Low disk space`.

### 4. Atomic Writes
Both image and video workers write outputs to a temporary file (`tempfile.mkstemp`) in the target directory. The file is only moved to the final path via `os.replace` after successful encoding, ensuring partially written files never overwrite existing files or appear as valid outputs.

---

## 8. REST API & WebSocket Event Reference

### REST API Endpoints

| Method | Path | Request Body | Response Codes | Description |
|--------|------|--------------|----------------|-------------|
| `GET` | `/healthz` | None | `200`, `503` | Basic health check for load balancers. |
| `GET` | `/api/v1/health` | None | `200`, `503` | Extended health reporting worker and queue counts. |
| `GET` | `/api/v1/version` | None | `200` | Application metadata and version string. |
| `GET` | `/version` | None | `200` | Legacy route alias for `/api/v1/version`. |
| `GET` | `/api/v1/system` | None | `200`, `503` | Hardware detection profile, detected GPU, and recommendations. |
| `GET` | `/api/v1/profiles` | None | `200` | Complete dictionary of configured compression profiles. |
| `GET` | `/api/v1/profiles/<name>` | None | `200`, `404` | Specific compression profile parameters. |
| `GET` | `/api/v1/jobs` | Query: `page`, `limit` | `200` | Paginated listing of compression jobs. |
| `POST` | `/api/v1/jobs` | JSON (see below) | `201`, `400` | Creates a job and begins asynchronous folder scan. |
| `GET` | `/api/v1/jobs/<id>` | None | `200`, `404` | Job status and progress counters. |
| `PUT` | `/api/v1/jobs/<id>/pause` | None | `200`, `404` | Pauses job; pending files are withheld from dispatch. |
| `PUT` | `/api/v1/jobs/<id>/resume` | None | `200`, `404` | Resumes job; pending files become eligible for dispatch. |
| `DELETE` | `/api/v1/jobs/<id>` | None | `200`, `404` | Deletes job record and associated file entries from database. |
| `GET` | `/api/v1/jobs/<id>/files` | Query: `page`, `limit`, `status` | `200`, `404` | Paginated list of files belonging to job. |
| `POST` | `/api/v1/jobs/<id>/retry_failed` | None | `200`, `404` | Resets all failed files in job to pending. |
| `GET` | `/api/v1/jobs/<id>/manifest` | None | `200`, `404` | Returns generated JSON manifest for job. |
| `GET` | `/api/v1/files` | Query: `page`, `limit`, `status` | `200` | Paginated list of files across all jobs. |
| `GET` | `/api/v1/files/<id>` | None | `200`, `404` | File details and compression metrics. |
| `GET` | `/api/v1/stats` | None | `200` | Aggregate statistics: bytes processed, saved, ratios. |
| `POST` | `/api/v1/clear_completed` | None | `200` | Deletes completed file rows from database. |
| `POST` | `/api/v1/cancel_queue` | None | `200`, `503` | Cancels pending/processing files and kills running FFmpeg tasks. |
| `POST` | `/api/v1/clear_history` | None | `200`, `503` | Cancels active queue and flushes all jobs and files from database. |

#### Create Job Payload (`POST /api/v1/jobs`)
```json
{
  "input_folder": "/path/to/media",
  "output_folder": "/path/to/output",
  "image_profile": "balanced",
  "video_profile": "web_optimized",
  "priority": 0,
  "preserve_metadata": true,
  "image_settings": {},
  "video_settings": {}
}
```

### WebSocket Events

| Event Name | Direction | Payload | Description |
|------------|-----------|---------|-------------|
| `connect` | Client → Server | — | Client establishes WebSocket connection. |
| `connection_status` | Server → Client | `{"status": "connected"}` | Emitted immediately upon connection. |
| `request_queue_counts` | Client → Server | — | Client requests current queue summary. |
| `queue_counts` | Server → Client | `{"total": N, "pending": N, "processing": N, "completed": N, "errors": N, "cancelled": N}` | Emitted on status changes. |
| `progress_update` | Server → Client | `{"file_id": N, "job_id": N, "status": "processing", "message": "...", "percent": 45}` | Progress updates emitted during encoding. |
| `job_scan_complete` | Server → Client | `{"job_id": N, "files_added": N}` | Emitted when background directory scan completes. |
| `job_updated` | Server → Client | Job dictionary | Emitted when job reaches terminal state or changes status. |
| `queue_cancelled` | Server → Client | `{"message": "...", "cancelled": N, "terminated": N}` | Broadcast when queue is cancelled. |
| `history_cleared` | Server → Client | `{"message": "...", "removed": N}` | Broadcast when database history is cleared. |

---

## 9. Behavior You Might Not Expect

1. **Duplicate File Submissions Are Silently Ignored**:
   Because `files.input_file_path` is indexed as `UNIQUE`, submitting the same folder twice results in 0 files enqueued for the second job. You must clear history to reprocess identical paths.
2. **CRF 0 Can Dramatically Increase File Size**:
   The `archival_lossless` video profile runs `libx265 -crf 0`. On typical H.264 video inputs, true lossless HEVC intra/inter frames regularly result in files 3×–6× larger than the original compressed input.
3. **`maximum_compression` Fails with Native FFmpeg Opus**:
   The profile requests `opus` audio in an MKV container. Native FFmpeg requires `-strict -2` or an external `libopus` library, triggering exit code 88 on default standard FFmpeg builds.
4. **`HW_ACCEL_MODE` Environment Variable Is Inactive**:
   Setting `HW_ACCEL_MODE=off` in `.env` has no effect on code execution. Hardware codec availability is determined solely by hardware probing and profile selection.
5. **Modification Timestamps (`mtime`) Are Not Preserved**:
   Output files receive fresh timestamps reflecting the time they were compressed, rather than copying source `mtime`.
6. **Watchdog Cannot Kill Individual Image Worker Processes**:
   While `ProcessRegistry` tracks FFmpeg PIDs and terminates them cleanly, Pillow tasks execute inside the shared `ProcessPoolExecutor`. If a Pillow process hangs, the watchdog can mark the database row as failed, but the child process in the pool cannot be targeted individually.
