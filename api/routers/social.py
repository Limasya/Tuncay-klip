"""
Sosyal Medya API Endpoints
──────────────────────────
TikTok, Reels ve Shorts için otomatik video kurgusu üretilmesini sağlayan endpointler.
"""
import logging
from dataclasses import asdict
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from services.kick_archive import (
    TARGET_CHANNEL_SLUG,
    TARGET_CHANNEL_URL,
    is_target_vod_url,
    kick_archive,
)
from services.social_video_generator import social_video_gen
from services.master_pipeline import master_pipeline
from services.ai_pipeline import ai_pipeline
from utils.auth_compat import Principal, Scope, require_scope

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/social", tags=["social"])


class ViralVideoRequest(BaseModel):
    input_video_path: str
    transcript_data: Dict[str, Any] | None = None
    facecam_position: str = "top_left"
    emotion_spikes: list[Dict[str, Any]] | None = None


@router.post("/generate-viral-video", status_code=202)
async def generate_viral_video_endpoint(
    request: ViralVideoRequest, background_tasks: BackgroundTasks
):
    """
    16:9 yatay bir klibi, 9:16 TikTok/Reels formatına çeviren
    render işlemini başlatır. (Arka planda çalışır)
    """
    try:
        # Arka planda FFmpeg çalıştır
        async def background_render():
            logger.info("Starting background viral render for %s", request.input_video_path)
            result = await social_video_gen.generate_viral_video(
                input_video_path=request.input_video_path,
                transcript_data=request.transcript_data,
                facecam_position=request.facecam_position,
                emotion_spikes=request.emotion_spikes
            )
            logger.info("Background viral render completed: %s", result)

        background_tasks.add_task(background_render)
        return {"status": "accepted", "message": "Viral video generation started in background"}
    except Exception as e:
        logger.error("Failed to start viral video generation: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


class MasterPipelineRequest(BaseModel):
    url: str


class ProcessLocalRequest(BaseModel):
    vod_path: str
    export_format: str = "social"
    max_clips: int = 5
    streamer: str = "Tuncay"
    game: str = "Kick"


class KickArchiveSyncRequest(BaseModel):
    """Bounded archive job options; no source channel or URL is accepted."""
    vod_limit: int | None = Field(default=None, ge=1, le=50)
    max_clips_per_vod: int | None = Field(default=None, ge=1, le=10)

@router.post("/generate-master-pipeline", status_code=202)
async def generate_master_pipeline_endpoint(
    request: MasterPipelineRequest,
    background_tasks: BackgroundTasks,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """
    Sadece URL vererek tüm süreci otonom işletir.
    (İndirme -> LLM Kırpma -> Yüz Takibi -> Render)
    """
    if not is_target_vod_url(request.url):
        raise HTTPException(
            status_code=400,
            detail=(
                "Only public VOD URLs from "
                f"{TARGET_CHANNEL_URL}/videos/... can be processed."
            ),
        )

    try:
        async def background_master():
            logger.info("Starting background master pipeline for %s", request.url)
            result = await master_pipeline.process_url(request.url)
            logger.info("Background master pipeline completed: %s", result)

        background_tasks.add_task(background_master)
        return {"status": "accepted", "message": "Master autonomous pipeline started in background"}
    except Exception as e:
        logger.error("Failed to start master pipeline: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-local", status_code=202)
async def process_local_endpoint(
    request: ProcessLocalRequest,
    background_tasks: BackgroundTasks,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Mevcut VOD dosyasını indirmeden doğrudan işle."""
    from pathlib import Path
    if not Path(request.vod_path).exists():
        raise HTTPException(status_code=404, detail=f"Dosya bulunamadi: {request.vod_path}")

    async def background_local():
        from services.master_pipeline import master_pipeline
        from services.master_pipeline import PipelineConfig
        cfg = PipelineConfig(
            export_format=request.export_format,
            max_clips=request.max_clips,
            streamer=request.streamer,
            game=request.game,
        )
        logger.info("Starting background process_local for %s", request.vod_path)
        result = await master_pipeline.process_local(request.vod_path, config=cfg)
        logger.info("Background process_local completed: %s", result)

    background_tasks.add_task(background_local)
    return {"status": "accepted", "message": f"Local VOD isleniyor: {request.vod_path}"}


class StreamProcessRequest(BaseModel):
    url: str
    export_format: str = "social"
    max_clips: int = 5
    streamer: str = "Tuncay"
    game: str = "Kick"


@router.post("/stream-process", status_code=202)
async def stream_process_endpoint(
    request: StreamProcessRequest,
    background_tasks: BackgroundTasks,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """VOD'u indirmeden HLS stream uzerinden isle (proxyless).

    Kick API'den HLS source URL alir, ffmpeg ile sadece sesi ceker,
    Groq/faster-whisper ile transkribe eder, LLM ile viral anlari bulur,
    her klip icin sadece o segmenti stream edip render eder.

    Tam VOD indirilmez. Sadece ihtiyac kadar bant genisligi kullanilir.
    """
    from services.master_pipeline import master_pipeline, PipelineConfig

    async def background_stream():
        try:
            cfg = PipelineConfig(
                export_format=request.export_format,
                max_clips=request.max_clips,
                streamer=request.streamer,
                game=request.game,
            )
            logger.info("Starting background stream_process for %s", request.url)
            result = await master_pipeline.process_stream(request.url, config=cfg)
            logger.info("Background stream_process completed: %s", result)
        except Exception as e:
            logger.error("Background stream_process FAILED: %s", e, exc_info=True)

    background_tasks.add_task(background_stream)
    return {"status": "accepted", "message": f"Stream isleniyor: {request.url} (indirmeden)"}


# ── Zero-Bandwidth Clip Engine ─────────────────────────────────────────────

class AnalyzeVODRequest(BaseModel):
    """VOD'u sadece metadata ile analiz et — sıfır video/ses indirme."""
    url: str


class RenderClipRequest(BaseModel):
    """Onaylanan bir clip'i render et — sadece o segmenti indir."""
    vod_url: str
    clip_id: str
    clip_title: str = ""
    clip_description: str = ""
    start_time: float = 0.0
    end_time: float = 30.0
    duration: float = 30.0
    confidence: float = 0.5
    platform: str = "tiktok"


@router.post("/analyze-vod", status_code=200)
async def analyze_vod_endpoint(
    request: AnalyzeVODRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """VOD'u sadece metadata ile analiz et — HİÇBİR video/ses indirmez.

    Bant genişliği kullanımı: ~2-5 KB (sadece API JSON'u)
    Analiz: LLM ile metadata tabanlı clip önerileri
    """
    from services.zero_bandwidth_clipper import zero_bandwidth_clipper

    try:
        analysis = await zero_bandwidth_clipper.analyze_vod(request.url)
        return {
            "success": True,
            "vod_id": analysis.vod_id,
            "title": analysis.title,
            "duration": analysis.duration,
            "category": analysis.category,
            "ai_summary": analysis.ai_summary,
            "clips_found": len(analysis.clips),
            "clips": [asdict(c) for c in analysis.clips],
            "analysis_time_sec": analysis.analysis_time_sec,
            "bandwidth_used_kb": analysis.bandwidth_used_kb,
            "message": f"{len(analysis.clips)} clip önerisi bulundu (sıfır video indirme)",
        }
    except Exception as e:
        logger.error("VOD analiz hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-all-vods", status_code=200)
async def analyze_all_vods_endpoint(
    limit: int = 10,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Tüm VOD'ları analiz et — sıfır video/ses indirme."""
    from services.zero_bandwidth_clipper import zero_bandwidth_clipper

    try:
        analyses = await zero_bandwidth_clipper.analyze_all_vods(limit=limit)
        results = []
        total_clips = 0
        total_kb = 0
        for a in analyses:
            total_clips += len(a.clips)
            total_kb += a.bandwidth_used_kb
            results.append({
                "vod_id": a.vod_id,
                "title": a.title,
                "duration": a.duration,
                "clips_count": len(a.clips),
                "clips": [asdict(c) for c in a.clips[:3]],  # İlk 3 clip'i göster
                "analysis_time_sec": a.analysis_time_sec,
            })

        return {
            "success": True,
            "total_vods": len(analyses),
            "total_clips": total_clips,
            "total_bandwidth_kb": round(total_kb, 1),
            "analyses": results,
            "message": f"{len(analyses)} VOD analiz edildi, {total_clips} clip önerisi (sıfır video indirme)",
        }
    except Exception as e:
        logger.error("Toplu VOD analiz hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/render-clip", status_code=202)
async def render_clip_endpoint(
    request: RenderClipRequest,
    background_tasks: BackgroundTasks,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Onaylanan bir clip'i render et — sadece o segmenti indir.

    Bant genişliği: ~2-5 MB per 30sn clip (vs 1-3 GB tam VOD).
    """
    from services.zero_bandwidth_clipper import zero_bandwidth_clipper, ClipSuggestion

    clip = ClipSuggestion(
        clip_id=request.clip_id,
        title=request.clip_title,
        description=request.clip_description,
        start_time=request.start_time,
        end_time=request.end_time,
        duration=request.duration,
        confidence=request.confidence,
        reason="",
        platform=request.platform,
    )

    async def background_render():
        try:
            result = await zero_bandwidth_clipper.render_clip(request.vod_url, clip)
            logger.info("Clip render completed: %s", result)
        except Exception as e:
            logger.error("Clip render FAILED: %s", e, exc_info=True)

    background_tasks.add_task(background_render)
    return {
        "status": "accepted",
        "clip_id": request.clip_id,
        "message": f"Clip render başlatıldı: {request.clip_title} ({request.start_time:.0f}-{request.end_time:.0f} sn)",
    }


@router.get("/clip-suggestions")
async def get_clip_suggestions(
    vod_id: str | None = None,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Önbelleğe alınmış clip önerilerini getir."""
    from services.zero_bandwidth_clipper import zero_bandwidth_clipper

    if vod_id:
        analysis = zero_bandwidth_clipper.get_cached_analysis(vod_id)
        if not analysis:
            raise HTTPException(status_code=404, detail=f"VOD analizi bulunamadı: {vod_id}")
        return {
            "vod_id": analysis.vod_id,
            "title": analysis.title,
            "clips": [asdict(c) for c in analysis.clips],
        }

    # Tüm cache'lenmiş analizleri getir
    all_analyses = zero_bandwidth_clipper._analysis_cache
    return {
        "total_analyses": len(all_analyses),
        "analyses": [
            {
                "vod_id": a.vod_id,
                "title": a.title,
                "clips_count": len(a.clips),
            }
            for a in all_analyses.values()
        ],
    }


@router.post("/audio-fallback", status_code=200)
async def toggle_audio_fallback(
    enabled: bool = True,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Ses-only fallback modunu ac/kapa.

    Community clip'i olmayan VOD'lar icin ses-only transkripsiyon yapar.
    AAC 64kbps = ~28.8 MB/saat bant genisligi kullanir.
    Varsayilan: kapali.
    """
    from services.zero_bandwidth_clipper import zero_bandwidth_clipper
    zero_bandwidth_clipper.audio_only_fallback_enabled = enabled
    return {
        "audio_only_fallback_enabled": enabled,
        "message": (
            "Ses-only fallback AKTIF. Community clip'i olmayan VOD'lar icin ses transkripsiyonu yapilacak."
            if enabled
            else "Ses-only fallback KAPATILDI. Sadece metadata + community clip kullanilacak."
        ),
    }


@router.post("/kick-archive/sync", status_code=202)
async def start_kick_archive_sync(
    request: KickArchiveSyncRequest,
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Discover and process new public VODs from the fixed Tuncay channel."""
    result = kick_archive.start_sync(
        vod_limit=request.vod_limit,
        max_clips_per_vod=request.max_clips_per_vod,
    )
    return {
        **result,
        "message": (
            "Public Tuncay VOD archive processing started."
            if result["status"] == "accepted"
            else "A public Tuncay VOD archive job is already running."
        ),
        "channel": TARGET_CHANNEL_SLUG,
        "channel_url": TARGET_CHANNEL_URL,
    }


@router.get("/kick-archive/status")
async def get_kick_archive_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Return archive progress and deduplication state for the fixed channel."""
    return await kick_archive.get_status()


# ── Zero-Bandwidth periyodik tarama ───────────────────────────────────────

@router.post("/zero-bandwidth/sync", status_code=202)
async def start_zero_bandwidth_sync(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Tek seferlik zero-bandwidth VOD analizi baslat (metadata + LLM, sifir indirme)."""
    result = kick_archive.start_zero_bandwidth_sync()
    return {
        **result,
        "message": (
            "Zero-bandwidth VOD analizi baslatildi."
            if result["status"] == "accepted"
            else "Zero-bandwidth tarama zaten calisiyor."
        ),
    }


@router.post("/zero-bandwidth/scheduler", status_code=200)
async def start_zero_bandwidth_scheduler(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Zero-bandwidth periyodik tarama scheduler'ini baslat (2 saat aralikla)."""
    settings = get_settings()
    if not settings.zero_bandwidth_scan_enabled:
        return {"status": "disabled", "message": "zero_bandwidth_scan_enabled=False. Config'den acin."}
    started = await kick_archive.start_zero_bandwidth_scheduler()
    return {
        "status": "started" if started else "already_running",
        "interval_minutes": settings.zero_bandwidth_scan_interval_minutes,
    }


@router.get("/zero-bandwidth/status")
async def get_zero_bandwidth_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Zero-bandwidth analiz durumu ve sonuclari."""
    return await kick_archive.get_zero_bandwidth_status()


# ── Kick Stream Monitor endpoints ──────────────────────────────────────────

@router.post("/kick-monitor/start", status_code=200)
async def start_kick_monitor(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Kick canlı yayın monitörünü başlat. Yayın başladığında otomatik klip üretir."""
    from services.kick_stream_monitor import kick_stream_monitor
    started = await kick_stream_monitor.start()
    return {
        "success": started,
        "status": "started" if started else "already_running",
        "channel": "thetuncay",
        "channel_url": "https://kick.com/thetuncay",
        "message": (
            "Kick Stream Monitor başlatıldı. Canlı yayın bekleniyor."
            if started
            else "Kick Stream Monitor zaten çalışıyor."
        ),
    }


@router.post("/kick-monitor/stop", status_code=200)
async def stop_kick_monitor(
    _principal: Principal = Depends(require_scope(Scope.STREAMS_MANAGE)),
):
    """Kick canlı yayın monitörünü durdur."""
    from services.kick_stream_monitor import kick_stream_monitor
    await kick_stream_monitor.stop()
    return {"success": True, "status": "stopped"}


@router.get("/kick-monitor/status")
async def get_kick_monitor_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Kick Stream Monitor'un anlık durumunu döndürür."""
    from services.kick_stream_monitor import kick_stream_monitor
    return kick_stream_monitor.get_status()


# ── Kick VOD list endpoint ──────────────────────────────────────────────────

@router.get("/kick-vods")
async def list_kick_vods(
    limit: int = 5,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """
    Kick kanalındaki (thetuncay) son VOD'ları listeler.
    Pipeline başlatmadan, sadece metadata görüntülemek için kullanılır.
    """
    from services.kick_api import kick_service
    limit = max(1, min(limit, 20))
    vods = await kick_service.list_public_vods(limit=limit)
    return {
        "channel": "thetuncay",
        "channel_url": "https://kick.com/thetuncay",
        "count": len(vods),
        "vods": vods,
    }


@router.get("/kick-live")
async def get_kick_live_status():
    """Kick kanalının anlık canlı yayın durumunu döndürür (auth gerektirmez)."""
    from services.kick_api import kick_service
    info = await kick_service.get_livestream_info()
    return info
