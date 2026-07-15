"""
Shared event schemas — the contract between all microservices.
Every event flowing through the system is defined here.
"""
from __future__ import annotations
import time
import uuid
from datetime import datetime
from enum import Enum
from typing import ClassVar, Optional
from pydantic import BaseModel, Field


def _uuid7() -> str:
    """Generate a time-sortable UUID."""
    return uuid.uuid4().hex


# ─── Event Types ──────────────────────────────────────────────

class EventType(str, Enum):
    # Stream lifecycle
    STREAM_STARTED = "stream.started"
    STREAM_ENDED = "stream.ended"
    STREAM_ERROR = "stream.error"

    # Frame events
    FRAME_EXTRACTED = "frame.extracted"

    # Video analysis events
    FACE_DETECTED = "analysis.face_detected"
    EMOTION_DETECTED = "analysis.emotion_detected"
    POSE_DETECTED = "analysis.pose_detected"
    OBJECT_DETECTED = "analysis.object_detected"
    TEXT_DETECTED = "analysis.text_detected"

    # Audio events
    AUDIO_FEATURES = "audio.features"
    AUDIO_SPIKE = "audio.spike"
    VAD_DETECTED = "audio.vad_detected"
    TRANSCRIPT_READY = "audio.transcript_ready"
    SPEECH_EMOTION = "audio.speech_emotion"

    # Chat events
    CHAT_MESSAGE = "chat.message"
    CHAT_SENTIMENT = "chat.sentiment"
    CHAT_TOXICITY = "chat.toxicity"
    CHAT_SPIKE = "chat.spike"

    # Viewer events
    VIEWER_COUNT = "viewer.count"

    # Decision events
    EVENT_SCORED = "decision.event_scored"
    CLIP_CANDIDATE = "decision.clip_candidate"
    CLIP_REJECTED = "decision.clip_rejected"

    # Clip lifecycle
    CLIP_CREATED = "clip.created"
    CLIP_CLASSIFIED = "clip.classified"
    SUBTITLE_READY = "clip.subtitle_ready"
    EDIT_READY = "clip.edit_ready"
    THUMBNAIL_READY = "clip.thumbnail_ready"
    AI_METADATA_READY = "clip.ai_metadata_ready"
    CLIP_PUBLISHED = "clip.published"

    # Viewer / donation events
    DONATION_RECEIVED = "viewer.donation"


# ─── Base Event ───────────────────────────────────────────────

class SystemEvent(BaseModel):
    """Base event flowing through the system."""
    event_id: str = Field(default_factory=_uuid7)
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_service: str = ""
    stream_id: str = ""
    correlation_id: str = ""
    causation_id: Optional[str] = None
    payload: dict = Field(default_factory=dict)

    def age_seconds(self) -> float:
        return (datetime.utcnow() - self.timestamp).total_seconds()


# ─── Video Analysis Results ──────────────────────────────────

class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2)


class FaceDetection(BaseModel):
    face_id: str = Field(default_factory=_uuid7)
    bbox: BoundingBox
    confidence: float
    landmarks: Optional[dict] = None


class EmotionResult(BaseModel):
    face_id: str
    label: str  # angry, disgust, fear, happy, sad, surprise, neutral
    confidence: float
    scores: dict[str, float] = Field(default_factory=dict)

    HIGHLIGHT_EMOTIONS: ClassVar[set] = {"happy", "surprise", "fear", "angry"}

    def is_highlight_emotion(self) -> bool:
        return self.label in self.HIGHLIGHT_EMOTIONS


class PoseKeypoints(BaseModel):
    keypoints: dict[str, tuple[float, float]] = Field(default_factory=dict)
    gestures: list[str] = Field(default_factory=list)
    gesture_scores: dict[str, float] = Field(default_factory=dict)
    motion_score: float = 0.0


class ObjectDetection(BaseModel):
    class_name: str
    confidence: float
    bbox: BoundingBox


class OCRResult(BaseModel):
    text: str
    bbox: list[list[float]] = Field(default_factory=list)
    confidence: float = 0.0
    is_highlight_keyword: bool = False


