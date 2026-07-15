"""
Ana FastAPI uygulaması.
Tüm router'ları birleştirir, CORS ve middleware ayarlarını yapar.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from api.routers import clips, system, preferences, edit
from api.routers import pipeline as pipeline_router
from services.database import init_db
from config import get_settings

settings = get_settings()

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama yaşam döngüsü."""
    logger.info("Veritabanı başlatılıyor...")
    await init_db()
    logger.info("Klip Yakalama Sistemi hazır!")
    yield
    # Cleanup — stop both orchestrators if running
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
    except Exception:
        pass
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

# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Routers
app.include_router(clips.router)
app.include_router(system.router)
app.include_router(preferences.router)
app.include_router(pipeline_router.router)
app.include_router(edit.router)


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
    return {"status": "ok", "version": "1.0.0"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
