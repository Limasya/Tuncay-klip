"""
Merkezi yapılandırma modülü - tüm ortam değişkenlerini yönetir.
Pydantic v1 uyumlu.
"""
import utils.pydantic_compat  # noqa: F401  patch v1 BaseModel
from pydantic import BaseSettings, validator, root_validator
import os
from functools import lru_cache


class Settings(BaseSettings):
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
    # Kick API
    kick_client_id: str = ""
    kick_client_secret: str = ""
    kick_redirect_uri: str = "http://localhost:8000/auth/callback"
    kick_broadcaster_user_id: str = ""
    kick_channel_slug: str = ""

    # Kick API Endpoints
    kick_api_base: str = "https://kick.com/api/v2"
    kick_public_api_base: str = "https://api.kick.app/public/v1"
    kick_auth_url: str = "https://kick.com/oauth/authorize"
    kick_token_url: str = "https://api.kick.app/oauth/token"

    # Stream
    stream_buffer_seconds: int = 30
    clip_pre_seconds: int = 5
    clip_post_seconds: int = 5
    analysis_fps: int = 2
    max_clip_duration: int = 60

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    event_bus_backend: str = "memory"  # "memory" or "redis"

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/klip.db"

    # AWS
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "eu-central-1"
    s3_bucket_name: str = "klip-storage"

    # Whisper
    whisper_model_size: str = "base"

    # Emotion
    emotion_threshold: float = 0.7
    excitement_threshold: float = 0.8

    # Decision Engine
    decision_clip_threshold: float = 0.55
    decision_cooldown_seconds: float = 15.0
    decision_min_evidence: int = 2
    decision_confirmation_window: int = 3       # evaluations to look back
    decision_confirmation_required: int = 2     # must pass N out of window
    decision_threshold_floor: float = 0.35      # never go below this
    decision_evidence_threshold: float = 0.2    # min signal value to count as evidence
    decision_score_interval: float = 2.0        # seconds between score evaluations
    decision_decay_halflife: float = 5.0        # temporal decay half-life (seconds)

    # Signal Weights (must sum > 0; normalized at load time)
    weight_audio_spike: float = 0.20
    weight_chat_velocity: float = 0.18
    weight_emotion_intensity: float = 0.15
    weight_emotion_change: float = 0.10
    weight_pose_gesture: float = 0.12
    weight_pose_motion: float = 0.08
    weight_chat_sentiment: float = 0.05
    weight_viewer_delta: float = 0.03
    weight_ocr_keyword: float = 0.02
    weight_speech_content: float = 0.02
    weight_donation: float = 0.05

    # Security
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    @root_validator
    def check_secret_key(cls, values):
        # Enforce secret_key change only in production environment
        if values.get('secret_key') == "change-me-in-production" and values.get('deployment_environment', 'production') == 'production':
            raise ValueError("secret_key must be set to a secure value in production")
        return values

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Webhooks / Notifications
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    generic_webhook_url: str = ""
    webhook_secret: str = ""
    webhook_rate_limit: int = 30

    # Observability (IP_PART6 — Platform Engineering)
    service_name: str = "platform-api"
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_sample_ratio: float = 0.1
    deployment_environment: str = "production"
    prometheus_metrics_enabled: bool = True

    # Feature Flags (IP_PART6 Bölüm 37)
    feature_flags_file: str = ""  # opsiyonel JSON dosya yolu



@lru_cache()
def get_settings() -> Settings:
    return Settings()
