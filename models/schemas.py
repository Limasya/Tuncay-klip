"""
Pydantic şemaları - API istek/yanıt modelleri.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# --- Enums ---
class ClipCategoryEnum(str, Enum):
    funny = "funny"
    exciting = "exciting"
    emotional = "emotional"
    victory = "victory"
    fail = "fail"
    rage = "rage"
    wholesome = "wholesome"
    skill = "skill"
    other = "other"


class ClipStatusEnum(str, Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"
    exported = "exported"


class TriggerTypeEnum(str, Enum):
    emotion = "emotion"
    motion = "motion"
    audio = "audio"
    chat = "chat"
    manual = "manual"
    composite = "composite"


# --- Broadcaster ---
class BroadcasterCreate(BaseModel):
    kick_user_id: str
    channel_slug: str
    display_name: Optional[str] = None


class BroadcasterResponse(BaseModel):
    id: int
    kick_user_id: str
    channel_slug: str
    display_name: Optional[str]
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# --- Stream Info ---
class StreamInfo(BaseModel):
    is_live: bool
    title: Optional[str] = None
    category: Optional[str] = None
    viewer_count: Optional[int] = None
    thumbnail_url: Optional[str] = None
    playback_url: Optional[str] = None
    started_at: Optional[datetime] = None


# --- Clip ---
class ClipCreate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: ClipCategoryEnum = ClipCategoryEnum.other
    trigger_type: TriggerTypeEnum = TriggerTypeEnum.manual
    is_manual: bool = True


class ClipResponse(BaseModel):
    id: int
    broadcaster_id: int
    title: Optional[str]
    description: Optional[str]
    category: Optional[ClipCategoryEnum]
    status: Optional[ClipStatusEnum]
    trigger_type: Optional[TriggerTypeEnum]
    clip_start_time: Optional[datetime]
    clip_end_time: Optional[datetime]
    duration_seconds: Optional[float]
    video_path: Optional[str]
    thumbnail_path: Optional[str]
    subtitle_path: Optional[str]
    s3_url: Optional[str]
    viewer_count: Optional[int]
    stream_title: Optional[str]
    category_name: Optional[str]
    dominant_emotion: Optional[str]
    emotion_score: Optional[float]
    motion_score: Optional[float]
    audio_energy: Optional[float]
    chat_sentiment: Optional[float]
    tags: Optional[List[str]]
    classification_labels: Optional[List[str]]
    is_manual: bool
    is_exported: bool
    is_favorite: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ClipListResponse(BaseModel):
    clips: List[ClipResponse]
    total: int
    page: int
    page_size: int


# --- Analysis ---
class EmotionData(BaseModel):
    happy: float = 0.0
    sad: float = 0.0
    angry: float = 0.0
    surprised: float = 0.0
    fearful: float = 0.0
    disgusted: float = 0.0
    neutral: float = 0.0


class AnalysisFrameResult(BaseModel):
    timestamp: float
    face_detected: bool
    face_count: int
    emotions: Optional[EmotionData]
    dominant_emotion: Optional[str]
    emotion_confidence: Optional[float]
    motion_magnitude: Optional[float]
    is_significant_motion: bool
    audio_energy: Optional[float]
    speech_detected: bool
    speech_text: Optional[str]


# --- Preferences ---
class UserPreferencesUpdate(BaseModel):
    preferred_categories: Optional[List[str]] = None
    min_clip_duration: Optional[int] = None
    max_clip_duration: Optional[int] = None
    auto_subtitle: Optional[bool] = None
    subtitle_language: Optional[str] = None
    subtitle_style: Optional[str] = None
    emotion_sensitivity: Optional[float] = Field(None, ge=0.0, le=1.0)
    motion_sensitivity: Optional[float] = Field(None, ge=0.0, le=1.0)
    audio_trigger_enabled: Optional[bool] = None
    chat_trigger_enabled: Optional[bool] = None
    auto_export: Optional[bool] = None
    export_format: Optional[str] = None
    export_resolution: Optional[str] = None
    add_watermark: Optional[bool] = None
    watermark_text: Optional[str] = None
    priority_tags: Optional[List[str]] = None
    excluded_tags: Optional[List[str]] = None
    sort_by: Optional[str] = None


class UserPreferencesResponse(BaseModel):
    broadcaster_id: int
    preferred_categories: Optional[List[str]]
    min_clip_duration: int
    max_clip_duration: int
    auto_subtitle: bool
    subtitle_language: str
    subtitle_style: str
    emotion_sensitivity: float
    motion_sensitivity: float
    audio_trigger_enabled: bool
    chat_trigger_enabled: bool
    auto_export: bool
    export_format: str
    export_resolution: str
    add_watermark: bool
    watermark_text: Optional[str]
    priority_tags: Optional[List[str]]
    excluded_tags: Optional[List[str]]
    sort_by: str

    class Config:
        from_attributes = True


# --- Auth ---
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


# --- System Status ---
class SystemStatus(BaseModel):
    is_monitoring: bool
    target_channel: Optional[str]
    stream_active: bool
    clips_today: int
    buffer_usage_mb: float
    analysis_fps: float
    cpu_usage: float
    memory_usage: float
    gpu_available: bool


# --- Chat ---
class ChatMessageResponse(BaseModel):
    id: int
    username: str
    message: str
    sentiment_score: Optional[float]
    sentiment_label: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True
