"""
Knowledge Base API — Tüm yayınların bilgi bankası.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Any, Optional

router = APIRouter(prefix="/kb", tags=["knowledge-base"])


# ── Request/Response Models ──

class KBSearchRequest(BaseModel):
    text: Optional[str] = None
    fact_types: list[str] = Field(default_factory=list)
    stream_id: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    min_confidence: float = 0.5
    limit: int = 50


class KBSearchResponse(BaseModel):
    facts: list[dict[str, Any]] = Field(default_factory=list)
    total_count: int = 0
    query_time_ms: float = 0.0
    narrative: str = ""


class KBStreamSummary(BaseModel):
    stream_id: str
    title: str = ""
    game: str = ""
    started_at: str = ""
    duration_minutes: float = 0.0
    peak_viewers: int = 0
    participants: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    fact_count: int = 0


class KBStats(BaseModel):
    total_facts: int = 0
    total_sessions: int = 0
    fact_types: dict[str, int] = Field(default_factory=dict)
    unique_tags: int = 0
    unique_streams: int = 0


# ── Endpoints ──

@router.get("/stats", response_model=KBStats)
async def get_stats():
    """Knowledge Base istatistikleri."""
    from services.knowledge_base import knowledge_base
    stats = await knowledge_base.get_stats()
    return KBStats(**stats)


@router.get("/search", response_model=KBSearchResponse)
async def search_facts(
    text: str = Query(None, description="Arama metni"),
    fact_types: str = Query(None, description="Fact türleri (virgülle ayrılmış)"),
    stream_id: str = Query(None, description="Stream ID"),
    tags: str = Query(None, description="Etiketler (virgülle ayrılmış)"),
    min_confidence: float = Query(0.5, description="Minimum güven skoru"),
    limit: int = Query(50, description="Maksimum sonuç sayısı"),
):
    """Knowledge Base'de ara."""
    from services.knowledge_base import KBQuery, knowledge_base
    from services.knowledge_base import FactType

    # Parse fact_types
    ft_list = []
    if fact_types:
        for ft_str in fact_types.split(","):
            try:
                ft_list.append(FactType(ft_str.strip()))
            except ValueError:
                pass

    # Parse tags
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    query = KBQuery(
        text=text,
        fact_types=ft_list,
        stream_id=stream_id,
        tags=tag_list,
        min_confidence=min_confidence,
        limit=limit,
    )

    result = await knowledge_base.search(query)

    return KBSearchResponse(
        facts=[f.model_dump() for f in result.facts],
        total_count=result.total_count,
        query_time_ms=result.query_time_ms,
        narrative=result.narrative,
    )


@router.get("/streams", response_model=list[KBStreamSummary])
async def list_streams(limit: int = Query(20, description="Maksimum yayın sayısı")):
    """Tüm yayınları listele."""
    from services.knowledge_base import knowledge_base

    sessions = await knowledge_base.get_all_sessions()
    sessions = sessions[:limit]

    return [
        KBStreamSummary(
            stream_id=s.stream_id,
            title=s.title,
            game=s.game,
            started_at=s.started_at,
            duration_minutes=s.duration_seconds / 60,
            peak_viewers=s.peak_viewer_count,
            participants=s.participants,
            topics=s.topics,
            highlights=s.highlights,
            fact_count=s.fact_count,
        )
        for s in sessions
    ]


@router.get("/streams/{stream_id}", response_model=KBStreamSummary)
async def get_stream(stream_id: str):
    """Belirli bir yayın hakkında detaylı bilgi."""
    from services.knowledge_base import knowledge_base

    session = await knowledge_base.get_stream_summary(stream_id)
    if not session:
        raise HTTPException(status_code=404, detail="Stream not found")

    return KBStreamSummary(
        stream_id=session.stream_id,
        title=session.title,
        game=session.game,
        started_at=session.started_at,
        duration_minutes=session.duration_seconds / 60,
        peak_viewers=session.peak_viewer_count,
        participants=session.participants,
        topics=session.topics,
        highlights=session.highlights,
        fact_count=session.fact_count,
    )


