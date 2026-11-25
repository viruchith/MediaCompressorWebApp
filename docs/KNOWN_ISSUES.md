# Known Issues, Gaps, and Edge Cases

This document records confirmed bugs, architectural limitations, and sharp edges identified during the codebase audit of **MediaCompressorWebApp** v2.4.0.

---

### 1. High Severity: Native Opus Audio Encoding Fails in `maximum_compression` Profile
- **Severity**: High (causes job failure on default video profile)
- **Component**: `app/compression/profiles.py:99`, `app/workers/video_worker.py:120`
- **Description**: The `maximum_compression` profile configures video audio as `"audio_codec": "opus"`. When executing `ffmpeg` with `-c:a opus`, standard FFmpeg builds reject the command with:
  ```
  [opus @ 0x...] The encoder 'opus' is experimental but experimental codecs are not enabled, add '-strict -2' if you want to use it.
  Alternatively use the non experimental encoder 'libopus'.
  ```
  FFmpeg exits with code 88, failing the video compression task.
- **Reproduction**:
  1. Create a test video `test.mp4`.
  2. Compress using `maximum_compression` video profile:
     ```python
     from app.workers.video_worker import compress_video
     from app.compression.profiles import PROFILES
     compress_video("test.mp4", "out", PROFILES["maximum_compression"]["video"])
     ```
  3. Notice `RuntimeError: FFmpeg failed with code 88`.
- **Workaround**: Specify custom video settings overriding `audio_codec` to `aac` or use an FFmpeg binary compiled with `libopus`.

---

### 2. High Severity: Unauthenticated Remote Access & Arbitrary Path Traversal by Default
- **Severity**: High (Security Posture)
- **Component**: `app/config.py:29`, `app/routes.py:133-145`
- **Description**: The application defaults to binding on `HOST=0.0.0.0:5000` with NO authentication or session authorization required for either the web UI or REST API. Any network client that can reach port 5000 can invoke `POST /api/v1/jobs` with arbitrary filesystem paths for `input_folder` and `output_folder`, allowing reading of arbitrary media and writing to arbitrary writable locations on the host. Additionally, destructive actions like `POST /api/v1/clear_history` (flushing the database) require no credentials.
- **Reproduction**:
  1. Run the app with default settings (`python run.py`).
  2. From another machine or terminal:
     ```bash
     curl -X POST http://<host-ip>:5000/api/v1/clear_history
     ```
  3. Entire database queue is flushed without prompt or authentication.
- **Remediation**: In production, bind to `127.0.0.1`, set up reverse proxy authentication (e.g. Nginx basic auth / Authelia / OAuth2-proxy), and do not expose port 5000 directly to untrusted networks.

---

### 3. Medium Severity: `input_file_path` Database UNIQUE Constraint Silently Drops Recompressed Files
- **Severity**: Medium (Functional edge case / User surprise)
- **Component**: `app/db.py:37, 396-410`
- **Description**: In SQLite schema `SCHEMA_V1`, `input_file_path TEXT NOT NULL UNIQUE` prevents the same file from ever being enqueued across multiple jobs. If a user processes a folder, and later starts a second job pointing to the same input folder (or an overlapping subfolder), `db.add_files_batch()` executes `INSERT OR IGNORE`. The files are silently skipped. The API returns `201 Created` with `status: "scanning"`, but 0 files are enqueued and the job immediately transitions to completed without processing any files.
- **Reproduction**:
  1. Create a job for `/path/to/media` to `/path/to/output1`.
  2. Create a second job for `/path/to/media` to `/path/to/output2`.
  3. Inspect job 2: `total_files` is 0.
- **Workaround**: Must call `clear_history` (or manually delete the files from SQLite) before reprocessing an existing input folder.

---

### 4. Medium Severity: `HW_ACCEL_MODE` Environment Variable Is Non-Functional
- **Severity**: Medium (Dead configuration)
- **Component**: `app/config.py:23`
- **Description**: `config.env.example`, `README.md`, and `TECHNICAL.md` document `HW_ACCEL_MODE` (`auto`, `force`, `off`). While defined in `Config`, this setting is never checked anywhere in `app/hardware.py`, `app/workers/video_worker.py`, or `app/factory.py`. Setting `HW_ACCEL_MODE=off` does not prevent hardware acceleration from being probed or used if hardware codecs are selected.
- **Reproduction**:
  1. Set `HW_ACCEL_MODE=off` in `.env`.
  2. Run `python run.py`.
  3. Hardware initialization still probes and initializes hardware acceleration (`hevc_videotoolbox` on macOS).

---

### 5. Medium Severity: `is_poison_file()` Exists but Is Never Called in Dispatcher
- **Severity**: Medium (Unimplemented architectural claim)
- **Component**: `app/db.py:869`, `app/workers/manager.py:240-320`
- **Description**: `CHANGELOG.md` and `TECHNICAL.md` claim dead-letter/poison file detection enables faster skipping of known-bad media. While `app/db.py` contains `is_poison_file()`, `WorkerManager` never invokes this method during queue dispatching or file claiming. Files simply retry until `retry_count >= max_retries` via standard error handling.
- **Reproduction**:
  1. Inspect `app/workers/manager.py`. Notice no calls to `is_poison_file()`.

---

### 6. Low Severity: File Modification Times (`mtime`) Are Not Preserved
- **Severity**: Low (Metadata preservation gap)
- **Component**: `app/workers/image_worker.py:135`, `app/workers/video_worker.py:125`
- **Description**: Docs claim archival metadata preservation. While EXIF and container tags (`-map_metadata 0`) are retained, filesystem modification times (`mtime`) are not copied to the compressed outputs (`os.utime()` is never invoked). Output files receive current system timestamps upon creation.

---

### 7. Low Severity: ImageMagick Documentation Is Completely Fabricated
- **Severity**: Low (Documentation error)
- **Component**: `README.md:44, 98`, `CHANGELOG.md:120`
- **Description**: Documentation claims optional ImageMagick support (`Pillow (+ optional ImageMagick)`). The codebase contains zero ImageMagick integration code. Image processing is performed exclusively via Pillow and `pillow-heif`.

---

### 8. Low Severity: Missing Screenshots in `docs/images/`
- **Severity**: Low (Broken documentation links)
- **Component**: `README.md:51-60`
- **Description**: README displays Markdown image links to four screenshots (`screenshot-dashboard.png`, `screenshot-job-detail.png`, etc.) in `docs/images/`, none of which exist.
