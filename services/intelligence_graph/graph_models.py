"""
Content Intelligence Graph — Veri Modelleri
────────────────────────────────────────────
Her şey birbirine bağlı:

Video → Frame → Object → Speech → Emotion → Movement → Chat → Viewer → Game Event → Knowledge Graph

Her node bir entity, her edge bir relationship.
AI graph'ı traverse ederek "tek olay" olduğunu anlar.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── Entity Types ──

class EntityType(str, Enum):
    VIDEO = "video"
    FRAME = "frame"
    OBJECT = "object"
    SPEECH = "speech"
    EMOTION = "emotion"
    MOVEMENT = "movement"
    CHAT = "chat"
    VIEWER = "viewer"
    GAME_EVENT = "game_event"
    SOUND = "sound"
    SCENE = "scene"
    KEYWORD = "keyword"
    MOMENT = "moment"
    CLIP = "clip"
    PERSON = "person"


class EdgeType(str, Enum):
    # Temporal
    FOLLOWS = "follows"
    COINCIDES = "coincides"
    PRECEDES = "precedes"
    # Causal
    CAUSES = "causes"
    TRIGGERS = "triggers"
    AMPLIFIES = "amplifies"
    # Spatial
    CONTAINS = "contains"
    LOCATED_IN = "located_in"
    # Semantic
    SIMILAR_TO = "similar_to"
    PART_OF = "part_of"
    DESCRIBES = "describes"
    # Interaction
    RESPONDS_TO = "responds_to"
    REINFORCES = "reinforces"
    # Game
    KILLED_BY = "killed_by"
    USED_BY = "used_by"
    ACHIEVES = "achieves"


class EmotionalValence(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    MIXED = "mixed"


# ── Node Models ──

class GraphNode(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    entity_type: EntityType
    label: str
    timestamp: float = 0.0  # seconds into stream/video
    duration: float = 0.0
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    embedding: Optional[list[float]] = None  # for similarity search
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_context_string(self) -> str:
        """AI'ın anlayacağı string format."""
        parts = [f"[{self.entity_type.value}] {self.label}"]
        if self.metadata:
            key_attrs = {k: v for k, v in self.metadata.items()
                        if k in ("text", "emotion", "action", "viewer_count", "spam_rate",
                                 "category", "weapon", "player", "score", "count",
                                 "intensity", "direction", "speed", "word", "sentiment")}
            if key_attrs:
                parts.append(str(key_attrs))
        return " | ".join(parts)


class FrameNode(GraphNode):
    entity_type: EntityType = EntityType.FRAME
    frame_index: int = 0
    resolution: tuple[int, int] = (1920, 1080)


class ObjectNode(GraphNode):
    entity_type: EntityType = EntityType.OBJECT
    object_class: str = ""
    bbox: Optional[tuple[int, int, int, int]] = None
    tracking_id: Optional[int] = None


class SpeechNode(GraphNode):
    entity_type: EntityType = EntityType.SPEECH
    text: str = ""
    speaker: str = "streamer"
    language: str = "tr"
    word_timestamps: list[dict[str, Any]] = Field(default_factory=list)


class EmotionNode(GraphNode):
    entity_type: EntityType = EntityType.EMOTION
    emotion: str = "neutral"
    valence: EmotionalValence = EmotionalValence.NEUTRAL
    intensity: float = 0.5
    source: str = "face"  # face, voice, chat


class MovementNode(GraphNode):
    entity_type: EntityType = EntityType.MOVEMENT
    action: str = ""
    direction: str = ""
    speed: float = 0.0
    body_parts: list[str] = Field(default_factory=list)


class ChatNode(GraphNode):
    entity_type: EntityType = EntityType.CHAT
    message: str = ""
    username: str = ""
    sentiment: float = 0.0
    is_emote: bool = False
    spam_count: int = 0


class ViewerNode(GraphNode):
    entity_type: EntityType = EntityType.VIEWER
    viewer_count: int = 0
    delta: int = 0  # change from previous
    event_type: str = "viewers"  # follow, sub, donation, raid


class GameEventNode(GraphNode):
    entity_type: EntityType = EntityType.GAME_EVENT
    event_type: str = ""  # kill, headshot, win, death, etc.
    game: str = "valorant"
    player: str = ""
    weapon: str = ""
    target: str = ""
    score_change: int = 0


class SoundNode(GraphNode):
    entity_type: EntityType = EntityType.SOUND
    sound_class: str = ""  # scream, laugh, clap, gunshot, music
    intensity: float = 0.0
    frequency: float = 0.0


class SceneNode(GraphNode):
    entity_type: EntityType = EntityType.SCENE
    scene_type: str = ""  # gameplay, facecam, transition, ad
    transition_type: str = ""


class KeywordNode(GraphNode):
    entity_type: EntityType = EntityType.KEYWORD
    word: str = ""
    category: str = ""  # game, emotion, action, reaction
    frequency: int = 0


class MomentNode(GraphNode):
    """Bir clip veya highlight anı — tüm entity'leri bir araya getirir."""
    entity_type: EntityType = EntityType.MOMENT
    viral_score: float = 0.0
    reason: str = ""
    connected_nodes: list[str] = Field(default_factory=list)  # node IDs


class ClipNode(GraphNode):
    entity_type: EntityType = EntityType.CLIP
    clip_path: str = ""
    thumbnail_path: str = ""
    platform_scores: dict[str, float] = Field(default_factory=dict)


class PersonNode(GraphNode):
    entity_type: EntityType = EntityType.PERSON
    role: str = "streamer"  # streamer, player, viewer
    username: str = ""


# ── Edge Model ──

class GraphEdge(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    source_id: str
    target_id: str
    edge_type: EdgeType
    weight: float = 1.0
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Graph Query Models ──

class GraphQuery(BaseModel):
    """Graph traversal sorgusu."""
    start_node_id: Optional[str] = None
    entity_types: list[EntityType] = Field(default_factory=list)
    edge_types: list[EdgeType] = Field(default_factory=list)
    max_depth: int = 3
    min_confidence: float = 0.5
    time_window: Optional[tuple[float, float]] = None  # (start, end) seconds
    limit: int = 50


class GraphContext(BaseModel):
    """AI'a sunulacak graph context'i."""
    moment_id: str
    timestamp: float
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    narrative: str = ""  # AI'ın anlayacağı hikaye
    viral_score: float = 0.0
    connected_signals: list[str] = Field(default_factory=list)


class GraphStats(BaseModel):
    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_type: dict[str, int] = Field(default_factory=dict)
    edges_by_type: dict[str, int] = Field(default_factory=dict)
    avg_confidence: float = 0.0
    time_span: float = 0.0  # seconds
    density: float = 0.0  # edges / possible edges
