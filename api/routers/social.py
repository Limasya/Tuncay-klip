"""
Sosyal Medya API Endpoints
──────────────────────────
TikTok, Reels ve Shorts için otomatik video kurgusu üretilmesini sağlayan endpointler.
"""
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from services.social_video_generator import social_video_gen
from services.ai_pipeline import ai_pipeline

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
