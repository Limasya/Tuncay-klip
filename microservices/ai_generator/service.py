"""
AI Generator Microservice
──────────────────────────
Subscribes to CLIP_CREATED → generates title, description, hashtags, tags
using the existing src/ai_generator.py AITitleGenerator.

Publishes AI_METADATA_READY when done.
"""
from __future__ import annotations

import logging
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("ai_generator_ms")


class AIGeneratorMicroservice:
    """
    Event-driven AI metadata generator.

    On CLIP_CREATED, generates:
    - Clickbait-friendly title
    - Description text
    - Platform-specific hashtag list
    - Tag suggestions

    Publishes AI_METADATA_READY with all metadata.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        streamer_name: str = "Tuncay",
        default_platform: str = "youtube",
    ):
        self.event_bus = event_bus or get_event_bus()
        self.streamer_name = streamer_name
        self.default_platform = default_platform

        # Metrics
        self._generated = 0
        self._failed = 0

        # Subscribe to CLIP_CREATED
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

        logger.info("AIGeneratorMicroservice initialized")

    async def _on_clip_created(self, event: SystemEvent):
        """Handle clip created — generate AI metadata."""
        payload = event.payload
        clip_id = payload.get("clip_id", "")
        category = payload.get("category", "exciting")
        tags = payload.get("tags", [])
        score = payload.get("highlight_score", 0.0)

        try:
            from src.ai_generator import ai_title_generator

            # Determine emotion from category
            emotion_map = {
                "exciting": "exciting",
                "hype": "hype",
                "funny": "funny",
                "rage": "rage",
                "emotional": "emotional",
                "celebration": "victory",
                "highlight": "exciting",
            }
            emotion = emotion_map.get(category, "exciting")

            # Generate full metadata
            metadata = ai_title_generator.generate_full_metadata(
                emotion=emotion,
                category=category,
                streamer_name=self.streamer_name,
                viewer_count=0,
                stream_title="",
                game_name="",
                platform=self.default_platform,
                custom_tags=tags,
            )

            self._generated += 1

            # Publish AI_METADATA_READY
            await self.event_bus.publish_quick(
                EventType.AI_METADATA_READY,
                payload={
                    "clip_id": clip_id,
                    "title": metadata.get("title", ""),
                    "description": metadata.get("description", ""),
                    "hashtags": metadata.get("hashtags", []),
                    "category": category,
                    "emotion": emotion,
                    "highlight_score": score,
                },
                source_service="ai_generator",
                stream_id=event.stream_id,
                causation_id=event.event_id,
            )

            logger.info(
                "AI metadata generated for %s: '%s'",
                clip_id, metadata.get("title", "")[:60],
            )

        except Exception as e:
            self._failed += 1
            logger.error("AI metadata generation failed: %s", e, exc_info=True)

    def get_status(self) -> dict:
        return {
            "generated": self._generated,
            "failed": self._failed,
            "streamer_name": self.streamer_name,
            "default_platform": self.default_platform,
        }
