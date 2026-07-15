"""
Thumbnail Microservice
───────────────────────
Subscribes to CLIP_CREATED → generates a thumbnail from the clip
via FFmpeg frame extraction.

Publishes THUMBNAIL_READY when done.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("thumbnail_ms")

THUMBNAILS_DIR = Path("data/thumbnails")
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)


class ThumbnailMicroservice:
    """
    Event-driven thumbnail generator.

    Extracts a key frame from the clip and optionally applies
    text overlay, face-centering, and platform sizing.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        time_point: float = 0.5,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.time_point = time_point  # seconds into clip

        # Metrics
        self._generated = 0
        self._failed = 0

        # Subscribe to CLIP_CREATED
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

        logger.info("ThumbnailMicroservice initialized")

    async def _on_clip_created(self, event: SystemEvent):
        """Generate thumbnail from the new clip."""
        payload = event.payload
        clip_path = payload.get("file_path", "")
        clip_id = payload.get("clip_id", "")
        category = payload.get("category", "")

        if not clip_path or not os.path.exists(clip_path):
            logger.warning("Clip file not found for thumbnail: %s", clip_path)
            return

        try:
            thumb_path = await self._generate_thumbnail(
                clip_path=clip_path,
                clip_id=clip_id,
                category=category,
            )

            if thumb_path:
                self._generated += 1

                await self.event_bus.publish_quick(
                    EventType.THUMBNAIL_READY,
                    payload={
                        "clip_id": clip_id,
                        "thumbnail_path": thumb_path,
                        "category": category,
                    },
                    source_service="thumbnail",
                    stream_id=event.stream_id,
                    causation_id=event.event_id,
                )

                logger.info("Thumbnail ready: %s", thumb_path)
            else:
                self._failed += 1

        except Exception as e:
            self._failed += 1
            logger.error("Thumbnail generation failed: %s", e, exc_info=True)

    async def _generate_thumbnail(
        self,
        clip_path: str,
        clip_id: str,
        category: str = "",
    ) -> Optional[str]:
        """Extract a frame and save as thumbnail."""
        thumb_path = str(THUMBNAILS_DIR / f"{clip_id or Path(clip_path).stem}.jpg")

        # Try the smart thumbnail engine first (if available)
        try:
            from services.thumbnail_engine import thumbnail_engine
            result = await thumbnail_engine.generate_smart_thumbnail(
                video_path=clip_path,
                output_path=thumb_path,
                time_point=self.time_point,
                add_title=False,
            )
            if result:
                return result
        except (ImportError, Exception) as e:
            logger.debug("Smart thumbnail unavailable, falling back to FFmpeg: %s", e)

        # Fallback: FFmpeg frame extraction
        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-ss", str(self.time_point),
            "-vframes", "1",
            "-q:v", "2",
            thumb_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)

            if proc.returncode == 0 and os.path.exists(thumb_path):
                return thumb_path
            else:
                logger.error("FFmpeg thumbnail error: %s", stderr.decode()[:300])
                return None

        except asyncio.TimeoutError:
            logger.error("Thumbnail extraction timeout")
            return None
        except Exception as e:
            logger.error("Thumbnail extraction error: %s", e)
            return None

    def get_status(self) -> dict:
        return {
            "generated": self._generated,
            "failed": self._failed,
        }
