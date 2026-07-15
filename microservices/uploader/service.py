"""
Uploader Microservice
──────────────────────
Subscribes to EDIT_READY → uploads exported clips to social platforms
via src/uploader.py AutoPublisher.

Publishes CLIP_PUBLISHED when upload succeeds.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("uploader_ms")


class UploaderMicroservice:
    """
    Event-driven uploader.

    Waits for EDIT_READY (exported clips per platform),
    then uploads each to the corresponding platform.
    Also subscribes to AI_METADATA_READY to attach title/hashtags.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        auto_upload: bool = False,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.auto_upload = auto_upload

        # Cache metadata from AI generator
        self._metadata_cache: dict[str, dict] = {}

        # Metrics
        self._uploaded = 0
        self._failed = 0
        self._pending = 0

        # Subscribe to EDIT_READY and AI_METADATA_READY
        self.event_bus.subscribe(
            EventType.EDIT_READY.value,
            self._on_edit_ready,
        )
        self.event_bus.subscribe(
            EventType.AI_METADATA_READY.value,
            self._on_ai_metadata,
        )

        logger.info("UploaderMicroservice initialized (auto=%s)", auto_upload)

    async def _on_ai_metadata(self, event: SystemEvent):
        """Cache AI metadata for use during upload."""
        clip_id = event.payload.get("clip_id", "")
        if clip_id:
            self._metadata_cache[clip_id] = event.payload

    async def _on_edit_ready(self, event: SystemEvent):
        """Handle edit ready — upload to platforms if auto_upload is on."""
        if not self.auto_upload:
            logger.debug("Auto-upload disabled, skipping")
            return

        payload = event.payload
        clip_id = payload.get("clip_id", "")
        exports = payload.get("exports", {})

        # Get metadata if available
        metadata = self._metadata_cache.pop(clip_id, {})
        title = metadata.get("title", f"Clip {clip_id[:8]}")
        description = metadata.get("description", "")
        hashtags = metadata.get("hashtags", [])

        for platform, file_path in exports.items():
            if not os.path.exists(file_path):
                logger.warning("Export file not found: %s", file_path)
                continue

            try:
                from src.uploader import auto_publisher

                result = await auto_publisher.publish(
                    video_path=file_path,
                    title=title,
                    description=description,
                    tags=hashtags,
                    platform=platform,
                    privacy="private",
                )

                if result:
                    self._uploaded += 1
                    await self.event_bus.publish_quick(
                        EventType.CLIP_PUBLISHED,
                        payload={
                            "clip_id": clip_id,
                            "platform": platform,
                            "video_id": result.get("video_id", ""),
                            "url": result.get("url", ""),
                            "file_path": file_path,
                        },
                        source_service="uploader",
                        stream_id=event.stream_id,
                        causation_id=event.event_id,
                    )
                    logger.info("Uploaded to %s: %s", platform, result.get("url"))
                else:
                    self._failed += 1

            except Exception as e:
                self._failed += 1
                logger.error("Upload to %s failed: %s", platform, e)

    async def manual_upload(
        self,
        clip_path: str,
        platform: str,
        title: str = "",
        description: str = "",
        tags: list[str] = None,
    ) -> Optional[dict]:
        """Manually upload a clip to a platform."""
        from src.uploader import auto_publisher

        return await auto_publisher.publish(
            video_path=clip_path,
            title=title or "Auto-generated clip",
            description=description,
            tags=tags or [],
            platform=platform,
            privacy="private",
        )

    def get_status(self) -> dict:
        return {
            "uploaded": self._uploaded,
            "failed": self._failed,
            "pending": self._pending,
            "auto_upload": self.auto_upload,
            "metadata_cached": len(self._metadata_cache),
        }
