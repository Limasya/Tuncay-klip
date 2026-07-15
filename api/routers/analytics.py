"""
Analytics API Router
────────────────────
Endpoints for clip performance analytics: views, engagement, platform stats.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("analytics_api")

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class AnalyticsUpdateRequest(BaseModel):
    clip_id: int
    platform: str
    views: int = 0
    likes: int = 0
    dislikes: int = 0
    comments: int = 0
    shares: int = 0
    impressions: int = 0
    watch_time_seconds: float = 0.0
    avg_watch_percentage: float = 0.0


class AnalyticsSummary(BaseModel):
    total_clips: int = 0
    total_views: int = 0
    total_likes: int = 0
    total_shares: int = 0
    avg_engagement_rate: float = 0.0
    top_clips: list = []


@router.get("/summary")
async def get_analytics_summary(
    platform: Optional[str] = Query(None, description="Filter by platform"),
    days: int = Query(30, description="Look back period in days"),
):
    """Get overall analytics summary."""
    from services.database import async_session
    from models.database import ClipAnalytics, Clip
    from sqlalchemy import func, select

    async with async_session() as session:
        query = select(
            func.count(ClipAnalytics.id.distinct()).label("snapshots"),
            func.coalesce(func.sum(ClipAnalytics.views), 0).label("total_views"),
            func.coalesce(func.sum(ClipAnalytics.likes), 0).label("total_likes"),
            func.coalesce(func.sum(ClipAnalytics.shares), 0).label("total_shares"),
            func.coalesce(func.avg(ClipAnalytics.engagement_rate), 0).label("avg_engagement"),
        )
        if platform:
            query = query.where(ClipAnalytics.platform == platform)

        result = await session.execute(query)
        row = result.one()

        # Top clips by views
        top_query = (
            select(ClipAnalytics)
            .order_by(ClipAnalytics.views.desc())
            .limit(10)
        )
        if platform:
            top_query = top_query.where(ClipAnalytics.platform == platform)

        top_result = await session.execute(top_query)
        top_clips = [a.to_dict() for a in top_result.scalars().all()]

        return {
            "total_snapshots": row.snapshots or 0,
            "total_views": int(row.total_views),
            "total_likes": int(row.total_likes),
            "total_shares": int(row.total_shares),
            "avg_engagement_rate": round(float(row.avg_engagement), 2),
            "top_clips": top_clips,
            "platform_filter": platform,
            "period_days": days,
        }


@router.get("/clip/{clip_id}")
async def get_clip_analytics(clip_id: int):
    """Get analytics for a specific clip."""
    from services.database import async_session
    from models.database import ClipAnalytics
    from sqlalchemy import select

    async with async_session() as session:
        query = (
            select(ClipAnalytics)
            .where(ClipAnalytics.clip_id == clip_id)
            .order_by(ClipAnalytics.snapshot_at.desc())
        )
        result = await session.execute(query)
        records = result.scalars().all()

        if not records:
            return {"clip_id": clip_id, "analytics": [], "summary": None}

        # Aggregate across all snapshots
        total_views = sum(r.views for r in records)
        total_likes = sum(r.likes for r in records)
        total_shares = sum(r.shares for r in records)
        platforms = list(set(r.platform for r in records))

        return {
            "clip_id": clip_id,
            "analytics": [r.to_dict() for r in records],
            "summary": {
                "total_views": total_views,
                "total_likes": total_likes,
                "total_shares": total_shares,
                "platforms": platforms,
                "snapshots": len(records),
            },
        }


@router.post("/update")
async def update_analytics(request: AnalyticsUpdateRequest):
    """Record a new analytics snapshot for a clip."""
    from services.database import async_session
    from models.database import ClipAnalytics

    async with async_session() as session:
        snapshot = ClipAnalytics(
            clip_id=request.clip_id,
            platform=request.platform,
            views=request.views,
            likes=request.likes,
            dislikes=request.dislikes,
            comments=request.comments,
            shares=request.shares,
            impressions=request.impressions,
            watch_time_seconds=request.watch_time_seconds,
            avg_watch_percentage=request.avg_watch_percentage,
        )
        snapshot.engagement_rate = snapshot.compute_engagement_rate()
        session.add(snapshot)
        await session.commit()
        await session.refresh(snapshot)

        return {"status": "recorded", "id": snapshot.id, "engagement_rate": snapshot.engagement_rate}


@router.get("/platform/{platform}")
async def get_platform_analytics(platform: str):
    """Get analytics aggregated by platform."""
    from services.database import async_session
    from models.database import ClipAnalytics
    from sqlalchemy import select, func

    async with async_session() as session:
        query = (
            select(
                func.count(ClipAnalytics.id).label("snapshots"),
                func.coalesce(func.sum(ClipAnalytics.views), 0).label("total_views"),
                func.coalesce(func.sum(ClipAnalytics.likes), 0).label("total_likes"),
                func.coalesce(func.sum(ClipAnalytics.shares), 0).label("total_shares"),
                func.coalesce(func.avg(ClipAnalytics.engagement_rate), 0).label("avg_engagement"),
            )
            .where(ClipAnalytics.platform == platform)
        )
        result = await session.execute(query)
        row = result.one()

        return {
            "platform": platform,
            "snapshots": row.snapshots or 0,
            "total_views": int(row.total_views),
            "total_likes": int(row.total_likes),
            "total_shares": int(row.total_shares),
            "avg_engagement_rate": round(float(row.avg_engagement), 2),
        }
