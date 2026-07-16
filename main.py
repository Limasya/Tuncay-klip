"""
Ana FastAPI uygulaması.
Tüm router'ları birleştirir, CORS ve middleware ayarlarını yapar.
"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

import importlib

from api.routers import clips, system, preferences, edit, projects
from api.routers import pipeline as pipeline_router
from api.routers import analytics as analytics_router

_platform_available = False
platform_router = None
try:
    platform_router = importlib.import_module("api.routers.platform")
    _platform_available = True
except Exception:
    logging.debug(
        "platform_eng ve bağımlılıkları kurulu değil; "
        "/api/v1/platform endpoint'leri atlanıyor"
    )
from services.database import init_db
from config import get_settings

settings = get_settings()

# Structured logging
from utils.logging_config import setup_logging
setup_logging(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    json_format=os.environ.get("LOG_FORMAT", "") == "json",
)

logger = logging.getLogger(__name__)


def _init_platform_observability() -> None:
    """OpenTelemetry tracing + feature flag yüklemesi (IP_PART6 34-37)."""
    # Distributed tracing (opsiyonel; otel_enabled + paketler mevcutsa)
    if settings.otel_enabled:
        try:
            from platform_eng.observability import init_tracing
            init_tracing(
                service_name=settings.service_name,
                otlp_endpoint=settings.otel_exporter_otlp_endpoint,
                sample_ratio=settings.otel_sample_ratio,
                environment=settings.deployment_environment,
            )
            logger.info("OpenTelemetry tracing enabled: %s", settings.service_name)
        except Exception as e:  # pragma: no cover
            logger.warning("Tracing init failed (devam ediliyor): %s", e)

    # Feature flags — opsiyonel JSON dosyasından yükle
    if settings.feature_flags_file and os.path.exists(settings.feature_flags_file):
        try:
            import json
            from platform_eng.flags import default_client
            with open(settings.feature_flags_file, "r", encoding="utf-8") as f:
                default_client.reload(json.load(f))
            logger.info("Feature flags loaded from %s", settings.feature_flags_file)
        except Exception as e:  # pragma: no cover
            logger.warning("Feature flag load failed: %s", e)



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü."""
    logger.info("Veritabanı başlatılıyor...")
    await init_db()
    logger.info("Klip Yakalama Sistemi hazır!")

    # Ensure data directories exist
    for d in ["data/clips", "data/buffer", "data/subtitles",
               "data/exports", "data/thumbnails", "data/uploads",
               "data/projects", "data/timeline-jobs",
               "static", "templates"]:
        os.makedirs(d, exist_ok=True)

    yield

    # Graceful shutdown — stop both orchestrators if running
    logger.info("Shutting down pipeline...")
    try:
        from services.orchestrator import orchestrator as svc_orch
        if svc_orch.is_monitoring:
            await svc_orch.stop()
    except Exception:
        pass
    try:
        from microservices.orchestrator import orchestrator as pipe_orch
        if pipe_orch._is_running:
            await pipe_orch.stop()
    except Exception as e:
        logger.error("Pipeline shutdown error: %s", e)
    logger.info("Sistem kapatıldı.")


