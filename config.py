"""
Merkezi yapılandırma modülü - tüm ortam değişkenlerini yönetir.
Pydantic v1 uyumlu.
"""
from pydantic import BaseSettings
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

    # Security
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    # Server
    host: str = "0.0.0.0"
    port: int = 8000


@lru_cache()
def get_settings() -> Settings:
    return Settings()
