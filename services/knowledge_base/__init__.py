"""
Knowledge Base — Tüm Yayınların Yapılandırılmış Bilgi Bankası
─────────────────────────────────────────────────────────────
Her yayın için:
  • Kim vardı (participants)
  • Ne konuşuldu (topics, keywords)
  • Hangi oyun (game, game_events)
  • Hangi item (items, weapons)
  • Hangi olay (events, highlights)
  • Kim öldü / kim geldi (game events, viewer events)
  • Ne zaman oldu (timestamps)

Intelligence Graph'tan otomatik beslenir, natural language ile sorgulanabilir.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from shared.utils.json_state import JsonStateStore

from pydantic import BaseModel, Field

logger = logging.getLogger("knowledge_base")


# ── Knowledge Categories ──

class FactType(str, Enum):
    """Bilgi bankasındaki fact türleri."""
    STREAM = "stream"                # Yayın bilgisi
    PARTICIPANT = "participant"      # Kim vardı
    TOPIC = "topic"                  # Ne konuşuldu
    GAME = "game"                    # Hangi oyun
    GAME_EVENT = "game_event"        # Oyun içi olay (kill, death, win)
    ITEM = "item"                    # Silah, item, ekipman
    HIGHLIGHT = "highlight"          # Öne çıkan an
    VIEWER_EVENT = "viewer_event"    # İzleyici olayları (raid, follow, sub)
    EMOTION = "emotion"              # Duygu durumu
    SOUND = "sound"                  # Ses olayları
    KEYWORD = "keyword"              # Önemli kelimeler
    CHAT_TOPIC = "chat_topic"        # Chat'te konuşulan konular
    CLIP = "clip"                    # Oluşturulan klibin referansı


class EventSeverity(str, Enum):
    """Olayın önem derecesi."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ── Core Models ──

