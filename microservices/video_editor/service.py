"""
Video Editor Microservice
───────────────────────────
Subscribes to CLIP_CREATED (or SUBTITLE_READY) and exports clips to
multiple aspect ratios for different platforms.

Publishes EDIT_READY when done.

Wraps services/video_editor.py (VideoEditor) into the event-driven pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("video_editor_ms")

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


# Default export profiles for each platform
DEFAULT_PLATFORM_PROFILES = {
    "youtube": "16:9",
    "tiktok": "9:16",
    "instagram_reels": "9:16",
    "instagram_post": "1:1",
    "shorts": "9:16",
}


class VideoEditorMicroservice:
    """
    Event-driven video editor.

    Subscribes to CLIP_CREATED events, exports the clip to multiple
    aspect ratios / resolutions, and publishes EDIT_READY.

    Delegates actual FFmpeg work to the existing VideoEditor singleton.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        auto_export: bool = True,
        platforms: Optional[list[str]] = None,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.auto_export = auto_export
        self.platforms = platforms or ["youtube", "tiktok"]

        # Metrics
        self._exports_done = 0
        self._exports_failed = 0

        # Subscribe to CLIP_CREATED (runs in parallel with subtitle service)
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

        logger.info(
            "VideoEditorMicroservice initialized (platforms=%s)", self.platforms
        )

    async def _on_clip_created(self, event: SystemEvent):
        """Handle clip created — export to platform aspect ratios."""
        if not self.auto_export:
            return

        payload = event.payload
        clip_path = payload.get("file_path", "")
        clip_id = payload.get("clip_id", "")

        if not clip_path or not os.path.exists(clip_path):
            logger.warning("Clip file not found: %s", clip_path)
            return

        try:
            from services.video_editor import video_editor

            exported = {}
            for platform in self.platforms:
                resolution_key = DEFAULT_PLATFORM_PROFILES.get(platform, "720p")

                # Build output path
                base = Path(clip_path).stem
                out_path = str(
                    EXPORTS_DIR / f"{base}_{platform}_{resolution_key}.mp4"
                )

                result = await video_editor.export_clip(
                    input_path=clip_path,
                    resolution=resolution_key,
                    output_format="mp4",
                    output_path=out_path,
                )

                if result:
                    exported[platform] = result
                    self._exports_done += 1
                    logger.info("Exported %s: %s", platform, result)
                else:
                    self._exports_failed += 1

            if exported:
                await self.event_bus.publish_quick(
                    EventType.EDIT_READY,
                    payload={
                        "clip_id": clip_id,
                        "original_path": clip_path,
                        "exports": exported,  # {platform: path}
                    },
                    source_service="video_editor",
                    stream_id=event.stream_id,
                    causation_id=event.event_id,
                )

        except Exception as e:
            self._exports_failed += 1
            logger.error("Video editor error: %s", e, exc_info=True)

    def get_status(self) -> dict:
        return {
            "exports_done": self._exports_done,
            "exports_failed": self._exports_failed,
            "platforms": self.platforms,
            "auto_export": self.auto_export,
        }
