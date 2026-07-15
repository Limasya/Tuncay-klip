"""
Sistem kontrol API router'ı.
Başlat/durdur, durum, ayarlar.
"""
from fastapi import APIRouter, HTTPException
from models.schemas import SystemStatus
from services.orchestrator import orchestrator
from config import get_settings

router = APIRouter(prefix="/api/system", tags=["system"])
settings = get_settings()


@router.post("/start")
async def start_monitoring():
    """Yayın izlemeyi ve otomatik klip yakalamayı başlatır."""
    if orchestrator.is_monitoring:
        raise HTTPException(400, "Sistem zaten çalışıyor")

    import asyncio
    asyncio.create_task(orchestrator.start())

    return {"message": "Sistem başlatılıyor...", "channel": settings.kick_channel_slug}


@router.post("/stop")
async def stop_monitoring():
    """Sistemi durdurur."""
    if not orchestrator.is_monitoring:
        raise HTTPException(400, "Sistem zaten durmuş")

    await orchestrator.stop()
    return {"message": "Sistem durduruldu."}


@router.get("/status", response_model=SystemStatus)
async def get_status():
    """Anlık sistem durumunu döndürür."""
    status = orchestrator.get_status()
    return SystemStatus(
        is_monitoring=status["is_monitoring"],
        target_channel=status["target_channel"],
        stream_active=status["stream_active"],
        clips_today=status["clips_today"],
        buffer_usage_mb=status["buffer_frames"] * 1280 * 720 * 3 / (1024 * 1024),
        analysis_fps=settings.analysis_fps,
        cpu_usage=status["cpu_usage"],
        memory_usage=status["memory_usage"],
        gpu_available=status["gpu_available"],
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
