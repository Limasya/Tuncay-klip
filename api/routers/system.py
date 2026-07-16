"""
Sistem kontrol API router'ı.
Başlat/durdur, durum, ayarlar.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from models.schemas import SystemStatus
from config import get_settings
from utils.auth_compat import Principal, Scope, get_current_principal, require_scope

router = APIRouter(prefix="/api/system", tags=["system"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("/start")
async def start_monitoring(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Yayın izlemeyi ve otomatik klip yakalamayı başlatır."""
    from services.orchestrator import orchestrator
    from services.kick_api import kick_service

    if orchestrator.is_monitoring:
        raise HTTPException(400, "Sistem zaten çalışıyor")

    import asyncio
    asyncio.create_task(orchestrator.start())

    return {"message": "Sistem başlatılıyor...", "channel": settings.kick_channel_slug}


@router.post("/stop")
async def stop_monitoring(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Sistemi durdurur."""
    from services.orchestrator import orchestrator

    if not orchestrator.is_monitoring:
        raise HTTPException(400, "Sistem zaten durmuş")

    await orchestrator.stop()
    return {"message": "Sistem durduruldu."}


@router.get("/status")
async def get_status(
    _principal: Principal = Depends(get_current_principal),
):
    """Anlık sistem durumunu döndürür."""
    import psutil

    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except ImportError:
        gpu_available = False

    from services.orchestrator import orchestrator
    status = orchestrator.get_status()

    return SystemStatus(
        is_monitoring=status.get("is_monitoring", False),
        target_channel=settings.kick_channel_slug,
        stream_active=status.get("stream_active", False),
        clips_today=status.get("clips_today", 0),
        buffer_usage_mb=status.get("buffer_frames", 0) * 1280 * 720 * 3 / (1024 * 1024),
        analysis_fps=settings.analysis_fps,
        cpu_usage=psutil.cpu_percent(),
        memory_usage=psutil.virtual_memory().percent,
        gpu_available=gpu_available,
    )


@router.get("/stream-info")
async def get_stream_info(
    _principal: Principal = Depends(get_current_principal),
):
    """Kick API'den güncel yayın bilgisini çeker."""
    from services.kick_api import kick_service
    try:
        info = await kick_service.get_livestream_info()
        return info
    except Exception as e:
        raise HTTPException(500, f"Yayın bilgisi alınamadı: {e}")


@router.get("/channel-info")
async def get_channel_info(
    _principal: Principal = Depends(get_current_principal),
):
    """Kick kanal bilgilerini çeker."""
    from services.kick_api import kick_service
    try:
        info = await kick_service.get_channel_info()
        return info
    except Exception as e:
        raise HTTPException(500, f"Kanal bilgisi alınamadı: {e}")


@router.get("/analysis-stats")
async def get_analysis_stats(
    _principal: Principal = Depends(get_current_principal),
):
    """Analiz pipeline istatistikleri."""
    from services.analysis.pipeline import analysis_pipeline
    return analysis_pipeline.stats


@router.post("/test-clip")
async def test_clip_trigger(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """
    Test amaçlı manuel klip tetikleyici.
    Buffer'dan son 10 saniyeyi klip olarak çıkarır.
    """
    from services.stream_capture import stream_capture
    import time

    if not stream_capture.is_capturing:
        raise HTTPException(400, "Stream yakalama aktif değil")

    event_time = time.time()
    clip_path = await stream_capture.capture_clip(
        event_time=event_time,
        pre_seconds=5,
        post_seconds=5,
        clip_name="test_manual",
    )

    if clip_path:
        return {"message": "Test klibi oluşturuldu", "path": clip_path}

    raise HTTPException(500, "Test klibi oluşturulamadı")
