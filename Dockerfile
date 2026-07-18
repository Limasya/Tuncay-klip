FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps for OpenCV, FFmpeg, numpy, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 curl wget && \
    rm -rf /var/lib/apt/lists/*

# Hangi bağımlılık setinin kurulacağı build-time seçilebilir:
#   full monolit (varsayılan): requirements-ml.txt (base + ağır ML)
#   hafif mikroservis        : --build-arg REQUIREMENTS=requirements-base.txt
ARG REQUIREMENTS=requirements-ml.txt
COPY requirements.txt requirements-base.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r ${REQUIREMENTS}

COPY . .

# Download ML models
RUN python scripts/setup_models.py --vision || true

RUN mkdir -p /app/data /app/logs /app/static

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
