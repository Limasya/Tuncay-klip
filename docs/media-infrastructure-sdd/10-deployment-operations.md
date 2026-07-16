# 10. Dağıtım ve Operasyonlar

## Docker, Kubernetes ve Üretim Ortamı Dağıtımı

---

## İçindekiler

1. [Docker Mimarisi](#1-docker-mimarisi)
2. [Kubernetes Dağıtımı](#2-kubernetes-dağıtımı)
3. [Worker Otomatik Ölçeklendirme](#3-worker-otomatik-ölçeklendirme)
4. [İzleme ve Gözlemlenebilirlik](#4-izleme-ve-gözlemlenebilirlik)
5. [Yapılandırma Yönetimi](#5-yapılandırma-yönetimi)
6. [CI/CD Hattı](#6-cicd-hattı)
7. [Üretim Kontrol Listesi](#7-üretim-kontrol-listesi)

---

## 1. Docker Mimarisi

### 1.1 Amaç

Video işleme altyapısının Docker konteyner mimarisi, GPU kaynaklarına erişim, katman optimizasyonu, veri dayanıklılığı ve üretim ortamına hazır konfigürasyon sağlamak üzere tasarlanmıştır. Multi-stage build yaklaşımı ile build ve runtime ortamları ayrılarak konteyner görüntü boyutları %60-70 oranında küçültülür.

### 1.2 Multi-Stage Dockerfile

#### 1.2.1 Build Aşaması — FFmpeg ve Bağımlılık Derleme

```dockerfile
# ============================================================
# AŞAMA 1: Build ortamı — FFmpeg, Python bağımlılıkları
# ============================================================
FROM nvidia/cuda:12.4.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Sistem bağımlılıkları (build-only)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    nasm \
    yasm \
    pkg-config \
    libssl-dev \
    libva-dev \
    libdrm-dev \
    libvulkan-dev \
    python3-dev \
    python3-pip \
    python3-venv \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# FFmpeg kaynaktan derleme (NVENC, VAAPI, Vulkan desteği ile)
WORKDIR /build/ffmpeg

ARG FFMPEG_VERSION=7.0
ARG NVIDIA_VIDEO_CODEC_SDK_VERSION=12.1.14

# NVIDIA Video Codec SDK indirme (NVENC için zorunlu)
RUN curl -L -o nv-sdk.zip \
    "https://developer.nvidia.com/video-codec-sdk-${NVIDIA_VIDEO_CODEC_SDK_VERSION}-download" \
    && unzip nv-sdk.zip -d /opt/nv-sdk \
    && rm nv-sdk.zip

ENV FFMPEG_BUILD_FLAGS=" \
    --enable-gpl \
    --enable-nonfree \
    --enable-cuda-nvcc \
    --enable-cuvid \
    --enable-nvenc \
    --enable-nvdec \
    --enable-libnpp \
    --enable-libfreetype \
    --enable-libfribidi \
    --enable-libass \
    --enable-libvulkan \
    --enable-libpulse \
    --enable-openssl \
    --enable-vaapi \
    --enable-vdpau \
    --extra-cflags='-I/opt/nv-sdk/Interface/nvEncodeAPI.h' \
    --extra-ldflags='-L/opt/nv-sdk/lib/linux/x86_64' \
    --prefix=/opt/ffmpeg \
    "

RUN curl -L -o ffmpeg-snapshot.tar.bz2 \
    "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.bz2" \
    && tar xjf ffmpeg-snapshot.tar.bz2 \
    && cd ffmpeg-* \
    && ./configure ${FFMPEG_BUILD_FLAGS} \
    && make -j$(nproc) \
    && make install \
    && make distclean \
    && cd / \
    && rm -rf /build/ffmpeg ffmpeg-*

# Python sanal ortamı ve bağımlılıklar
WORKDIR /build/app

COPY pyproject.toml poetry.lock ./

RUN pip install poetry \
    && poetry config virtualenvs.create true \
    && poetry config virtualenvs.in-project true \
    && poetry install --only main --no-interaction --no-ansi \
    && poetry cache clear --all -n

# ============================================================
# AŞAMA 2: Runtime ortamı — Minimal çalıştırma katmanı
# ============================================================
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/opt/ffmpeg/bin:$PATH \
    LD_LIBRARY_PATH=/opt/ffmpeg/lib:/usr/local/cuda/lib64:${LD_LIBRARY_PATH}

# Runtime-only sistem bağımlılıkları
RUN apt-get update && apt-get install -y --no-install-recommends \
    libva2 \
    libdrm2 \
    libvulkan1 \
    libfreetype6 \
    libfribidi0 \
    libass9 \
    libpulse0 \
    libssl3 \
    libgomp1 \
    python3 \
    python3-pip \
    python3-venv \
    tini \
    curl \
    dumb-init \
    && rm -rf /var/lib/apt/lists/*

# Güvenli konteyner kullanıcısı oluştur
RUN groupadd -r -g 1000 appuser \
    && useradd -r -g appuser -u 1000 -d /app -s /sbin/nologin appuser

# Builder'dan FFmpeg'i kopyala
COPY --from=builder /opt/ffmpeg /opt/ffmpeg
COPY --from=builder /opt/nv-sdk /opt/nv-sdk

# Builder'dan Python sanal ortamını kopyala
COPY --from=builder /build/app/.venv /app/.venv

# Uygulama kodunu kopyala
WORKDIR /app
COPY --chown=appuser:appuser ./src ./src
COPY --chown=appuser:appuser ./configs ./configs

# Çalışma ve veri dizinleri
RUN mkdir -p /data/input /data/output /data/temp /data/templates /data/logs \
    && chown -R appuser:appuser /data \
    && chown -R appuser:appuser /app

# Port ve kullanıcı tanımlama
EXPOSE 8000 9090
USER appuser

# Sağlık kontrolü
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8000/health", "||", "exit 1"]

# Varsayılan giriş noktası
ENTRYPOINT ["tini", "--"]
CMD ["python3", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

#### 1.2.2 Worker Konteyner Dockerfile

```dockerfile
# ============================================================
# Worker — GPU-intensive render işleri için konteyner
# ============================================================
FROM nvidia/cuda:12.4.0-devel-ubuntu22.04 AS worker-builder

# (Aynı build aşaması yukarıdaki ile aynı, kısaltılmış)

# ============================================================
# Worker Runtime
# ============================================================
FROM nvidia/cuda:12.4.0-runtime-ubuntu22.04 AS worker-runtime

# ... (Aynı runtime kurulumu)

# Sadece worker için giriş noktası
ENTRYPOINT ["tini", "--"]
CMD ["python3", "-m", "src.workers.render_worker", "--concurrency", "4"]

# Worker sağlık kontrolü (farklı endpoint)
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8001/health/worker", "||", "exit 1"]

EXPOSE 8001
```

### 1.3 GPU-Enabled Konteyner Mimarisi

NVIDIA Container Toolkit ile GPU erişimi:

```yaml
# docker-compose.gpu.yml
version: "3.9"

services:
  render-worker:
    build:
      context: .
      dockerfile: Dockerfile
      target: worker-runtime
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, compute, utility]
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
      - NVIDIA_DRIVER_CAPABILITIES=compute,utility,video
      - CUDA_VISIBLE_DEVICES=0
      - GPU_MEM_FRACTION=0.8
    runtime: nvidia
    volumes:
      - nvidia-driver:/usr/local/nvidia:ro
      - /dev/nvidia0:/dev/nvidia0
      - /dev/nvidiactl:/dev/nvidiactl
      - /dev/nvidia-uvm:/dev/nvidia-uvm

volumes:
  nvidia-driver:
    driver: local
    driver_opts:
      type: none
      device: /usr/lib/x86_64-linux-gnu
      o: bind
```

### 1.4 Konteyner Katman Optimizasyonu

```
Katman Analizi:
┌─────────────────────────────────────────────────┐
│ Layer 0: nvidia/cuda:12.4.0-runtime (8.2 GB)    │  ← GPU runtime (paylaşımlı)
├─────────────────────────────────────────────────┤
│ Layer 1: apt-get install (sistem paketleri)      │  ← ~200 MB, rarely değişir
├─────────────────────────────────────────────────┤
│ Layer 2: FFmpeg (opt/ffmpeg)                     │  ← ~150 MB, version-based
├─────────────────────────────────────────────────┤
│ Layer 3: Python .venv                            │  ← ~300 MB, dependency-based
├─────────────────────────────────────────────────┤
│ Layer 4: Uygulama kodu (src/)                    │  ← ~50 MB, sık değişir
├─────────────────────────────────────────────────┤
│ Layer 5: Konfigürasyon                           │  ← ~5 MB, environment-based
└─────────────────────────────────────────────────┘

Toplam boyut: ~9 GB (paylaşımlı katmanlar olmadan ~1.2 GB)
```

Optimasyon stratejileri:

```dockerfile
# 1. COPY sıralaması: Değişme sıklığına göre (az → çok)
COPY pyproject.toml poetry.lock ./        # Nadiren değişir
COPY src/models ./src/models             # Nadiren değişir
COPY src/workers ./src/workers           # Bazen değişir
COPY src/api ./src/api                   # Sık değişir

# 2. Multi-stage ile build-only bağımlılıkları atla
# 3. .dockerignore ile gereksiz dosyaları hariç tut
# 4. apt cache temizliği
RUN apt-get update && apt-get install -y --no-install-recommends ... \
    && rm -rf /var/lib/apt/lists/*

# 5. pip cache temizliği
RUN pip install --no-cache-dir -r requirements.txt
```

`.dockerignore` dosyası:

```
.git
.github
.vscode
.idea
__pycache__
*.pyc
*.pyo
.pytest_cache
.mypy_cache
.coverage
htmlcov
node_modules
*.log
.env
.env.*
docker-compose*.yml
Dockerfile*
docs/
tests/
*.md
*.toml
!pyproject.toml
!poetry.lock
```

### 1.5 Veri Dayanıklılığı — Volume Mounts

```yaml
# docker-compose.volumes.yml
volumes:
  media-input:
    driver: local
    driver_opts:
      type: nfs
      o: addr=10.0.1.100,rw,nfsvers=4.1
      device: ":/mnt/media/input"

  media-output:
    driver: local
    driver_opts:
      type: nfs
      o: addr=10.0.1.100,rw,nfsvers=4.1
      device: ":/mnt/media/output"

  redis-data:
    driver: local

  postgres-data:
    driver: local

  temp-workspace:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=50G,uid=1000
```

### 1.6 Konteyner Sağlık Kontrolleri

```python
# src/api/health.py
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
import redis.asyncio as redis
import asyncio

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    version: str
    uptime_seconds: float
    checks: dict[str, "HealthCheck"]


class HealthCheck(BaseModel):
    status: str
    latency_ms: Optional[float] = None
    message: Optional[str] = None


async def check_redis(redis_client: redis.Redis) -> HealthCheck:
    try:
        start = asyncio.get_event_loop().time()
        await redis_client.ping()
        latency = (asyncio.get_event_loop().time() - start) * 1000
        return HealthCheck(status="healthy", latency_ms=latency)
    except Exception as e:
        return HealthCheck(status="unhealthy", message=str(e))


async def check_gpu() -> HealthCheck:
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return HealthCheck(status="healthy")
        return HealthCheck(status="unhealthy", message="nvidia-smi failed")
    except Exception as e:
        return HealthCheck(status="unhealthy", message=str(e))


async def check_disk_space(min_free_gb: float = 10.0) -> HealthCheck:
    import shutil
    total, used, free = shutil.disk_usage("/data/temp")
    free_gb = free / (1024 ** 3)
    if free_gb < min_free_gb:
        return HealthCheck(
            status="unhealthy",
            message=f"Disk alanı düşük: {free_gb:.1f} GB (min: {min_free_gb} GB)"
        )
    return HealthCheck(status="healthy", latency_ms=0)


@router.get("", response_model=HealthResponse)
async def health_check(redis_client: redis.Redis = Depends(get_redis)):
    import time
    start = time.time()

    redis_check = await check_redis(redis_client)
    gpu_check = await check_gpu()
    disk_check = await check_disk_space()

    checks = {
        "redis": redis_check,
        "gpu": gpu_check,
        "disk": disk_check,
    }

    statuses = [c.status for c in checks.values()]
    if all(s == "healthy" for s in statuses):
        overall = "healthy"
    elif any(s == "unhealthy" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    return HealthResponse(
        status=overall,
        version=get_version(),
        uptime_seconds=time.time() - START_TIME,
        checks=checks,
    )


@router.get("/ready", response_model=HealthCheck)
async def readiness_check(redis_client: redis.Redis = Depends(get_redis)):
    try:
        await redis_client.ping()
        return HealthCheck(status="healthy")
    except Exception:
        return HealthCheck(status="unhealthy", message="Redis bağlantısı yok")
```

### 1.7 Docker Compose — Yerel Geliştirme Ortamı

```yaml
# docker-compose.yml
version: "3.9"

x-common-env: &common-env
  APP_ENV: development
  LOG_LEVEL: debug
  REDIS_URL: redis://redis:6379/0
  DATABASE_URL: postgresql+asyncpg://app:secret@postgres:5432/tuncay_klip
  RABBITMQ_URL: amqp://guest:guest@rabbitmq:5672/
  S3_ENDPOINT: http://minio:9000
  S3_ACCESS_KEY: minioadmin
  S3_SECRET_KEY: minioadmin
  S3_BUCKET: tuncay-klip
  TEMP_DIR: /data/temp
  TEMPLATE_DIR: /data/templates

services:
  # ─────────────── Uygulama Sunucusu ───────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile
      target: runtime
      args:
        - BUILD_DATE=${BUILD_DATE:-unknown}
        - VCS_REF=${VCS_REF:-unknown}
    ports:
      - "8000:8000"
      - "9090:9090"  # Prometheus metrics
    environment:
      <<: *common-env
      WORKER_CONCURRENCY: 1
    volumes:
      - ./src:/app/src:ro
      - ./configs:/app/configs:ro
      - media-input:/data/input
      - media-output:/data/output
      - temp-workspace:/data/temp
    depends_on:
      redis:
        condition: service_healthy
      postgres:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    networks:
      - frontend
      - backend
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 2G
          cpus: "2.0"
        reservations:
          memory: 512M

  # ─────────────── GPU Worker ───────────────
  worker-render:
    build:
      context: .
      dockerfile: Dockerfile
      target: worker-runtime
    environment:
      <<: *common-env
      WORKER_TYPE: render
      WORKER_CONCURRENCY: 4
      GPU_MEMORY_LIMIT: "8589934592"
    volumes:
      - ./src:/app/src:ro
      - ./configs:/app/configs:ro
      - media-input:/data/input
      - media-output:/data/output
      - media-templates:/data/templates
      - temp-workspace:/data/temp
    deploy:
      replicas: 2
      resources:
        limits:
          memory: 16G
          cpus: "8.0"
        reservations:
          memory: 4G
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu, compute, utility]
    runtime: nvidia
    depends_on:
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    networks:
      - backend
    restart: unless-stopped

  # ─────────────── CPU Worker (post-processing) ───────────────
  worker-postprocess:
    build:
      context: .
      dockerfile: Dockerfile
      target: worker-runtime
    environment:
      <<: *common-env
      WORKER_TYPE: postprocess
      WORKER_CONCURRENCY: 8
    volumes:
      - media-input:/data/input
      - media-output:/data/output
      - temp-workspace:/data/temp
    deploy:
      replicas: 3
      resources:
        limits:
          memory: 4G
          cpus: "4.0"
        reservations:
          memory: 1G
    depends_on:
      redis:
        condition: service_healthy
      rabbitmq:
        condition: service_healthy
    networks:
      - backend
    restart: unless-stopped

  # ─────────────── Message Broker ───────────────
  rabbitmq:
    image: rabbitmq:3.13-management-alpine
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
      RABBITMQ_VM_MEMORY_HIGH_WATERMARK: "0.6"
    volumes:
      - rabbitmq-data:/var/lib/rabbitmq
    healthcheck:
      test: ["CMD", "rabbitmq-diagnostics", "-q", "ping"]
      interval: 15s
      timeout: 10s
      retries: 5
      start_period: 30s
    networks:
      - backend

  # ─────────────── Redis (kuyruk ve önbellek) ───────────────
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    command: >
      redis-server
      --maxmemory 2gb
      --maxmemory-policy allkeys-lru
      --appendonly yes
      --appendfsync everysec
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend

  # ─────────────── PostgreSQL ───────────────
  postgres:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: tuncay_klip
      POSTGRES_USER: app
      POSTGRES_PASSWORD: secret
      POSTGRES_INITDB_ARGS: "--encoding=UTF-8 --lc-collate=C --lc-ctype=C"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d tuncay_klip"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - backend

  # ─────────────── MinIO (S3 uyumlu object storage) ───────────────
  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    volumes:
      - minio-data:/data
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 15s
      timeout: 10s
      retries: 5
    networks:
      - backend

  # ─────────────── Prometheus ───────────────
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9091:9090"
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./monitoring/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus-data:/prometheus
    networks:
      - monitoring

  # ─────────────── Grafana ───────────────
  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
      GF_INSTALL_PLUGINS: grafana-clock-panel,grafana-piechart-panel
    volumes:
      - grafana-data:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./monitoring/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    depends_on:
      - prometheus
    networks:
      - monitoring

  # ─────────────── Loki (Log aggregation) ───────────────
  loki:
    image: grafana/loki:2.9.0
    ports:
      - "3100:3100"
    volumes:
      - ./monitoring/loki.yml:/etc/loki/local-config.yaml:ro
      - loki-data:/loki
    networks:
      - monitoring

  # ─────────────── Promtail (Log collector) ───────────────
  promtail:
    image: grafana/promtail:2.9.0
    volumes:
      - ./monitoring/promtail.yml:/etc/promtail/config.yml:ro
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
    command: -config.file=/etc/promtail/config.yml
    depends_on:
      - loki
    networks:
      - monitoring

# ─────────────── Volume Tanımları ───────────────
volumes:
  media-input:
    driver: local
  media-output:
    driver: local
  media-templates:
    driver: local
  temp-workspace:
    driver: local
    driver_opts:
      type: tmpfs
      device: tmpfs
      o: size=50G
  redis-data:
    driver: local
  postgres-data:
    driver: local
  minio-data:
    driver: local
  rabbitmq-data:
    driver: local
  prometheus-data:
    driver: local
  grafana-data:
    driver: local
  loki-data:
    driver: local

# ─────────────── Ağ Tanımları ───────────────
networks:
  frontend:
    driver: bridge
  backend:
    driver: bridge
    internal: true
  monitoring:
    driver: bridge
```

### 1.8 Veri Yapıları

```python
# src/infrastructure/docker_config.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class VolumeType(str, Enum):
    BIND = "bind"
    VOLUME = "volume"
    TMPFS = "tmpfs"
    NFS = "nfs"


class VolumeMount(BaseModel):
    source: str
    target: str
    type: VolumeType = VolumeType.VOLUME
    read_only: bool = False
    driver: Optional[str] = None
    driver_opts: Optional[dict[str, str]] = None


class GPUConfig(BaseModel):
    device_count: int = Field(default=1, ge=0, le=8)
    capabilities: list[str] = Field(
        default=["gpu", "compute", "utility"]
    )
    driver: str = "nvidia"
    memory_limit: Optional[int] = None  # byte cinsinden


class ContainerConfig(BaseModel):
    name: str
    image: str
    tag: str = "latest"
    build_target: Optional[str] = None
    ports: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    volumes: list[VolumeMount] = Field(default_factory=list)
    gpu: Optional[GPUConfig] = None
    cpu_limit: Optional[str] = None
    memory_limit: Optional[str] = None
    cpu_reservation: Optional[str] = None
    memory_reservation: Optional[str] = None
    replicas: int = 1
    depends_on: list[str] = Field(default_factory=list)
    healthcheck_cmd: Optional[str] = None
    healthcheck_interval: str = "30s"
    healthcheck_timeout: str = "10s"
    healthcheck_retries: int = 3
    restart_policy: str = "unless-stopped"
    networks: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)


class DockerComposeConfig(BaseModel):
    version: str = "3.9"
    services: dict[str, ContainerConfig]
    volumes: dict[str, dict] = Field(default_factory=dict)
    networks: dict[str, dict] = Field(default_factory=dict)

    def to_compose_yaml(self) -> str:
        """Docker Compose YAML çıktısı üretir."""
        # Gerçek implementasyonda pyyaml veya jinja2 kullanılır
        raise NotImplementedError

    def validate_services(self) -> list[str]:
        """Servis bağımlılıklarını doğrular."""
        errors = []
        service_names = set(self.services.keys())
        for name, config in self.services.items():
            for dep in config.depends_on:
                if dep not in service_names:
                    errors.append(
                        f"Servis '{name}' '{dep}' servisine bağımlı, "
                        f"ama '{dep}' tanımlı değil"
                    )
        return errors
```

---

## 2. Kubernetes Dağıtımı

### 2.1 Amaç

Üretim ortamında Kubernetes, konteyner orkestrasyonu için aşağıdaki gereksinimleri karşılar:

- GPU kaynaklarının programatik yönetimi
- Otomatik ölçeklendirme (HPA/VPA)
- Sıfır kesintili dağıtım (rolling update, canary)
- Servis keşfi ve yük dengeleme
- Yapılandırma ve sır yönetimi
- Günlük toplama ve izleme entegrasyonu

### 2.2 Namespace Tanımı

```yaml
# k8s/base/namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tuncay-klip
  labels:
    app.kubernetes.io/part-of: tuncay-klip
    app.kubernetes.io/version: "1.0.0"
    istio-injection: enabled
  annotations:
    scheduler.alpha.kubernetes.io/defaultTolerations: >-
      [{"key":"nvidia.com/gpu","operator":"Exists","effect":"NoSchedule"}]
```

### 2.3 ConfigMap ve Secrets

```yaml
# k8s/base/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: tuncay-klip-config
  namespace: tuncay-klip
data:
  APP_ENV: "production"
  LOG_LEVEL: "info"
  LOG_FORMAT: "json"
  WORKER_RENDER_CONCURRENCY: "4"
  WORKER_POSTPROCESS_CONCURRENCY: "8"
  REDIS_MAX_CONNECTIONS: "50"
  RABBITMQ_PREFETCH_COUNT: "10"
  S3_BUCKET: "tuncay-klip-production"
  TEMP_DIR: "/data/temp"
  TEMPLATE_DIR: "/data/templates"
  MAX_CONCURRENT_RENDERS: "100"
  JOB_TIMEOUT_SECONDS: "3600"
  FFmpeg_THREADS: "4"
  GPU_MEMORY_FRACTION: "0.85"
  prometheus.yml: |
    global:
      scrape_interval: 15s
      evaluation_interval: 15s
    scrape_configs:
      - job_name: 'tuncay-klip-api'
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names: ['tuncay-klip']
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
            action: keep
            regex: true
          - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
            action: replace
            target_label: __address__
            regex: (.+)
            replacement: ${1}:9090

---
# k8s/base/secrets.yaml (base64 encoded değerler)
apiVersion: v1
kind: Secret
metadata:
  name: tuncay-klip-secrets
  namespace: tuncay-klip
type: Opaque
data:
  DATABASE_URL: cG9zdGdyZXNxbCthc3luY3BnOi8vYXBwOnNlY3JldEBwb3N0Z3Jlczp1a3AtcHJvZC5zZWNyZXRzLnN2Yy5jbHVzdGVyLmxvY2FsOjU0MzIvdHVuY2F5X2tsaXA=
  REDIS_URL: cmVkaXM6Ly86c2VjcmV0QHJlZGlzLmhlYWRsZXNzLnR1bmNheS1rbGlwLnN2Yy5jbHVzdGVyLmxvY2FsOjYzNzkvMA==
  RABBITMQ_DEFAULT_PASS: dG9rZW4tc2VjcmV0LWtleQ==
  S3_ACCESS_KEY: YWtpYS1zZWNyZXQta2V5
  S3_SECRET_KEY: c2VjcmV0LWJ1Y2tldC1rZXk=
  JWT_SECRET: dGVzdC1zZWNyZXQta2V5LWZvci1qd3Q=
```

### 2.4 Deployment — API Sunucusu

```yaml
# k8s/api/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: tuncay-klip-api
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-api
    app.kubernetes.io/component: api
    app.kubernetes.io/part-of: tuncay-klip
spec:
  replicas: 3
  revisionHistoryLimit: 10
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app.kubernetes.io/name: tuncay-klip-api
  template:
    metadata:
      labels:
        app.kubernetes.io/name: tuncay-klip-api
        app.kubernetes.io/component: api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"
        sidecar.istio.io/inject: "true"
    spec:
      serviceAccountName: tuncay-klip-api
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app.kubernetes.io/name: tuncay-klip-api
      containers:
        - name: api
          image: registry.tuncay-klip.io/api:1.0.0
          imagePullPolicy: Always
          ports:
            - name: http
              containerPort: 8000
              protocol: TCP
            - name: metrics
              containerPort: 9090
              protocol: TCP
          envFrom:
            - configMapRef:
                name: tuncay-klip-config
            - secretRef:
                name: tuncay-klip-secrets
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2000m"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 10
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /health/ready
              port: http
            initialDelaySeconds: 10
            periodSeconds: 5
            timeoutSeconds: 5
            failureThreshold: 3
          startupProbe:
            httpGet:
              path: /health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
            failureThreshold: 30
          volumeMounts:
            - name: temp-volume
              mountPath: /data/temp
            - name: templates-volume
              mountPath: /data/templates
              readOnly: true
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: false
            capabilities:
              drop: ["ALL"]
      volumes:
        - name: temp-volume
          emptyDir:
            sizeLimit: 10Gi
        - name: templates-volume
          configMap:
            name: tuncay-klip-templates
```

### 2.5 Deployment — GPU Worker (DaemonSet)

```yaml
# k8s/workers/daemonset-gpu.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: tuncay-klip-gpu-worker
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-gpu-worker
    app.kubernetes.io/component: worker
    app.kubernetes.io/worker-type: gpu
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: tuncay-klip-gpu-worker
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
  template:
    metadata:
      labels:
        app.kubernetes.io/name: tuncay-klip-gpu-worker
        app.kubernetes.io/component: worker
        app.kubernetes.io/worker-type: gpu
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
        prometheus.io/path: "/metrics"
    spec:
      nodeSelector:
        accelerator: nvidia-tesla-a100
        node-role.kubernetes.io/gpu: "true"
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
        - key: dedicated
          operator: Equal
          value: gpu-pool
          effect: NoSchedule
      serviceAccountName: tuncay-klip-worker
      terminationGracePeriodSeconds: 120
      containers:
        - name: worker
          image: registry.tuncay-klip.io/worker:1.0.0
          imagePullPolicy: Always
          command: ["python3", "-m", "src.workers.render_worker"]
          args:
            - "--concurrency"
            - "4"
            - "--prefetch"
            - "10"
          envFrom:
            - configMapRef:
                name: tuncay-klip-config
            - secretRef:
                name: tuncay-klip-secrets
          env:
            - name: WORKER_TYPE
              value: "render"
            - name: NVIDIA_VISIBLE_DEVICES
              valueFrom:
                fieldRef:
                  fieldPath: metadata.annotations['nvidia.com/gpu.dev']
            - name: GPU_MEMORY_LIMIT
              value: "8589934592"
            - name: NODE_NAME
              valueFrom:
                fieldRef:
                  fieldPath: spec.nodeName
          resources:
            requests:
              cpu: "4000m"
              memory: "8Gi"
              nvidia.com/gpu: "1"
            limits:
              cpu: "8000m"
              memory: "16Gi"
              nvidia.com/gpu: "1"
          volumeMounts:
            - name: media-input
              mountPath: /data/input
            - name: media-output
              mountPath: /data/output
            - name: temp-volume
              mountPath: /data/temp
            - name: templates-volume
              mountPath: /data/templates
              readOnly: true
            - name: nvidia-driver
              mountPath: /usr/local/nvidia
              readOnly: true
            - name: dev-nvidia
              mountPath: /dev/nvidia0
            - name: dev-nvidiactl
              mountPath: /dev/nvidiactl
            - name: dev-nvidia-uvm
              mountPath: /dev/nvidia-uvm
          livenessProbe:
            httpGet:
              path: /health/worker
              port: 8001
            initialDelaySeconds: 30
            periodSeconds: 15
            timeoutSeconds: 10
            failureThreshold: 3
          securityContext:
            allowPrivilegeEscalation: false
      volumes:
        - name: media-input
          persistentVolumeClaim:
            claimName: tuncay-klip-media-input
        - name: media-output
          persistentVolumeClaim:
            claimName: tuncay-klip-media-output
        - name: temp-volume
          hostPath:
            path: /mnt/nvme/temp
            type: DirectoryOrCreate
        - name: templates-volume
          configMap:
            name: tuncay-klip-templates
        - name: nvidia-driver
          hostPath:
            path: /usr/lib/x86_64-linux-gnu
            type: Directory
        - name: dev-nvidia
          hostPath:
            path: /dev/nvidia0
            type: CharDevice
        - name: dev-nvidiactl
          hostPath:
            path: /dev/nvidiactl
            type: CharDevice
        - name: dev-nvidia-uvm
          hostPath:
            path: /dev/nvidia-uvm
            type: CharDevice
```

### 2.6 Deployment — CPU Worker (StatefulSet / Koordinatör)

```yaml
# k8s/workers/statefulset-coordinator.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: tuncay-klip-coordinator
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-coordinator
    app.kubernetes.io/component: coordinator
spec:
  serviceName: tuncay-klip-coordinator
  replicas: 1
  podManagementPolicy: OrderedReady
  selector:
    matchLabels:
      app.kubernetes.io/name: tuncay-klip-coordinator
  template:
    metadata:
      labels:
        app.kubernetes.io/name: tuncay-klip-coordinator
        app.kubernetes.io/component: coordinator
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
    spec:
      nodeSelector:
        node-role.kubernetes.io/worker: "true"
      serviceAccountName: tuncay-klip-coordinator
      containers:
        - name: coordinator
          image: registry.tuncay-klip.io/coordinator:1.0.0
          command: ["python3", "-m", "src.workers.coordinator"]
          envFrom:
            - configMapRef:
                name: tuncay-klip-config
            - secretRef:
                name: tuncay-klip-secrets
          env:
            - name: COORDINATOR_ROLE
              value: "master"
            - name: COORDINATOR_ID
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          resources:
            requests:
              cpu: "2000m"
              memory: "4Gi"
            limits:
              cpu: "4000m"
              memory: "8Gi"
          volumeMounts:
            - name: coordinator-data
              mountPath: /data/coordinator
            - name: media-input
              mountPath: /data/input
            - name: media-output
              mountPath: /data/output
  volumeClaimTemplates:
    - metadata:
        name: coordinator-data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: fast-ssd
        resources:
          requests:
            storage: 50Gi
```

### 2.7 Service ve Ingress

```yaml
# k8s/networking/service-api.yaml
apiVersion: v1
kind: Service
metadata:
  name: tuncay-klip-api
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-api
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "9090"
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: tuncay-klip-api
  ports:
    - name: http
      port: 80
      targetPort: http
      protocol: TCP
    - name: metrics
      port: 9090
      targetPort: metrics
      protocol: TCP

---
# k8s/networking/service-worker.yaml
apiVersion: v1
kind: Service
metadata:
  name: tuncay-klip-gpu-worker
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-gpu-worker
spec:
  type: ClusterIP
  clusterIP: None  # Headless service (DaemonSet için)
  selector:
    app.kubernetes.io/name: tuncay-klip-gpu-worker
  ports:
    - name: metrics
      port: 9090
      targetPort: metrics

---
# k8s/networking/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: tuncay-klip-ingress
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-ingress
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "500m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "600"
    nginx.ingress.kubernetes.io/proxy-connect-timeout: "60"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/rate-limit-connections: "10"
    nginx.ingress.kubernetes.io/rate-limit-rps: "50"
    nginx.ingress.kubernetes.io/configuration-snippet: |
      more_set_headers "X-Request-ID: $request_id";
      more_set_headers "X-Real-IP: $remote_addr";
      more_set_headers "Strict-Transport-Security: max-age=31536000; includeSubDomains";
      more_set_headers "X-Content-Type-Options: nosniff";
      more_set_headers "X-Frame-Options: DENY";
      more_set_headers "Referrer-Policy: strict-origin-when-cross-origin";
    cert-manager.io/cluster-issuer: letsencrypt-prod
    traefik.ingress.kubernetes.io/ratelimit-average: "100"
    traefik.ingress.kubernetes.io/ratelimit-burst: "200"
spec:
  ingressClassName: nginx
  tls:
    - hosts:
        - api.tuncay-klip.io
      secretName: tuncay-klip-tls
  rules:
    - host: api.tuncay-klip.io
      http:
        paths:
          - path: /api/v1
            pathType: Prefix
            backend:
              service:
                name: tuncay-klip-api
                port:
                  name: http
          - path: /health
            pathType: Exact
            backend:
              service:
                name: tuncay-klip-api
                port:
                  name: http
          - path: /metrics
            pathType: Exact
            backend:
              service:
                name: tuncay-klip-api
                port:
                  name: metrics
```

### 2.8 Persistent Volume Claims

```yaml
# k8s/storage/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: tuncay-klip-media-input
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/part-of: tuncay-klip
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-client
  resources:
    requests:
      storage: 500Gi

---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: tuncay-klip-media-output
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/part-of: tuncay-klip
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: nfs-client
  resources:
    requests:
      storage: 1Ti

---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: fast-ssd
  annotations:
    storageclass.kubernetes.io/is-default-class: "false"
provisioner: kubernetes.io/aws-ebs
parameters:
  type: gp3
  fsType: ext4
  iopsPerGB: "50"
  throughput: "250"
reclaimPolicy: Retain
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
---
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nfs-client
provisioner: nfs-subdir-external-provisioner
parameters:
  server: 10.0.1.100
  path: /exports/media
reclaimPolicy: Retain
volumeBindingMode: Immediate
```

### 2.9 Veri Yapıları

```python
# src/infrastructure/k8s_config.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class K8sResourceType(str, Enum):
    DEPLOYMENT = "Deployment"
    DAEMONSET = "DaemonSet"
    STATEFULSET = "StatefulSet"
    SERVICE = "Service"
    INGRESS = "Ingress"
    HPA = "HorizontalPodAutoscaler"


class ResourceRequests(BaseModel):
    cpu: str = "100m"
    memory: str = "128Mi"
    gpu: Optional[str] = None  # "nvidia.com/gpu: 1"


class ResourceLimits(BaseModel):
    cpu: str = "1000m"
    memory: str = "1Gi"
    gpu: Optional[str] = None


class ProbeConfig(BaseModel):
    path: str = "/health"
    port: int = 8000
    initial_delay_seconds: int = 30
    period_seconds: int = 15
    timeout_seconds: int = 10
    failure_threshold: int = 3


class K8sDeployment(BaseModel):
    name: str
    namespace: str = "tuncay-klip"
    replicas: int = 3
    image: str
    tag: str = "latest"
    ports: list[int] = Field(default_factory=lambda: [8000])
    env_from_configmap: Optional[str] = None
    env_from_secret: Optional[str] = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    requests: ResourceRequests = Field(default_factory=ResourceRequests)
    limits: ResourceLimits = Field(default_factory=ResourceLimits)
    liveness_probe: Optional[ProbeConfig] = None
    readiness_probe: Optional[ProbeConfig] = None
    node_selector: dict[str, str] = Field(default_factory=dict)
    tolerations: list[dict] = Field(default_factory=list)
    volumes: list[dict] = Field(default_factory=list)
    volume_mounts: list[dict] = Field(default_factory=list)
    strategy: str = "RollingUpdate"
    max_surge: int = 1
    max_unavailable: int = 0
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)

    def to_yaml(self) -> str:
        """Kubernetes Deployment YAML manifesti üretir."""
        raise NotImplementedError


class K8sService(BaseModel):
    name: str
    namespace: str = "tuncay-klip"
    service_type: str = "ClusterIP"  # ClusterIP, NodePort, LoadBalancer
    selector: dict[str, str]
    ports: list[dict] = Field(default_factory=list)
    session_affinity: bool = False


class HPAConfig(BaseModel):
    name: str
    namespace: str = "tuncay-klip"
    target_ref: str  # Deployment adı
    min_replicas: int = 2
    max_replicas: int = 20
    metrics: list["ScalingMetric"] = Field(default_factory=list)
    behavior: Optional["HPABehavior"] = None


class HPABehavior(BaseModel):
    scale_up_stabilization_window: int = 60
    scale_down_stabilization_window: int = 300
    scale_up_policies: list[dict] = Field(default_factory=list)
    scale_down_policies: list[dict] = Field(default_factory=list)
```

---

## 3. Worker Otomatik Ölçeklendirme

### 3.1 Amaç

Otomatik ölçeklendirme, iş kuyruğundaki yüke göre GPU ve CPU worker sayısını dinamik olarak ayarlar. Böylece:
- Yüksek yükte yeterli iş gücü sağlanır
- Düşük yükte kaynak israfı önlenir
- Maliyet optimizasyonu yapılır

### 3.2 HPA — Job Queue Tabanlı Ölçeklendirme

```yaml
# k8s/autoscaling/hpa-gpu-worker.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: tuncay-klip-gpu-worker-hpa
  namespace: tuncay-klip
  labels:
    app.kubernetes.io/name: tuncay-klip-gpu-worker
    app.kubernetes.io/component: autoscaler
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: DaemonSet
    name: tuncay-klip-gpu-worker
  minReplicas: 2
  maxReplicas: 20
  metrics:
    # Özel metrik: Kuyruktaki bekleme iş sayısı
    - type: Pods
      pods:
        metric:
          name: render_queue_depth
        target:
          type: AverageValue
          averageValue: "5"

    # GPU kullanımı ortalaması
    - type: Pods
      pods:
        metric:
          name: gpu_utilization_percent
        target:
          type: AverageValue
          averageValue: "70"

    # CPU kullanımı
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 75

    # Bellek kullanımı
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 60
      policies:
        - type: Percent
          value: 100
          periodSeconds: 60
        - type: Pods
          value: 4
          periodSeconds: 60
      selectPolicy: Max
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 25
          periodSeconds: 120
        - type: Pods
          value: 2
          periodSeconds: 120
      selectPolicy: Min

---
# k8s/autoscaling/hpa-api.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: tuncay-klip-api-hpa
  namespace: tuncay-klip
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: tuncay-klip-api
  minReplicas: 3
  maxReplicas: 15
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 65
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 75
    # Request rate tabanlı ölçeklendirme (Prometheus custom metric)
    - type: Pods
      pods:
        metric:
          name: http_requests_per_second
        target:
          type: AverageValue
          averageValue: "100"
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 30
      policies:
        - type: Percent
          value: 50
          periodSeconds: 60
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 120
```

### 3.3 Custom Metrics Adapter — Prometheus

```yaml
# k8s/autoscaling/prometheus-adapter.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-adapter-config
  namespace: custom-metrics
data:
  config.yaml: |
    rules:
      - seriesQuery: 'render_queue_depth{namespace!="",pod!=""}'
        resources:
          overrides:
            namespace: {resource: "namespace"}
            pod: {resource: "pod"}
        name:
          matches: "^(.*)$"
          as: "${1}"
        metricsQuery: 'max_over_time(<<.Series>>[5m])'

      - seriesQuery: 'gpu_utilization_percent{namespace!="",pod!=""}'
        resources:
          overrides:
            namespace: {resource: "namespace"}
            pod: {resource: "pod"}
        name:
          matches: "^(.*)$"
          as: "${1}"
        metricsQuery: 'avg_over_time(<<.Series>>[5m])'

      - seriesQuery: 'http_requests_per_second{namespace!="",pod!=""}'
        resources:
          overrides:
            namespace: {resource: "namespace"}
            pod: {resource: "pod"}
        name:
          matches: "^(.*)$"
          as: "${1}"
        metricsQuery: 'sum(rate(<<.Series>>[5m])) by (<<.LabelGroups>>)'
```

### 3.4 Spot Instance Desteği

```yaml
# k8s/autoscaling/spot-instances.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: spot-interrupt-handler
  namespace: tuncay-klip
data:
  handler.sh: |
    #!/bin/bash
    # Spot instance kesinti sinyali işleyicisi
    # SIGTERM sinyali geldiğinde mevcut işleri bitir
    trap 'echo "Spot kesinti sinyali alındı, graceful shutdown başlatılıyor..."; \
          python3 -c "from src.workers.render_worker import graceful_shutdown; graceful_shutdown()"; \
          exit 0' SIGTERM SIGINT

    # Aktif işleri kaydet
    echo "$(date): Worker başlatıldı, PID=$$"

    # Worker ana döngüsü
    python3 -m src.workers.render_worker --graceful-shutdown-timeout=300

---
# k8s/autoscaling/node-pool-gpu-spot.yaml
apiVersion: v1
kind: NodePool
metadata:
  name: gpu-spot-pool
spec:
  instanceTypes:
    - p3.2xlarge
    - p3.8xlarge
    - g4dn.xlarge
    - g4dn.2xlarge
  capacityType: spot
  labels:
    accelerator: nvidia-tesla
    node-role.kubernetes.io/gpu: "true"
    node-pool: gpu-spot
  taints:
    - key: nvidia.com/gpu
      value: "true"
      effect: NoSchedule
  scalingConfig:
    minSize: 0
    maxSize: 10
    desiredSize: 2
```

### 3.5 Veri Yapıları

```python
# src/infrastructure/scaling.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class MetricType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    GPU_UTILIZATION = "gpu_utilization"
    QUEUE_DEPTH = "queue_depth"
    REQUEST_RATE = "request_rate"
    CUSTOM = "custom"


class ScalingDirection(str, Enum):
    UP = "up"
    DOWN = "down"


class ScalingMetric(BaseModel):
    type: MetricType
    name: Optional[str] = None  # Custom metric için
    target_value: float
    target_type: str = "utilization"  # utilization | averageValue | value
    window_seconds: int = 300


class ScalingPolicy(BaseModel):
    direction: ScalingDirection
    type: str  # "percent" | "pods" | "cpu" | "memory"
    value: int
    period_seconds: int = 60


class ScaleDownConfig(BaseModel):
    stabilization_window: int = 300
    grace_period: int = 120
    max_scale_down_percent: int = 25
    min_job_completion_before_scale: int = 300
    enable_eviction_check: bool = True


class SpotInstanceConfig(BaseModel):
    enabled: bool = True
    max_spot_price: Optional[float] = None  # $/saat
    interrupt_handling: str = "graceful"  # graceful | immediate
    fallback_to_on_demand: bool = True
    drain_timeout: int = 300
    instance_types: list[str] = Field(
        default=["p3.2xlarge", "p3.8xlarge", "g4dn.xlarge", "g4dn.2xlarge"]
    )


class PredictiveScalingConfig(BaseModel):
    enabled: bool = False
    schedule: list["ScalingSchedule"] = Field(default_factory=list)
    forecast_window_minutes: int = 30


class ScalingSchedule(BaseModel):
    name: str
    cron_expression: str  # "0 9 * * 1-5" (Pazartesi-Cuma 09:00)
    min_replicas: int
    max_replicas: int
    target_utilization: float = 0.6
    time_zone: str = "Europe/Istanbul"
```

---

## 4. İzleme ve Gözlemlenebilirlik

### 4.1 Amaç

Üretim ortamında tam gözlemlenebilirlik sağlamak için üç temel sütun kullanılır:
- **Metrikler**: Sayısal veriler (Prometheus + Grafana)
- **Günlükler**: Olay kayıtları (Loki + Promtail)
- **İzleme**: Dağıtık izleme (OpenTelemetry + Jaeger)

### 4.2 Prometheus Metrikleri

```python
# src/monitoring/metrics.py
from prometheus_client import (
    Counter, Histogram, Gauge, Summary, Info, Enum
)
from prometheus_client import CollectorRegistry, generate_latest
from typing import Optional
import time


# ─────────────── İş Kuyruğu Metrikleri ───────────────
RENDER_JOBS_TOTAL = Counter(
    name="tuncay_klip_render_jobs_total",
    description="Toplam render iş sayısı",
    labelnames=["status", "template_type", "output_format", "priority"],
    registry=None
)

RENDER_JOB_DURATION = Histogram(
    name="tuncay_klip_render_job_duration_seconds",
    description="Render iş süresi (saniye)",
    labelnames=["template_type", "output_format", "complexity"],
    buckets=[1, 5, 10, 30, 60, 120, 300, 600, 1800, 3600],
    registry=None
)

RENDER_JOB_QUEUE_DEPTH = Gauge(
    name="tuncay_klip_render_queue_depth",
    description="Kuyruktaki bekleme iş sayısı",
    labelnames=["queue_name", "priority"],
    registry=None
)

RENDER_JOB_IN_PROGRESS = Gauge(
    name="tuncay_klip_render_jobs_in_progress",
    description="İşlenmekte olan aktif iş sayısı",
    labelnames=["worker_id", "worker_type"],
    registry=None
)

RENDER_JOB_FAILED = Counter(
    name="tuncay_klip_render_jobs_failed_total",
    description="Başarısız render iş sayısı",
    labelnames=["error_type", "template_type", "retry_count"],
    registry=None
)

RENDER_JOB_RETRY = Counter(
    name="tuncay_klip_render_job_retries_total",
    description="Yeniden deneme sayısı",
    labelnames=["error_type"],
    registry=None
)

# ─────────────── GPU Metrikleri ───────────────
GPU_UTILIZATION = Gauge(
    name="tuncay_klip_gpu_utilization_percent",
    description="GPU kullanım yüzdesi",
    labelnames=["gpu_id", "worker_id"],
    registry=None
)

GPU_MEMORY_USAGE = Gauge(
    name="tuncay_klip_gpu_memory_usage_bytes",
    description="GPU bellek kullanımı (byte)",
    labelnames=["gpu_id", "worker_id"],
    registry=None
)

GPU_TEMPERATURE = Gauge(
    name="tuncay_klip_gpu_temperature_celsius",
    description="GPU sıcaklığı (santigrat)",
    labelnames=["gpu_id"],
    registry=None
)

GPU_POWER_USAGE = Gauge(
    name="tuncay_klip_gpu_power_usage_watts",
    description="GPU güç tüketimi (watt)",
    labelnames=["gpu_id"],
    registry=None
)

# ─────────────── Sistem Metrikleri ───────────────
API_REQUEST_TOTAL = Counter(
    name="tuncay_klip_api_requests_total",
    description="Toplam API istek sayısı",
    labelnames=["method", "endpoint", "status_code"],
    registry=None
)

API_REQUEST_DURATION = Histogram(
    name="tuncay_klip_api_request_duration_seconds",
    description="API istek süresi (saniye)",
    labelnames=["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    registry=None
)

API_REQUEST_IN_PROGRESS = Gauge(
    name="tuncay_klip_api_requests_in_progress",
    description="İşlenmekte olan API istek sayısı",
    registry=None
)

STORAGE_USAGE = Gauge(
    name="tuncay_klip_storage_usage_bytes",
    description="Depolama kullanımı (byte)",
    labelnames=["mount_point", "storage_type"],
    registry=None
)

# ─────────────── Sistem Bilgi Metrikleri ───────────────
APP_INFO = Info(
    name="tuncay_klip_app",
    description="Uygulama bilgileri",
    registry=None
)

WORKER_STATUS = Enum(
    name="tuncay_klip_worker_status",
    description="Worker durumu",
    states=["idle", "busy", "error", "draining"],
    labelnames=["worker_id", "worker_type"],
    registry=None
)
```

### 4.3 Metrik Exporter Endpoint

```python
# src/api/metrics_endpoint.py
from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from src.monitoring.metrics import (
    RENDER_JOBS_TOTAL, RENDER_JOB_QUEUE_DEPTH, GPU_UTILIZATION,
    APP_INFO
)

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics():
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )
```

### 4.4 Prometheus Yapılandırması

```yaml
# monitoring/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s
  scrape_timeout: 10s

alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093

rule_files:
  - /etc/prometheus/alerts.yml

scrape_configs:
  - job_name: "tuncay-klip-api"
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names: ["tuncay-klip"]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_name]
        regex: tuncay-klip-api
        action: keep
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:9090

  - job_name: "tuncay-klip-worker"
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names: ["tuncay-klip"]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app_kubernetes_io_worker_type]
        regex: gpu
        action: keep
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: (.+)
        replacement: ${1}:9090

  - job_name: "nvidia-gpu-exporter"
    static_configs:
      - targets:
          - nvidia-exporter:9835

  - job_name: "redis"
    static_configs:
      - targets:
          - redis:6379

  - job_name: "rabbitmq"
    static_configs:
      - targets:
          - rabbitmq:15692
```

### 4.5 Alert Kuralları

```yaml
# monitoring/alerts.yml
groups:
  - name: tuncay-klip-rendering
    rules:
      # Kuyruk birikmesi
      - alert: RenderQueueBackedUp
        expr: render_queue_depth{queue_name="render"} > 50
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Render kuyruğu birikti"
          description: >
            Render kuyruğunda {{ $value }} iş bekliyor.
            Eşik: 50 iş. 5 dakikadan uzun süredir birikme devam ediyor.
          runbook_url: https://runbooks.tuncay-klip.io/render-queue-backup

      - alert: RenderQueueCritical
        expr: render_queue_depth{queue_name="render"} > 200
        for: 2m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "Render kuyruğu KRİTİK"
          description: >
            Render kuyruğunda {{ $value }} iş bekliyor.
            Eşik: 20 iş. Hemen müdahale gerekli!

      # Render hataları
      - alert: RenderFailureRateHigh
        expr: |
          rate(tuncay_klip_render_jobs_failed_total[5m])
          / rate(tuncay_klip_render_jobs_total[5m]) > 0.1
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Yüksek render hata oranı"
          description: >
            Son 5 dakikada %{{ $value | humanizePercentage }} hata oranı.
            Eşik: %10.

      # Render süresi çok uzun
      - alert: RenderDurationHigh
        expr: |
          histogram_quantile(0.95, rate(tuncay_klip_render_job_duration_seconds_bucket[5m])) > 300
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Render süreleri çok uzun"
          description: >
            P95 render süresi {{ $value }} saniye. Eşik: 300 saniye.

      # Tüm worker'lar meşgul
      - alert: AllWorkersBusy
        expr: |
          count(tuncay_klip_render_jobs_in_progress > 0)
          == count(tuncay_klip_render_jobs_in_progress)
        for: 15m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Tüm worker'lar meşgul"
          description: >
            Tüm worker'lar {{ $value }} dakikadan beri meşgul.
            Ölçeklendirme gerekebilir.

  - name: tuncay-klip-gpu
    rules:
      # GPU hatası
      - alert: GPUError
        expr: tuncay_klip_gpu_utilization_percent == 0
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "GPU hatası tespit edildi"
          description: >
            GPU {{ $labels.gpu_id }} 5 dakikadır kullanılmıyor olabilir.
            GPU arızası kontrol edilmeli.

      # GPU sıcaklığı yüksek
      - alert: GPUTemperatureHigh
        expr: tuncay_klip_gpu_temperature_celsius > 85
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "GPU sıcaklığı yüksek"
          description: >
            GPU {{ $labels.gpu_id }} sıcaklığı {{ $value }}°C.
            Eşik: 85°C.

      # GPU bellek dolu
      - alert: GPUMemoryHigh
        expr: |
          tuncay_klip_gpu_memory_usage_bytes
          / nvidia_gpu_memory_total_bytes > 0.95
        for: 5m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "GPU bellek kullanımı çok yüksek"
          description: >
            GPU {{ $labels.gpu_id }} bellek kullanımı %{{ $value | humanizePercentage }}.
            Eşik: %95.

      # GPU gücü yüksek
      - alert: GPUPowerHigh
        expr: tuncay_klip_gpu_power_usage_watts > 300
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "GPU güç tüketimi yüksek"
          description: >
            GPU {{ $labels.gpu_id }} güç tüketimi {{ $value }}W.

  - name: tuncay-klip-system
    rules:
      # API yüksek hata oranı
      - alert: APIHighErrorRate
        expr: |
          sum(rate(tuncay_klip_api_requests_total{status_code=~"5.."}[5m]))
          / sum(rate(tuncay_klip_api_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: critical
          team: platform
        annotations:
          summary: "API yüksek hata oranı"
          description: >
            API hata oranı %{{ $value | humanizePercentage }}.
            Eşik: %5.

      # API yavaş yanıt
      - alert: APISlowResponse
        expr: |
          histogram_quantile(0.95, rate(tuncay_klip_api_request_duration_seconds_bucket[5m])) > 2
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "API yavaş yanıt veriyor"
          description: >
            P95 API yanıt süresi {{ $value }} saniye.
            Eşik: 2 saniye.

      # Disk alanı azalıyor
      - alert: DiskSpaceLow
        expr: |
          node_filesystem_avail_bytes{mountpoint="/data"} / node_filesystem_size_bytes{mountpoint="/data"} < 0.15
        for: 10m
        labels:
          severity: warning
          team: platform
        annotations:
          summary: "Disk alanı azalıyor"
          description: >
            /data disk alanının yalnızca %{{ $value | humanizePercentage }}'ı kaldı.
            Eşik: %15.
```

### 4.6 Dağıtık İzleme — OpenTelemetry

```python
# src/monitoring/tracing.py
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.celery import CeleryInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.pymongo import PymongoInstrumentor
from contextlib import contextmanager
from typing import Optional
import time


# Kaynak tanımı
resource = Resource.create({
    "service.name": "tuncay-klip",
    "service.version": "1.0.0",
    "service.environment": "production",
})

# Tracer provider yapılandırması
provider = TracerProvider(
    resource=resource,
    sampler=TraceIdRatioBased(0.1),  # %10 örnekleme
)
processor = BatchSpanProcessor(
    OTLPSpanExporter(endpoint="http://otel-collector:4317")
)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("tuncay-klip")


@contextmanager
def trace_render_job(
    job_id: str,
    template_type: str,
    output_format: str
):
    """Render işi için izleme bağlamı."""
    with tracer.start_as_current_span(
        "render_job",
        attributes={
            "job.id": job_id,
            "job.template_type": template_type,
            "job.output_format": output_format,
        }
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_status(trace.StatusCode.OK)
            span.set_attribute("job.duration_seconds", time.time() - start)
        except Exception as e:
            span.set_status(trace.StatusCode.ERROR, str(e))
            span.record_exception(e)
            raise


@contextmanager
def trace_render_phase(
    phase: str,
    parent_span: Optional[trace.Span] = None
):
    """Render aşaması için izleme bağlamı."""
    with tracer.start_as_current_span(
        f"render.{phase}",
        attributes={"render.phase": phase}
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_attribute("phase.duration_ms", (time.time() - start) * 1000)
        except Exception as e:
            span.set_record_exception(True)
            raise


def init_fastapi_tracing(app):
    """FastAPI uygulaması için otomatik HTTP izleme."""
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="health,metrics",
        server_request_hook=_server_request_hook,
    )


def _server_request_hook(span, scope):
    """HTTP istek hook'u — özel attribute'lar ekler."""
    if span and span.is_recording():
        headers = dict(scope.get("headers", []))
        if "x-job-id" in headers:
            span.set_attribute("http.request.job_id", headers["x-job-id"])
        if "x-priority" in headers:
            span.set_attribute("http.request.priority", headers["x-priority"])
```

### 4.7 Grafana Dashboard Yapısı

```json
{
  "dashboard": {
    "title": "Tuncay Klip - İşlem Altyapısı",
    "tags": ["tuncay-klip", "video-processing", "gpu"],
    "timezone": "turkey",
    "panels": [
      {
        "title": "Kuyruk Derinliği",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
        "targets": [
          {
            "expr": "render_queue_depth{queue_name=\"render\"}",
            "legendFormat": "{{ priority }}"
          }
        ]
      },
      {
        "title": "Aktif Render İşleri",
        "type": "stat",
        "gridPos": { "h": 8, "w": 6, "x": 12, "y": 0 },
        "targets": [
          {
            "expr": "sum(tuncay_klip_render_jobs_in_progress)",
            "legendFormat": "Aktif İş"
          }
        ]
      },
      {
        "title": "GPU Kullanımı",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
        "targets": [
          {
            "expr": "tuncay_klip_gpu_utilization_percent",
            "legendFormat": "GPU {{ gpu_id }}"
          }
        ]
      },
      {
        "title": "Render Hata Oranı",
        "type": "timeseries",
        "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
        "targets": [
          {
            "expr": "rate(tuncay_klip_render_jobs_failed_total[5m])",
            "legendFormat": "{{ error_type }}"
          }
        ]
      }
    ]
  }
}
```

### 4.8 Veri Yapıları

```python
# src/monitoring/definitions.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class MetricType(str, Enum):
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"
    INFO = "info"


class MetricDefinition(BaseModel):
    name: str
    description: str
    type: MetricType
    labels: list[str] = Field(default_factory=list)
    buckets: Optional[list[float]] = None  # Histogram için


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertRule(BaseModel):
    name: str
    expr: str  # PromQL sorgusu
    duration: str = "5m"  # Uzunluk
    severity: AlertSeverity
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    runbook_url: Optional[str] = None


class AlertManagerConfig(BaseModel):
    smtp_smarthost: str = "smtp.gmail.com:587"
    smtp_from: str = "alerts@tuncay-klip.io"
    smtp_auth_username: str = ""
    smtp_auth_password: str = ""
    slack_api_url: str = ""
    slack_channel: str = "#tuncay-klip-alerts"
    pagerduty_service_key: str = ""
```

---

## 5. Yapılandırma Yönetimi

### 5.1 Amaç

Uygulama yapılandırması:
- Ortama göre dinamik değişkenlik gösterir (geliştirme, test, prod)
- Sırlar güvenli şekilde saklanır
- Çalışma zamanında güncellenebilir
- Feature flags ile yeni özellikler kademeli olarak açılır

### 5.2 Ortam Tabanlı Yapılandırma

```python
# src/config/schema.py
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Optional
from enum import Enum


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class DatabaseConfig(BaseModel):
    url: str
    pool_size: int = 20
    max_overflow: int = 10
    pool_timeout: int = 30
    pool_recycle: int = 1800
    echo: bool = False


class RedisConfig(BaseModel):
    url: str
    max_connections: int = 50
    socket_timeout: int = 5
    socket_connect_timeout: int = 5
    retry_on_timeout: bool = True
    health_check_interval: int = 30


class RabbitMQConfig(BaseModel):
    url: str
    prefetch_count: int = 10
    heartbeat: int = 60
    blocked_connection_timeout: int = 300
    connection_attempts: int = 5


class S3Config(BaseModel):
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    region: str = "eu-west-1"
    multipart_threshold: int = 8388608  # 8 MB
    multipart_chunksize: int = 8388608
    max_concurrency: int = 10


class WorkerConfig(BaseModel):
    render_concurrency: int = 4
    postprocess_concurrency: int = 8
    max_concurrent_renders: int = 100
    job_timeout_seconds: int = 3600
    max_retries: int = 3
    retry_delay_seconds: int = 30


class FFmpegConfig(BaseModel):
    threads: int = 4
    hwaccel: str = "cuda"
    hwaccel_output_format: str = "cuda"
    gpu_memory_fraction: float = 0.85


class MonitoringConfig(BaseModel):
    prometheus_port: int = 9090
    otel_endpoint: str = "http://otel-collector:4317"
    log_level: str = "info"
    log_format: str = "json"
    sample_rate: float = 0.1


class AppConfig(BaseSettings):
    # Genel
    app_name: str = "tuncay-klip"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False

    # Alt yapılandırma nesneleri
    database: DatabaseConfig
    redis: RedisConfig
    rabbitmq: RabbitMQConfig
    s3: S3Config
    worker: WorkerConfig
    ffmpeg: FFmpegConfig
    monitoring: MonitoringConfig

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_nested_delimiter = "__"
        case_sensitive = False

    @classmethod
    def from_env(cls, env: str = "development") -> "AppConfig":
        """Ortam değişkenlerinden yapılandırma oluşturur."""
        import os
        os.environ["ENVIRONMENT"] = env
        return cls()
```

### 5.3 Feature Flags

```python
# src/config/feature_flags.py
from pydantic import BaseModel
from typing import Optional
from enum import Enum
from datetime import datetime
import redis.asyncio as redis


class FlagStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    PERCENTAGE = "percentage"  # Kademeli açma


class FeatureFlag(BaseModel):
    name: str
    description: str
    status: FlagStatus = FlagStatus.DISABLED
    percentage: int = 0  # 0-100 arası
    allowed_users: list[str] = []  # Belirli kullanıcılara açma
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    tags: list[str] = []


class FeatureFlagManager:
    """Redis tabanlı feature flag yöneticisi."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.prefix = "feature_flag:"

    async def is_enabled(
        self,
        flag_name: str,
        user_id: Optional[str] = None
    ) -> bool:
        """Flag'ın aktif olup olmadığını kontrol eder."""
        flag_data = await self.redis.hgetall(f"{self.prefix}{flag_name}")
        if not flag_data:
            return False

        status = flag_data.get(b"status", b"disabled").decode()
        if status == "disabled":
            return False
        if status == "enabled":
            return True

        # Yüzde bazlı kontrol
        if status == "percentage":
            percentage = int(flag_data.get(b"percentage", 0))
            if user_id:
                # Kullanıcıya göre tutarlı hashing
                hash_val = hash(f"{flag_name}:{user_id}") % 100
                return hash_val < percentage
            return False

        return False

    async def set_flag(
        self,
        flag: FeatureFlag
    ) -> None:
        """Flag değerini ayarlar."""
        await self.redis.hset(
            f"{self.prefix}{flag.name}",
            mapping={
                "description": flag.description,
                "status": flag.status.value,
                "percentage": str(flag.percentage),
                "allowed_users": ",".join(flag.allowed_users),
            }
        )

    async def get_all_flags(self) -> dict[str, FeatureFlag]:
        """Tüm flag'ları getirir."""
        keys = []
        async for key in self.redis.scan_iter(f"{self.prefix}*"):
            keys.append(key)

        flags = {}
        for key in keys:
            name = key.decode().replace(self.prefix, "")
            data = await self.redis.hgetall(key)
            flags[name] = FeatureFlag(
                name=name,
                description=data.get(b"description", b"").decode(),
                status=FlagStatus(data.get(b"status", b"disabled").decode()),
                percentage=int(data.get(b"percentage", 0)),
                allowed_users=data.get(b"allowed_users", b"").decode().split(","),
            )
        return flags


# Tanımlı flag'lar
KNOWN_FLAGS = {
    "gpu-accelerated-templates": FeatureFlag(
        name="gpu-accelerated-templates",
        description="Yeni GPU hızlandırmalı şablonları aktif et",
        status=FlagStatus.PERCENTAGE,
        percentage=25,
    ),
    "parallel-render-engine": FeatureFlag(
        name="parallel-render-engine",
        description="Paralel render motorunu aktif et",
        status=FlagStatus.DISABLED,
    ),
    "new-thumbnail-generation": FeatureFlag(
        name="new-thumbnail-generation",
        description="Yeni küçük resim oluşturma algoritması",
        status=FlagStatus.PERCENTAGE,
        percentage=50,
    ),
}
```

### 5.4 Vault Entegrasyonu

```python
# src/config/vault.py
import hvac  # HashiCorp Vault client
from typing import Optional
import os


class VaultSecretManager:
    """HashiCorp Vault ile sır yönetimi."""

    def __init__(
        self,
        vault_url: str = "http://vault:8200",
        vault_token: Optional[str] = None,
        vault_role: Optional[str] = None
    ):
        self.client = hvac.Client(url=vault_url)

        if vault_token:
            self.client.token = vault_token
        elif os.environ.get("VAULT_ROLE"):
            # Kubernetes auth method
            self.client.auth.kubernetes.login(
                role=os.environ.get("VAULT_ROLE"),
                jwt=open("/var/run/secrets/kubernetes.io/serviceaccount/token").read()
            )

    def get_secret(self, path: str, key: Optional[str] = None) -> str:
        """Sır değerini okur."""
        secret = self.client.secrets.kv.v2.read_secret_version(
            path=path,
            raise_on_deleted_version=True
        )
        if key:
            return secret["data"]["data"][key]
        return secret["data"]["data"]

    def get_database_credentials(self) -> dict:
        """Veritabanı bilgilerini getirir."""
        return self.get_secret("tuncay-klip/database")

    def get_redis_credentials(self) -> dict:
        """Redis bilgilerini getirir."""
        return self.get_secret("tuncay-klip/redis")

    def get_s3_credentials(self) -> dict:
        """S3/MinIO bilgilerini getirir."""
        return self.get_secret("tuncay-klip/s3")
```

### 5.5 Çalışma Zamanı Yapılandırma Güncelleme

```python
# src/config/hot_reload.py
import asyncio
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from typing import Callable
import yaml
import logging

logger = logging.getLogger(__name__)


class ConfigFileHandler(FileSystemEventHandler):
    """Yapılandırma dosyası değişikliklerini izler."""

    def __init__(self, config_callback: Callable):
        self.config_callback = config_callback

    def on_modified(self, event):
        if event.src_path.endswith(('.yaml', '.yml', '.json')):
            logger.info(f"Yapılandırma dosyası değişti: {event.src_path}")
            try:
                with open(event.src_path, 'r') as f:
                    new_config = yaml.safe_load(f)
                self.config_callback(new_config)
                logger.info("Yapılandırma başarıyla güncellendi")
            except Exception as e:
                logger.error(f"Yapılandırma güncelleme hatası: {e}")


class ConfigWatcher:
    """Yapılandırma dosyalarını izler ve sıcak yeniden yükleme yapar."""

    def __init__(self, config_dir: str, reload_callback: Callable):
        self.observer = Observer()
        self.handler = ConfigFileHandler(reload_callback)
        self.config_dir = config_dir

    def start(self):
        self.observer.schedule(
            self.handler,
            self.config_dir,
            recursive=True
        )
        self.observer.start()
        logger.info(f"Yapılandırma izleyici başlatıldı: {self.config_dir}")

    def stop(self):
        self.observer.stop()
        self.observer.join()
```

### 5.6 Veri Yapıları

```python
# src/config/definitions.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class ConfigSource(str, Enum):
    ENV = "env"
    FILE = "file"
    VAULT = "vault"
    K8S_CONFIGMAP = "k8s_configmap"
    K8S_SECRET = "k8s_secret"
    REMOTE = "remote"


class ConfigSchema(BaseModel):
    key: str
    value: str
    source: ConfigSource
    sensitive: bool = False
    description: Optional[str] = None
    default: Optional[str] = None
    validation_regex: Optional[str] = None


class FeatureFlag(BaseModel):
    name: str
    description: str
    status: str = "disabled"
    percentage: int = 0
    allowed_users: list[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
```

---

## 6. CI/CD Hattı

### 6.1 Amaç

Otomasyonlu CI/CD hattı, aşağıdaki aşamaları kapsar:
1. Kod kalitesi kontrolleri (lint, test, güvenlik taraması)
2. Konteyner görüntüleri oluşturma ve depolama
3. Staging ortamına dağıtma
4. Canary dağıtımı
5. Üretim ortamına tam dağıtım
6. Geri alma stratejisi

### 6.2 Build Hattı

```yaml
# .github/workflows/build.yml
name: Build & Test Pipeline

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}
  PYTHON_VERSION: "3.11"

jobs:
  # ─────────────── 1. Kod Kalitesi ───────────────
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: poetry

      - name: Install dependencies
        run: poetry install --no-interaction

      - name: Ruff linting
        run: poetry run ruff check src/ tests/

      - name: Ruff format kontrolü
        run: poetry run ruff format --check src/ tests/

      - name: MyPy tip kontrolü
        run: poetry run mypy src/ --ignore-missing-imports

      - name: Bandit güvenlik taraması
        run: poetry run bandit -r src/ -f json -o bandit-report.json || true

  # ─────────────── 2. Test ───────────────
  test:
    runs-on: ubuntu-latest
    needs: lint
    services:
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: tuncay_klip_test
          POSTGRES_USER: test
          POSTGRES_PASSWORD: test
        ports: ["5432:5432"]
      rabbitmq:
        image: rabbitmq:3.13-management-alpine
        ports: ["5672:5672"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: poetry

      - name: Install dependencies
        run: poetry install --no-interaction

      - name: Unit testleri çalıştır
        run: poetry run pytest tests/unit -v --tb=short --cov=src --cov-report=xml

      - name: Entegrasyon testleri çalıştır
        run: poetry run pytest tests/integration -v --tb=short
        env:
          DATABASE_URL: postgresql+asyncpg://test:test@localhost:5432/tuncay_klip_test
          REDIS_URL: redis://localhost:6379/0
          RABBITMQ_URL: amqp://guest:guest@localhost:5672/

      - name: Test coverage raporu
        uses: codecov/codecov-action@v3
        with:
          file: ./coverage.xml

  # ─────────────── 3. Güvenlik Taraması ───────────────
  security:
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - name: Trivy vulnerability scanner (dependencies)
        uses: aquasecurity/trivy-action@master
        with:
          scan-type: "fs"
          scan-ref: "."
          format: "sarif"
          output: "trivy-fs-results.sarif"

      - name: Snyk security scan
        uses: snyk/actions/python@master
        continue-on-error: true
        env:
          SNYK_TOKEN: ${{ secrets.SNYK_TOKEN }}

  # ─────────────── 4. Konteyner Oluşturma ───────────────
  build:
    runs-on: ubuntu-latest
    needs: [test, security]
    permissions:
      contents: read
      packages: write
    outputs:
      image-tag: ${{ steps.meta.outputs.tags }}
      image-digest: ${{ steps.build-push.outputs.digest }}

    steps:
      - uses: actions/checkout@v4

      - name: Docker metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}
          tags: |
            type=ref,event=branch
            type=ref,event=pr
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=sha,prefix=

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to GHCR
        uses: docker/login-action@v3
        with:
          registry: ${{ env.REGISTRY }}
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push API image
        id: build-push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile
          target: runtime
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          build-args: |
            BUILD_DATE=${{ github.event.head_commit.timestamp }}
            VCS_REF=${{ github.sha }}

      - name: Build and push Worker image
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile
          target: worker-runtime
          push: true
          tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}/worker:${{ steps.meta.outputs.version }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Trivy vulnerability scan (image)
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.version }}
          format: "table"
          exit-code: "1"
          severity: "CRITICAL,HIGH"
```

### 6.3 Dağıtım Hattı

```yaml
# .github/workflows/deploy.yml
name: Deploy Pipeline

on:
  workflow_run:
    workflows: ["Build & Test Pipeline"]
    types: [completed]
    branches: [main]

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: ${{ github.repository }}
  K8S_NAMESPACE: tuncay-klip

jobs:
  # ─────────────── 1. Staging Dağıtımı ───────────────
  deploy-staging:
    runs-on: ubuntu-latest
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    environment: staging
    steps:
      - uses: actions/checkout@v4

      - name: Set up kubectl
        uses: azure/setup-kubectl@v3
        with:
          version: v1.28.0

      - name: Configure kubeconfig
        run: |
          mkdir -p $HOME/.kube
          echo "${{ secrets.KUBE_CONFIG_STAGING }}" | base64 -d > $HOME/.kube/config

      - name: Deploy to staging
        run: |
          IMAGE_TAG="${{ github.event.workflow_run.head_sha }}"
          export IMAGE_TAG

          # ConfigMap güncelle
          kubectl create configmap tuncay-klip-config \
            --from-env-file=configs/staging.env \
            --namespace=$K8S_NAMESPACE \
            --dry-run=client -o yaml | kubectl apply -f -

          # Deployment güncelle
          kubectl set image deployment/tuncay-klip-api \
            api=$REGISTRY/$IMAGE_NAME:$IMAGE_TAG \
            --namespace=$K8S_NAMESPACE

          kubectl set image daemonset/tuncay-klip-gpu-worker \
            worker=$REGISTRY/$IMAGE_NAME/worker:$IMAGE_TAG \
            --namespace=$K8S_NAMESPACE

      - name: Rolling update durumunu kontrol et
        run: |
          kubectl rollout status deployment/tuncay-klip-api \
            --namespace=$K8S_NAMESPACE --timeout=300s

          kubectl rollout status daemonset/tuncay-klip-gpu-worker \
            --namespace=$K8S_NAMESPACE --timeout=300s

      - name: Sağlık kontrolü
        run: |
          for i in {1..30}; do
            STATUS=$(curl -s https://staging-api.tuncay-klip.io/health | jq -r '.status')
            if [ "$STATUS" = "healthy" ]; then
              echo "✅ Staging sağlık kontrolü başarılı"
              exit 0
            fi
            echo "Bekleniyor... ($i/30)"
            sleep 10
          done
          echo "❌ Staging sağlık kontrolü başarısız"
          exit 1

  # ─────────────── 2. Canary Dağıtımı ───────────────
  canary-deploy:
    runs-on: ubuntu-latest
    needs: deploy-staging
    environment: canary
    steps:
      - uses: actions/checkout@v4

      - name: Canary deployment başlat
        run: |
          IMAGE_TAG="${{ github.event.workflow_run.head_sha }}"

          # %10 canary trafiği
          cat <<EOF | kubectl apply -f -
          apiVersion: apps/v1
          kind: Deployment
          metadata:
            name: tuncay-klip-api-canary
            namespace: $K8S_NAMESPACE
            labels:
              app.kubernetes.io/name: tuncay-klip-api
              app.kubernetes.io/variant: canary
          spec:
            replicas: 1
            selector:
              matchLabels:
                app.kubernetes.io/name: tuncay-klip-api
                app.kubernetes.io/variant: canary
            template:
              metadata:
                labels:
                  app.kubernetes.io/name: tuncay-klip-api
                  app.kubernetes.io/variant: canary
                annotations:
                  prometheus.io/scrape: "true"
                  prometheus.io/port: "9090"
              spec:
                containers:
                  - name: api
                    image: $REGISTRY/$IMAGE_NAME:$IMAGE_TAG
                    ports:
                      - containerPort: 8000
                    resources:
                      requests:
                        cpu: "500m"
                        memory: "512Mi"
          EOF

      - name: Canary metriklerini izle (10 dakika)
        run: |
          echo "Canary izleme başlatılıyor (10 dakika)..."
          for i in {1..20}; do
            ERROR_RATE=$(curl -s "http://prometheus:9090/api/v1/query?query=rate(tuncay_klip_api_requests_total{status_code=~'5..',pod=~'.*canary.*'}[5m])" | jq '.data.result[0].value[1] // "0"')
            echo "Canary hata oranı: $ERROR_RATE ($i/20)"

            if (( $(echo "$ERROR_RATE > 0.05" | bc -l) )); then
              echo "❌ Canary hata oranı çok yüksek: $ERROR_RATE"
              kubectl delete deployment tuncay-klip-api-canary \
                --namespace=$K8S_NAMESPACE
              exit 1
            fi
            sleep 30
          done
          echo "✅ Canary metrikleri normal"

      - name: Canary'yi production'a promote et
        run: |
          IMAGE_TAG="${{ github.event.workflow_run.head_sha }}"

          kubectl set image deployment/tuncay-klip-api \
            api=$REGISTRY/$IMAGE_NAME:$IMAGE_TAG \
            --namespace=$K8S_NAMESPACE

          kubectl set image daemonset/tuncay-klip-gpu-worker \
            worker=$REGISTRY/$IMAGE_NAME/worker:$IMAGE_TAG \
            --namespace=$K8S_NAMESPACE

          kubectl rollout status deployment/tuncay-klip-api \
            --namespace=$K8S_NAMESPACE --timeout=600s

          kubectl delete deployment tuncay-klip-api-canary \
            --namespace=$K8S_NAMESPACE

          echo "✅ Production dağıtımı tamamlandı"

  # ─────────────── 3. Dağıtım Sonrası Doğrulama ───────────────
  verify:
    runs-on: ubuntu-latest
    needs: canary-deploy
    steps:
      - name: Production sağlık kontrolü
        run: |
          for i in {1..10}; do
            STATUS=$(curl -s https://api.tuncay-klip.io/health | jq -r '.status')
            if [ "$STATUS" = "healthy" ]; then
              echo "✅ Production sağlık kontrolü başarılı"
              exit 0
            fi
            echo "Bekleniyor... ($i/10)"
            sleep 30
          done
          echo "❌ Production sağlık kontrolü başarısız — geri alma başlatılacak"
          exit 1
```

### 6.4 Geri Alma Stratejisi

```yaml
# k8s/ops/rollback.yaml
#!/bin/bash
# k8s/ops/rollback.sh — Otomatik geri alma betiği

set -euo pipefail

NAMESPACE="tuncay-klip"
DEPLOYMENT="${1:-tuncay-klip-api}"
REVISION="${2:-}"

echo "🔄 Geri alma başlatılıyor: $DEPLOYMENT"

# Önceki revizyonu al
if [ -z "$REVISION" ]; then
    REVISION=$(kubectl rollout history deployment/$DEPLOYMENT \
        --namespace=$NAMESPACE | tail -2 | head -1 | awk '{print $1}')
fi

echo "Hedef revizyon: $REVISION"

# Geri alma işlemini başlat
kubectl rollout undo deployment/$DEPLOYMENT \
    --to-revision=$REVISION \
    --namespace=$NAMESPACE

# Durumunu izle
echo "Geri alma durumu izleniyor..."
if kubectl rollout status deployment/$DEPLOYMENT \
    --namespace=$NAMESPACE --timeout=300s; then
    echo "✅ Geri alma başarılı"
else
    echo "❌ Geri alma başarısız — manuel müdahale gerekli"
    exit 1
fi

# Sağlık kontrolü
echo "Sağlık kontrolü yapılıyor..."
for i in {1..10}; do
    STATUS=$(curl -s https://api.tuncay-klip.io/health | jq -r '.status')
    if [ "$STATUS" = "healthy" ]; then
        echo "✅ Sistem sağlıklı"
        exit 0
    fi
    sleep 15
done

echo "❌ Sistem sağlıklı değil — acil durum prosedürü"
exit 1
```

### 6.5 Veri Yapıları

```python
# src/cicd/pipeline.py
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class PipelineStage(str, Enum):
    LINT = "lint"
    TEST = "test"
    SECURITY = "security"
    BUILD = "build"
    PUSH = "push"
    DEPLOY_STAGING = "deploy-staging"
    CANARY = "canary"
    DEPLOY_PRODUCTION = "deploy-production"
    VERIFY = "verify"
    ROLLBACK = "rollback"


class PipelineTrigger(str, Enum):
    PUSH = "push"
    PR = "pull_request"
    MANUAL = "manual"
    SCHEDULE = "schedule"
    WORKFLOW_RUN = "workflow_run"


class PipelineStep(BaseModel):
    name: str
    stage: PipelineStage
    command: Optional[str] = None
    uses: Optional[str] = None  # GitHub Action reference
    with_params: dict = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
    timeout_minutes: int = 30
    continue_on_error: bool = False
    needs: list[str] = Field(default_factory=list)
    if_condition: Optional[str] = None


class PipelineConfig(BaseModel):
    name: str
    trigger: PipelineTrigger
    branches: list[str] = Field(default_factory=lambda: ["main"])
    steps: list[PipelineStep]
    environment: str = "staging"
    concurrency_group: Optional[str] = None
    timeout_minutes: int = 60
    env_vars: dict[str, str] = Field(default_factory=dict)


class DeployStrategy(str, Enum):
    ROLLING = "rolling"
    BLUE_GREEN = "blue-green"
    CANARY = "canary"
    RECREATE = "recreate"


class DeployConfig(BaseModel):
    strategy: DeployStrategy = DeployStrategy.ROLLING
    namespace: str = "tuncay-klip"
    max_surge: int = 1
    max_unavailable: int = 0
    canary_percentage: int = 10
    canary_duration_minutes: int = 10
    rollback_on_failure: bool = True
    health_check_url: str = "/health"
    health_check_timeout: int = 300
```

---

## 7. Üretim Kontrol Listesi

### 7.1 Güvenlik Sertleştirmesi

```yaml
# k8s/security/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tuncay-klip-network-policy
  namespace: tuncay-klip
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # API sunucusuna sadece Ingress'ten erişim
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
      to:
        - port:
            number: 8000
    # Worker'lar arası iletişim (RabbitMQ)
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/component: worker
      to:
        - port:
            number: 8001
  egress:
    # DNS erişimi
    - to:
        - namespaceSelector: {}
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # Redis'e erişim
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: redis
      ports:
        - protocol: TCP
          port: 6379
    # RabbitMQ'ya erişim
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: rabbitmq
      ports:
        - protocol: TCP
          port: 5672

---
# k8s/security/pod-security-policy.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: restricted-pss-policy
  namespace: tuncay-klip
data:
  restricted.yaml: |
    apiVersion: pod-security.kubernetes.io/v1
    kind: restricted
    metadata:
      name: restricted
    spec:
      enforce: "restricted"
      audit: "restricted"
      warn: "restricted"
      exemptImages:
        - "registry.tuncay-klip.io/*"
```

```python
# src/security/rate_limiter.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import redis.asyncio as redis
import time


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Token bucket rate limiting middleware."""

    def __init__(
        self,
        app,
        redis_client: redis.Redis,
        requests_per_second: int = 100,
        burst_size: int = 200,
    ):
        super().__init__(app)
        self.redis = redis_client
        self.rps = requests_per_second
        self.burst = burst_size

    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        key = f"rate_limit:{client_ip}"

        # Redis ile sliding window rate limiting
        current = await self.redis.get(key)
        if current and int(current) >= self.burst:
            raise HTTPException(
                status_code=429,
                detail="Çok fazla istek. Lütfen bekleyin.",
                headers={"Retry-After": "1"}
            )

        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 1)
        await pipe.execute()

        response = await call_next(request)
        remaining = self.burst - int(await self.redis.get(key) or 0)
        response.headers["X-RateLimit-Limit"] = str(self.burst)
        response.headers["X-RateLimit-Remaining"] = str(max(0, remaining))
        return response
```

### 7.2 Yedekleme ve Felaket Kurtarma

```yaml
# k8s/backup/cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: tuncay-klip-backup
  namespace: tuncay-klip
spec:
  schedule: "0 2 * * *"  # Her gün saat 02:00
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 7
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 7200  # 2 saat timeout
      template:
        spec:
          serviceAccountName: tuncay-klip-backup
          containers:
            - name: backup
              image: registry.tuncay-klip.io/backup:latest
              command: ["/bin/bash", "/scripts/backup.sh"]
              envFrom:
                - secretRef:
                    name: tuncay-klip-backup-secrets
              env:
                - name: BACKUP_TARGET
                  value: "s3://tuncay-klip-backups"
                - name: RETENTION_DAYS
                  value: "30"
                - name: DATABASE_URL
                  valueFrom:
                    secretKeyRef:
                      name: tuncay-klip-secrets
                      key: DATABASE_URL
              volumeMounts:
                - name: backup-scripts
                  mountPath: /scripts
                - name: temp-backup
                  mountPath: /tmp/backup
          volumes:
            - name: backup-scripts
              configMap:
                name: tuncay-klip-backup-scripts
            - name: temp-backup
              emptyDir:
                sizeLimit: 100Gi
          restartPolicy: OnFailure
```

```bash
#!/bin/bash
# k8s/backup/backup.sh — Yedekleme betiği

set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/tmp/backup/$TIMESTAMP"
mkdir -p "$BACKUP_DIR"

echo "🔄 Yedekleme başlatıldı: $TIMESTAMP"

# 1. Veritabanı yedekleme
echo "📦 Veritabanı yedekleniyor..."
pg_dump "$DATABASE_URL" | gzip > "$BACKUP_DIR/database.sql.gz"

# 2. Redis yedekleme
echo "🔴 Redis yedekleniyor..."
redis-cli -u "$REDIS_URL" BGSAVE
sleep 5
redis-cli -u "$REDIS_URL" LASTSAVE > "$BACKUP_DIR/redis_lastsave.txt"
cp /data/dump.rdb "$BACKUP_DIR/redis_dump.rdb" 2>/dev/null || true

# 3. Template dosyaları yedekleme
echo "📄 Şablonlar yedekleniyor..."
tar -czf "$BACKUP_DIR/templates.tar.gz" /data/templates/

# 4. ConfigMap yedekleme
echo "⚙️ Yapılandırmalar yedekleniyor..."
kubectl get configmap -n tuncay-klip -o yaml > "$BACKUP_DIR/configmaps.yaml"

# 5. S3'e yükleme
echo "☁️ S3'e yükleniyor..."
aws s3 sync "$BACKUP_DIR" "$BACKUP_TARGET/$TIMESTAMP/" \
    --storage-class STANDARD_IA

# 6. Eski yedekleri temizle
echo "🧹 Eski yedekler temizleniyor..."
aws s3 ls "$BACKUP_TARGET/" | \
    awk '{print $2}' | \
    while read dir; do
        dir_date=$(echo $dir | cut -d'/' -f1)
        if [[ $(date -d "$dir_date" +%s) -lt $(date -d "-${RETENTION_DAYS} days" +%s) ]]; then
            aws s3 rm "$BACKUP_TARGET/$dir" --recursive
        fi
    done

echo "✅ Yedekleme tamamlandı: $TIMESTAMP"
```

### 7.3 Maliyet Optimizasyonu Stratejileri

```python
# src/ops/cost_optimizer.py
from pydantic import BaseModel
from typing import Optional
from enum import Enum
import datetime


class CostOptimizationStrategy(BaseModel):
    name: str
    description: str
    estimated_savings_percent: float
    implementation_complexity: str  # low | medium | high
    risk_level: str  # low | medium | high


STRATEGIES = [
    CostOptimizationStrategy(
        name="Spot Instance Kullanımı",
        description="GPU worker'lar için spot instance kullanımı",
        estimated_savings_percent=60.0,
        implementation_complexity="medium",
        risk_level="medium",
    ),
    CostOptimizationStrategy(
        name="GPU Bellek Paylaşımı",
        description="MPS (Multi-Process Service) ile GPU paylaşımı",
        estimated_savings_percent=30.0,
        implementation_complexity="high",
        risk_level="medium",
    ),
    CostOptimizationStrategy(
        name="Programatik Ölçeklendirme",
        description="Düşük yüklü saatlerde otomatik küçültme",
        estimated_savings_percent=40.0,
        implementation_complexity="low",
        risk_level="low",
    ),
    CostOptimizationStrategy(
        name="S3 Intelligent-Tiering",
        description="Erişim sıklığına göre otomatik katmanlama",
        estimated_savings_percent=25.0,
        implementation_complexity="low",
        risk_level="low",
    ),
    CostOptimizationStrategy(
        name="Reserved Instances",
        description="1-3 yıllık ayrılmış instance'lar",
        estimated_savings_percent=45.0,
        implementation_complexity="low",
        risk_level="low",
    ),
]


class SchedulingConfig(BaseModel):
    # Yoğun saatler
    peak_hours_start: int = 9   # 09:00
    peak_hours_end: int = 21    # 21:00
    peak_days: list[int] = [0, 1, 2, 3, 4]  # Pzt-Cmt

    # Düşük saatler
    off_peak_min_replicas: int = 1
    off_peak_max_replicas: int = 3

    # Yoğun saatler
    peak_min_replicas: int = 5
    peak_max_replicas: int = 20

    # Hafta sonu
    weekend_min_replicas: int = 1
    weekend_max_replicas: int = 5

    def get_current_schedule(self) -> dict:
        now = datetime.datetime.now()
        is_weekend = now.weekday() not in self.peak_days
        is_peak = (
            not is_weekend
            and self.peak_hours_start <= now.hour < self.peak_hours_end
        )

        if is_peak:
            return {"min": self.peak_min_replicas, "max": self.peak_max_replicas}
        elif is_weekend:
            return {"min": self.weekend_min_replicas, "max": self.weekend_max_replicas}
        else:
            return {"min": self.off_peak_min_replicas, "max": self.off_peak_max_replicas}
```

### 7.4 SLA Tanımları

```python
# src/ops/sla.py
from pydantic import BaseModel
from typing import Optional


class SLADefinition(BaseModel):
    """Servis Seviyesi Anlaşması tanımları."""

    # Uptime
    availability_target: float = 99.9  # %99.9 uptime
    monthly_downtime_budget_minutes: float = 43.8  # 0.1% × 43800 dk

    # Performans
    api_response_time_p95_ms: float = 500
    api_response_time_p99_ms: float = 1000
    render_completion_time_p95_seconds: float = 300

    # Hata oranları
    error_rate_target: float = 0.01  # %0.1 hata oranı
    render_success_rate: float = 99.5  # %99.5 başarılı render

    # Kuyruk
    max_queue_wait_time_seconds: float = 60
    max_queue_depth: int = 100

    # Veri dayanıklılığı
    data_durability: float = 99.999999999  # 11 nine (S3 standard)
    backup_rto_hours: float = 4  # Kurtarma süresi
    backup_rpo_hours: float = 1  # Veri kaybı toleransı


class SLOMetric(BaseModel):
    name: str
    target: float
    current: Optional[float] = None
    error_budget_remaining: Optional[float] = None

    def calculate_error_budget(self, window_days: int = 30) -> float:
        """Hata bütçesini hesaplar."""
        allowed_downtime = window_days * 24 * 60 * (1 - self.target / 100)
        return allowed_downtime
```

### 7.5 Operasyonel Çalışma Kitapları (Runbooks)

```markdown
# k8s/runbooks/render-queue-backup.md

# Runbook: Render Kuyruğu Birikmesi

## Severity: WARNING / CRITICAL

## Belirtiler
- `render_queue_depth{queue_name="render"} > 50` (warning) veya `> 200` (critical)
- Kullanıcılar render işlerinin tamamlanmasını uzun süre bekliyor

## Muhtemel Nedenler
1. GPU worker'lar yetersiz veya arızalı
2. Render işleri çok karmaşık (yüksek çözünürlük, uzun süre)
3. GPU bellek yetersizliği
4. Network bandwidth darboğazı (S3 okuma/yazma)
5. FFmpeg hataları (codec uyumsuzluğu)

## Müdahale Adımları

### 1. Mevcut Durumu Değerlendir
```bash
# Kuyruk derinliğini kontrol et
kubectl exec -n tuncay-klip redis-0 -- redis-cli LLEN queue:render

# Worker durumunu kontrol et
kubectl get pods -n tuncay-klip -l app.kubernetes.io/component=worker

# GPU durumunu kontrol et
kubectl exec -n tuncay-klip <worker-pod> -- nvidia-smi

# Hatalı iş sayısını kontrol et
kubectl exec -n tuncay-klip redis-0 -- redis-cli LLEN queue:render:failed
```

### 2. Worker Sayısını Artır
```bash
# GPU worker sayısını geçici olarak artır
kubectl scale daemonset tuncay-klip-gpu-worker \
    --namespace=tuncay-klip \
    --replicas=10
```

### 3. Eski İşleri Temizle
```bash
# 1 saatten eski bekleme işlerini temizle
kubectl exec -n tuncay-klip redis-0 -- redis-cli \
    ZREMRANGEBYSCORE queue:render -inf $(date -d '1 hour ago' +%s)
```

### 4. GPU Belleğini Kontrol Et
```bash
# GPU bellek kullanımını kontrol et
kubectl exec -n tuncay-klip <worker-pod> -- \
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv
```

## Çözüm Sonrası
1. Worker sayısını normal seviyeye döndür
2. Kuyruk derinliğini izlemeye devam et
3. Olayı postmortem raporuna ekle
```

```markdown
# k8s/runbooks/gpu-failure.md

# Runbook: GPU Arızası

## Severity: CRITICAL

## Belirtiler
- `tuncay_klip_gpu_utilization_percent == 0` (5 dakikadan uzun)
- `nvidia-smi` komutu başarısız
- Render işleri GPU hatası ile başarısız oluyor

## Müdahale Adımları

### 1. GPU Durumunu Doğrula
```bash
# Tüm GPU'ların durumunu kontrol et
kubectl get nodes -l accelerator=nvidia-tesla-a100 -o wide
kubectl exec -n tuncay-klip <worker-pod> -- nvidia-smi -L
kubectl exec -n tuncay-klip <worker-pod> -- nvidia-smi -q
```

### 2. GPU Sürücüsünü Kontrol Et
```bash
# Sürücü sürümünü kontrol et
kubectl exec -n tuncay-klip <worker-pod> -- cat /proc/driver/nvidia/version

# Dmesg hatalarını kontrol et
kubectl exec -n tuncay-klip <worker-pod> -- dmesg | grep -i nvidia
```

### 3. Worker'ı Yeniden Başlat
```bash
# Sorunlu pod'ı sil (DaemonSet otomatik yeni pod oluşturur)
kubectl delete pod <worker-pod> -n tuncay-klip

# Veya node'u drain et
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data
```

### 4. Fallback CPU Moduna Geç
```bash
# GPU kullanamayan worker'ları CPU modunda çalıştır
kubectl set env deployment/tuncay-klip-cpu-worker \
    WORKER_TYPE=render \
    --namespace=tuncay-klip
```
```

### 7.6 Üretim Kontrol Listesi

```
┌─────────────────────────────────────────────────────────────────┐
│                    ÜRETİM KONTROL LİSTESİ                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GÜVENLİK                                                      │
│  □ TLS sertifikaları aktif (Let's Encrypt / ACM)               │
│  □ NetworkPolicy'ler uygulandı                                  │
│  □ Pod Security Standards aktif                                 │
│  □ RBAC rolleri tanımlandı                                      │
│  □ Sırlar Vault/K8s Secrets'ta saklı                           │
│  □ Container image'ları imzalandı (Cosign)                      │
│  □ SAST/DAST taramaları CI/CD hattında aktif                    │
│  □ Rate limiting middleware aktif                                │
│  □ CORS ayarları kısıtlandı                                     │
│  □ Security headers eklendi (HSTS, CSP, X-Frame-Options)       │
│                                                                 │
│  ERİŞİLEBİLİRLİK                                                │
│  □ Health check endpoint'leri aktif (/health, /ready)           │
│  □ Liveness/Readiness/Startup probes tanımlandı                 │
│  □ PodDisruptionBudget tanımlandı                                │
│  □ Topology spread constraints uygulandı                        │
│  □ Resource requests/limits ayarlandı                           │
│  □ Graceful shutdown destekleniyor                              │
│                                                                 │
│  PERFORMANS                                                     │
│  □ GPU driver ve CUDA sürümü doğrulandı                         │
│  □ FFmpeg NVENC/VAAPI desteği aktif                             │
│  □ Container image katmanları optimize edildi                   │
│  □ NFS/SSD storage performansı test edildi                      │
│  □ CDN yapılandırıldı (statik varlıklar için)                   │
│  □ Veritabanı connection pooling aktif                          │
│                                                                 │
│  İZLEME                                                         │
│  □ Prometheus metrikleri toplanıyor                              │
│  □ Grafana dashboard'ları oluşturuldu                           │
│  □ Alert kuralları tanımlandı                                   │
│  □ AlertManager entegrasyonu aktif                              │
│  □ Log aggregation (Loki) çalışıyor                             │
│  □ Distributed tracing (OpenTelemetry) aktif                    │
│  □ Error tracking (Sentry) entegre                              │
│                                                                 │
│  YEDEKLEME                                                      │
│  □ Veritabanı otomatik yedekleme aktif                          │
│  □ Yedekler S3'e yükleniyor                                     │
│  □ Yedek geri yükleme test edildi                               │
│  □ RTO/RPO tanımlandı ve doğrulandı                             │
│                                                                 │
│  DAĞITIM                                                        │
│  □ CI/CD hattı çalışıyor                                        │
│  □ Canary dağıtımı test edildi                                  │
│  □ Rollback prosedürü dokümante edildi                          │
│  □ Blue-green deployment desteği hazır                          │
│  □ Feature flags sistemi aktif                                  │
│                                                                 │
│  MALİYET                                                        │
│  □ Spot instance desteği aktif                                  │
│  □ Programatik ölçeklendirme ayarlandı                          │
│  □ S3 Intelligent-Tiering aktif                                 │
│  □ Boşta kalan kaynaklar tespit edildi                          │
│  □ Reserved instance değerlendirmesi yapıldı                    │
│                                                                 │
│  DOKÜMANTASYON                                                  │
│  □ Runbook'lar yazıldı                                         │
│  □ Arka plan bilgilendirmesi hazır                              │
│  □ API dokümantasyonu (OpenAPI/Swagger) aktif                   │
│  □ Acil durum iletişim listesi güncellendi                       │
│  □ Postmortem şablonu hazır                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Ek: Dağıtım Mimarisi Diyagramı

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        ÜRETİM ORTAMI MİMARİSİ                           │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────┐    ┌─────────────────────────────────────────────────────┐  │
│  │ Kullanıcı│───▶│              NGINX INGRESS / TRAEFIK               │  │
│  └─────────┘    │            (TLS, Rate Limiting, WAF)                │  │
│                  └──────────────────────┬──────────────────────────────┘  │
│                                         │                                │
│                              ┌──────────┴──────────┐                    │
│                              ▼                     ▼                    │
│                  ┌──────────────────┐   ┌──────────────────┐           │
│                  │   API Server     │   │   API Server     │           │
│                  │   (Pod 1)        │   │   (Pod 2)        │           │
│                  │   CPU: 2c/2G     │   │   CPU: 2c/2G     │           │
│                  └────────┬─────────┘   └────────┬─────────┘           │
│                           │                      │                      │
│                  ┌────────┴──────────────────────┴─────────┐           │
│                  ▼                                         ▼           │
│         ┌────────────────┐                        ┌────────────────┐  │
│         │   Redis Cluster│                        │  RabbitMQ      │  │
│         │   (Kuyruk +    │                        │  (Mesaj Broker)│  │
│         │    Önbellek)   │                        └────────┬───────┘  │
│         └────────────────┘                                 │          │
│                                               ┌────────────┴────────┐ │
│                                               ▼                     ▼ │
│                                ┌─────────────────────┐  ┌──────────┐  │
│                                │  GPU Worker Pool    │  │  CPU     │  │
│                                │  (DaemonSet)        │  │  Worker  │  │
│                                │  ┌─────┐ ┌─────┐   │  │  (Deploy)│  │
│                                │  │GPU 1│ │GPU 2│   │  │  Pod 1-5 │  │
│                                │  └─────┘ └─────┘   │  └──────────┘  │
│                                │  ┌─────┐ ┌─────┐   │                │
│                                │  │GPU 3│ │GPU 4│   │                │
│                                │  └─────┘ └─────┘   │                │
│                                └─────────┬───────────┘                │
│                                          │                            │
│                              ┌───────────┴────────────┐               │
│                              ▼                        ▼               │
│                  ┌──────────────────┐    ┌──────────────────┐        │
│                  │  S3 / MinIO      │    │  NFS Storage     │        │
│                  │  (Medya dosyalar)│    │  (Geçici dosyalar)│        │
│                  └──────────────────┘    └──────────────────┘        │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐│
│  │                       İZLEME KATMANI                            ││
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌──────────┐  ││
│  │  │ Prometheus  │  │  Grafana   │  │   Loki     │  │ Jaeger   │  ││
│  │  │ (Metrikler) │  │ (Dashboard)│  │ (Günlükler)│  │ (Trace)  │  ││
│  │  └────────────┘  └────────────┘  └────────────┘  └──────────┘  ││
│  │  ┌────────────┐                                              ││
│  │  │AlertManager│  ←── PagerDuty / Slack / E-posta bildirimleri ││
│  │  └────────────┘                                              ││
│  └──────────────────────────────────────────────────────────────────┘│
│                                                                      │
└──────────────────────────────────────────────────────────────────────────┘
```

---

*Bu belge, Tuncay Klip video işleme altyapısının Docker, Kubernetes ve üretim dağıtımı için kapsamlı bir rehber niteliğindedir. Her bölüm, pratik yapılandırma dosyaları, veri yapıları ve operasyonel prosedürler içerir.*
