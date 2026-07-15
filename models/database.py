"""
SQLAlchemy veritabanı modelleri - Klip, Yayıncı, Analiz sonuçları.
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, Enum as SAEnum, JSON
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class ClipStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    EXPORTED = "exported"


class ClipCategory(str, enum.Enum):
    FUNNY = "funny"
    EXCITING = "exciting"
    EMOTIONAL = "emotional"
    VICTORY = "victory"
    FAIL = "fail"
    RAGE = "rage"
    WHOLESONE = "wholesome"
    SKILL = "skill"
    OTHER = "other"


class TriggerType(str, enum.Enum):
    EMOTION = "emotion"
    MOTION = "motion"
    AUDIO = "audio"
    CHAT = "chat"
    MANUAL = "manual"
    COMPOSITE = "composite"


class Broadcaster(Base):
    __tablename__ = "broadcasters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kick_user_id = Column(String, unique=True, nullable=False, index=True)
    channel_slug = Column(String, nullable=False)
    display_name = Column(String)
    profile_picture_url = Column(String)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    clips = relationship("Clip", back_populates="broadcaster")
    preferences = relationship("UserPreferences", back_populates="broadcaster",
                               uselist=False)


class Clip(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    broadcaster_id = Column(Integer, ForeignKey("broadcasters.id"), nullable=False)
    title = Column(String(255))
    description = Column(Text)
    category = Column(SAEnum(ClipCategory), default=ClipCategory.OTHER)
    status = Column(SAEnum(ClipStatus), default=ClipStatus.PENDING)
    trigger_type = Column(SAEnum(TriggerType), nullable=False)

    # Timing
    stream_start_time = Column(DateTime)
    clip_start_time = Column(DateTime)
    clip_end_time = Column(DateTime)
    duration_seconds = Column(Float)

    # File paths
    video_path = Column(String(512))
    thumbnail_path = Column(String(512))
    subtitle_path = Column(String(512))
    s3_url = Column(String(512))

    # Metadata from Kick API
    viewer_count = Column(Integer)
    stream_title = Column(String(255))
    category_name = Column(String(100))

    # Analysis results
    dominant_emotion = Column(String(50))
    emotion_score = Column(Float)
    motion_score = Column(Float)
    audio_energy = Column(Float)
    chat_sentiment = Column(Float)
    tags = Column(JSON, default=list)
    classification_labels = Column(JSON, default=list)

    # Flags
    is_manual = Column(Boolean, default=False)
    is_exported = Column(Boolean, default=False)
    is_favorite = Column(Boolean, default=False)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    broadcaster = relationship("Broadcaster", back_populates="clips")
    analysis_results = relationship("AnalysisResult", back_populates="clip")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    timestamp = Column(Float, nullable=False)  # seconds from clip start
    frame_number = Column(Integer)

    # Face/Emotion
    face_detected = Column(Boolean, default=False)
    face_count = Column(Integer, default=0)
    emotions = Column(JSON, default=dict)  # {"happy": 0.8, "angry": 0.1, ...}
    dominant_emotion = Column(String(50))
    emotion_confidence = Column(Float)

    # Motion/Pose
    motion_magnitude = Column(Float)
    pose_data = Column(JSON, default=dict)  # MediaPipe landmarks
    is_significant_motion = Column(Boolean, default=False)

    # Audio
    audio_energy = Column(Float)
    speech_detected = Column(Boolean, default=False)
    speech_text = Column(Text)

    created_at = Column(DateTime, server_default=func.now())

    clip = relationship("Clip", back_populates="analysis_results")


class UserPreferences(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    broadcaster_id = Column(Integer, ForeignKey("broadcasters.id"),
                            unique=True, nullable=False)

    # Clip preferences
    preferred_categories = Column(JSON, default=list)
    min_clip_duration = Column(Integer, default=10)
    max_clip_duration = Column(Integer, default=60)
    auto_subtitle = Column(Boolean, default=True)
    subtitle_language = Column(String(10), default="tr")
    subtitle_style = Column(String(50), default="default")

    # Analysis preferences
    emotion_sensitivity = Column(Float, default=0.7)
    motion_sensitivity = Column(Float, default=0.6)
    audio_trigger_enabled = Column(Boolean, default=True)
    chat_trigger_enabled = Column(Boolean, default=True)

    # Export preferences
    auto_export = Column(Boolean, default=False)
    export_format = Column(String(20), default="mp4")
    export_resolution = Column(String(20), default="1080p")
    add_watermark = Column(Boolean, default=False)
    watermark_text = Column(String(100))

    # Priority/filter
    priority_tags = Column(JSON, default=list)
    excluded_tags = Column(JSON, default=list)
    sort_by = Column(String(50), default="created_at")

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    broadcaster = relationship("Broadcaster", back_populates="preferences")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    broadcaster_id = Column(Integer, ForeignKey("broadcasters.id"), nullable=False)
    username = Column(String(100))
    message = Column(Text)
    sentiment_score = Column(Float)
    sentiment_label = Column(String(20))
    timestamp = Column(DateTime)
    stream_session_id = Column(String)

    created_at = Column(DateTime, server_default=func.now())
