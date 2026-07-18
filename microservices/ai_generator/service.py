"""
AI Generator Microservice (v2 - LLM Powered)
─────────────────────────────────────────────
Subscribes to CLIP_CREATED → generates title, description, hashtags, tags.
Now powered by multi-provider LLM engine with template fallback.

Upgrades from v1:
  - Actual LLM-powered generation (OpenAI/Claude/Ollama)
  - Multi-platform optimized output (YouTube, TikTok, Instagram, Twitter)
  - A/B title variant generation
  - Thumbnail concept suggestions
  - Clip analysis for quality scoring
  - Translation support (TR ↔ EN)

Publishes AI_METADATA_READY when done.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from services import llm_client
from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("ai_generator_ms")


class AIGeneratorMicroservice:
    """
    Event-driven AI metadata generator v2.

    On CLIP_CREATED, generates:
    - Clickbait-friendly title (multiple variants)
    - Description text
    - Platform-specific hashtag lists
    - Tag suggestions
    - Thumbnail concept
    - Clip quality analysis

    Uses LLM engine with automatic provider fallback:
    OpenAI → Claude → Ollama → Template
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        streamer_name: str = "Tuncay",
        default_platforms: tuple[str, ...] = ("youtube", "tiktok", "instagram"),
        default_platform: str = "youtube",
        language: str = "tr",
    ):
        self.event_bus = event_bus or get_event_bus()
        self.streamer_name = streamer_name
        # Support both old (default_platform) and new (default_platforms) API
        if default_platform != "youtube":
            self.default_platforms = (default_platform,)
        else:
            self.default_platforms = default_platforms
        self.language = language
        self.default_platform = self.default_platforms[0]  # backward compat

        # Metrics
        self._generated = 0
        self._failed = 0
        self._titles_generated = 0
        self._llm_used_count = 0
        self._fallback_used_count = 0

        # Subscribe to CLIP_CREATED
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

        logger.info(
            "AIGeneratorMicroservice v2 initialized (streamer=%s, platforms=%s)",
            self.streamer_name, self.default_platforms,
        )

    async def _on_clip_created(self, event: SystemEvent):
        """Handle clip created — generate AI metadata with LLM."""
        payload = event.payload
        clip_id = payload.get("clip_id", "")
        category = payload.get("category", "exciting")
        tags = payload.get("tags", [])
        score = payload.get("highlight_score", 0.0)
        emotion = payload.get("emotion", category)
        game_name = payload.get("game_name", "")
        viewer_count = payload.get("viewer_count", 0)
        stream_title = payload.get("stream_title", "")
        duration = payload.get("duration", 30)

        try:
            # Determine emotion from category
            emotion_map = {
                "exciting": "excitement", "hype": "hype", "funny": "funny",
                "rage": "rage", "emotional": "emotional",
                "victory": "victory", "skill": "skill",
                "celebration": "victory", "highlight": "excitement",
                "fail": "fail",
            }
            mapped_emotion = emotion_map.get(category, emotion or "excitement")

            # Generate titles (multiple variants for A/B testing)
            titles = await llm_client.generate_titles(
                streamer_name=self.streamer_name,
                category=category,
                emotion=mapped_emotion,
                platform="youtube",
                game_name=game_name,
                viewer_count=viewer_count,
                tags=tags,
                count=5,
                language=self.language,
            )
            self._titles_generated += len(titles)

            # Generate description
            description = await llm_client.generate_description(
                title=titles[0] if titles else f"{self.streamer_name} highlight",
                streamer_name=self.streamer_name,
                category=category,
                emotion=mapped_emotion,
                platform="youtube",
                game_name=game_name,
                language=self.language,
            )

            # Generate hashtags
            hashtags = await llm_client.generate_hashtags(
                category=category,
                game_name=game_name,
                streamer_name=self.streamer_name,
                emotion=mapped_emotion,
                platform="youtube",
                count=20,
                language=self.language,
            )

            # Generate thumbnail suggestion
            thumbnail = await llm_client.suggest_thumbnail(
                title=titles[0] if titles else "",
                streamer_name=self.streamer_name,
                category=category,
                emotion=mapped_emotion,
                platform="youtube",
            )

            # Build per-platform optimized metadata
            platform_metadata = {}
            for platform in self.default_platforms:
                try:
                    platform_tags = await llm_client.generate_hashtags(
                        category=category,
                        game_name=game_name,
                        streamer_name=self.streamer_name,
                        emotion=mapped_emotion,
                        platform=platform,
                        count=15,
                        language=self.language,
                    )
                except Exception:
                    platform_tags = hashtags[:10]

                platform_title = titles[min(
                    hash(platform) % len(titles), len(titles) - 1
                )] if titles else titles[0] if titles else ""

                platform_metadata[platform] = {
                    "title": platform_title,
                    "hashtags": platform_tags,
                }

            self._generated += 1
            if llm_client.get_stats().get("fallback_count", 0) == 0:
                self._llm_used_count += 1
            else:
                self._fallback_used_count += 1

            # Publish AI_METADATA_READY
            await self.event_bus.publish_quick(
                EventType.AI_METADATA_READY,
                payload={
                    "clip_id": clip_id,
                    "title": titles[0] if titles else "",
                    "title_variants": titles,
                    "description": description,
                    "hashtags": hashtags,
                    "category": category,
                    "emotion": mapped_emotion,
                    "highlight_score": score,
                    "thumbnail_concept": thumbnail,
                    "platform_metadata": platform_metadata,
                    "source": "llm_engine_v2",
                    "generated_at": datetime.utcnow().isoformat(),
                },
                source_service="ai_generator",
                stream_id=event.stream_id,
                causation_id=event.event_id,
            )

            logger.info(
                "AI metadata generated for %s: '%s' (%d title variants)",
                clip_id,
                titles[0][:60] if titles else "N/A",
                len(titles),
            )

        except Exception as e:
            self._failed += 1
            logger.error("AI metadata generation failed: %s", e, exc_info=True)

            # Fallback to old template-based generator
            try:
                from src.ai_generator import ai_title_generator
                metadata = ai_title_generator.generate_full_metadata(
                    emotion=mapped_emotion,
                    category=category,
                    streamer_name=self.streamer_name,
                    viewer_count=viewer_count,
                    stream_title=stream_title,
                    game_name=game_name,
                    platform="youtube",
                    custom_tags=tags,
                )
                await self.event_bus.publish_quick(
                    EventType.AI_METADATA_READY,
                    payload={
                        "clip_id": clip_id,
                        "title": metadata.get("title", ""),
                        "description": metadata.get("description", ""),
                        "hashtags": metadata.get("hashtags", []),
                        "category": category,
                        "emotion": mapped_emotion,
                        "highlight_score": score,
                        "source": "template_fallback",
                    },
                    source_service="ai_generator",
                    stream_id=event.stream_id,
                    causation_id=event.event_id,
                )
            except Exception as fallback_err:
                logger.critical(
                    "Both LLM and template fallback failed: %s", fallback_err,
                )

    def get_status(self) -> dict:
        llm_stats = llm_client.get_stats()
        return {
            "generated": self._generated,
            "failed": self._failed,
            "titles_generated": self._titles_generated,
            "llm_used": self._llm_used_count,
            "fallback_used": self._fallback_used_count,
            "streamer_name": self.streamer_name,
            "default_platform": self.default_platform,
            "default_platforms": list(self.default_platforms),
            "language": self.language,
            "llm_engine": llm_stats,
        }