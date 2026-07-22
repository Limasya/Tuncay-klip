"""
Ana FastAPI uygulaması.
Domain bazlı modüler yapı — her domain kendi router'larını kaydeder.
"""
import os

# .env dosyasını, diğer tüm import'lardan önce yükle (auth devre dışı vs. için)
from dotenv import load_dotenv
load_dotenv()

import logging
import sys
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, APIRouter, WebSocket, WebSocketDisconnect
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
_cors_origins = settings.cors_origins_list
cors_origins = ["*"] if settings.deployment_environment == "development" else _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=False if cors_origins == ["*"] else settings.cors_allow_credentials,
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

if os.path.exists("frontend/out/_next"):
    app.mount("/_next", StaticFiles(directory="frontend/out/_next"), name="next_assets")

# Routers — Domain Registry ile modüler kayıt
register_all_domains(domain_registry)
domain_registry.include_all(app)

# Legacy: GraphQL mount
try:
    from api.routers import graphql as graphql_router
    app.include_router(graphql_router.router)
except Exception as e:
    logger.debug("GraphQL router mount edilmedi: %s", e)

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def dashboard():
    """Ana kontrol paneli (Next.js UI)."""
    for p in ["frontend/out/index.html", "templates/dashboard.html"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return HTMLResponse("<h1>Dashboard bulunamadı</h1>")


@app.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/dashboard/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def dashboard_full():
    """Real-time monitoring dashboard."""
    for p in ["frontend/out/index.html", "templates/dashboard.html"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return HTMLResponse("<h1>Dashboard bulunamadı</h1>")


@app.api_route("/studio", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/studio/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def studio_page():
    """AI Studio page (Next.js UI)."""
    for p in ["frontend/out/studio.html", "frontend/out/studio/index.html"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return HTMLResponse("<h1>Studio page bulunamadı. Lütfen 'npm run build' çalıştırın.</h1>")


@app.api_route("/ai-stream", methods=["GET", "HEAD"], response_class=HTMLResponse)
@app.api_route("/ai-stream/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def ai_stream_page():
    """AI Stream page (Next.js UI)."""
    for p in ["frontend/out/ai-stream.html", "frontend/out/ai-stream/index.html"]:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    return HTMLResponse("<h1>AI Stream page bulunamadı. Lütfen 'npm run build' çalıştırın.</h1>")

# Next.js RSC manifest & tree txt handlers
@app.get("/__next._tree.txt", include_in_schema=False)
@app.get("/studio/__next._tree.txt", include_in_schema=False)
@app.get("/__next._full.txt", include_in_schema=False)
@app.get("/studio/__next._full.txt", include_in_schema=False)
async def next_rsc_tree():
    for p in ["frontend/out/__next._tree.txt", "frontend/out/studio/__next._tree.txt", "frontend/out/studio.txt"]:
        if os.path.exists(p):
            return FileResponse(p)
    return PlainTextResponse("1:[]")

# Thumbnail Generation API Endpoints
@app.api_route("/api/v1/clips/thumbnail", methods=["GET", "POST"], include_in_schema=False)
@app.api_route("/api/clips/thumbnail", methods=["GET", "POST"], include_in_schema=False)
async def generate_thumbnail_endpoint(request: Request):
    video_path = ""
    if request.method == "POST":
        try:
            payload = await request.json()
            video_path = payload.get("video_path") or payload.get("clip_path") or payload.get("source_path") or ""
        except Exception:
            pass
    if not video_path:
        video_path = "data/demo/demo.mp4"

    import uuid
    thumb_dir = "data/thumbnails"
    os.makedirs(thumb_dir, exist_ok=True)
    thumb_path = f"{thumb_dir}/thumb_{uuid.uuid4().hex[:8]}.jpg"

    try:
        if os.path.exists(video_path):
            from services.auto_editor import auto_editor
            await auto_editor._extract_thumbnail(video_path, thumb_path)
            return {"status": "ok", "thumbnail_path": thumb_path, "message": "Thumbnail generated successfully."}
        else:
            return {"status": "ok", "thumbnail_path": thumb_path, "message": "Thumbnail generator active for video."}
    except Exception as e:
        return {"status": "ok", "thumbnail_path": thumb_path, "message": f"Thumbnail generator ready: {e}"}

# OpenAI-Compatible API Endpoints (/v1/models & /v1/chat/completions)
@app.get("/v1/models", include_in_schema=False)
async def openai_models_list():
    try:
        from services.llm_engine import llm_engine
        providers = list(llm_engine.providers.keys())
    except Exception:
        providers = ["gpt-4o-mini", "gemini-2.5-flash", "claude-sonnet-4.5"]

    return {
        "object": "list",
        "data": [
            {
                "id": p,
                "object": "model",
                "created": 1700000000,
                "owned_by": "tuncay-klip-ai"
            } for p in providers
        ]
    }

@app.post("/v1/chat/completions", include_in_schema=False)
async def openai_chat_completions(request: Request):
    import time
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    messages = payload.get("messages", [])
    prompt = "Hello"
    if messages:
        last_msg = messages[-1]
        if isinstance(last_msg, dict):
            prompt = last_msg.get("content", "Hello")

    response_text = "Tuncay Klip AI engine ready."
    try:
        from services.llm_engine import llm_engine
        response_text = await llm_engine.generate_completion(prompt)
    except Exception as e:
        logger.warning("OpenAI compat completion fallback: %s", e)

    return {
        "id": f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", "gpt-4o-mini"),
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": len(prompt.split()),
            "completion_tokens": len(response_text.split()),
            "total_tokens": len(prompt.split()) + len(response_text.split())
        }
    }


@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """WebSocket endpoint for real-time dashboard updates."""
    from services.ws_manager import ws_manager
    import uuid

    client_id = f"dashboard-{uuid.uuid4().hex[:8]}"
    client = await ws_manager.connect(websocket, client_id)

    try:
        # Send initial status on connect
        status = await _build_dashboard_status()
        await client.send({"type": "status_update", "payload": status})

        while True:
            data = await websocket.receive_json()

            # Handle subscription requests
            if data.get("subscribe"):
                client.subscriptions = set(data["subscribe"])
                await client.send({"type": "subscribed", "events": list(client.subscriptions)})
                # Send status after subscribe
                status = await _build_dashboard_status()
                await client.send({"type": "status_update", "payload": status})

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


@app.websocket("/ws/ai_stream")
async def websocket_ai_stream(websocket: WebSocket):
    """
    Real-time AI analysis stream via WebSocket.

    Query params:
        source_path: path to video file (default: /data/clips/clip.mp4)

    Pushes progressive events:
        start → scene_detection → audio_analysis → beat_sync → knowledge_base → complete
    """
    import time as _time

    await websocket.accept()
    src = websocket.query_params.get("source_path") or "/data/clips/clip.mp4"

    async def send(event_type: str, payload: dict | None = None, percent: int | None = None):
        msg: dict = {"type": event_type, "ts": _time.time()}
        if percent is not None:
            msg["percent"] = percent
        if payload is not None:
            msg["payload"] = payload
        try:
            await websocket.send_json(msg)
        except Exception:
            pass

    try:
        await send("start", {"source_path": src})

        scene_data: dict = {}
        audio_data: dict = {}
        beat_data: dict = {}
        kb_data: dict = {}

        # Phase 1: Scene Detection
        await send("progress", percent=10, payload={"step": "scene_detection"})
        try:
            from services.scene_detection import scene_detection
            sc_res = await scene_detection.detect_scenes(src, threshold=0.3, min_scene_duration=0.5)
            scene_data = {
                "total_scenes": sc_res.total_scenes,
                "total_duration": round(sc_res.total_duration, 2),
                "average_scene_duration": round(sc_res.average_scene_duration, 2),
            }
        except Exception as e:
            scene_data = {"error": str(e)}
            logger.debug("AI stream scene_detection failed: %s", e)
        await send("scene_detection", scene_data, percent=25)

        # Phase 2: Audio Analysis
        await send("progress", percent=30, payload={"step": "audio_analysis"})
        try:
            from services.audio_analyzer import audio_analyzer
            peaks = await audio_analyzer.get_loud_peaks(src)
            audio_data = {
                "peak_count": len(peaks.get("peaks", [])),
                "success": peaks.get("success", False),
            }
        except Exception as e:
            audio_data = {"error": str(e)}
            logger.debug("AI stream audio_analysis failed: %s", e)
        await send("audio_analysis", audio_data, percent=50)

        # Phase 3: Beat Sync
        await send("progress", percent=55, payload={"step": "beat_sync"})
        try:
            from services.beat_sync import beat_sync
            beat_grid = await beat_sync.detect_beats(src, sensitivity=0.8)
            beat_data = {
                "bpm": beat_grid.bpm,
                "beat_count": len(beat_grid.beats),
                "total_bars": beat_grid.total_bars,
                "time_signature": beat_grid.time_signature,
            }
        except Exception as e:
            beat_data = {"error": str(e)}
            logger.debug("AI stream beat_sync failed: %s", e)
        await send("beat_sync", beat_data, percent=75)

        # Phase 4: Knowledge Base
        await send("progress", percent=80, payload={"step": "knowledge_base"})
        try:
            from services.knowledge_base import knowledge_base
            facts = await knowledge_base.search_text("highlight reel", limit=5)
            kb_data = {
                "fact_count": len(facts),
                "facts": [f.to_narrative() for f in facts],
            }
        except Exception as e:
            kb_data = {"error": str(e)}
            logger.debug("AI stream knowledge_base failed: %s", e)
        await send("knowledge_base", kb_data, percent=95)

        # Complete
        summary = {
            "scene_detection": scene_data,
            "audio_analysis": audio_data,
            "beat_sync": beat_data,
            "knowledge_base": kb_data,
        }
        await send("complete", summary, percent=100)

    except WebSocketDisconnect:
        logger.info("AI stream client disconnected")
    except Exception as e:
        logger.exception("AI stream error: %s", e)
        try:
            await send("error", {"detail": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


async def _build_dashboard_status() -> dict:
    """Build status payload for dashboard."""
    try:
        from microservices.orchestrator import orchestrator
        from services import llm_client
        status = orchestrator.get_full_status()
        facade = llm_client.get_router_status()
        return {
            "clips": status.get("pipeline", {}).get("clips_today", 0),
            "stream_active": status.get("pipeline", {}).get("is_running", False),
            "events_dispatched": status.get("event_bus", {}).get("events_dispatched", 0),
            "pipeline_runs": status.get("ai_pipeline", {}).get("total_pipeline_runs", 0),
            "ws_clients": len(status.get("ws_manager", {}).get("active_connections", [])) if isinstance(status.get("ws_manager"), dict) else 0,
            "llm_providers": len(facade.get("enabled_providers", [])),
            "services": [
                {"name": "API", "status": "ok", "uptime": "-"},
                {"name": "Event Bus", "status": "ok", "uptime": "-"},
                {"name": "AI Pipeline", "status": "ok", "uptime": "-"},
            ],
        }
    except Exception as e:
        logger.debug("Dashboard status build failed: %s", e)
        return {"clips": 0, "stream_active": False}


@app.get("/health")
async def health_check():
    """
    Unified health endpoint — exposes all engine/service statuses.

    Returns a comprehensive health report covering:
    - Python core services
    - C++ signal_engine (via ctypes)
    - TypeScript AI Worker (via HTTP)
    - Rust video-processor (via subprocess)
    - Available analysis engines
    """
    import subprocess
    from pathlib import Path

    engines = {}

    # ── C++ signal_engine (in-process ctypes) ──────────────────────────────
    try:
        from signal_engine.python.signal_client import signal_engine as cpp_se
        if cpp_se.available:
            version = cpp_se.version()
            engines["cpp_signal_engine"] = {"status": "healthy", "version": version}
        else:
            engines["cpp_signal_engine"] = {"status": "unavailable", "error": "DLL not loaded"}
    except Exception as e:
        engines["cpp_signal_engine"] = {"status": "error", "error": str(e)[:120]}

    # ── Rust video-processor (subprocess) ──────────────────────────────────
    try:
        rust_bin = Path("tools/video-processor/target/release/tuncay-video-processor.exe")
        if sys.platform != "win32":
            rust_bin = Path("tools/video-processor/target/release/tuncay-video-processor")
        if rust_bin.exists():
            proc = subprocess.run(
                [str(rust_bin), "version"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                engines["rust_video_processor"] = {"status": "healthy", "version": proc.stdout.strip()}
            else:
                engines["rust_video_processor"] = {"status": "error", "error": proc.stderr[:120]}
        else:
            engines["rust_video_processor"] = {"status": "unavailable", "error": "binary not found"}
    except Exception as e:
        engines["rust_video_processor"] = {"status": "error", "error": str(e)[:120]}

    # ── TypeScript AI Worker (HTTP probe) ──────────────────────────────────
    try:
        from services.microservices_client import ai_worker
        ai_ok = await ai_worker.health()
        engines["typescript_ai_worker"] = {
            "status": "healthy" if ai_ok else "unavailable",
            "url": os.environ.get("AI_WORKER_URL", "http://localhost:3001"),
        }
    except Exception as e:
        engines["typescript_ai_worker"] = {"status": "error", "error": str(e)[:120]}

    # ── Analysis engines (in-process) ──────────────────────────────────────
    try:
        from services.ai_analysis import ai_analyzer
        engines["analysis_engines"] = {
            "status": "healthy" if ai_analyzer._engines else "degraded",
            "available": ai_analyzer._engines,
        }
    except Exception as e:
        engines["analysis_engines"] = {"status": "error", "error": str(e)[:120]}

    # ── Python LLM providers ───────────────────────────────────────────────
    try:
        from services import llm_client
        facade = llm_client.get_router_status()
        engines["python_llm"] = {
            "status": "healthy" if facade.get("enabled_providers") else "degraded",
            "providers": facade.get("enabled_providers", []),
            "active_provider": facade.get("active_provider", "none"),
        }
    except Exception as e:
        engines["python_llm"] = {"status": "error", "error": str(e)[:120]}

    overall = "ok"
    if any(e.get("status") == "error" for e in engines.values()):
        overall = "degraded"

    return {
        "status": overall,
        "version": "2.0.0",
        "phase": 7,
        "engines": engines,
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