@router.get("/streams/{stream_id}/facts")
async def get_stream_facts(
    stream_id: str,
    fact_type: str = Query(None, description="Fact türü filtresi"),
):
    """Belirli bir yayın için tüm fact'leri getir."""
    from services.knowledge_base import knowledge_base, FactType

    ft = None
    if fact_type:
        try:
            ft = FactType(fact_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid fact type: {fact_type}")

    facts = await knowledge_base.get_facts_by_stream(stream_id)
    if ft:
        facts = [f for f in facts if f.fact_type == ft]

    return {
        "stream_id": stream_id,
        "fact_type": fact_type,
        "facts": [f.model_dump() for f in facts],
        "count": len(facts),
    }


@router.get("/participants")
async def list_participants(
    stream_id: str = Query(None, description="Stream ID filtresi"),
    limit: int = Query(50),
):
    """Tüm katılımcıları listele."""
    from services.knowledge_base import knowledge_base, KBQuery, FactType

    query = KBQuery(fact_types=[FactType.PARTICIPANT], stream_id=stream_id, limit=limit)
    result = await knowledge_base.search(query)

    participants = []
    for f in result.facts:
        participants.append({
            "name": f.data.get("name", ""),
            "role": f.data.get("role", ""),
            "stream_id": f.stream_id,
            "timestamp": f.timestamp,
        })

    return {"participants": participants, "count": len(participants)}


@router.get("/topics")
async def list_topics(
    stream_id: str = Query(None),
    limit: int = Query(50),
):
    """Tüm konuşulan konuları listele."""
    from services.knowledge_base import knowledge_base, KBQuery, FactType

    query = KBQuery(fact_types=[FactType.TOPIC, FactType.CHAT_TOPIC], stream_id=stream_id, limit=limit)
    result = await knowledge_base.search(query)

    topics = []
    for f in result.facts:
        topics.append({
            "topic": f.data.get("topic", ""),
            "summary": f.data.get("summary", ""),
            "type": f.fact_type.value,
            "stream_id": f.stream_id,
            "timestamp": f.timestamp,
        })

    return {"topics": topics, "count": len(topics)}


@router.get("/highlights")
async def list_highlights(
    stream_id: str = Query(None),
    limit: int = Query(20),
):
    """Öne çıkan anları listele."""
    from services.knowledge_base import knowledge_base, KBQuery, FactType

    query = KBQuery(fact_types=[FactType.HIGHLIGHT], stream_id=stream_id, limit=limit)
    result = await knowledge_base.search(query)

    highlights = []
    for f in result.facts:
        highlights.append({
            "title": f.data.get("title", ""),
            "score": f.data.get("score", 0),
            "reason": f.data.get("reason", ""),
            "stream_id": f.stream_id,
            "timestamp": f.timestamp,
        })

    return {"highlights": highlights, "count": len(highlights)}


@router.get("/game-events")
async def list_game_events(
    stream_id: str = Query(None),
    event_type: str = Query(None, description="kill, death, win, etc."),
    limit: int = Query(50),
):
    """Oyun içi olayları listele."""
    from services.knowledge_base import knowledge_base, KBQuery, FactType

    query = KBQuery(fact_types=[FactType.GAME_EVENT], stream_id=stream_id, limit=limit)
    result = await knowledge_base.search(query)

    events = []
    for f in result.facts:
        if event_type and f.data.get("event_type", "") != event_type:
            continue
        events.append({
            "event_type": f.data.get("event_type", ""),
            "game": f.data.get("game", ""),
            "killer": f.data.get("killer", ""),
            "victim": f.data.get("victim", ""),
            "weapon": f.data.get("weapon", ""),
            "score_change": f.data.get("score_change", 0),
            "stream_id": f.stream_id,
            "timestamp": f.timestamp,
        })

    return {"events": events, "count": len(events)}


@router.get("/emotions")
async def list_emotions(
    stream_id: str = Query(None),
    limit: int = Query(50),
):
    """Duygu durumlarını listele."""
    from services.knowledge_base import knowledge_base, KBQuery, FactType

    query = KBQuery(fact_types=[FactType.EMOTION], stream_id=stream_id, limit=limit)
    result = await knowledge_base.search(query)

    emotions = []
    for f in result.facts:
        emotions.append({
            "emotion": f.data.get("emotion", ""),
            "intensity": f.data.get("intensity", 0),
            "source": f.data.get("source", ""),
            "stream_id": f.stream_id,
            "timestamp": f.timestamp,
        })

    return {"emotions": emotions, "count": len(emotions)}


@router.post("/ingest")
async def ingest_from_graph(
    stream_id: str = Query(..., description="Stream ID"),
    start_time: float = Query(0, description="Başlangıç zamanı (saniye)"),
    end_time: float = Query(None, description="Bitiş zamanı (saniye)"),
):
    """Intelligence Graph'tan bilgi bankasına veri aktar."""
    from services.knowledge_base import knowledge_ingester
    from services.intelligence_graph.graph_db import intelligence_graph

    time_window = (start_time, end_time) if end_time else None
    count = await knowledge_ingester.ingest_from_graph(
        intelligence_graph, stream_id, time_window
    )

    return {
        "stream_id": stream_id,
        "facts_ingested": count,
        "message": f"{count} fact bilgi bankasına aktarıldı.",
    }


@router.post("/save")
async def save_knowledge_base():
    """Knowledge Base'i kaydet."""
    from services.knowledge_base import knowledge_base
    await knowledge_base.save()
    return {"message": "Knowledge Base kaydedildi."}
