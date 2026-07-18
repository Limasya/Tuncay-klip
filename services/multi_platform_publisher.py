"""
Multi-Platform Publisher — Çoklu Platform Yükleme Mikroservisi
─────────────────────────────────────────────────────────────
FAZ-3.1: Zamanlanmış ve event-driven çoklu platform yükleme.

Features:
  - Event-driven: EDIT_READY → auto-publish to all platforms
  - Scheduled publishing: Platform bazında zamanlama (prime time)
  - Retry with exponential backoff
  - Platform-specific adaptations (title, description, hashtags)
  - Queue management with priority
  - Cross-platform analytics tracking
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from shared.utils.json_state import JsonStateStore

logger = logging.getLogger("publisher")


class PublishStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    UPLOADING = "uploading"
    PUBLISHED = "published"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class Platform(str, Enum):
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    YOUTUBE_SHORTS = "youtube_shorts"
    INSTAGRAM = "instagram_reels"
    TWITTER = "twitter"
    KICK = "kick"


class PublishJob(BaseModel):
    """Tek bir yükleme işi."""
    job_id: str = ""
    clip_id: str = ""
    platform: Platform
    status: PublishStatus = PublishStatus.PENDING
    video_path: str = ""
    title: str = ""
    description: str = ""
    hashtags: List[str] = Field(default_factory=list)
    thumbnail_path: str = ""
    privacy: str = "private"  # private, unlisted, public
    scheduled_at: str = ""
    published_at: str = ""
    platform_url: str = ""
    error_message: str = ""
    retry_count: int = 0
    max_retries: int = 3
    priority: int = 0  # higher = more urgent
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PlatformConfig(BaseModel):
    """Platform-specific konfigürasyon."""
    platform: Platform
    auto_publish: bool = False
    default_privacy: str = "private"
    max_title_length: int = 100
    max_description_length: int = 500
    max_hashtags: int = 5
    requires_thumbnail: bool = False
    supported_formats: List[str] = Field(default_factory=lambda: ["mp4"])
    max_file_size_mb: float = 100.0
    # Zamanlama
    prime_hours: List[int] = Field(default_factory=lambda: [18, 19, 20, 21])  # UTC
    timezone: str = "UTC"


# ── Platform Adaptations ──

PLATFORM_CONFIGS: Dict[Platform, PlatformConfig] = {
    Platform.TIKTOK: PlatformConfig(
        platform=Platform.TIKTOK,
        max_title_length=150,
        max_description_length=2200,
        max_hashtags=5,
        prime_hours=[12, 13, 14, 18, 19, 20, 21],
    ),
    Platform.YOUTUBE: PlatformConfig(
        platform=Platform.YOUTUBE,
        max_title_length=100,
        max_description_length=5000,
        max_hashtags=15,
        requires_thumbnail=True,
        prime_hours=[14, 15, 16, 19, 20, 21, 22],
    ),
    Platform.YOUTUBE_SHORTS: PlatformConfig(
        platform=Platform.YOUTUBE_SHORTS,
        max_title_length=100,
        max_description_length=100,
        max_hashtags=3,
        prime_hours=[12, 13, 14, 18, 19, 20, 21],
    ),
    Platform.INSTAGRAM: PlatformConfig(
        platform=Platform.INSTAGRAM,
        max_title_length=2200,
        max_description_length=2200,
        max_hashtags=10,
        prime_hours=[11, 12, 13, 17, 18, 19, 20, 21],
    ),
    Platform.TWITTER: PlatformConfig(
        platform=Platform.TWITTER,
        max_title_length=280,
        max_description_length=280,
        max_hashtags=3,
        prime_hours=[12, 13, 14, 17, 18, 19, 20, 21],
    ),
    Platform.KICK: PlatformConfig(
        platform=Platform.KICK,
        max_title_length=200,
        max_description_length=500,
        max_hashtags=5,
        prime_hours=[18, 19, 20, 21, 22, 23],
    ),
}


class MultiPlatformPublisher:
    """
    Çoklu platform yükleme mikroservisi.
    Event-driven ve zamanlanmış yükleme destekler.
    """

    def __init__(self, state_path: str | Path | None = None):
        self._jobs: Dict[str, PublishJob] = {}
        self._queue: deque = deque(maxlen=500)
        self._platform_configs = dict(PLATFORM_CONFIGS)
        self._upload_results: Dict[str, List[Dict]] = defaultdict(list)
        self._state = JsonStateStore(state_path or "data/publisher_state.json")

        # Metrics
        self._total_published = 0
        self._total_failed = 0
        self._total_retries = 0

    def create_job(
        self,
        clip_id: str,
        platform: str,
        video_path: str,
        title: str = "",
        description: str = "",
        hashtags: Optional[List[str]] = None,
        thumbnail_path: str = "",
        privacy: str = "private",
        scheduled_at: str = "",
        priority: int = 0,
    ) -> PublishJob:
        """Yeni bir yükleme işi oluştur."""
        import uuid
        job_id = f"pub_{uuid.uuid4().hex[:10]}"

        platform_enum = Platform(platform.lower()) if platform.lower() in Platform.__members__.values() else Platform.TIKTOK
        config = self._platform_configs.get(platform_enum, PLATFORM_CONFIGS[Platform.TIKTOK])

        # Platform-specific adaptasyonlar
        adapted_title = title[:config.max_title_length] if title else f"Clip {clip_id[:8]}"
        adapted_desc = description[:config.max_description_length] if description else ""
        adapted_hashtags = (hashtags or [])[:config.max_hashtags]

        job = PublishJob(
            job_id=job_id,
            clip_id=clip_id,
            platform=platform_enum,
            video_path=video_path,
            title=adapted_title,
            description=adapted_desc,
            hashtags=adapted_hashtags,
            thumbnail_path=thumbnail_path,
            privacy=privacy or config.default_privacy,
            scheduled_at=scheduled_at,
            priority=priority,
        )

        self._jobs[job_id] = job
        self._queue.append(job_id)

        logger.info(
            "Publish job created: %s → %s (%s)",
            clip_id[:8], platform_enum.value, job_id,
        )
        return job

    def create_multi_platform_jobs(
        self,
        clip_id: str,
        platforms: List[str],
        video_path: str,
        title: str = "",
        description: str = "",
        hashtags: Optional[List[str]] = None,
        thumbnail_path: str = "",
    ) -> List[PublishJob]:
        """Birden fazla platform için aynı klipten işler oluştur."""
        jobs = []
        for platform in platforms:
            job = self.create_job(
                clip_id=clip_id,
                platform=platform,
                video_path=video_path,
                title=title,
                description=description,
                hashtags=hashtags,
                thumbnail_path=thumbnail_path,
            )
            jobs.append(job)
        return jobs

    async def process_queue(self, max_concurrent: int = 3) -> List[Dict[str, Any]]:
        """Kuyruktaki işleri paralel olarak işle."""
        pending_jobs = [
            self._jobs[jid] for jid in self._queue
            if jid in self._jobs and self._jobs[jid].status in (PublishStatus.PENDING, PublishStatus.RETRYING)
        ]

        # Önceliğe göre sırala
        pending_jobs.sort(key=lambda j: j.priority, reverse=True)
        pending_jobs = pending_jobs[:max_concurrent]

        if not pending_jobs:
            return []

        results = []
        tasks = [self._process_job(job) for job in pending_jobs]
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        for result in completed:
            if isinstance(result, dict):
                results.append(result)
            elif isinstance(result, Exception):
                results.append({"error": str(result)})

        return results

    async def _process_job(self, job: PublishJob) -> Dict[str, Any]:
        """Tek bir yükleme işini xửükle."""
        job.status = PublishStatus.UPLOADING

        try:
            # Platform adaptasyonları
            adapted = self._adapt_for_platform(job)

            # Gerçek yükleme (src/uploader.py AutoPublisher kullanarak)
            result = await self._upload_to_platform(job, adapted)

            if result.get("success"):
                job.status = PublishStatus.PUBLISHED
                job.published_at = datetime.now(timezone.utc).isoformat()
                job.platform_url = result.get("url", "")
                self._total_published += 1

                self._upload_results[job.platform.value].append({
                    "clip_id": job.clip_id,
                    "job_id": job.job_id,
                    "url": job.platform_url,
                    "timestamp": job.published_at,
                })

                logger.info(
                    "Published %s → %s: %s",
                    job.clip_id[:8], job.platform.value, job.platform_url,
                )
                return {"success": True, "job_id": job.job_id, "url": job.platform_url}
            else:
                raise Exception(result.get("error", "Upload failed"))

        except Exception as e:
            job.error_message = str(e)
            job.retry_count += 1
            self._total_retries += 1

            if job.retry_count < job.max_retries:
                job.status = PublishStatus.RETRYING
                # Exponential backoff
                delay = 2 ** job.retry_count * 10
                logger.warning(
                    "Upload failed (retry %d/%d in %ds): %s",
                    job.retry_count, job.max_retries, delay, e,
                )
                await asyncio.sleep(delay)
                self._queue.append(job.job_id)
            else:
                job.status = PublishStatus.FAILED
                self._total_failed += 1
                logger.error("Upload permanently failed: %s", e)

            return {"success": False, "job_id": job.job_id, "error": str(e)}

    def _adapt_for_platform(self, job: PublishJob) -> Dict[str, Any]:
        """Platform'a göre adapte edilmiş parametreler."""
        config = self._platform_configs.get(job.platform)
        if not config:
            return {}

        adapted = {
            "title": job.title[:config.max_title_length],
            "description": job.description[:config.max_description_length],
            "hashtags": job.hashtags[:config.max_hashtags],
            "privacy": job.privacy,
        }

        # Hashtag formatı platforma göre değişir
        if job.platform == Platform.TIKTOK:
            adapted["hashtags"] = [f"#{h.lstrip('#')}" for h in adapted["hashtags"]]
        elif job.platform == Platform.INSTAGRAM:
            adapted["description"] = adapted["description"] + "\n\n" + " ".join(adapted["hashtags"])

        return adapted

    async def _upload_to_platform(
        self, job: PublishJob, adapted: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Platform'a yükle (gerçek API çağrısı)."""
        # src/uploader.py AutoPublisher'ı kullan
        try:
            from src.uploader import AutoPublisher
            publisher = AutoPublisher()
            result = await publisher.publish(
                video_path=job.video_path,
                title=adapted.get("title", job.title),
                description=adapted.get("description", ""),
                tags=adapted.get("hashtags", []),
                platform=job.platform.value,
                privacy=adapted.get("privacy", "private"),
            )
            return {"success": bool(result), "url": result.get("url", "") if result else ""}
        except Exception as e:
            logger.warning("Upload attempt failed: %s", e)
            return {"success": False, "error": str(e)}

    # ── Scheduling ──

    def get_optimal_posting_time(self, platform: str) -> Optional[str]:
        """Platform için en uygun paylaşma zamanını öner."""
        config = self._platform_configs.get(Platform(platform.lower()))
        if not config:
            return None

        now = datetime.now(timezone.utc)
        current_hour = now.hour

        # Bir sonraki prime time'ı bul
        future_hours = [h for h in config.prime_hours if h > current_hour]
        if future_hours:
            next_hour = min(future_hours)
        else:
            next_hour = min(config.prime_hours) + 24

        target_hour = next_hour % 24
        target = now.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if target_hour < current_hour:
            from datetime import timedelta
            target += timedelta(days=1)

        return target.isoformat()

    # ── Query ──

    def get_job(self, job_id: str) -> Optional[PublishJob]:
        return self._jobs.get(job_id)

    def get_jobs_by_status(self, status: PublishStatus) -> List[PublishJob]:
        return [j for j in self._jobs.values() if j.status == status]

    def get_jobs_by_clip(self, clip_id: str) -> List[PublishJob]:
        return [j for j in self._jobs.values() if j.clip_id == clip_id]

    def get_upload_results(self, platform: Optional[str] = None) -> Dict[str, Any]:
        if platform:
            return {platform: self._upload_results.get(platform, [])}
        return dict(self._upload_results)

    def get_stats(self) -> Dict[str, Any]:
        status_counts = defaultdict(int)
        for job in self._jobs.values():
            status_counts[job.status.value] += 1

        return {
            "total_jobs": len(self._jobs),
            "by_status": dict(status_counts),
            "total_published": self._total_published,
            "total_failed": self._total_failed,
            "total_retries": self._total_retries,
            "queue_size": len(self._queue),
            "platforms": list(set(j.platform.value for j in self._jobs.values())),
        }

    # ── Persistence ──

    async def save(self) -> None:
        await self._state.save({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "jobs": [j.model_dump() for j in list(self._jobs.values())[-200:]],
            "upload_results": dict(self._upload_results),
            "metrics": {
                "total_published": self._total_published,
                "total_failed": self._total_failed,
                "total_retries": self._total_retries,
            },
        })

    async def load(self) -> None:
        state = await self._state.load()
        if not state:
            return
        for jd in state.get("jobs", []):
            job = PublishJob(**jd)
            self._jobs[job.job_id] = job
        self._upload_results = defaultdict(list, state.get("upload_results", {}))
        metrics = state.get("metrics", {})
        self._total_published = metrics.get("total_published", 0)
        self._total_failed = metrics.get("total_failed", 0)
        self._total_retries = metrics.get("total_retries", 0)


# Singleton
multi_platform_publisher = MultiPlatformPublisher()
