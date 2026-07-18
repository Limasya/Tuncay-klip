"""
Content Intelligence Graph — Graph Database
────────────────────────────────────────────
Memory-based graph DB with JSON persistence.
Her şey birbirine bağlı, AI graph'ı traverse ederek bağlamı anlar.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from services.intelligence_graph.graph_models import (
    EntityType, EdgeType, GraphNode, GraphEdge, GraphQuery, GraphContext,
    GraphStats, FrameNode, ObjectNode, SpeechNode, EmotionNode, MovementNode,
    ChatNode, ViewerNode, GameEventNode, SoundNode, SceneNode, KeywordNode,
    MomentNode, ClipNode, PersonNode,
)

logger = logging.getLogger("intelligence_graph")


class IntelligenceGraphDB:
    """Content Intelligence Graph — in-memory graph database."""

    def __init__(self, state_path: str | Path | None = None):
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._node_index: dict[EntityType, set[str]] = defaultdict(set)
        self._edge_index: dict[EdgeType, set[str]] = defaultdict(set)
        self._adjacency: dict[str, set[str]] = defaultdict(set)  # node_id -> edge_ids
        self._reverse_adjacency: dict[str, set[str]] = defaultdict(set)
        self._state_path = Path(state_path or "data/intelligence_graph_state.json")
        self._lock = asyncio.Lock()

    # ── Node Operations ──

    async def add_node(self, node: GraphNode) -> str:
        """Graph'a node ekle."""
        async with self._lock:
            self._nodes[node.id] = node
            self._node_index[node.entity_type].add(node.id)
            return node.id

    async def add_nodes(self, nodes: list[GraphNode]) -> list[str]:
        """Toplu node ekle."""
        ids = []
        for node in nodes:
            nid = await self.add_node(node)
            ids.append(nid)
        return ids

    async def get_node(self, node_id: str) -> Optional[GraphNode]:
        """Node getir."""
        return self._nodes.get(node_id)

    async def get_nodes_by_type(self, entity_type: EntityType) -> list[GraphNode]:
        """Ttürüne göre node'ları getir."""
        node_ids = self._node_index.get(entity_type, set())
        return [self._nodes[nid] for nid in node_ids if nid in self._nodes]

    async def get_nodes_in_time_range(
        self, start: float, end: float, entity_types: Optional[list[EntityType]] = None
    ) -> list[GraphNode]:
        """Zaman aralığındaki node'ları getir."""
        results = []
        for node in self._nodes.values():
            if node.timestamp < start or node.timestamp > end:
                continue
            if entity_types and node.entity_type not in entity_types:
                continue
            results.append(node)
        return sorted(results, key=lambda n: n.timestamp)

    async def search_nodes(self, query: str, limit: int = 20) -> list[GraphNode]:
        """Node'larda metin ara."""
        query_lower = query.lower()
        results = []
        for node in self._nodes.values():
            score = 0.0
            if query_lower in node.label.lower():
                score += 3.0
            if query_lower in str(node.metadata).lower():
                score += 2.0
            # Speech-specific
            if hasattr(node, 'text') and query_lower in getattr(node, 'text', '').lower():
                score += 4.0
            if hasattr(node, 'message') and query_lower in getattr(node, 'message', '').lower():
                score += 3.0
            if hasattr(node, 'word') and query_lower in getattr(node, 'word', '').lower():
                score += 4.0
            if score > 0:
                results.append((score, node))
        results.sort(key=lambda x: x[0], reverse=True)
        return [node for _, node in results[:limit]]

    # ── Edge Operations ──

    async def add_edge(self, edge: GraphEdge) -> str:
        """Graph'a edge ekle."""
        async with self._lock:
            if edge.source_id not in self._nodes or edge.target_id not in self._nodes:
                logger.warning("Edge references non-existent node: %s -> %s",
                             edge.source_id, edge.target_id)
                return ""
            self._edges[edge.id] = edge
            self._edge_index[edge.edge_type].add(edge.id)
            self._adjacency[edge.source_id].add(edge.id)
            self._reverse_adjacency[edge.target_id].add(edge.id)
            return edge.id

    async def add_edges(self, edges: list[GraphEdge]) -> list[str]:
        """Toplu edge ekle."""
        ids = []
        for edge in edges:
            eid = await self.add_edge(edge)
            if eid:
                ids.append(eid)
        return ids

    async def get_edges_from(self, node_id: str, edge_type: Optional[EdgeType] = None) -> list[GraphEdge]:
        """Bir node'dan çıkan edge'leri getir."""
        edge_ids = self._adjacency.get(node_id, set())
        edges = [self._edges[eid] for eid in edge_ids if eid in self._edges]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    async def get_edges_to(self, node_id: str, edge_type: Optional[EdgeType] = None) -> list[GraphEdge]:
        """Bir node'a giren edge'leri getir."""
        edge_ids = self._reverse_adjacency.get(node_id, set())
        edges = [self._edges[eid] for eid in edge_ids if eid in self._edges]
        if edge_type:
            edges = [e for e in edges if e.edge_type == edge_type]
        return edges

    async def get_neighbors(self, node_id: str, depth: int = 1) -> list[GraphNode]:
        """Komşu node'ları getir (BFS)."""
        visited = {node_id}
        current_level = [node_id]
        neighbors = []

        for _ in range(depth):
            next_level = []
            for nid in current_level:
                # Outgoing
                for edge in await self.get_edges_from(nid):
                    if edge.target_id not in visited:
                        visited.add(edge.target_id)
                        next_level.append(edge.target_id)
                        if edge.target_id in self._nodes:
                            neighbors.append(self._nodes[edge.target_id])
                # Incoming
                for edge in await self.get_edges_to(nid):
                    if edge.source_id not in visited:
                        visited.add(edge.source_id)
                        next_level.append(edge.source_id)
                        if edge.source_id in self._nodes:
                            neighbors.append(self._nodes[edge.source_id])
            current_level = next_level

        return neighbors

    # ── Graph Traversal ──

    async def traverse(self, query: GraphQuery) -> list[GraphNode]:
        """Graph'ı traverse et."""
        if not query.start_node_id:
            # Time-based traversal
            return await self.get_nodes_in_time_range(
                query.time_window[0] if query.time_window else 0,
                query.time_window[1] if query.time_window else float('inf'),
                query.entity_types or None,
            )

        start = self._nodes.get(query.start_node_id)
        if not start:
            return []

        visited = {query.start_node_id}
        result_nodes = [start]
        current_level = [query.start_node_id]

        for depth in range(query.max_depth):
            next_level = []
            for nid in current_level:
                for edge in await self.get_edges_from(nid):
                    target = self._nodes.get(edge.target_id)
                    if not target or edge.target_id in visited:
                        continue
                    if edge.confidence < query.min_confidence:
                        continue
                    if query.entity_types and target.entity_type not in query.entity_types:
                        continue
                    if query.edge_types and edge.edge_type not in query.edge_types:
                        continue
                    visited.add(edge.target_id)
                    next_level.append(edge.target_id)
                    result_nodes.append(target)

                for edge in await self.get_edges_to(nid):
                    source = self._nodes.get(edge.source_id)
                    if not source or edge.source_id in visited:
                        continue
                    if edge.confidence < query.min_confidence:
                        continue
                    if query.entity_types and source.entity_type not in query.entity_types:
                        continue
                    if query.edge_types and edge.edge_type not in query.edge_types:
                        continue
                    visited.add(edge.source_id)
                    next_level.append(edge.source_id)
                    result_nodes.append(source)

            current_level = next_level

        return result_nodes[:query.limit]

    async def find_causal_chain(
        self, moment_id: str, max_depth: int = 5
    ) -> list[tuple[GraphNode, GraphEdge]]:
        """Bir moment'ten geriye doğru nedensel zinciri bul."""
        chain = []
        visited = {moment_id}
        current = moment_id

        causal_edges = {EdgeType.CAUSES, EdgeType.TRIGGERS, EdgeType.AMPLIFIES, EdgeType.RESPONDS_TO}

        for _ in range(max_depth):
            # Incoming causal edges
            for edge in await self.get_edges_to(current):
                if edge.edge_type not in causal_edges:
                    continue
                if edge.source_id in visited:
                    continue
                source = self._nodes.get(edge.source_id)
                if not source:
                    continue
                visited.add(edge.source_id)
                chain.append((source, edge))
                current = edge.source_id
                break

        return chain

    async def find_coincident_events(
        self, timestamp: float, window: float = 5.0
    ) -> list[GraphNode]:
        """Belirli bir zamana denk gelen olayları bul."""
        return await self.get_nodes_in_time_range(
            timestamp - window, timestamp + window
        )

    async def build_moment_context(
        self, moment_id: str, window: float = 10.0
    ) -> GraphContext:
        """Bir moment için tam bağlam oluştur (AI'a sunulacak)."""
        moment = self._nodes.get(moment_id)
        if not moment:
            return GraphContext(moment_id=moment_id, timestamp=0)

        # Zaman penceresindeki tüm node'ları bul
        nearby = await self.find_coincident_events(moment.timestamp, window)

        # Causal chain'i bul
        chain = await self.find_causal_chain(moment_id)

        # Tüm ilgili node'ları topla
        all_node_ids = {moment_id}
        all_nodes = [moment]
        all_edges = []

        for node in nearby:
            if node.id not in all_node_ids:
                all_node_ids.add(node.id)
                all_nodes.append(node)

        for node, edge in chain:
            if node.id not in all_node_ids:
                all_node_ids.add(node.id)
                all_nodes.append(node)
            all_edges.append(edge)

        # İlgili edge'leri bul
        for node in all_nodes:
            for edge in await self.get_edges_from(node.id):
                if edge.target_id in all_node_ids:
                    all_edges.append(edge)
            for edge in await self.get_edges_to(node.id):
                if edge.source_id in all_node_ids:
                    all_edges.append(edge)

        # Narrative oluştur
        narrative = self._build_narrative(all_nodes, all_edges, moment)

        return GraphContext(
            moment_id=moment_id,
            timestamp=moment.timestamp,
            nodes=all_nodes,
            edges=all_edges,
            narrative=narrative,
            viral_score=moment.metadata.get("viral_score", 0),
            connected_signals=[n.entity_type.value for n in all_nodes],
        )

    def _build_narrative(
        self, nodes: list[GraphNode], edges: list[GraphEdge], moment: GraphNode
    ) -> str:
        """Node ve edge'lerden anlamlı hikaye üret."""
        parts = []

        # Zaman bilgisi
        ts = moment.timestamp
        mins = int(ts // 60)
        secs = int(ts % 60)
        parts.append(f"Moment at {mins:02d}:{secs:02d}")

        # Entity'leri grupla
        by_type: dict[EntityType, list[GraphNode]] = defaultdict(list)
        for n in nodes:
            if n.id != moment.id:
                by_type[n.entity_type].append(n)

        if EntityType.OBJECT in by_type:
            objects = by_type[EntityType.OBJECT]
            obj_names = [o.label for o in objects[:5]]
            parts.append(f"Objects: {', '.join(obj_names)}")

        if EntityType.SPEECH in by_type:
            speeches = by_type[EntityType.SPEECH]
            texts = [s.metadata.get('text', s.label) for s in speeches[:3]]
            parts.append(f"Speech: {' | '.join(texts)}")

        if EntityType.EMOTION in by_type:
            emotions = by_type[EntityType.EMOTION]
            emo_list = [f"{e.metadata.get('emotion', 'neutral')}({e.metadata.get('intensity', 0):.1f})"
                       for e in emotions[:3]]
            parts.append(f"Emotions: {', '.join(emo_list)}")

        if EntityType.GAME_EVENT in by_type:
            events = by_type[EntityType.GAME_EVENT]
            event_strs = [e.metadata.get('event_type', e.label) for e in events[:3]]
            parts.append(f"Game Events: {', '.join(event_strs)}")

        if EntityType.CHAT in by_type:
            chats = by_type[EntityType.CHAT]
            chat_texts = [c.metadata.get('message', c.label) for c in chats[:3]]
            parts.append(f"Chat: {' | '.join(chat_texts)}")

        if EntityType.VIEWER in by_type:
            viewers = by_type[EntityType.VIEWER]
            for v in viewers[:1]:
                parts.append(f"Viewers: {v.metadata.get('viewer_count', 0)} "
                           f"(delta: {v.metadata.get('delta', 0)})")

        if EntityType.SOUND in by_type:
            sounds = by_type[EntityType.SOUND]
            sound_strs = [s.metadata.get('sound_class', s.label) for s in sounds[:3]]
            parts.append(f"Sounds: {', '.join(sound_strs)}")

        return " | ".join(parts)

    # ── Auto-connect: Entity'ler arası otomatik bağlantı ──

    async def auto_connect(self, time_window: float = 5.0) -> int:
        """Zaman penceresindeki benzer entity'leri otomatik bağla."""
        edges_added = 0
        all_nodes = sorted(self._nodes.values(), key=lambda n: n.timestamp)

        for i, node_a in enumerate(all_nodes):
            # Zaman penceresindeki node'ları bul
            window_nodes = [
                n for n in all_nodes
                if n.id != node_a.id
                and abs(n.timestamp - node_a.timestamp) <= time_window
            ]

            for node_b in window_nodes:
                # Coincides edge
                edge = GraphEdge(
                    source_id=node_a.id,
                    target_id=node_b.id,
                    edge_type=EdgeType.COINCIDES,
                    weight=1.0 / (1.0 + abs(node_a.timestamp - node_b.timestamp)),
                    confidence=0.8,
                )
                eid = await self.add_edge(edge)
                if eid:
                    edges_added += 1

                # Semantic connections
                if node_a.entity_type == EntityType.OBJECT and node_b.entity_type == EntityType.GAME_EVENT:
                    edge = GraphEdge(
                        source_id=node_a.id,
                        target_id=node_b.id,
                        edge_type=EdgeType.USED_BY,
                        weight=0.9,
                        confidence=0.7,
                    )
                    await self.add_edge(edge)
                    edges_added += 1

                if node_a.entity_type == EntityType.GAME_EVENT and node_b.entity_type == EntityType.EMOTION:
                    edge = GraphEdge(
                        source_id=node_a.id,
                        target_id=node_b.id,
                        edge_type=EdgeType.TRIGGERS,
                        weight=0.85,
                        confidence=0.75,
                    )
                    await self.add_edge(edge)
                    edges_added += 1

                if node_a.entity_type == EntityType.EMOTION and node_b.entity_type == EntityType.CHAT:
                    edge = GraphEdge(
                        source_id=node_a.id,
                        target_id=node_b.id,
                        edge_type=EdgeType.RESPONDS_TO,
                        weight=0.7,
                        confidence=0.65,
                    )
                    await self.add_edge(edge)
                    edges_added += 1

                if node_a.entity_type == EntityType.CHAT and node_b.entity_type == EntityType.CHAT:
                    if node_a.metadata.get('sentiment', 0) * node_b.metadata.get('sentiment', 0) > 0:
                        edge = GraphEdge(
                            source_id=node_a.id,
                            target_id=node_b.id,
                            edge_type=EdgeType.REINFORCES,
                            weight=0.6,
                            confidence=0.6,
                        )
                        await self.add_edge(edge)
                        edges_added += 1

                if node_a.entity_type == EntityType.VIEWER and node_b.entity_type == EntityType.VIEWER:
                    edge = GraphEdge(
                        source_id=node_a.id,
                        target_id=node_b.id,
                        edge_type=EdgeType.FOLLOWS,
                        weight=0.5,
                        confidence=0.7,
                    )
                    await self.add_edge(edge)
                    edges_added += 1

                if node_a.entity_type == EntityType.SOUND and node_b.entity_type == EntityType.EMOTION:
                    edge = GraphEdge(
                        source_id=node_a.id,
                        target_id=node_b.id,
                        edge_type=EdgeType.AMPLIFIES,
                        weight=0.75,
                        confidence=0.7,
                    )
                    await self.add_edge(edge)
                    edges_added += 1

        return edges_added

    # ── Stats ──

    async def get_stats(self) -> GraphStats:
        """Graph istatistiklerini getir."""
        nodes_by_type: dict[str, int] = defaultdict(int)
        for node in self._nodes.values():
            nodes_by_type[node.entity_type.value] += 1

        edges_by_type: dict[str, int] = defaultdict(int)
        for edge in self._edges.values():
            edges_by_type[edge.edge_type.value] += 1

        avg_conf = 0.0
        if self._edges:
            avg_conf = sum(e.confidence for e in self._edges.values()) / len(self._edges)

        timestamps = [n.timestamp for n in self._nodes.values() if n.timestamp > 0]
        time_span = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0

        n = len(self._nodes)
        possible_edges = n * (n - 1) if n > 1 else 1

        return GraphStats(
            total_nodes=n,
            total_edges=len(self._edges),
            nodes_by_type=dict(nodes_by_type),
            edges_by_type=dict(edges_by_type),
            avg_confidence=avg_conf,
            time_span=time_span,
            density=len(self._edges) / possible_edges if possible_edges > 0 else 0,
        )

    # ── Persistence ──

    async def save(self) -> None:
        """Graph'ı JSON'a kaydet."""
        state = {
            "channel": "thetuncay",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [n.model_dump() for n in self._nodes.values()],
            "edges": [e.model_dump() for e in self._edges.values()],
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._state_path.with_suffix(".tmp")
        await asyncio.to_thread(
            temp.write_text,
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            "utf-8",
        )
        await asyncio.to_thread(temp.replace, self._state_path)
        logger.info("Graph saved: %d nodes, %d edges", len(self._nodes), len(self._edges))

    async def load(self) -> None:
        """Graph'ı JSON'dan yükle."""
        if not self._state_path.exists():
            return
        try:
            data = await asyncio.to_thread(self._state_path.read_text, encoding="utf-8")
            state = json.loads(data)

            for nd in state.get("nodes", []):
                node = self._node_from_dict(nd)
                if node:
                    self._nodes[node.id] = node
                    self._node_index[node.entity_type].add(node.id)

            for ed in state.get("edges", []):
                edge = GraphEdge(**ed)
                if edge.source_id in self._nodes and edge.target_id in self._nodes:
                    self._edges[edge.id] = edge
                    self._edge_index[edge.edge_type].add(edge.id)
                    self._adjacency[edge.source_id].add(edge.id)
                    self._reverse_adjacency[edge.target_id].add(edge.id)

            logger.info("Graph loaded: %d nodes, %d edges",
                       len(self._nodes), len(self._edges))
        except Exception as e:
            logger.warning("Graph load failed: %s", e)

    def _node_from_dict(self, d: dict) -> Optional[GraphNode]:
        """Dict'ten uygun node tipine dönüştür."""
        etype = d.get("entity_type")
        cls_map = {
            "frame": FrameNode, "object": ObjectNode, "speech": SpeechNode,
            "emotion": EmotionNode, "movement": MovementNode, "chat": ChatNode,
            "viewer": ViewerNode, "game_event": GameEventNode, "sound": SoundNode,
            "scene": SceneNode, "keyword": KeywordNode, "moment": MomentNode,
            "clip": ClipNode, "person": PersonNode, "video": GraphNode,
        }
        cls = cls_map.get(etype, GraphNode)
        try:
            return cls(**d)
        except Exception as e:
            logger.debug("Graph node deserialization failed for type=%s: %s", etype, e)
            return None


# Singleton
intelligence_graph = IntelligenceGraphDB()
