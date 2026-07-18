"""
Ana FastAPI uygulaması.
Domain bazlı modüler yapı — her domain kendi router'larını kaydeder.
"""
import os

# .env dosyasını, diğer tüm import'lardan önce yükle (auth devre dışı vs. için)
from dotenv import load_dotenv
load_dotenv()

import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from api.domains import domain_registry, register_all_domains
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
    """Uygulama yaşam döngüsü — auto-boot ile tüm sistem otomatik başlatılır."""
    logger.info("Veritabanı başlatılıyor...")
    await init_db()
    logger.info("Veritabanı hazır!")

    # Ensure data directories exist
    for d in ["data/clips", "data/buffer", "data/subtitles",
               "data/exports", "data/thumbnails", "data/uploads",
               "data/projects", "data/timeline-jobs", "data/backups",
               "static", "templates", "models_store"]:
        os.makedirs(d, exist_ok=True)

    # Auto-boot: discover LLMs, download models, start monitors, wire everything
    boot_report = None
    try:
        from services.auto_boot import auto_boot
        boot_report = await auto_boot()
        logger.info(
            "Auto-boot complete in %.1fms — LLMs: %d available, errors: %d",
            boot_report.get("boot_time_ms", 0),
            len([p for p in boot_report.get("llm_providers", []) if p.get("available")]),
            len(boot_report.get("errors", [])),
        )
    except Exception as e:
        logger.warning("Auto-boot failed (manual fallback): %s", e)

    yield

    # Graceful shutdown
    logger.info("Kapatılıyor...")
    try:
        from services.auto_boot import auto_shutdown
        await auto_shutdown()
    except Exception as e:
        logger.warning("Auto-shutdown hatası: %s", e)
    try:
        from services.orchestrator import orchestrator as svc_orch
        if svc_orch.is_monitoring:
            await svc_orch.stop()
    except Exception as e:
        logger.warning("services orchestrator kapatılırken hata: %s", e)
    try:
        from microservices.orchestrator import orchestrator as pipe_orch
        if pipe_orch._is_running:
            await pipe_orch.stop()
    except Exception as e:
        logger.error("Pipeline shutdown error: %s", e)
    logger.info("Sistem kapatıldı.")


app = FastAPI(
    title="Tuncay-Klip - Otomatik Klip Yakalama Sistemi",
    description=(
        "Kick canlı yayınları için gerçek zamanlı duygu/hareket analizi "
        "ile otomatik klip yakalama, sınıflandırma ve düzenleme sistemi.\n\n"
        "**AI Services:** LLM Engine, Vision AI, Audio AI, Chat AI, "
        "Recommendation Engine, Smart Editor\n\n"
        "**Monitoring:** /dashboard (real-time), /metrics (Prometheus), "
        "/api/admin/* (admin API)"
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "Clips", "description": "Klip CRUD operations — create, read, update, delete clips"},
        {"name": "Pipeline", "description": "Stream processing pipeline — start/stop monitoring, analysis control"},
        {"name": "Analytics", "description": "Viewership, revenue, clip performance analytics"},
        {"name": "Edit", "description": "Subtitle burn-in, format conversion, clip editing"},
        {"name": "Recommendations", "description": "ML-powered clip recommendations, user preferences, trending"},
        {"name": "Smart Editor", "description": "AI-assisted trimming, beat-sync, platform optimization"},
        {"name": "Projects", "description": "Project management — create and manage clip projects"},
        {"name": "System", "description": "System status, health checks, configuration"},
        {"name": "Platform", "description": "Platform management — accounts, API keys, publishing"},
        {"name": "Admin", "description": "Admin API — deep health, metrics, service management"},
        {"name": "Knowledge", "description": "Knowledge Base — all streams, participants, topics, game events"},
    ],
)

