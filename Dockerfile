# Multi-stage Dockerfile for MediaCompressorWebApp
# Produces a minimal image with Python, FFmpeg, and the app ready to run.

FROM python:3.12-slim AS base

# Install FFmpeg and clean up apt cache in one layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for logs and database
RUN mkdir -p /app/logs /app/data

# Environment defaults (override at runtime)
ENV DB_PATH=/app/data/file_db.db \
    LOG_FILE=/app/logs/app.log \
    HOST=0.0.0.0 \
    PORT=5000 \
    WORKER_COUNT_IMAGES=4 \
    WORKER_COUNT_VIDEOS=2 \
    PROCESSING_TIMEOUT_MINUTES=30 \
    MIN_FREE_DISK_MB=100

EXPOSE 5000

# Health check using the /healthz endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/healthz')" || exit 1

# Run as non-root user for security
RUN useradd -m -r appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "run.py"]
