# Technical Documentation

> A deep-dive into the architecture, concurrency model, strategies, and internals of **MediaCompressorWebApp** for developers who want to understand, debug, or extend the codebase.

---

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Concurrency Model](#concurrency-model)
3. [Database Layer](#database-layer)
4. [Worker Pipeline](#worker-pipeline)
5. [Hardware Detection & Adaptive Scaling](#hardware-detection--adaptive-scaling)
6. [Video Encoding Strategy](#video-encoding-strategy)
7. [Resiliency Patterns](#resiliency-patterns)
8. [Real-Time Communication](#real-time-communication)
9. [File Processing Lifecycle](#file-processing-lifecycle)
10. [Configuration System](#configuration-system)
11. [Testing Strategy](#testing-strategy)
12. [Key Design Decisions](#key-design-decisions)
13. [Extension Points](#extension-points)
14. [Performance Tuning](#performance-tuning)
15. [Contributing Guide](#contributing-guide)

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Flask Application                            │
├─────────────────────────────────────────────────────────────────────┤
│  factory.py          │  routes.py (HTTP)     │  sockets.py (WS)     │
│  - App creation      │  - REST API v1        │  - queue_counts       │
│  - Signal handlers   │  - Web UI routes      │  - connection_status  │
│  - HW initialization │  - Health checks      │  - progress_update    │
│  - Logging setup     │  - /api/v1/system     │                       │
├──────────────────────┴───────────────────────┴───────────────────────┤
│                        WorkerManager                                  │
│  ┌─────────────────┐  ┌──────────────────┐  ┌────────────────────┐  │
│  │ Dispatcher Loop  │  │ Emit Consumer    │  │ Timeout Watchdog   │  │
│  │ (2s poll/event)  │  │ (queue → socket) │  │ (reaps stuck work) │  │
│  └────────┬─────────┘  └──────────────────┘  └────────────────────┘  │
│           │                                                           │
│  ┌────────▼──────────────────┐  ┌────────────────────────────────┐   │
│  │  ProcessPoolExecutor      │  │  ThreadPoolExecutor            │   │
│  │  (images — bypasses GIL)  │  │  (videos — FFmpeg subprocess)  │   │
│  │  Workers: AUTO_SCALE      │  │  Workers: AUTO_SCALE           │   │
│  └───────────────────────────┘  └────────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────────┤
│                        SQLite (WAL mode)                              │
│  jobs table │ files table │ schema_version │ crash recovery           │
└──────────────────────────────────────────────────────────────────────┘
```

### Module Responsibilities

| Module | Role |
|--------|------|
| `app/factory.py` | App factory, logging, signal handling, hardware init |
| `app/config.py` | Environment-variable-driven configuration dataclass |
| `app/hardware.py` | Cross-platform hardware detection and scaling recommendations |
| `app/db.py` | SQLite data layer, migrations, CRUD, queue scheduling |
| `app/routes.py` | HTTP routes (web UI + REST API) |
| `app/sockets.py` | WebSocket event handlers |
| `app/workers/manager.py` | Central orchestrator for all concurrent work |
| `app/workers/image_worker.py` | Pillow-based image compression |
| `app/workers/video_worker.py` | FFmpeg-based video compression with HW fallback |
| `app/workers/process_registry.py` | PID tracking for targeted process termination |
| `app/compression/settings.py` | Codec/preset/format validation |
| `app/compression/profiles.py` | Predefined compression presets |
| `app/utils/hashing.py` | SHA-256 streaming hash with cancellation |
| `app/utils/manifest.py` | JSON manifest generation for completed jobs |

---

## Concurrency Model

### Why Two Executor Types?

| Concern | Image Workers | Video Workers |
|---------|---------------|---------------|
| **Executor** | `ProcessPoolExecutor` | `ThreadPoolExecutor` |
| **Reason** | Pillow is CPU-bound; Python's GIL blocks true parallelism in threads | FFmpeg runs as a subprocess; the Python thread just monitors stderr |
| **Communication** | Return values via `Future` | Callbacks from thread context |
| **DB access** | None (processes can't share parent's connection) | Via `threading.local()` per thread |

### Thread Topology

```
Main Thread (Flask + Socket.IO)
├── worker-dispatcher (daemon) — polls DB, dispatches files
├── socket-emit (daemon) — drains _emit_queue → Socket.IO broadcast
├── vid-worker-0..N (ThreadPool) — each monitors an ffmpeg subprocess
└── [background scanner threads — one per job creation]

Separate Processes (spawn context):
├── image-worker-0..N (ProcessPool) — Pillow compression
```

### Critical Synchronization Primitives

| Primitive | Purpose |
|-----------|---------|
| `_lock` (threading.Lock) | Protects `_active` set from concurrent dispatcher + callback modification |
| `_shutdown_event` | Signals all loops to terminate |
| `_cancel_event` | Pauses dispatcher during cancel/clear operations |
| `_wake_event` | Wakes dispatcher immediately when new files are added (avoids 2s latency) |
| `_emit_queue` (SimpleQueue) | Thread-safe bridge from worker threads to Socket.IO emit thread |

### Why `spawn` Context?

```python
_MP_CONTEXT = multiprocessing.get_context("spawn")
```

On macOS (and recommended on Linux), `fork()` copies the parent process's memory — including SQLite connections and `threading.local()` state. This causes:
- SQLite "database is locked" errors in child processes
- Corrupted thread-local data

Using `spawn` starts fresh Python interpreters for each worker, avoiding these issues entirely. The tradeoff is slightly slower process startup (~100ms vs ~10ms for fork).

---

## Database Layer

### Connection Strategy

```python
local = threading.local()

def get_db():
    if not hasattr(local, "connection"):
        local.connection = sqlite3.connect(config.DB_PATH, timeout=30)
        local.connection.execute("PRAGMA journal_mode=WAL")
        local.connection.execute("PRAGMA busy_timeout=5000")
    return local.connection
```

- **One connection per thread** via `threading.local()`
- **WAL mode** enables concurrent reads while one writer holds the lock
- **busy_timeout=5000ms** prevents immediate "database is locked" errors under contention

### Schema Migration

The `schema_version` table tracks the current schema version. On startup, `init_db()` applies any missing migrations sequentially. This ensures forward compatibility without manual intervention.

### Fair Scheduling Algorithm

```sql
SELECT * FROM (
    SELECT f.*, ROW_NUMBER() OVER (PARTITION BY f.job_id ORDER BY f.priority DESC, f.id) AS rn
    FROM files f
    WHERE f.status = 0  -- pending
) sub
ORDER BY sub.rn, sub.priority DESC
LIMIT ?
```

This interleaves files from multiple jobs using `ROW_NUMBER()` round-robin — job A file 1, job B file 1, job A file 2, job B file 2, etc. Without this, a 10,000-file job would starve a 10-file job submitted afterward.

### Atomic File Claiming

```python
def claim_file(file_id: int) -> bool:
    """Atomically transition file from PENDING → PROCESSING."""
    cursor = get_db().execute(
        "UPDATE files SET status = ?, started_at = ? WHERE id = ? AND status = ?",
        (STATUS_PROCESSING, now, file_id, STATUS_PENDING)
    )
    get_db().commit()
    return cursor.rowcount > 0
```

The `WHERE status = ?` predicate ensures only one thread/process can successfully claim a file, even under high concurrency.

---

## Worker Pipeline

### Image Processing Flow

```
Dispatcher → claim_file() → submit to ProcessPool → compress_image()
                                                         │
                                                         ├── compute_file_hash(input)
                                                         ├── Pillow open/resize/save
                                                         ├── compute_file_hash(output)
                                                         └── return (out_path, hashes, sizes, ratio)
                                                                    │
Future.add_done_callback() ← ──────────────────────────────────────┘
    │
    ├── Update DB: status=COMPLETED, hashes, sizes
    ├── Emit progress_update via _emit_queue
    └── Remove from _active set
```

**Key constraint:** `compress_image()` runs in a child process and cannot access the DB or Socket.IO. All DB writes happen in the callback on the dispatcher thread.

### Video Processing Flow

```
Dispatcher → claim_file() → submit to ThreadPool → _process_file()
                                                        │
                                                        ├── Check disk space
                                                        ├── compress_video()
                                                        │       ├── compute_file_hash(input)
                                                        │       ├── _build_ffmpeg_cmd() [HW-aware]
                                                        │       ├── Popen(ffmpeg) + parse progress
                                                        │       ├── [HW fail? retry with libx265]
                                                        │       ├── atomic rename (tmp → output)
                                                        │       └── compute_file_hash(output)
                                                        │
                                                        ├── Update DB: COMPLETED
                                                        ├── Emit progress_update
                                                        └── Remove from _active set
```

**Key difference:** Videos run in threads (not processes) because the expensive work is done by the `ffmpeg` subprocess. The Python thread just reads stderr for progress parsing.

---

## Hardware Detection & Adaptive Scaling

### Detection Pipeline

```python
def detect_hardware() -> HardwareProfile:
    # 1. CPU: sysctl (macOS) / /proc/cpuinfo (Linux) / wmic (Windows)
    # 2. RAM: sysctl+vm_stat / /proc/meminfo / wmic
    # 3. GPU: system_profiler / nvidia-smi+lspci / wmic
    # 4. FFmpeg: -hwaccels, -encoders, -decoders
    # 5. Recommendations: algorithm based on all above
```

### Scaling Algorithm

```
image_workers = clamp(min(ram_budget / 500MB, cores - 2), 2, 12)
video_workers = clamp(cores // 3, 2, 6)    # with HW accel
video_workers = clamp(cores // 4, 1, 4)    # software only
```

**Rationale:**
- Each Pillow process uses ~500MB peak memory
- Leave 2 cores for dispatcher + OS
- HW encoding uses minimal CPU → more parallel video workers possible
- Low-RAM systems (< 4GB) always get minimum workers to prevent OOM

### Codec Priority Order

```
hevc_videotoolbox > hevc_nvenc > hevc_qsv > hevc_amf > libx265
```

The first available encoder in this list is selected. This prioritizes:
1. Apple's dedicated media engine (lowest CPU overhead)
2. NVIDIA's NVENC (dedicated ASIC)
3. Intel's Quick Sync (iGPU-based)
4. AMD's AMF
5. Software fallback (always available)

---

## Video Encoding Strategy

### Platform-Aware Command Building

Each HW encoder requires different quality control flags:

| Encoder | Quality Flag | Preset | HWAccel Decode |
|---------|-------------|--------|----------------|
| `hevc_videotoolbox` | `-q:v 50` | N/A | `-hwaccel videotoolbox` |
| `hevc_nvenc` | `-cq:v 28` | `-preset p5` | `-hwaccel cuda` |
| `hevc_qsv` | `-global_quality 28` | N/A | `-hwaccel qsv` |
| `hevc_amf` | `-rc cqp -qp_i 28 -qp_p 28` | N/A | `-hwaccel d3d11va` |
| `libx265` | `-crf 28` | `-preset slow` | None |

**Critical:** `-hwaccel` flags MUST appear BEFORE `-i` in the FFmpeg command. The video worker's `_build_ffmpeg_cmd` handles this correctly.

### Runtime Fallback

```python
try:
    _run_ffmpeg(hw_cmd, ...)
except RuntimeError:
    # HW encoder failed (driver issue, unsupported pixel format, etc.)
    logger.warning("HW encoder %s failed, falling back to libx265", codec)
    sw_settings = dict(settings, codec="libx265", hw_accel=False, preset="slow")
    _run_ffmpeg(_build_ffmpeg_cmd(input, tmp, sw_settings), ...)
```

This ensures no file permanently fails due to a transient HW encoder issue.

---

## Resiliency Patterns

### 1. Timeout Watchdog

The dispatcher loop calls `_reap_timed_out_files()` every 2 seconds:

```python
def _reap_timed_out_files(self):
    timed_out = db.get_timed_out_files(config.PROCESSING_TIMEOUT_MINUTES)
    for file_rec in timed_out:
        self._process_registry.terminate_by_id(file_rec.id)
        if file_rec.retry_count < config.MAX_RETRIES:
            db.requeue_file(file_rec.id)
        else:
            db.mark_file_permanent_fail(file_rec.id, "Timed out after retries")
```

### 2. Disk Space Pre-Check

Before starting any compression:
```python
free_mb = shutil.disk_usage(output_dir).free / (1024 * 1024)
if free_mb < config.MIN_FREE_DISK_MB:
    raise RuntimeError(f"Insufficient disk space: {free_mb:.0f} MB free")
```

### 3. Poison File Detection

Files that fail repeatedly with the same error are detected and skipped:
```python
def is_poison_file(file_id: int) -> bool:
    """True if file has failed MAX_RETRIES times with identical error."""
```

### 4. Crash Recovery on Startup

```python
def reset_processing_on_shutdown():
    """Reset any PROCESSING files back to PENDING so they retry on next start."""
```

### 5. Graceful Shutdown Sequence

```
SIGTERM/SIGINT received
  → reset_processing_on_shutdown()  # Requeue in-flight files
  → worker_manager.stop(wait=True)
      → shutdown_event.set()         # Signal all loops
      → dispatcher_thread.join()     # Wait for dispatcher
      → image_pool.shutdown()        # Finish in-progress images
      → video_pool.shutdown()        # Finish in-progress videos
      → emit_thread.join(timeout=3)  # Drain pending WebSocket events
  → close_db()
  → sys.exit(0)
```

---

## Real-Time Communication

### Architecture

```
Worker threads ──→ _emit_queue (SimpleQueue) ──→ Emit Consumer Thread ──→ Socket.IO broadcast
```

**Why a queue?** Socket.IO's `socketio.emit()` is NOT thread-safe when `async_mode="threading"`. The emit consumer thread serializes all broadcasts through a single thread that owns the Socket.IO context.

### Event Types

| Event | Trigger | Payload |
|-------|---------|---------|
| `progress_update` | File status change | `{file_id, job_id, status, percent, message}` |
| `queue_counts` | Every dispatcher cycle | `{total, pending, processing, completed, errors, cancelled}` |
| `job_updated` | Job state change | `{job_id, status, ...}` |
| `job_scan_complete` | Background scan finishes | `{job_id, file_count}` |
| `queue_cancelled` | Cancel operation | `{message, cancelled, terminated}` |
| `history_cleared` | Clear history | `{message, removed}` |
| `connection_status` | Client connects | `{status: "connected"}` |

### Client Fallback

The frontend uses WebSocket push as primary, with a 120-second polling fallback for degraded connections.

---

## File Processing Lifecycle

```
┌──────────┐    scan     ┌─────────┐   claim    ┌────────────┐
│  On Disk │ ──────────→ │ PENDING │ ─────────→ │ PROCESSING │
└──────────┘             └─────────┘            └─────┬──────┘
                              ↑                       │
                              │ requeue               │
                              │ (retry < MAX)         ▼
                         ┌────┴─────┐         ┌─────────────┐
                         │  (retry) │         │  compress()  │
                         └──────────┘         └──┬─────┬────┘
                                                 │     │
                              success ───────────┘     └────── failure
                                   │                           │
                                   ▼                           ▼
                           ┌───────────┐             ┌──────────────┐
                           │ COMPLETED │             │ ERROR / PERM │
                           └───────────┘             └──────────────┘
```

**Status codes:**
- `0` — Pending
- `2` — Processing
- `1` — Completed
- `-1` — Error (retryable)
- `-2` — Permanent failure (exhausted retries)
- `-3` — Cancelled

---

## Configuration System

All configuration flows through `app/config.py`:

```python
@dataclass
class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key")
    WORKER_COUNT_IMAGES: int = int(os.getenv("WORKER_COUNT_IMAGES", "4"))
    AUTO_SCALE: bool = os.getenv("AUTO_SCALE", "true").lower() in ("1", "true", "yes")
    HW_ACCEL_MODE: str = os.getenv("HW_ACCEL_MODE", "auto")
    # ...
```

**Priority chain:**
1. Environment variables (highest priority)
2. `.env` file (loaded via `python-dotenv`)
3. Hardcoded defaults in the dataclass

**AUTO_SCALE interaction:**
- When `AUTO_SCALE=true`: `WORKER_COUNT_*` values are ignored; hardware profile recommendations are used
- When `AUTO_SCALE=false`: Static `WORKER_COUNT_*` values are used as-is

---

## Testing Strategy

### Test Organization

```
tests/
├── conftest.py          # Shared fixtures (app, client, temp DB)
├── test_db.py           # SQLite operations, migrations, scheduling
├── test_api.py          # HTTP endpoint integration tests
├── test_utils.py        # Hashing, image/video workers, process registry
└── test_hardware.py     # Hardware detection (heavily mocked)
```

### Testing Patterns

**1. Database tests** — use a temporary SQLite file per test:
```python
@pytest.fixture
def temp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    with patch.object(config, "DB_PATH", db_path):
        db.init_db()
        yield
```

**2. Hardware tests** — mock all system calls:
```python
@patch("app.hardware._detect_cpu")
@patch("app.hardware._detect_ram")
@patch("app.hardware._detect_gpu")
@patch("app.hardware._probe_ffmpeg")
def test_full_detection_flow(mock_ffmpeg, mock_gpu, mock_ram, mock_cpu):
    mock_cpu.return_value = ("Test CPU", 8, 16, None, None)
    # ...
```

**3. API tests** — use Flask's test client:
```python
def test_health_check(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json["status"] == "healthy"
```

### Running Tests

```bash
# Activate venv
source venv/bin/activate

# Run all tests
python -m pytest tests/ -v

# Run specific module
python -m pytest tests/test_hardware.py -v

# Run with coverage
python -m pytest tests/ --cov=app --cov-report=term-missing
```

---

## Key Design Decisions

| Decision | Rationale | Tradeoffs |
|----------|-----------|-----------|
| SQLite over PostgreSQL | Zero-dependency embedded DB; sufficient for single-node workloads | Single writer; no horizontal scaling |
| ProcessPool for images | Bypasses GIL for CPU-bound Pillow work | Higher memory usage (~500MB/worker); slower startup |
| ThreadPool for videos | FFmpeg is a subprocess — threads just parse stderr | Cannot truly parallelize if Python code is CPU-heavy |
| `spawn` multiprocessing | Prevents fork-safety bugs with SQLite and threading.local | ~100ms slower worker startup vs fork |
| WAL journal mode | Allows concurrent reads during writes | Slightly more complex crash recovery |
| Emit queue pattern | Socket.IO is not thread-safe in "threading" mode | Extra thread; slight latency on events |
| HW encode fallback | Ensures no permanent failure from transient driver issues | Double encoding time on fallback |
| No external message queue | Simplicity; suitable for single-node deployment | Cannot distribute work across machines |
| Streaming SHA-256 (1MB chunks) | Handles multi-GB video files without loading into memory | Still slow for very large files |

---

## Extension Points

### Adding a New Compression Profile

1. Edit `app/compression/profiles.py`
2. Add a new entry to the `PROFILES` dict:
```python
PROFILES["my_profile"] = {
    "image": {"quality": 80, "output_format": "avif"},
    "video": {"codec": "libx265", "crf": 24, "preset": "medium"},
}
```

### Adding a New HW Encoder

1. Add encoder config to `app/hardware.py`:
```python
HW_ENCODER_CONFIG["hevc_new_encoder"] = {
    "quality_flag": "-qp",
    "quality_value": "25",
    "hwaccel": "new_method",
}
```
2. Add to `CODEC_PRIORITY` list at appropriate position
3. Add to `VIDEO_CODECS_HW` in `app/compression/settings.py`
4. Add detection logic in `_detect_gpu()` for the new vendor

### Adding a New API Endpoint

1. Add route to `app/routes.py` under the appropriate blueprint:
```python
@api_bp.route("/my_endpoint", methods=["GET"])
def my_endpoint():
    return jsonify({"key": "value"})
```
2. Update `CURRENT_STATE.md` API table

### Adding a New Worker Type

If you need a new kind of worker (e.g., audio-only):
1. Create `app/workers/audio_worker.py`
2. Add pool in `WorkerManager.__init__`
3. Add file type routing in `_dispatch_pending()`
4. Add supported extensions in `config.py`

---

## Performance Tuning

### Bottleneck Identification

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Low CPU usage, slow throughput | Too few workers | Increase `WORKER_COUNT_*` or enable `AUTO_SCALE` |
| High memory, OOM kills | Too many image workers | Reduce `WORKER_COUNT_IMAGES` or lower `MAX_IMAGE_WORKERS` |
| "database is locked" errors | High write contention | Reduce workers; increase `busy_timeout` |
| Videos encoding slowly | No HW acceleration | Set `HW_ACCEL_MODE=auto` and verify `ffmpeg -hwaccels` |
| Dispatcher lag (files wait) | Wake event not fired | Ensure `notify_new_files()` is called after DB inserts |

### Monitoring

```bash
# Check hardware profile and current recommendations
curl http://localhost:5000/api/v1/system | python -m json.tool

# Check health and active workers
curl http://localhost:5000/api/v1/health | python -m json.tool

# Watch logs in real time
tail -f logs/app.log
```

### SQLite Tuning

The current pragmas optimize for our workload:
```sql
PRAGMA journal_mode=WAL;      -- Concurrent reads during writes
PRAGMA busy_timeout=5000;     -- Wait 5s before "database is locked"
PRAGMA synchronous=NORMAL;    -- Good durability/performance balance
```

For very high-throughput scenarios, consider:
```sql
PRAGMA cache_size=-64000;     -- 64MB page cache (default is 2MB)
PRAGMA mmap_size=268435456;   -- Memory-map up to 256MB of the DB file
```

---

## Contributing Guide

### Development Setup

```bash
# Clone and set up
git clone https://github.com/viruchith/MediaCompressorWebApp.git
cd MediaCompressorWebApp
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run tests
python -m pytest tests/ -v

# Run linter
flake8 app/ tests/ --max-line-length=120

# Start dev server
python run.py
```

### Code Style

- **Python**: PEP 8 with 120-char line limit
- **Docstrings**: Google style for public functions
- **Type hints**: Use throughout (`typing` module)
- **Comments**: Only where logic is non-obvious; prefer self-documenting code
- **Imports**: stdlib → third-party → local, alphabetical within each group

### Commit Convention

```
type: short description

Longer explanation if needed.

Co-authored-by: Name <email>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`

### Pull Request Checklist

- [ ] All existing tests pass (`python -m pytest tests/`)
- [ ] New code has corresponding tests
- [ ] No new linter warnings (`flake8`)
- [ ] `CHANGELOG.md` updated under `[Unreleased]`
- [ ] `CURRENT_STATE.md` updated if API/config changed
- [ ] `README.md` updated if user-facing behavior changed

### Architecture Principles

1. **Zero external services** — the app runs with only Python + FFmpeg
2. **Graceful degradation** — missing GPU, missing FFmpeg, low RAM all handled
3. **Fail-safe defaults** — conservative settings that work everywhere
4. **Observable** — structured logging, health endpoints, real-time events
5. **Atomic operations** — file writes use tmp+rename; DB claims use WHERE-based CAS

---

## Glossary

| Term | Meaning |
|------|---------|
| **Job** | A compression task: one input folder → one output folder |
| **File record** | A single image/video within a job tracked in the `files` table |
| **Profile** | A named preset bundle (e.g., "balanced", "archival_lossless") |
| **Claim** | Atomically transitioning a file from PENDING → PROCESSING |
| **Poison file** | A file that repeatedly fails with the same error |
| **Dead letter** | A file that has exhausted all retries (PERMANENT_FAIL) |
| **Fair scheduling** | Round-robin dispatch across jobs via ROW_NUMBER |
| **HW accel** | Hardware-accelerated video encoding (GPU ASIC) |
| **Emit queue** | Thread-safe buffer between workers and Socket.IO broadcast |
| **WAL** | Write-Ahead Logging — SQLite journal mode for concurrent access |