# CORS — origin listesi config'den okunur (dev varsayılan localhost; prod'da set edilmeli)
_cors_origins = settings.cors_origins_list
if settings.deployment_environment == "production" and _cors_origins == [
    "http://localhost:8000", "http://127.0.0.1:8000",
]:
    logger.warning(
        "CORS production'da hâlâ localhost varsayılanında — CORS_ORIGINS ortam değişkenini set edin."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting (optional — enabled via env)
if os.environ.get("RATE_LIMIT_ENABLED", "false").lower() in ("true", "1", "yes"):
    from utils.rate_limiter import RateLimitMiddleware, get_rate_limiter
    app.add_middleware(RateLimitMiddleware, limiter=get_rate_limiter())
    logger.info("Rate limiting enabled: %d req/%ds", get_rate_limiter().max_requests, get_rate_limiter().window_seconds)

# New rate limiter (services/rate_limiter.py) — always enabled in production
if settings.deployment_environment == "production":
    try:
        from services.rate_limiter import RateLimitMiddleware as NewRateLimitMiddleware
        app.add_middleware(NewRateLimitMiddleware, requests_per_minute=120, burst=30)
        logger.info("Production rate limiter enabled: 120 req/min")
    except Exception as e:
        logger.warning("Production rate limiter init edilemedi: %s", e)

# Prometheus metrics (services/metrics.py)
try:
    from services.metrics import setup_metrics
    setup_metrics(app)
    logger.info("Prometheus metrics middleware enabled")
except Exception as e:
    logger.debug("Prometheus metrics setup atlandı: %s", e)

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

# Routers — Domain Registry ile modüler kayıt
register_all_domains(domain_registry)
domain_registry.include_all(app)

# Legacy: GraphQL mount
try:
    from api.routers import graphql as graphql_router
    app.include_router(graphql_router.router)
except Exception as e:
    logger.debug("GraphQL router mount edilmedi: %s", e)

logger.info(
    "Domains registered: %s",
    ", ".join(domain_registry._domains.keys()),
)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Ana kontrol paneli."""
    try:
        with open("templates/dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard template bulunamadı</h1>"


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_full():
    """Real-time monitoring dashboard."""
    try:
        with open("templates/dashboard.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Dashboard template bulunamadı</h1>"


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    from services.ws_manager import ws_manager
    import uuid

    client_id = f"dashboard-{uuid.uuid4().hex[:8]}"
    client = await ws_manager.connect(websocket, client_id)

    try:
        while True:
            data = await websocket.receive_json()

            # Handle subscription requests
            if data.get("subscribe"):
                client.subscriptions = set(data["subscribe"])
                await client.send({"type": "subscribed", "events": list(client.subscriptions)})

            # Handle pong
            if data.get("type") == "pong":
                client.last_pong = time.time()

            # Handle status request
            if data.get("type") == "get_status":
                status = await _build_dashboard_status()
                await client.send({"type": "status_update", "payload": status})

    except WebSocketDisconnect:
        await ws_manager.disconnect(client_id)
    except Exception:
        await ws_manager.disconnect(client_id)


async def _build_dashboard_status() -> dict:
    """Build status payload for dashboard."""
    try:
        from microservices.orchestrator import orchestrator
        status = orchestrator.get_full_status()
        return {
            "clips": status.get("pipeline", {}).get("clips_today", 0),
            "stream_active": status.get("pipeline", {}).get("is_running", False),
            "events_dispatched": status.get("event_bus", {}).get("events_dispatched", 0),
            "pipeline_runs": status.get("ai_pipeline", {}).get("total_pipeline_runs", 0),
            "ws_clients": 0,
        }
    except Exception:
        return {"clips": 0, "stream_active": False}


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "2.0.0",
        "phase": 7,
        "services": "15 microservices + 9 AI services",
        "ai_features": [
            "LLM Engine (OpenAI/Claude/Ollama)",
            "Vision AI (Scene/Object/Gesture/KeyFrame)",
            "Audio AI (Speech/Event/Crowd/Music)",
            "Chat AI (NLP/Toxicity/Language/Hype/Trends)",
            "Recommendation Engine",
            "Smart Editor",
            "AI Pipeline Hub",
        ],
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
    except Exception as e:
        logger.debug("Prometheus RED metrikleri eklenemedi: %s", e)

    return output



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
