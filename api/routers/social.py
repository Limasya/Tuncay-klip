"""
Sosyal Medya API Endpoints
──────────────────────────
TikTok, Reels ve Shorts için otomatik video kurgusu üretilmesini sağlayan endpointler.
"""
import logging
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
