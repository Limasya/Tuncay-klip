"""
Sistem kontrol API router'ı.
Başlat/durdur, durum, ayarlar.

This uses the **pipeline orchestrator** (event-driven microservice architecture)
as the single production path. The legacy services/orchestrator is kept for
backward compatibility but is no longer the primary control surface.
"""
import logging
from fastapi import APIRouter, HTTPException
from models.schemas import SystemStatus
from config import get_settings

router = APIRouter(prefix="/api/system", tags=["system"])
settings = get_settings()
logger = logging.getLogger(__name__)


@router.post("/start")
async def start_monitoring():
    """Yayın izlemeyi ve otomatik klip yakalamayı başlatır."""
    from microservices.orchestrator import orchestrator as pipeline
    from services.kick_api import kick_service

    if pipeline._is_running:
        raise HTTPException(400, "Sistem zaten çalışıyor")

    # Get stream URL from Kick API
    try:
        stream_url = await kick_service.get_stream_url()
        if not stream_url:
            raise HTTPException(503, "Stream URL alınamadı (yayın offline olabilir)")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(503, f"Kick API hatası: {e}")

    import asyncio
    asyncio.create_task(pipeline.start_stream(
        stream_url=stream_url,
        target_fps=settings.analysis_fps,
        buffer_seconds=settings.stream_buffer_seconds,
    ))

    return {"message": "Sistem başlatılıyor...", "channel": settings.kick_channel_slug}


@router.post("/stop")
async def stop_monitoring():
    """Sistemi durdurur."""
    from microservices.orchestrator import orchestrator as pipeline

    if not pipeline._is_running:
        raise HTTPException(400, "Sistem zaten durmuş")

    await pipeline.stop()
    return {"message": "Sistem durduruldu."}


@router.get("/status")
async def get_status():
    """Anlık sistem durumunu döndürür."""
    from microservices.orchestrator import orchestrator as pipeline
    import psutil
    import torch

    status = pipeline.get_full_status()
    is_running = status.get("pipeline", {}).get("is_running", False)
    capture_status = status.get("stream_capture", {})
    frames = capture_status.get("buffer_frames", 0)

    return SystemStatus(
        is_monitoring=is_running,
        target_channel=settings.kick_channel_slug,
        stream_active=capture_status.get("is_capturing", False),
        clips_today=status.get("clip_generator", {}).get("clips_generated", 0),
        buffer_usage_mb=frames * 1280 * 720 * 3 / (1024 * 1024),
        analysis_fps=settings.analysis_fps,
        cpu_usage=psutil.cpu_percent(),
        memory_usage=psutil.virtual_memory().percent,
        gpu_available=torch.cuda.is_available(),
    )


@router.get("/stream-info")
async def get_stream_info():
    """Kick API'den güncel yayın bilgisini çeker."""
    from services.kick_api import kick_service
    try:
        info = await kick_service.get_livestream_info()
        return info
    except Exception as e:
        raise HTTPException(500, f"Yayın bilgisi alınamadı: {e}")


@router.get("/channel-info")
async def get_channel_info():
    """Kick kanal bilgilerini çeker."""
    from services.kick_api import kick_service
    try:
        info = await kick_service.get_channel_info()
        return info
    except Exception as e:
        raise HTTPException(500, f"Kanal bilgisi alınamadı: {e}")


@router.get("/analysis-stats")
async def get_analysis_stats():
    """Analiz pipeline istatistikleri."""
    from services.analysis.pipeline import analysis_pipeline
    return analysis_pipeline.stats


@router.post("/test-clip")
async def test_clip_trigger():
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
