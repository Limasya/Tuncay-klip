# ─── Stage 1: C++ signal_engine ───────────────────────────────────
FROM python:3.13-slim AS cpp-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake g++ make && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY signal_engine/CMakeLists.txt signal_engine/

# Copy headers and source
COPY signal_engine/include signal_engine/include
COPY signal_engine/src signal_engine/src

RUN mkdir -p signal_engine/build && \
    cd signal_engine/build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=ON && \
    make -j$(nproc)

# ─── Stage 2: Rust video-processor (optional, binary only) ───────
FROM rust:1.82-slim AS rust-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY tools/video-processor/Cargo.toml tools/video-processor/Cargo.lock* tools/video-processor/
COPY tools/video-processor/src tools/video-processor/src

RUN cd tools/video-processor && \
    cargo build --release 2>/dev/null || echo "Rust build skipped (optional component)"

# ─── Stage 3: Python application ─────────────────────────────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Runtime deps: FFmpeg, OCR, curl, and OpenCV runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tesseract-ocr tesseract-ocr-tur libgl1 libglib2.0-0 curl && \
    rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN groupadd -r klip && useradd -r -g klip -d /app -s /sbin/nologin klip

# Install Python dependencies
# Hangi bağımlılık setinin kurulacağı build-time seçilebilir:
#   full monolit (varsayılan): requirements-ml.txt (base + ağır ML)
#   hafif mikroservis        : --build-arg REQUIREMENTS=requirements-base.txt
ARG REQUIREMENTS=requirements-ml.txt
COPY requirements.txt requirements-base.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}

# Copy application code
COPY . .

# Copy C++ built library (optional — graceful degradation if missing)
COPY --from=cpp-builder /src/signal_engine/build/lib/ /app/signal_engine/build/lib/

# Copy Rust binary (optional — graceful degradation if missing)
COPY --from=rust-builder /src/tools/video-processor/target/release/video-processor /app/tools/video-processor/build/video-processor 2>/dev/null || true

# Create directories for runtime data
RUN mkdir -p /app/data /app/logs /app/static /app/clips && \
    chown -R klip:klip /app

# Download ML models (optional — fails gracefully)
RUN python scripts/setup_models.py --vision || true
RUN chown -R klip:klip /app/models_store 2>/dev/null || true

# Switch to non-root user
USER klip

EXPOSE 8000

# /live = lightweight liveness (always 200 if process alive)
# /health = full health (includes DB/Redis checks)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -sf http://localhost:8000/live || exit 1

# Single worker: EventBus/stream pipeline is single-process.
# --workers N > 1 causes duplicate event processing.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
