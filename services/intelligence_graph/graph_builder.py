"""
Content Intelligence Graph — Builder & Ingestion Pipeline
─────────────────────────────────────────────────────────
Tüm AI sinyallerini alır, graph'a dönüştürür, otomatik bağlar,
moment'leri tespit eder ve AI'a context sunar.

Akış:
  AI Results → Entity Extractor → Graph DB → Auto-Connect → Moment Detection → Context
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from services.intelligence_graph.graph_models import (
    EntityType, EdgeType, GraphNode, GraphEdge, GraphQuery,
    GraphContext, MomentNode, GraphStats,
)
from services.intelligence_graph.graph_db import IntelligenceGraphDB, intelligence_graph
from services.intelligence_graph.entity_extractor import EntityExtractor, entity_extractor

logger = logging.getLogger("intelligence_graph")


class GraphBuilder:
    """Content Intelligence Graph — ana servis."""

    def __init__(
        self,
        graph: IntelligenceGraphDB | None = None,
        extractor: EntityExtractor | None = None,
    ):
        self._graph = graph or intelligence_graph
        self._extractor = extractor or entity_extractor
        self._ingest_lock = asyncio.Lock()
        self._auto_connect_interval = 30.0  # saniye
        self._moment_detection_window = 10.0  # saniye

    async def start(self) -> bool:
        """Graph builder'ı başlat, varsa yükle."""
        await self._graph.load()
        stats = await self._graph.get_stats()
        logger.info("Graph Builder started: %d nodes, %d edges",
                    stats.total_nodes, stats.total_edges)
        return True

    # ── Ingest: Tek anlık veri → Graph ──

    async def ingest_frame(
        self,
        timestamp: float,
        frame_index: int,
        vision_result: Optional[dict] = None,
        audio_result: Optional[dict] = None,
        chat_messages: Optional[list[dict]] = None,
        game_events: Optional[list[dict]] = None,
        viewer_count: int = 0,
        viewer_delta: int = 0,
    ) -> dict[str, Any]:
        """Tek bir zaman dilimindeki tüm sinyalleri graph'a ekle."""
        async with self._ingest_lock:
            nodes, edges = self._extractor.extract_from_all(
                timestamp=timestamp,
                vision_result=vision_result,
                audio_result=audio_result,
                chat_messages=chat_messages,
                game_events=game_events,
                viewer_count=viewer_count,
                viewer_delta=viewer_delta,
                frame_index=frame_index,
            )

            node_ids = await self._graph.add_nodes(nodes)
            edge_ids = await self._graph.add_edges(edges)

            return {
                "timestamp": timestamp,
                "nodes_added": len(node_ids),
                "edges_added": len(edge_ids),
                "node_ids": node_ids,
                "edge_ids": edge_ids,
            }

    async def ingest_batch(self, frames: list[dict[str, Any]]) -> dict[str, Any]:
        """Toplu ingestion — birden fazla frame."""
        total_nodes = 0
        total_edges = 0

        for frame_data in frames:
            result = await self.ingest_frame(**frame_data)
            total_nodes += result["nodes_added"]
            total_edges += result["edges_added"]

        return {
            "frames_processed": len(frames),
            "total_nodes_added": total_nodes,
            "total_edges_added": total_edges,
        }

    # ── Auto-Connect: Otomatik bağlantı ──

    async def auto_connect(self) -> int:
        """Graph'taki tüm node'ları zaman penceresine göre otomatik bağla."""
        edges_added = await self._graph.auto_connect(time_window=self._auto_connect_interval)
        logger.info("Auto-connect: %d new edges", edges_added)
        return edges_added

    # ── Moment Detection: Viral momentleri tespit et ──

    async def detect_moments(
        self,
        window: float = 10.0,
        min_score: float = 0.6,
    ) -> list[MomentNode]:
        """Graph'taki yoğunluklu noktaları moment olarak işaretle."""
        stats = await self._graph.get_stats()
        if stats.total_nodes < 3:
            return []

        # Tüm node'ları zamana göre sırala
        all_nodes = sorted(self._graph._nodes.values(), key=lambda n: n.timestamp)
        if not all_nodes:
            return []

        moments: list[MomentNode] = []
        processed_timestamps: set[float] = set()

        for node in all_nodes:
            # Bu timestamp'i daha önce işledik mi?
            ts_bucket = round(node.timestamp / window) * window
            if ts_bucket in processed_timestamps:
                continue

            # Pencere içindeki tüm node'ları topla
            window_nodes = [
                n for n in all_nodes
                if abs(n.timestamp - node.timestamp) <= window
            ]

            if len(window_nodes) < 3:
                continue

            # Çeşitlilik skoru — farklı entity türleri ne kadar çoksa o kadar iyi
            unique_types = set(n.entity_type for n in window_nodes)
            diversity_score = min(len(unique_types) / 6.0, 1.0)

            # Yoğunluk skoru — pencere içindeki node yoğunluğu
            density_score = min(len(window_nodes) / 15.0, 1.0)

            # Emotion intensite
            emotion_nodes = [n for n in window_nodes if n.entity_type == EntityType.EMOTION]
            emotion_score = 0.0
            if emotion_nodes:
                max_intensity = max(
                    n.metadata.get("intensity", 0) for n in emotion_nodes
                )
                emotion_score = max_intensity

            # Chat spam
            chat_nodes = [n for n in window_nodes if n.entity_type == EntityType.CHAT]
            spam_nodes = [n for n in chat_nodes if n.metadata.get("spam_count", 1) > 3]
            spam_score = min(len(spam_nodes) / 5.0, 1.0)

            # Game event significance
            game_nodes = [n for n in window_nodes if n.entity_type == EntityType.GAME_EVENT]
            game_score = 0.0
            for gn in game_nodes:
                et = gn.metadata.get("event_type", "")
                if et in ("headshot", "ace", "clutch", "kill"):
                    game_score = max(game_score, 0.9)
                elif et in ("kill", "death", "win"):
                    game_score = max(game_score, 0.6)
                else:
                    game_score = max(game_score, 0.3)

            # Sound significance
            sound_nodes = [n for n in window_nodes if n.entity_type == EntityType.SOUND]
            sound_score = 0.0
            for sn in sound_nodes:
                sc = sn.metadata.get("sound_class", "")
                if sc in ("scream", "cheer"):
                    sound_score = max(sound_score, 0.8)
                elif sc in ("laugh", "clap"):
                    sound_score = max(sound_score, 0.5)

            # Toplam viral skor
            viral_score = (
                diversity_score * 0.25 +
                density_score * 0.20 +
                emotion_score * 0.20 +
                spam_score * 0.15 +
                game_score * 0.10 +
                sound_score * 0.10
            )

            if viral_score >= min_score:
                # Reason oluştur
                reasons = []
                if diversity_score > 0.5:
                    reasons.append(f"high diversity ({len(unique_types)} types)")
                if density_score > 0.5:
                    reasons.append(f"dense ({len(window_nodes)} events)")
                if emotion_score > 0.6:
                    reasons.append(f"strong emotion ({emotion_score:.1f})")
                if spam_score > 0.3:
                    reasons.append(f"chat spam ({len(spam_nodes)} messages)")
                if game_score > 0.5:
                    reasons.append(f"game event ({[gn.metadata.get('event_type') for gn in game_nodes]})")
                if sound_score > 0.5:
                    reasons.append(f"sound spike ({[sn.metadata.get('sound_class') for sn in sound_nodes]})")

                connected_ids = [n.id for n in window_nodes]

                moment = MomentNode(
                    label=f"Moment at {int(node.timestamp // 60):02d}:{int(node.timestamp % 60):02d}",
                    timestamp=node.timestamp,
                    viral_score=viral_score,
                    reason=" | ".join(reasons),
                    connected_nodes=connected_ids,
                    confidence=viral_score,
                    metadata={
                        "viral_score": viral_score,
                        "reason": " | ".join(reasons),
                        "node_count": len(window_nodes),
                        "type_count": len(unique_types),
                        "window": window,
                    },
                )
                moments.append(moment)
                processed_timestamps.add(ts_bucket)

        # Moment'leri graph'a ekle
        moment_nodes = await self._graph.add_nodes(moments)

        # Moment → connected node edge'leri
        for moment in moments:
            for connected_id in moment.connected_nodes:
                edge = GraphEdge(
                    source_id=moment.id,
                    target_id=connected_id,
                    edge_type=EdgeType.PART_OF,
                    weight=moment.viral_score,
                    confidence=moment.confidence,
                )
                await self._graph.add_edge(edge)

        logger.info("Detected %d moments from graph", len(moments))
        return moments

    # ── Context Builder: AI'a sunum ──

    async def get_context_for_moment(
        self, moment_id: str, window: float = 15.0
    ) -> GraphContext:
        """Bir moment için tam context oluştur (AI'a sunulacak)."""
        return await self._graph.build_moment_context(moment_id, window)

    async def get_context_for_timestamp(
        self, timestamp: float, window: float = 10.0
    ) -> GraphContext:
        """Belirli bir zamandaki bağlamı getir."""
        nodes = await self._graph.get_nodes_in_time_range(
            timestamp - window, timestamp + window
        )
        if not nodes:
            return GraphContext(moment_id="", timestamp=timestamp)

        # En yüksek skorlu moment'i bul veya oluştur
        moment_nodes = [n for n in nodes if n.entity_type == EntityType.MOMENT]
        if moment_nodes:
            best = max(moment_nodes, key=lambda n: n.metadata.get("viral_score", 0))
            return await self.get_context_for_moment(best.id, window)

        # Moment yoksa kendimiz oluştur
        return GraphContext(
            moment_id=f"ts_{int(timestamp)}",
            timestamp=timestamp,
            nodes=nodes,
            narrative=f"Events at {int(timestamp // 60):02d}:{int(timestamp % 60):02d}",
            connected_signals=[n.entity_type.value for n in nodes],
        )

    async def build_clip_context(
        self,
        clip_start: float,
        clip_end: float,
    ) -> dict[str, Any]:
        """Bir klip için tam context paketi oluştur."""
        nodes = await self._graph.get_nodes_in_time_range(clip_start, clip_end)
        if not nodes:
            return {"error": "No data in time range"}

        # Node türlerine göre grupla
        by_type: dict[str, list] = {}
        for node in nodes:
            t = node.entity_type.value
            if t not in by_type:
                by_type[t] = []
            by_type[t].append({
                "id": node.id,
                "label": node.label,
                "timestamp": node.timestamp,
                "metadata": node.metadata,
            })

        # Narrative oluştur
        narrative_parts = []
        if "speech" in by_type:
            texts = [n["metadata"].get("text", n["label"]) for n in by_type["speech"][:3]]
            narrative_parts.append(f"Speech: {' | '.join(texts)}")
        if "game_event" in by_type:
            events = [n["metadata"].get("event_type", "") for n in by_type["game_event"]]
            narrative_parts.append(f"Game: {', '.join(events)}")
        if "emotion" in by_type:
            emotions = [n["metadata"].get("emotion", "") for n in by_type["emotion"][:3]]
            narrative_parts.append(f"Emotion: {', '.join(emotions)}")
        if "chat" in by_type:
            msgs = [n["metadata"].get("message", "") for n in by_type["chat"][:3]]
            narrative_parts.append(f"Chat: {' | '.join(msgs)}")

        # LLM prompt için context string
        context_for_llm = "\n".join([
            f"[{t.upper()}] " + " | ".join(
                n["label"] for n in nodes_of_type[:5]
            )
            for t, nodes_of_type in by_type.items()
        ])

        return {
            "time_range": {"start": clip_start, "end": clip_end},
            "total_nodes": len(nodes),
            "types": by_type.keys(),
            "nodes_by_type": by_type,
            "narrative": " | ".join(narrative_parts),
            "context_for_llm": context_for_llm,
            "connected_signals": list(by_type.keys()),
        }

    # ── Stats ──

    async def get_stats(self) -> GraphStats:
        return await self._graph.get_stats()

    async def get_status(self) -> dict[str, Any]:
        stats = await self._graph.get_stats()
        return {
            "running": True,
            "stats": stats.model_dump(),
            "state_file": str(self._graph._state._path),
        }


# Singleton
graph_builder = GraphBuilder()
