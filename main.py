"""
Ana FastAPI uygulaması.
Tüm router'ları birleştirir, CORS ve middleware ayarlarını yapar.
"""
import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from api.routers import clips, system, preferences, edit
from api.routers import pipeline as pipeline_router
from api.routers import analytics as analytics_router
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü."""
    logger.info("Veritabanı başlatılıyor...")
    await init_db()
    logger.info("Klip Yakalama Sistemi hazır!")

    # Ensure data directories exist
    for d in ["data/clips", "data/buffer", "data/subtitles",
              "data/exports", "data/thumbnails", "data/uploads",
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate Limiting (optional — enabled via env)
if os.environ.get("RATE_LIMIT_ENABLED", "false").lower() in ("true", "1", "yes"):
    from utils.rate_limiter import RateLimitMiddleware, get_rate_limiter
    app.add_middleware(RateLimitMiddleware, limiter=get_rate_limiter())
    logger.info("Rate limiting enabled: %d req/%ds", get_rate_limiter().max_requests, get_rate_limiter().window_seconds)

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(clips.router)
app.include_router(system.router)
app.include_router(preferences.router)
app.include_router(pipeline_router.router)
app.include_router(edit.router)
app.include_router(analytics_router.router)


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
        "event_bus": pipe_orch.event_bus is not None if pipe_orch.event_bus else True,
        "pipeline_running": pipe_orch._is_running,
    }
    ready = all(checks.values())
    return {"ready": ready, "checks": checks}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
