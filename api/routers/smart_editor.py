"""
Smart Editor API Router
────────────────────────
AI-powered clip editing recommendations: trim points, beat sync, platform optimization.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from utils.auth_compat import Principal, Scope, require_scope

logger = logging.getLogger("smart_editor_api")

router = APIRouter(prefix="/api/smart-editor", tags=["smart-editor"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class AnalyzeClipRequest(BaseModel):
    highlight_scores: list[dict[str, Any]] = []
    emotion_arc: list[dict[str, Any]] = []
    audio_spikes: list[dict[str, Any]] = []
    chat_spikes: list[dict[str, Any]] = []
    duration: float = 60.0
    platform: str = "youtube"


class TrimRequest(BaseModel):
    clip_duration: float
    highlight_scores: list[dict[str, Any]] = []
    audio_spikes: list[dict[str, Any]] = []
    platform: str = "youtube"


class BeatSyncRequest(BaseModel):
    audio_data_b64: Optional[str] = None
    duration: float = 60.0


class PlatformInfo(BaseModel):
    aspect_ratio: str
    recommended_duration: int
    subtitle_position: str = "bottom"


# ---------------------------------------------------------------------------
# Lazy engine singletons
# ---------------------------------------------------------------------------

_content_analyzer = None
_trim_suggestor = None
_beat_sync_analyzer = None


def _get_content_analyzer():
    global _content_analyzer
    if _content_analyzer is None:
        from services.smart_editor import ClipContentAnalyzer
        _content_analyzer = ClipContentAnalyzer()
    return _content_analyzer


def _get_trim_suggestor():
    global _trim_suggestor
    if _trim_suggestor is None:
        from services.smart_editor import AutoTrimSuggestor
        _trim_suggestor = AutoTrimSuggestor()
    return _trim_suggestor


def _get_beat_sync():
    global _beat_sync_analyzer
    if _beat_sync_analyzer is None:
        from services.smart_editor import BeatSyncAnalyzer
        _beat_sync_analyzer = BeatSyncAnalyzer()
    return _beat_sync_analyzer


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze")
async def analyze_clip(
    body: AnalyzeClipRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Analyze clip content and return editing recommendations."""
    analyzer = _get_content_analyzer()
    result = analyzer.analyze(
        highlight_scores=body.highlight_scores,
        emotion_arc=body.emotion_arc,
        audio_spikes=body.audio_spikes,
        chat_spikes=body.chat_spikes,
        duration=body.duration,
        platform=body.platform,
    )
    return result


@router.post("/trim")
async def suggest_trims(
    body: TrimRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Suggest optimal trim points for a clip on a target platform."""
    suggestor = _get_trim_suggestor()
    result = suggestor.suggest_trims(
        clip_duration=body.clip_duration,
        highlight_scores=body.highlight_scores,
        audio_spikes=body.audio_spikes,
        platform=body.platform,
    )
    return result


@router.post("/beat-sync")
async def beat_sync(
    body: BeatSyncRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Detect beats in audio and return sync points for transitions."""
    import base64
    import numpy as np

    analyzer = _get_beat_sync()
    audio_data = None

    if body.audio_data_b64:
        try:
            raw = base64.b64decode(body.audio_data_b64)
            audio_data = np.frombuffer(raw, dtype=np.float32)
        except Exception:
            logger.debug("Failed to decode audio; falling back to empty data")

    result = analyzer.analyze_audio(audio_data=audio_data)
    result["sync_points"] = analyzer.get_sync_points(body.duration)
    return result


@router.get("/platforms")
async def list_platforms(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """List all supported platforms and their optimization rules."""
    from services.smart_editor import PLATFORM_OPTIMIZATION

    platforms = []
    for name, rules in PLATFORM_OPTIMIZATION.items():
        platforms.append({
            "name": name,
            "aspect_ratio": f"{rules['aspect_ratio'][0]}:{rules['aspect_ratio'][1]}",
            "recommended_duration": rules["recommended_duration"],
            "optimal_duration": rules["optimal_duration"],
            "max_resolution": rules.get("max_resolution", "1080p"),
            "subtitle_position": rules.get("subtitle_position", "bottom"),
        })
    return {"platforms": platforms}


@router.get("/platforms/{platform}")
async def get_platform_info(
    platform: str,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Get optimization details for a specific platform."""
    from services.smart_editor import PLATFORM_OPTIMIZATION

    rules = PLATFORM_OPTIMIZATION.get(platform)
    if rules is None:
        return {"error": f"Unknown platform: {platform}", "available": list(PLATFORM_OPTIMIZATION.keys())}
    return {
        "name": platform,
        "aspect_ratio": f"{rules['aspect_ratio'][0]}:{rules['aspect_ratio'][1]}",
        "recommended_duration": rules["recommended_duration"],
        "optimal_duration": rules["optimal_duration"],
        "max_resolution": rules.get("max_resolution", "1080p"),
        "subtitle_position": rules.get("subtitle_position", "bottom"),
        "intro_style": rules.get("intro_style", "standard"),
        "hashtag_limit": rules.get("hashtag_limit", 30),
    }


@router.get("/status")
async def engine_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Get smart editor service status."""
    return {
        "content_analyzer": "ready",
        "trim_suggestor": _get_trim_suggestor().get_status(),
        "beat_sync": _get_beat_sync().get_status(),
    }
