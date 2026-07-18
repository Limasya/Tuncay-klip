"""
Sistem kontrol API router'ı.
Başlat/durdur, durum, ayarlar.

.. note::
    /start, /stop, /status endpoint'leri artık ``microservices.orchestrator``
    (PipelineOrchestrator) kullanıyor. Legacy ``services.orchestrator``
    deprecated edildi.
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from models.schemas import SystemStatus
from config import get_settings
from utils.auth_compat import Principal, Scope, get_current_principal, require_scope

router = APIRouter(prefix="/api/system", tags=["system"])
settings = get_settings()
logger = logging.getLogger(__name__)


def _get_pipeline_orch():
    """Lazy import of the canonical microservices orchestrator."""
    try:
        from microservices.orchestrator import orchestrator
        return orchestrator
    except Exception as e:
        logger.warning("Pipeline orchestrator unavailable: %s", e)
        return None


@router.post("/start")
async def start_monitoring(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Yayın izlemeyi ve otomatik klip yakalamayı başlatır (pipeline orchestrator üzerinden)."""
    from services.kick_api import kick_service

    orch = _get_pipeline_orch()
    if orch is None:
        raise HTTPException(503, "Pipeline orchestrator unavailable (Redis required)")

    if orch._is_running:
        raise HTTPException(400, "Sistem zaten çalışıyor")

    try:
        stream_url = await kick_service.get_stream_url()
    except Exception as exc:
        raise HTTPException(503, f"Kick stream URL alınamadı: {exc}")

    if not stream_url:
        raise HTTPException(409, "Hedef kanal şu an canlı değil")

    asyncio.create_task(orch.start_stream(stream_url=stream_url))

    return {"message": "Sistem başlatılıyor...", "channel": settings.kick_channel_slug}


@router.post("/stop")
async def stop_monitoring(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Sistemi durdurur (pipeline orchestrator üzerinden)."""
    orch = _get_pipeline_orch()
    if orch is None:
        raise HTTPException(503, "Pipeline orchestrator unavailable")

    if not orch._is_running:
        raise HTTPException(400, "Sistem zaten durmuş")

    await orch.stop()
    return {"message": "Sistem durduruldu."}


@router.get("/status")
async def get_status(
    _principal: Principal = Depends(get_current_principal),
):
    """Anlık sistem durumunu döndürür (pipeline orchestrator üzerinden)."""
    import psutil

    try:
        import torch
        gpu_available = torch.cuda.is_available()
    except ImportError:
        gpu_available = False

    orch = _get_pipeline_orch()
    if orch is None:
        return SystemStatus(
            is_monitoring=False,
            target_channel=settings.kick_channel_slug,
            stream_active=False,
            clips_today=0,
            buffer_usage_mb=0,
            analysis_fps=settings.analysis_fps,
            cpu_usage=psutil.cpu_percent(),
            memory_usage=psutil.virtual_memory().percent,
            gpu_available=gpu_available,
        )

    status = orch.get_full_status()
    pipeline = status.get("pipeline", {})

    return SystemStatus(
        is_monitoring=pipeline.get("is_running", False),
        target_channel=settings.kick_channel_slug,
        stream_active=pipeline.get("is_running", False),
        clips_today=pipeline.get("clips_today", 0),
        buffer_usage_mb=0,
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
