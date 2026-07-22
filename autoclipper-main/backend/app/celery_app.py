# backend/celery_app.py
from celery import Celery
import os

celery = Celery(
    "auto_clipper",
    broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
)
celery.conf.beat_schedule = {
    "scan-youtube-every-hour": {
        "task": "services.youtube.scan_channel",
        "schedule": 3600.0,
        "args": (),
    },
}

@celery.task(name="services.youtube.scan_channel")
def scan_channel(channel_id: str):
    from services.youtube import fetch_highlights
    fetch_highlights(channel_id)
