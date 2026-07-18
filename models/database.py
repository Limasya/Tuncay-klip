"""
SQLAlchemy ORM ŞEMASI — Klip, Yayıncı, Analiz sonuçları vb. tablo tanımları.

Bu modül SADECE veri modellerini (declarative_base + tablo sınıfları) içerir.
Projede tek `Base` burada tanımlıdır; alembic migration'ları bu şemayı takip eder.

Bağlantı/engine/session yönetimi için bkz. services/database.py
(iki dosya da `database.py` adını taşır ama sorumlulukları ayrıdır:
 models.database = ŞEMA, services.database = BAĞLANTI).
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
    WHOLESOME = "wholesome"
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

    # AI Critic (closed-loop QC) — render sonrası içerik/viral kalite skoru
    critic_score = Column(Float, nullable=True)      # 0-10
    critique = Column(JSON, nullable=True)           # CritiqueReport.to_dict()

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


class ClipExport(Base):
    """Track exported clips per platform."""
    __tablename__ = "clip_exports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    platform = Column(String(50), nullable=False)  # youtube, tiktok, etc.
    export_path = Column(String(512))
    resolution = Column(String(20))  # 16:9, 9:16, etc.
    upload_url = Column(String(512))
    upload_video_id = Column(String(100))
    upload_status = Column(String(20), default="pending")  # pending, uploaded, failed
    title = Column(String(255))
    description = Column(Text)
    hashtags = Column(JSON, default=list)

    created_at = Column(DateTime, server_default=func.now())

    clip = relationship("Clip")


class ClipMetadata(Base):
    """AI-generated metadata for clips."""
    __tablename__ = "clip_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    title = Column(String(255))
    description = Column(Text)
    hashtags = Column(JSON, default=list)
    emotion = Column(String(50))
    category = Column(String(50))
    highlight_score = Column(Float)

    created_at = Column(DateTime, server_default=func.now())

    clip = relationship("Clip")


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


class ClipAnalytics(Base):
    """Track clip performance metrics over time (views, likes, shares)."""
    __tablename__ = "clip_analytics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clip_id = Column(Integer, ForeignKey("clips.id"), nullable=False)
    platform = Column(String(50), nullable=False)

    views = Column(Integer, default=0)
    likes = Column(Integer, default=0)
    dislikes = Column(Integer, default=0)
    comments = Column(Integer, default=0)
    shares = Column(Integer, default=0)
    impressions = Column(Integer, default=0)
    watch_time_seconds = Column(Float, default=0.0)
    avg_watch_percentage = Column(Float, default=0.0)

    # Engagement rate = (likes + comments + shares) / views * 100
    engagement_rate = Column(Float, default=0.0)

    snapshot_at = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())

    clip = relationship("Clip")

    def compute_engagement_rate(self) -> float:
        if self.views and self.views > 0:
            return ((self.likes + self.comments + self.shares) / self.views) * 100
        return 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "clip_id": self.clip_id,
            "platform": self.platform,
            "views": self.views,
            "likes": self.likes,
            "dislikes": self.dislikes,
            "comments": self.comments,
            "shares": self.shares,
            "impressions": self.impressions,
            "watch_time_seconds": self.watch_time_seconds,
            "avg_watch_percentage": self.avg_watch_percentage,
            "engagement_rate": self.engagement_rate,
            "snapshot_at": self.snapshot_at.isoformat() if self.snapshot_at else None,
        }
