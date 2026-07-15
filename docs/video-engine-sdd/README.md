# Video Processing Engine - Software Design Document

**Proje:** AI-Driven Otomatik Sosyal Video Edit Motoru
**Durum:** Aktif geliştirme
**Son güncelleme:** 2026-07-15

---

## Amaç

Bu belge, AI tarafından üretilen Clip JSON'unu (ClipSpec) alarak profesyonel sosyal medya videoları üreten render motorunun tam tasarımını tanımlar. Sistem; video decode/filter/encode, altyazı, animasyon, yüz takibi, ses miksajı, thumbnail üretimi, çoklu platform export ve production-grade operasyonu tek bir tutarlı mimari altında birleştirir.

---

## Okuma Haritası

### Temel Mimari

| Dosya | Kapsam | Boyut |
|---|---|---|
| `README.md` | Bu dosya - okuma haritası ve genel bakış | — |
| `00-system-architecture.md` | Mimari omurga, NFR/SLO, component design, data flow, security, migration, ADR | ~800 satır |

### Render Pipeline Bölümleri

| Dosya | Kapsam | Bölümler |
|---|---|---|
| `01-media-foundations.md` | Video processing temeli: decode/encode, mux/demux, FFmpeg, hardware acceleration (NVENC/CUDA/VAAPI/DXVA) | 1-12 |
| `02-timeline-captions-motion.md` | Timeline engine, subtitle rendering (ASS/SRT), word-level timing, template engine, motion graphics, keyframe/Bezier animation, face tracking | 13-24 |
| `03-visual-intelligence-effects.md` | Auto reframe, smart crop, camera/zoom/pan/shake engines, motion blur, glow/bloom, chromatic aberration, transitions | 25-35 |
| `04-audio-assets-cache.md` | Audio mixing, music ducking, sound effects, loudness normalization, thumbnail/preview generation, asset management, plugin/preset systems, video cache | 36-45 |

### Yürütme ve Operasyon

| Dosya | Kapsam | Bölümler |
|---|---|---|
| `05-execution-storage-delivery.md` | Temporary files, render queue, worker pool, parallel rendering, job scheduler, retry, storage, cloud upload, YouTube/TikTok/Instagram/Kick export | 46-57 |
| `06-platform-operations.md` | API design, database schema, Docker, monitoring, profiling, GPU/RAM optimization, benchmark, testing, CI/CD, deployment, error recovery, scalability | 58-70 |

### Sözleşmeler ve Şemalar

| Dosya | Kapsam |
|---|---|
| `07-contracts-reference.md` | ClipSpec v1 sözleşmesi, validation, normalization, compiler pseudo-code, REST API samples, webhook/progress events |
| `schemas/clip-spec-v1.schema.json` | ClipSpec v1 JSON Schema (Draft 2020-12) |
| `schemas/clip-spec-v1.example.json` | Geçerli ClipSpec v1 örneği (18 sn, 9:16, çoklu track) |

---

## Mimari Karar Özeti

1. **AI çıktısı doğrudan FFmpeg'e çevrilmez.** Önce sürümlenmiş `ClipSpec`, sonra doğrulanmış ve değişmez `RenderPlan` DAG'i üretilir.
2. **Control plane:** Python 3.12 FastAPI/Pydantic v2, PostgreSQL metadata, S3 content-addressed storage.
3. **Workflow orchestration:** Temporal durable execution. Celery yalnız MVP/migration alternatifi.
4. **Render workers:** FFmpeg 7.x/libav subprocess. CPU ve donanım sınıfına göre ayrı GPU worker havuzları (NVIDIA NVENC/CUDA, Linux VAAPI, Windows D3D11VA).
5. **Zaman modeli:** Rational time (ticks), PTS/DTS bilinci, VFR/CFR destek.
6. **Renk/piksel modeli:** Linear-light compositing, premultiplied alpha, explicit color management.
7. **Ses modeli:** 48 kHz planar float32 internal, sample-accurate timeline.
8. **Cache:** Content-addressed, Merkle fingerprint, L1 NVMe + L2 S3 + Redis hot index.
9. **Güvenlik:** Multi-tenant isolation, Vault/KMS secrets, log redaction, deterministic builds.
10. **Observability:** OpenTelemetry trace/metric/log correlation, RED/USE metrics, SLO-based alerting.

---

## Hızlı Başlangıç

### Ortam Gereksinimleri

```bash
# Python 3.12+
python --version

# FFmpeg 7.x (libav codec desteği ile)
ffmpeg -version

# NVIDIA GPU (opsiyonel, NVENC/CUDA için)
nvidia-smi

# Docker (opsiyonel, container deployment için)
docker --version
```

### Kurulum

```bash
# 1. Bağımlılıklar
pip install -r requirements.txt

# 2. Ortam değişkenleri
cp .env.example .env
# .env dosyasını düzenle

# 3. Veritabanı migrasyonu
alembic upgrade head

# 4. Sunucu
uvicorn main:app --host 0.0.0.0 --port 8000
```

### ClipSpec Gönderimi

```bash
curl -X POST http://localhost:8000/v1/render-jobs \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: test-001" \
  -d @schemas/clip-spec-v1.example.json
```

### Render Durumu Sorgulama

```bash
curl http://localhost:8000/v1/render-jobs/{job_id}
```

---

## Dosya ve Klasör Yapısı (Hedef)

```
video_engine/
  domain/                 # Domain models (ClipSpec, RenderPlan, RationalTime)
  compiler/               # ClipSpec → RenderPlan compiler
    passes/               # Normalization, validation, optimization passes
  analysis/               # ML analysis (face, shot, ASR, alignment)
    face/
    shot/
    asr/
  render/                 # Render execution
    graph/                # DAG execution engine
    nodes/                # Render node implementations
    filters/              # FFmpeg filter wrappers
  media/                  # Core media operations
    decode/
    encode/
    mux/
    demux/
    color/
    audio/
  timeline/               # Timeline model and evaluation
  subtitle/               # ASS/SRT rendering (libass/HarfBuzz/FreeType)
  animation/              # Keyframe, Bezier, motion graphics
  effects/                # Visual effects (glow, bloom, etc.)
  transitions/            # Transition engine
  thumbnail/              # Thumbnail generator
  preview/                # Preview generator
  cache/                  # Content-addressed cache
  delivery/               # Platform adapters (YouTube, TikTok, Instagram, Kick)
  api/                    # FastAPI routes
  database/               # SQLAlchemy models, migrations
  workers/                # Render worker processes
  platform/               # Infrastructure (telemetry, config, secrets)
tests/
  unit/
  contract/
  integration/
  golden/
  property/
  fuzz/
  chaos/
  benchmark/
deploy/
  k8s/
  argocd/
  docker/
```

---

## Teknoloji Yığını

| Katman | Teknoloji |
|---|---|
| API | FastAPI, Pydantic v2, Uvicorn |
| Database | PostgreSQL 16, SQLAlchemy 2.0, Alembic |
| Cache | Redis 7 (hot index/lease), S3 (CAS L2), NVMe (L1) |
| Workflow | Temporal |
| Video | FFmpeg 7.x, libav, OpenCV |
| ML/AI | ONNX Runtime, TensorRT, MediaPipe, PyTorch |
| Subtitle | libass, HarfBuzz, FreeType, ICU |
| Container | Docker, Kubernetes |
| Monitoring | OpenTelemetry, Prometheus, Loki |
| Secrets | HashiCorp Vault, KMS |
| CI/CD | GitHub Actions, ArgoCD, cosign |

---

## Lisans

Bu proje kişisel kullanım için geliştirilmektedir.