app = FastAPI(
    title="Otomatik Klip Yakalama ve Duygu-Hareket Analizi",
    description=(
        "Kick canlı yayınları için gerçek zamanlı duygu/hareket analizi "
        "ile otomatik klip yakalama, sınıflandırma ve düzenleme sistemi."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting (optional — enabled via env)
if os.environ.get("RATE_LIMIT_ENABLED", "false").lower() in ("true", "1", "yes"):
    from utils.rate_limiter import RateLimitMiddleware, get_rate_limiter
    app.add_middleware(RateLimitMiddleware, limiter=get_rate_limiter())
    logger.info("Rate limiting enabled: %d req/%ds", get_rate_limiter().max_requests, get_rate_limiter().window_seconds)

# Observability (IP_PART6 34-36) — Prometheus RED metrics + OTel tracing
try:
    _init_platform_observability()
except Exception:
    logger.debug("Observability init skipped (platform_eng not available)")

if settings.prometheus_metrics_enabled:
    try:
        from platform_eng.observability import PrometheusMiddleware
        app.add_middleware(PrometheusMiddleware, service_name=settings.service_name)
    except ImportError:
        logger.debug("PrometheusMiddleware skipped (platform_eng not available)")
    except Exception as exc:
        logger.warning("PrometheusMiddleware init failed: %s", exc)

if settings.otel_enabled:
    try:
        from platform_eng.observability import instrument_fastapi
        if instrument_fastapi(app, settings.service_name):
            logger.info("FastAPI OpenTelemetry instrumentation enabled")
    except ImportError:
        logger.debug("OTel instrumentation skipped (platform_eng not available)")
    except Exception as exc:
        logger.warning("FastAPI instrumentation failed: %s", exc)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(clips.router)
app.include_router(system.router)
app.include_router(preferences.router)
app.include_router(pipeline_router.router)
app.include_router(edit.router)
app.include_router(analytics_router.router)
if _platform_available and platform_router is not None:
    app.include_router(platform_router.router)
app.include_router(projects.router)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Ana kontrol paneli."""
    try:
        with open("templates/dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard template bulunamadı</h1>"


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "1.0.0",
        "phase": 4,
        "services": "15 microservices + 6 celery tasks",
    }


@app.get("/ready")
async def readiness_check():
    """Kubernetes-style readiness probe."""
    from microservices.orchestrator import orchestrator as pipe_orch
    checks = {
        "database": True,
        "event_bus": pipe_orch.event_bus is not None,
        "pipeline_running": pipe_orch._is_running,
    }
    ready = all(checks.values())
    return {"ready": ready, "checks": checks}


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Prometheus-compatible metrics endpoint.

    Exposes pipeline metrics in Prometheus exposition format.
    Scrape this endpoint with Prometheus or compatible collector.
    """
    lines = []

    def gauge(name, value, help_text="", labels=None):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
        label_str = ""
        if labels:
            label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        lines.append(f"{name}{label_str} {value}")

    def counter(name, value, help_text="", labels=None):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
        label_str = ""
        if labels:
            label_str = "{" + ",".join(f'{k}="{v}"' for k, v in labels.items()) + "}"
        lines.append(f"{name}{label_str} {value}")

    try:
        from microservices.orchestrator import orchestrator
        status = orchestrator.get_full_status()

        # Pipeline status
        pipeline = status.get("pipeline", {})
        gauge(
            "klip_pipeline_running",
            1 if pipeline.get("is_running") else 0,
            "Whether the pipeline is currently running",
        )

        # Event bus metrics
        bus_metrics = status.get("event_bus", {})
        counter(
            "klip_events_published_total",
            bus_metrics.get("events_published", 0),
            "Total events published to the event bus",
        )
        counter(
            "klip_events_dispatched_total",
            bus_metrics.get("events_dispatched", 0),
            "Total events dispatched to handlers",
        )
        counter(
            "klip_events_failed_total",
            bus_metrics.get("events_failed", 0),
            "Total event handler failures",
        )
        counter(
            "klip_events_dlq_total",
            bus_metrics.get("events_dlq", 0),
            "Total events sent to dead-letter queue",
        )

        # Event detector metrics
        det = status.get("event_detector", {})
        counter(
            "klip_detector_events_processed_total",
            det.get("events_processed", 0),
            "Total events processed by event detector",
        )
        gauge(
            "klip_detector_current_score",
            det.get("current_score", 0),
            "Current composite highlight score",
        )
        gauge(
            "klip_detector_high_scores_total",
            det.get("high_scores", 0),
            "Total number of high-score evaluations",
        )
        gauge(
            "klip_detector_active_streams",
            det.get("active_streams", 0),
            "Number of active streams being tracked",
        )

        # Decision engine metrics
        de = status.get("decision_engine", {})
        counter(
            "klip_decision_clips_created_total",
            de.get("clips_created", 0),
            "Total clips created",
        )
        counter(
            "klip_decision_clips_rejected_total",
            de.get("clips_rejected", 0),
            "Total clip candidates rejected",
        )
        counter(
            "klip_decision_confirmation_rejects_total",
            de.get("confirmation_rejects", 0),
            "Total rejections due to confirmation window",
        )
        conf = de.get("confirmation_window", {})
        gauge(
            "klip_decision_confirmation_pass_count",
            conf.get("pass_count", 0),
            "Current confirmation window pass count",
        )
        gauge(
            "klip_decision_confirmation_avg_score",
            conf.get("avg_score", 0),
            "Average score in confirmation window",
        )

        # Per-service status
        for svc_name in [
            "audio_analysis", "chat_analysis", "video_analysis",
            "clip_generator", "transcription", "uploader",
        ]:
            svc = status.get(svc_name)
            if svc and isinstance(svc, dict):
                gauge(
                    f"klip_{svc_name}_available",
                    1,
                    labels={"service": svc_name},
                )

    except Exception as e:
        lines.append(f"# ERROR: Failed to collect metrics: {e}")

    output = "\n".join(lines) + "\n"

    # IP_PART6 36.2 — prometheus_client kayıt defterindeki RED/USE metrikleri ekle
    try:
        from platform_eng.observability import render_latest, PROMETHEUS_AVAILABLE
        if PROMETHEUS_AVAILABLE:
            payload, _ = render_latest()
            output += payload.decode("utf-8")
    except Exception:
        pass

    return output



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
