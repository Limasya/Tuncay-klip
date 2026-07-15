"""
Pydantic şemaları - API istek/yanıt modelleri. Pydantic v1 uyumlu.
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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


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

    model_config = ConfigDict(from_attributes=True)


# --- Otomatik Edit ---

class EditSpecRequest(BaseModel):
    """Manuel edit spec oluşturma isteği."""
    source_path: str
    category: ClipCategoryEnum = ClipCategoryEnum.other
    aspect_ratio: str = "9:16"
    resolution: str = "1080p"
    custom_overrides: Optional[Dict[str, Any]] = None


class EditSpecResponse(BaseModel):
    """Üretilen edit spec yanıtı."""
    version: str
    source_path: str
    aspect_ratio: str
    resolution: str
    color_preset: str
    subtitle_style: str
    speed_segments_count: int
    has_watermark: bool
    has_music: bool
    category: Optional[str]
    composite_score: float


class RenderJobCreate(BaseModel):
    """Yeni render işi oluşturma."""
    source_path: str
    category: ClipCategoryEnum = ClipCategoryEnum.other
    aspect_ratio: str = "9:16"
    resolution: str = "1080p"
    output_format: str = "mp4"
    add_music: bool = True
    add_sfx: bool = True
    add_subtitle: bool = True
    custom_overrides: Optional[Dict[str, Any]] = None


class RenderJobResponse(BaseModel):
    """Render iş durumu yanıtı."""
    job_id: str
    status: str  # pending, processing, completed, failed
    source_path: str
    output_path: Optional[str]
    edit_spec: Optional[EditSpecResponse]
    created_at: datetime
    completed_at: Optional[datetime]
    error: Optional[str]


class MontageCreate(BaseModel):
    """Montaj oluşturma isteği."""
    clip_paths: List[str] = Field(min_length=2)
    transition_type: str = "fade"
    transition_duration: float = 0.5
    add_background_music: bool = True
    background_music_path: Optional[str] = None
    output_path: Optional[str] = None


class MusicLibraryResponse(BaseModel):
    """Müzik kütüphanesi yanıtı."""
    tracks: List[Dict[str, Any]]
    total: int


class SFXLibraryResponse(BaseModel):
    """SFX kütüphanesi yanıtı."""
    clips: List[Dict[str, Any]]
    total: int


class AudioDuckingRequest(BaseModel):
    """Ducking parametreleri hesaplama isteği."""
    speech_level: float = Field(ge=0, le=1)
    music_level: float = Field(ge=0, le=1)
    target_ratio: float = Field(default=0.15, ge=0, le=1)


class AudioDuckingResponse(BaseModel):
    """Ducking parametreleri yanıtı."""
    threshold: float
    ratio: float
    attack: int
    release: int
    filter_string: str


# --- Gelistirilmis Edit Ozellikleri ---

class BeatSyncRequest(BaseModel):
    """Beat-sync analiz ve filtre istegi."""
    source_path: str
    audio_path: Optional[str] = None
    bpm: Optional[float] = None
    zoom_on_beat: bool = True
    zoom_level: float = 1.05
    flash_on_beat: bool = False
    shake_on_beat: bool = False
    speed_variation: bool = False
    downbeats_only: bool = False


class BeatSyncResponse(BaseModel):
    """Beat-sync sonucu."""
    bpm: float
    total_beats: int
    total_bars: int
    duration: float
    filters_generated: int


class SceneDetectionRequest(BaseModel):
    """Sahne algilama istegi."""
    source_path: str
    threshold: float = 0.3
    min_scene_duration: float = 0.5
    apply_effects: bool = True
    highlight_reel: bool = False
    max_highlight_duration: float = 60.0


class SceneInfo(BaseModel):
    """Sahne bilgisi."""
    index: int
    start: float
    end: float
    duration: float


class SceneDetectionResponse(BaseModel):
    """Sahne algilama sonucu."""
    total_scenes: int
    total_duration: float
    average_scene_duration: float
    scenes: List[SceneInfo]
    highlight_reel: Optional[List[List[float]]] = None


class SplitScreenRequest(BaseModel):
    """Split screen render istegi."""
    clip_paths: List[str] = Field(min_length=2, max_length=9)
    layout: str = "side_by_side"
    gap: int = 4
    output_path: Optional[str] = None


class EndScreenRequest(BaseModel):
    """End screen overlay istegi."""
    source_path: str
    template: str = "subscribe_cta"
    custom_text: Optional[Dict[str, str]] = None
    call_to_action: Optional[str] = None
    cta_position: str = "bottom_right"


class LowerThirdRequest(BaseModel):
    """Lower third ekleme istegi."""
    source_path: str
    name: str
    title: str = ""
    style: str = "news"
    start_time: float = 0.0
    duration: float = 5.0
    position: str = "bottom_left"
    animated: bool = True


class StickerOverlayRequest(BaseModel):
    """Sticker/emoji overlay istegi."""
    source_path: str
    reaction_type: Optional[str] = None
    reaction_start: float = 0.0
    reaction_duration: float = 2.0
    emoji_rain: bool = False
    emoji_rain_emoji: str = "fire"
    confetti: bool = False


class EmotionArcRequest(BaseModel):
    """Emotion arc efekt istegi."""
    source_path: str
    segments: List[Dict[str, Any]]
    apply_color: bool = True
    apply_speed: bool = True
    apply_vignette: bool = True


class AdvancedRenderRequest(BaseModel):
    """Tam gelistirilmis render istegi (tum ozellikler)."""
    source_path: str
    aspect_ratio: str = "9:16"
    resolution: str = "1080p"
    crf: int = 23
    category: str = "other"
    # Beat sync
    beat_sync_enabled: bool = False
    beat_sync_bpm: Optional[float] = None
    beat_sync_zoom: bool = True
    # Word highlight
    word_highlight_enabled: bool = False
    word_highlight_words: List[Dict[str, Any]] = Field(default_factory=list)
    word_highlight_palette: str = "neon"
    # Stickers
    stickers_enabled: bool = False
    sticker_reaction: Optional[str] = None
    sticker_emoji_rain: bool = False
    sticker_confetti: bool = False
    # Lower thirds
    lower_thirds_enabled: bool = False
    lower_thirds_name: str = ""
    lower_thirds_title: str = ""
    lower_thirds_style: str = "news"
    # End screen
    end_screen_enabled: bool = False
    end_screen_template: str = "subscribe_cta"
    # Emotion arc
    emotion_arc_enabled: bool = False
    emotion_arc_segments: List[Dict[str, Any]] = Field(default_factory=list)
    # Scene detection
    scene_detection_enabled: bool = False
    scene_detection_threshold: float = 0.3


class WordTimingRequest(BaseModel):
    """Kelime zamanlama cikarma istegi."""
    source_path: str
    language: Optional[str] = None


class WordTimingInfo(BaseModel):
    """Tek bir kelime zamanlama bilgisi."""
    word: str
    start: float
    end: float
    confidence: float


class WordTimingResponse(BaseModel):
    """Kelime zamanlama sonucu."""
    source_path: str
    language: Optional[str]
    total_words: int
    words: List[WordTimingInfo]
    method: str  # whisper veya segment_based


class SceneAutoEffectsRequest(BaseModel):
    """Sahne bazli otomatik efekt istegi."""
    source_path: str
    threshold: float = 0.3
    min_scene_duration: float = 0.5


class SceneAutoEffectsResponse(BaseModel):
    """Sahne bazli otomatik efekt sonucu."""
    scene_count: int
    average_scene_duration: float
    total_duration: float
    speed_segments: List[Dict[str, Any]]
    color_preset: str
    visual_effects: Dict[str, float]
    scene_transitions: bool
