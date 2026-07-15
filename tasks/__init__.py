"""
Celery application — background task execution for heavy operations.

Production: Workers process subtitle burn-in, video export, thumbnail generation,
AI metadata generation, and platform uploads.

Usage:
    celery -A tasks.celery_app worker --loglevel=info --concurrency=2
"""
from celery import Celery
from config import get_settings

settings = get_settings()

celery_app = Celery(
    "klip_tasks",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,          # 10 min hard limit
    task_soft_time_limit=480,     # 8 min soft limit (raises SoftTimeLimitExceeded)
    worker_prefetch_multiplier=1,  # Don't prefetch — GPU tasks are heavy
    worker_max_tasks_per_child=50, # Restart worker after 50 tasks (memory leak guard)
    task_acks_late=True,          # Acknowledge after completion (at-least-once)
)

# Import tasks so Celery discovers them
import tasks.pipeline_tasks  # noqa: F401, E402