class StreamFact(BaseModel):
    """Tek bir yayın hakkında bir bilgi parçası."""
    fact_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    fact_type: FactType
    stream_id: str
    timestamp: float  # stream içindeki saniye
    confidence: float = 1.0
    data: dict[str, Any] = Field(default_factory=dict)
    source: str = ""  # hangi servisten geldi (video_analysis, audio, chat, etc.)
    tags: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_narrative(self) -> str:
        """AI'ın anlayacağı hikaye formatı."""
        d = self.data
        if self.fact_type == FactType.STREAM:
            return f"Yayın: {d.get('title', '?')} | Oyun: {d.get('game', '?')} | İzleyici: {d.get('viewer_count', 0)}"
        if self.fact_type == FactType.PARTICIPANT:
            return f"Katılımcı: {d.get('name', '?')} ({d.get('role', '?')}) - {d.get('description', '')}"
        if self.fact_type == FactType.TOPIC:
            return f"Konu: {d.get('topic', '?')} — {d.get('summary', '')}"
        if self.fact_type == FactType.GAME:
            return f"Oyun: {d.get('game_name', '?')} — {d.get('mode', '')} modu"
        if self.fact_type == FactType.GAME_EVENT:
            mins = int(self.timestamp // 60)
            secs = int(self.timestamp % 60)
            return f"[{mins:02d}:{secs:02d}] {d.get('event_type', '?')}: {d.get('killer', '?')} → {d.get('victim', '?')} ({d.get('weapon', '')})"
        if self.fact_type == FactType.ITEM:
            return f"Item: {d.get('name', '?')} — {d.get('description', '')}"
        if self.fact_type == FactType.HIGHLIGHT:
            return f"Highlight: {d.get('title', '?')} (skor: {d.get('score', 0):.2f})"
        if self.fact_type == FactType.VIEWER_EVENT:
            return f"İzleyici: {d.get('event_type', '?')} — {d.get('description', '')}"
        if self.fact_type == FactType.EMOTION:
            return f"Duygu: {d.get('emotion', '?')} (yoğunluk: {d.get('intensity', 0):.1f})"
        if self.fact_type == FactType.KEYWORD:
            return f"Kelime: {d.get('word', '?')} (frekans: {d.get('frequency', 0)})"
        if self.fact_type == FactType.CHAT_TOPIC:
            return f"Chat Konusu: {d.get('topic', '?')} — {d.get('summary', '')}"
        if self.fact_type == FactType.CLIP:
            return f"Klip: {d.get('title', '?')} — {d.get('category', '?')}"
        return f"[{self.fact_type.value}] {json.dumps(d, ensure_ascii=False)[:100]}"


class StreamSession(BaseModel):
    """Bir yayın oturumu hakkında özet bilgi."""
    stream_id: str
    title: str = ""
    game: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0
    peak_viewer_count: int = 0
    total_viewers: int = 0
    total_chat_messages: int = 0
    total_clips_created: int = 0
    participants: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    games_played: list[str] = Field(default_factory=list)
    key_events: list[str] = Field(default_factory=list)
    summary: str = ""  # AI-generated özet
    fact_count: int = 0

    def to_narrative(self) -> str:
        parts = [
            f"Yayın: {self.title}",
            f"Oyun: {', '.join(self.games_played) if self.games_played else self.game}",
            f"Süre: {int(self.duration_seconds // 60)}dk",
            f"En yüksek izleyici: {self.peak_viewer_count}",
            f"Katılımcılar: {', '.join(self.participants[:10])}",
            f"Konular: {', '.join(self.topics[:5])}",
            f"Highlight'lar: {len(self.highlights)} adet",
            f"Klip sayısı: {self.total_clips_created}",
        ]
        if self.summary:
            parts.append(f"Özet: {self.summary}")
        return " | ".join(parts)


# ── Query Models ──

class KBQuery(BaseModel):
    """Knowledge Base sorgusu."""
    text: Optional[str] = None  # natural language
    fact_types: list[FactType] = Field(default_factory=list)
    stream_id: Optional[str] = None
    time_range: Optional[tuple[float, float]] = None  # (start, end) seconds
    tags: list[str] = Field(default_factory=list)
    min_confidence: float = 0.5
    limit: int = 50


class KBResult(BaseModel):
    """Knowledge Base sorgu sonucu."""
    facts: list[StreamFact] = Field(default_factory=list)
    sessions: list[StreamSession] = Field(default_factory=list)
    total_count: int = 0
    query_time_ms: float = 0.0
    narrative: str = ""  # AI'a sunulacak özet


# ── Knowledge Base ──

class KnowledgeBase:
    """
    Tüm yayınların yapılandırılmış bilgi bankası.

    Architecture:
    ┌─────────────┐     ┌──────────────┐     ┌──────────────┐
    │ Intelligence │────►│ Knowledge    │────►│ API / LLM    │
    │ Graph        │     │ Base         │     │ Query Layer  │
    └─────────────┘     └──────────────┘     └──────────────┘
          │                     │
          ▼                     ▼
    ┌─────────────┐     ┌──────────────┐
    │ JSON State  │     │ SQLite       │
    └─────────────┘     └──────────────┘
    """

    def __init__(self, state_path: str | Path | None = None):
        self._facts: dict[str, StreamFact] = {}
        self._sessions: dict[str, StreamSession] = {}
        self._fact_index: dict[FactType, set[str]] = defaultdict(set)
        self._stream_index: dict[str, set[str]] = defaultdict(set)
        self._tag_index: dict[str, set[str]] = defaultdict(set)
        self._state = JsonStateStore(state_path or "data/knowledge_base_state.json")

    # ── Fact Operations ──

    async def add_fact(self, fact: StreamFact) -> str:
        """Bilgi bankasına bir fact ekle."""
        self._facts[fact.fact_id] = fact
        self._fact_index[fact.fact_type].add(fact.fact_id)
        self._stream_index[fact.stream_id].add(fact.fact_id)
        for tag in fact.tags:
            self._tag_index[tag].add(fact.fact_id)
        return fact.fact_id

    async def add_facts(self, facts: list[StreamFact]) -> list[str]:
        """Toplu fact ekle."""
        ids = []
        for f in facts:
            fid = await self.add_fact(f)
            ids.append(fid)
        return ids

    async def get_fact(self, fact_id: str) -> Optional[StreamFact]:
        return self._facts.get(fact_id)

    async def get_facts_by_type(self, fact_type: FactType) -> list[StreamFact]:
        fact_ids = self._fact_index.get(fact_type, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]

    async def get_facts_by_stream(self, stream_id: str) -> list[StreamFact]:
        fact_ids = self._stream_index.get(stream_id, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]

    async def get_facts_by_tag(self, tag: str) -> list[StreamFact]:
        fact_ids = self._tag_index.get(tag, set())
        return [self._facts[fid] for fid in fact_ids if fid in self._facts]

    # ── Search ──

    async def search(self, query: KBQuery) -> KBResult:
        """Knowledge Base'de ara."""
        start_time = time.time()
        results: list[StreamFact] = []

        # Fact type filtresi
        candidate_ids: Optional[set[str]] = None
        if query.fact_types:
            for ft in query.fact_types:
                ids = self._fact_index.get(ft, set())
                if candidate_ids is None:
                    candidate_ids = set(ids)
                else:
                    candidate_ids |= ids
        else:
            candidate_ids = set(self._facts.keys())

        # Stream filtresi
        if query.stream_id:
            stream_ids = self._stream_index.get(query.stream_id, set())
            candidate_ids &= stream_ids

        # Tag filtresi
        if query.tags:
            for tag in query.tags:
                tag_ids = self._tag_index.get(tag, set())
                candidate_ids &= tag_ids

        # Filtreleme ve arama
        for fid in candidate_ids:
            fact = self._facts.get(fid)
            if not fact:
                continue
            if fact.confidence < query.min_confidence:
                continue
            if query.time_range:
                start, end = query.time_range
                if fact.timestamp < start or fact.timestamp > end:
                    continue
            if query.text:
                text_lower = query.text.lower()
                narrative = fact.to_narrative().lower()
                if text_lower not in narrative and text_lower not in json.dumps(fact.data, ensure_ascii=False).lower():
                    continue
            results.append(fact)

        # Sıralama: timestamp'e göre
        results.sort(key=lambda f: f.timestamp)

        # Limit
        results = results[:query.limit]

        elapsed_ms = (time.time() - start_time) * 1000

        return KBResult(
            facts=results,
            total_count=len(results),
            query_time_ms=elapsed_ms,
            narrative=self._build_result_narrative(results, query),
        )

    async def search_text(self, text: str, limit: int = 20) -> list[StreamFact]:
        """Metin tabanlı basit arama."""
        query = KBQuery(text=text, limit=limit)
        result = await self.search(query)
        return result.facts

    # ── Session Operations ──

    async def add_session(self, session: StreamSession) -> str:
        self._sessions[session.stream_id] = session
        return session.stream_id

    async def get_session(self, stream_id: str) -> Optional[StreamSession]:
        return self._sessions.get(stream_id)

    async def get_all_sessions(self) -> list[StreamSession]:
        return sorted(
            self._sessions.values(),
            key=lambda s: s.started_at or "",
            reverse=True,
        )

    async def get_session_facts(self, stream_id: str) -> dict[str, list[StreamFact]]:
        """Bir yayın için tüm fact'leri kategorilere göre grupla."""
        facts = await self.get_facts_by_stream(stream_id)
        grouped: dict[str, list[StreamFact]] = defaultdict(list)
        for f in facts:
            grouped[f.fact_type.value].append(f)
        return dict(grouped)

    # ── Statistics ──

    async def get_stats(self) -> dict[str, Any]:
        """Knowledge Base istatistikleri."""
        fact_type_counts = {}
        for ft, fids in self._fact_index.items():
            fact_type_counts[ft.value] = len(fids)

        return {
            "total_facts": len(self._facts),
            "total_sessions": len(self._sessions),
            "fact_types": fact_type_counts,
            "unique_tags": len(self._tag_index),
            "unique_streams": len(self._stream_index),
        }

    async def get_stream_summary(self, stream_id: str) -> Optional[StreamSession]:
        """Bir yayın için özet oluştur."""
        session = self._sessions.get(stream_id)
        facts = await self.get_facts_by_stream(stream_id)

        if not facts:
            return session

        # Otomatik istatistikler
        participants = set()
        topics = set()
        games = set()
        highlights = []
        game_events = []
        viewer_events = []
        keywords = []

        for f in facts:
            if f.fact_type == FactType.PARTICIPANT:
                participants.add(f.data.get("name", ""))
            elif f.fact_type == FactType.TOPIC:
                topics.add(f.data.get("topic", ""))
            elif f.fact_type == FactType.GAME:
                games.add(f.data.get("game_name", ""))
            elif f.fact_type == FactType.HIGHLIGHT:
                highlights.append(f.to_narrative())
            elif f.fact_type == FactType.GAME_EVENT:
                game_events.append(f.to_narrative())
            elif f.fact_type == FactType.VIEWER_EVENT:
                viewer_events.append(f.to_narrative())
            elif f.fact_type == FactType.KEYWORD:
                keywords.append(f.data.get("word", ""))

        if session:
            session.participants = list(participants - {""})
            session.topics = list(topics - {""})
            session.games_played = list(games - {""})
            session.highlights = highlights
            session.key_events = game_events[:10]
            session.fact_count = len(facts)

        return session

    # ── Build narratives ──

    def _build_result_narrative(self, facts: list[StreamFact], query: KBQuery) -> str:
        """Sorgu sonucundan AI'a sunulacak özet üret."""
        if not facts:
            return "Sonuç bulunamadı."

        parts = [f"{len(facts)} sonuç bulundu."]

        # Kategorilere göre grupla
        by_type: dict[str, list[StreamFact]] = defaultdict(list)
        for f in facts:
            by_type[f.fact_type.value].append(f)

        for ftype, type_facts in by_type.items():
            parts.append(f"\n[{ftype.upper()}] ({len(type_facts)} adet)")
            for f in type_facts[:5]:
                parts.append(f"  • {f.to_narrative()}")
            if len(type_facts) > 5:
                parts.append(f"  ... ve {len(type_facts) - 5} tane daha")

        return "\n".join(parts)

    # ── Persistence ──

    async def save(self) -> None:
        """Knowledge Base'i JSON'a kaydet."""
        await self._state.save({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "facts": [f.model_dump() for f in self._facts.values()],
            "sessions": [s.model_dump() for s in self._sessions.values()],
        })
        logger.info(
            "Knowledge Base saved: %d facts, %d sessions",
            len(self._facts),
            len(self._sessions),
        )

    async def load(self) -> None:
        """Knowledge Base'i JSON'dan yükle."""
        state = await self._state.load()
        if not state:
            return

        for fd in state.get("facts", []):
            fact = StreamFact(**fd)
            self._facts[fact.fact_id] = fact
            self._fact_index[fact.fact_type].add(fact.fact_id)
            self._stream_index[fact.stream_id].add(fact.fact_id)
            for tag in fact.tags:
                self._tag_index[tag].add(fact.fact_id)

        for sd in state.get("sessions", []):
            session = StreamSession(**sd)
            self._sessions[session.stream_id] = session

        logger.info(
            "Knowledge Base loaded: %d facts, %d sessions",
            len(self._facts),
            len(self._sessions),
        )


# ── Ingestion: Intelligence Graph → Knowledge Base ──

class KnowledgeIngester:
    """
    Intelligence Graph'tan bilgi bankasına veri aktarımı.
    Graph node'larını StreamFact'lere dönüştürür.
    """

    def __init__(self, kb: KnowledgeBase):
        self.kb = kb

    async def ingest_from_graph(
        self,
        graph_db,
        stream_id: str,
        time_window: Optional[tuple[float, float]] = None,
    ) -> int:
        """Intelligence Graph'tan bilgi bankasına fact aktar."""
        from services.intelligence_graph.graph_models import EntityType

        # Graph'tan tüm node'ları al
        all_nodes = []
        for etype in EntityType:
            nodes = await graph_db.get_nodes_by_type(etype)
            all_nodes.extend(nodes)

        # Stream ID filtresi (stream_id metadata'dan gelir)
        if time_window:
            all_nodes = [
                n for n in all_nodes
                if time_window[0] <= n.timestamp <= time_window[1]
            ]

        facts = []
        for node in all_nodes:
            fact = self._node_to_fact(node, stream_id)
            if fact:
                facts.append(fact)

        # Session oluştur veya güncelle
        session = StreamSession(stream_id=stream_id, fact_count=len(facts))
        await self.kb.add_session(session)

        # Fact'leri ekle
        await self.kb.add_facts(facts)
        return len(facts)

    def _node_to_fact(self, node, stream_id: str) -> Optional[StreamFact]:
        """Graph node'unu StreamFact'e dönüştür."""
        from services.intelligence_graph.graph_models import EntityType

        etype = node.entity_type

        if etype == EntityType.PERSON:
            return StreamFact(
                fact_type=FactType.PARTICIPANT,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "name": node.metadata.get("username", node.label),
                    "role": node.metadata.get("role", "viewer"),
                    "description": node.label,
                },
                source="intelligence_graph",
                tags=["participant"],
            )

        if etype == EntityType.GAME_EVENT:
            event_type = node.metadata.get("event_type", node.label)
            return StreamFact(
                fact_type=FactType.GAME_EVENT,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "event_type": event_type,
                    "game": node.metadata.get("game", ""),
                    "killer": node.metadata.get("player", ""),
                    "victim": node.metadata.get("target", ""),
                    "weapon": node.metadata.get("weapon", ""),
                    "score_change": node.metadata.get("score_change", 0),
                },
                source="intelligence_graph",
                tags=["game", event_type.lower()],
            )

        if etype == EntityType.GAME_EVENT:
            return StreamFact(
                fact_type=FactType.GAME,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "game_name": node.metadata.get("game", node.label),
                    "mode": node.metadata.get("mode", ""),
                },
                source="intelligence_graph",
                tags=["game"],
            )

        if etype == EntityType.SPEECH:
            text = node.metadata.get("text", node.label)
            return StreamFact(
                fact_type=FactType.TOPIC,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "topic": text[:50],
                    "summary": text,
                    "speaker": node.metadata.get("speaker", "streamer"),
                    "language": node.metadata.get("language", "tr"),
                },
                source="intelligence_graph",
                tags=["speech", "topic"],
            )

        if etype == EntityType.EMOTION:
            return StreamFact(
                fact_type=FactType.EMOTION,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "emotion": node.metadata.get("emotion", node.label),
                    "intensity": node.metadata.get("intensity", 0),
                    "source": node.metadata.get("source", "face"),
                    "valence": node.metadata.get("valence", "neutral"),
                },
                source="intelligence_graph",
                tags=["emotion"],
            )

        if etype == EntityType.KEYWORD:
            return StreamFact(
                fact_type=FactType.KEYWORD,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "word": node.metadata.get("word", node.label),
                    "category": node.metadata.get("category", ""),
                    "frequency": node.metadata.get("frequency", 1),
                },
                source="intelligence_graph",
                tags=["keyword"],
            )

        if etype == EntityType.VIEWER:
            event_type = node.metadata.get("event_type", "viewers")
            return StreamFact(
                fact_type=FactType.VIEWER_EVENT,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "event_type": event_type,
                    "viewer_count": node.metadata.get("viewer_count", 0),
                    "delta": node.metadata.get("delta", 0),
                    "description": f"{event_type}: {node.metadata.get('viewer_count', 0)}",
                },
                source="intelligence_graph",
                tags=["viewer", event_type],
            )

        if etype == EntityType.MOMENT:
            return StreamFact(
                fact_type=FactType.HIGHLIGHT,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "title": node.label,
                    "score": node.metadata.get("viral_score", 0),
                    "reason": node.metadata.get("reason", ""),
                    "connected_nodes": node.metadata.get("connected_nodes", []),
                },
                source="intelligence_graph",
                tags=["highlight", "moment"],
            )

        if etype == EntityType.OBJECT:
            return StreamFact(
                fact_type=FactType.ITEM,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "name": node.metadata.get("object_class", node.label),
                    "description": node.label,
                    "class": node.metadata.get("object_class", ""),
                },
                source="intelligence_graph",
                tags=["object", "item"],
            )

        if etype == EntityType.SOUND:
            return StreamFact(
                fact_type=FactType.SOUND,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "sound_class": node.metadata.get("sound_class", node.label),
                    "intensity": node.metadata.get("intensity", 0),
                },
                source="intelligence_graph",
                tags=["sound"],
            )

        if etype == EntityType.CHAT:
            return StreamFact(
                fact_type=FactType.CHAT_TOPIC,
                stream_id=stream_id,
                timestamp=node.timestamp,
                confidence=node.confidence,
                data={
                    "topic": node.metadata.get("message", node.label)[:50],
                    "summary": node.metadata.get("message", node.label),
                    "username": node.metadata.get("username", ""),
                    "sentiment": node.metadata.get("sentiment", 0),
                },
                source="intelligence_graph",
                tags=["chat"],
            )

        return None


# ── Singleton ──

knowledge_base = KnowledgeBase()
knowledge_ingester = KnowledgeIngester(knowledge_base)
