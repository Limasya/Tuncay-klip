"""
Recommendation Engine API Router
─────────────────────────────────
Endpoints for clip recommendations, similar clips, trending, and user preferences.
"""
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from utils.auth_compat import Principal, Scope, get_current_principal, require_scope

logger = logging.getLogger("recommendations_api")

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------

class SimilarClipsRequest(BaseModel):
    clip_id: str
    top_n: int = 10


class SimilarClipResult(BaseModel):
    clip_id: str
    score: float


class RankRequest(BaseModel):
    clips: list[dict[str, Any]]
    user_id: str
    top_n: int = 20
    exclude_watched: list[str] = []


class RankedClipResult(BaseModel):
    clip_id: str
    score: float
    category: str = ""
    emotion: str = ""


class WatchEventRequest(BaseModel):
    user_id: str
    clip_id: str
    clip_profile: dict[str, Any] = {}


class LikeEventRequest(BaseModel):
    user_id: str
    clip_id: str
    clip_profile: dict[str, Any] = {}


class SkipEventRequest(BaseModel):
    user_id: str
    clip_id: str
    clip_profile: dict[str, Any] = {}


class UserPreferencesResponse(BaseModel):
    categories: dict[str, float] = {}
    emotions: dict[str, float] = {}
    avg_duration: float = 30.0
    total_watched: int = 0
    total_liked: int = 0
    total_skipped: int = 0


# ---------------------------------------------------------------------------
# Lazy engine singleton
# ---------------------------------------------------------------------------

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from services.recommendation_engine import (
            ClipSimilarityEngine,
            UserPreferenceLearner,
            ClipRanker,
        )
        _engine = {
            "similarity": ClipSimilarityEngine(),
            "learner": UserPreferenceLearner(),
            "ranker": ClipRanker(),
        }
    return _engine


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/similar/{clip_id}")
async def get_similar_clips(
    clip_id: str,
    top_n: int = Query(10, ge=1, le=50),
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Find clips similar to the given clip_id using content-based filtering."""
    eng = _get_engine()
    results = eng["similarity"].find_similar(clip_id, top_n=top_n)
    return {"clip_id": clip_id, "similar": [{"clip_id": cid, "score": round(sc, 4)} for cid, sc in results]}


@router.post("/similar")
async def find_similar(
    body: SimilarClipsRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Find clips similar to a given clip using the similarity engine."""
    eng = _get_engine()
    results = eng["similarity"].find_similar(body.clip_id, top_n=body.top_n)
    return {
        "clip_id": body.clip_id,
        "similar": [{"clip_id": cid, "score": round(sc, 4)} for cid, sc in results],
    }


@router.post("/rank")
async def rank_clips(
    body: RankRequest,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Rank a set of clips for a user using the multi-factor ranking model."""
    eng = _get_engine()
    user_prefs = eng["learner"].get_preferences(body.user_id)
    watched = set(body.exclude_watched)
    ranked = eng["ranker"].rank(
        body.clips,
        user_prefs=user_prefs,
        recently_watched=watched,
        top_n=body.top_n,
    )
    return {"user_id": body.user_id, "ranked": ranked}


@router.get("/trending")
async def get_trending(
    top_n: int = Query(20, ge=1, le=100),
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Get currently trending clips (highest engagement + freshness)."""
    eng = _get_engine()
    trending = eng["ranker"]._trending_boost
    return {"trending": [{"clip_id": cid, "boost": round(sc, 4)} for cid, sc in sorted(trending.items(), key=lambda x: x[1], reverse=True)[:top_n]]}


@router.post("/trending/set")
async def set_trending(
    clip_ids: list[str],
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Mark clips as trending to boost their ranking."""
    eng = _get_engine()
    eng["ranker"].set_trending(clip_ids)
    return {"marked": len(clip_ids)}


@router.get("/user/{user_id}/preferences")
async def get_user_preferences(
    user_id: str,
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Get learned preferences for a user."""
    eng = _get_engine()
    prefs = eng["learner"].get_preferences(user_id)
    return UserPreferencesResponse(**prefs)


@router.post("/user/watch")
async def record_watch(
    body: WatchEventRequest,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Record a clip watch event to learn user preferences."""
    eng = _get_engine()
    eng["learner"].record_watch(body.user_id, body.clip_id, body.clip_profile)
    return {"status": "recorded", "user_id": body.user_id, "clip_id": body.clip_id}


@router.post("/user/like")
async def record_like(
    body: LikeEventRequest,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Record a like event (strong positive signal)."""
    eng = _get_engine()
    eng["learner"].record_like(body.user_id, body.clip_id, body.clip_profile)
    return {"status": "recorded", "user_id": body.user_id, "clip_id": body.clip_id}


@router.post("/user/skip")
async def record_skip(
    body: SkipEventRequest,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Record a skip event (negative signal)."""
    eng = _get_engine()
    eng["learner"].record_skip(body.user_id, body.clip_id, body.clip_profile)
    return {"status": "recorded", "user_id": body.user_id, "clip_id": body.clip_id}


@router.get("/status")
async def engine_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Get recommendation engine status."""
    eng = _get_engine()
    return {
        "similarity": eng["similarity"].get_status(),
        "learner": eng["learner"].get_status(),
        "ranker": eng["ranker"].get_status(),
    }