class FrameAnalysisResult(BaseModel):
    """Complete analysis result for a single frame."""
    frame_id: str
    timestamp: datetime
    stream_time_seconds: float = 0.0
    faces: list[FaceDetection] = Field(default_factory=list)
    emotions: list[EmotionResult] = Field(default_factory=list)
    poses: list[PoseKeypoints] = Field(default_factory=list)
    objects: list[ObjectDetection] = Field(default_factory=list)
    texts: list[OCRResult] = Field(default_factory=list)
    inference_time_ms: float = 0.0


# ─── Audio Analysis Results ──────────────────────────────────

class AudioFeatures(BaseModel):
    chunk_id: str = Field(default_factory=_uuid7)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    rms_energy: float = 0.0
    zero_crossing_rate: float = 0.0
    spectral_centroid: float = 0.0
    spectral_rolloff: float = 0.0
    mfcc: list[float] = Field(default_factory=list)
    is_speech: bool = False
    speech_probability: float = 0.0
    is_spike: bool = False
    spike_magnitude: float = 0.0


class AudioSpikeEvent(BaseModel):
    start_time: float
    end_time: float
    duration: float
    peak_magnitude: float
    avg_energy: float
    chunk_count: int = 0


class TranscriptResult(BaseModel):
    text: str
    language: str = ""
    language_probability: float = 0.0
    words: list[dict] = Field(default_factory=list)
    duration: float = 0.0


class SpeechEmotionResult(BaseModel):
    label: str
    confidence: float
    scores: dict[str, float] = Field(default_factory=dict)


# ─── Chat Analysis Results ────────────────────────────────────

class SentimentResult(BaseModel):
    label: str  # POSITIVE, NEGATIVE, NEUTRAL
    score: float  # -1.0 to +1.0
    confidence: float = 0.0


class ChatSpikeEvent(BaseModel):
    timestamp: float
    messages_per_second: float
    baseline_rate: float
    spike_ratio: float


class ToxicityResult(BaseModel):
    is_toxic: bool = False
    score: float = 0.0
    category: str = ""


# ─── Highlight / Decision Results ─────────────────────────────

class HighlightScore(BaseModel):
    composite_score: float = 0.0
    breakdown: dict[str, float] = Field(default_factory=dict)
    timestamp: float = Field(default_factory=time.time)
    active_signals: int = 0


class ClipCandidate(BaseModel):
    candidate_id: str = Field(default_factory=_uuid7)
    stream_id: str = ""
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: datetime = Field(default_factory=datetime.utcnow)
    event_timestamp: datetime = Field(default_factory=datetime.utcnow)
    highlight_score: HighlightScore = Field(default_factory=HighlightScore)
    trigger_signals: list[str] = Field(default_factory=list)
    priority: float = 0.0
    rank_score: float = 0.0


class DecisionResult(BaseModel):
    decision: str  # CREATE_CLIP or REJECT
    reason: str = ""
    score: Optional[HighlightScore] = None
    candidate: Optional[ClipCandidate] = None
    priority: float = 0.0


# ─── Clip Results ─────────────────────────────────────────────

class ClipResult(BaseModel):
    clip_id: str = Field(default_factory=_uuid7)
    file_path: str = ""
    thumbnail_path: str = ""
    duration_seconds: float = 0.0
    start_time: datetime = Field(default_factory=datetime.utcnow)
    end_time: datetime = Field(default_factory=datetime.utcnow)
    highlight_score: float = 0.0
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    classification_labels: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


# ─── Stream State ─────────────────────────────────────────────

class StreamState(str, Enum):
    OFFLINE = "offline"
    STARTING = "starting"
    WARMING_UP = "warming_up"
    STEADY = "steady"
    HIGH_ENERGY = "high_energy"
    PEAK_MOMENT = "peak_moment"
    COOLING_DOWN = "cooling_down"
    ENDING = "ending"


class StreamInfo(BaseModel):
    stream_id: str = Field(default_factory=_uuid7)
    platform: str = "kick"
    channel_slug: str = ""
    title: str = ""
    started_at: datetime = Field(default_factory=datetime.utcnow)
    viewer_count: int = 0
    state: StreamState = StreamState.OFFLINE
