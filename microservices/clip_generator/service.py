"""
Clip Generator Microservice
────────────────────────────
Extracts clips from rolling buffer when approved by Decision Engine.

Flow: CLIP_CANDIDATE → Extract from Buffer → Classify → Save → Events
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, ClipCandidate, ClipResult,
)

logger = logging.getLogger("clip_generator")


class ClipGeneratorService:
    """
    Generates clips from the rolling buffer.

    Subscribes to CLIP_CANDIDATE events from Decision Engine.
    Extracts frames from capture buffer, writes video file,
    classifies content, and publishes CLIP_CREATED events.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        capture_service=None,
        output_dir: str = "data/clips",
    ):
        self.event_bus = event_bus or get_event_bus()
        self.capture_service = capture_service
        self.output_dir = output_dir

        os.makedirs(output_dir, exist_ok=True)

        self._clips_generated = 0
        self._clips_failed = 0

        # Subscribe to clip candidates
        self.event_bus.subscribe(
            EventType.CLIP_CANDIDATE.value,
            self._on_clip_candidate,
        )

    async def _on_clip_candidate(self, event: SystemEvent):
        """Handle a new clip candidate — extract the clip."""
        candidate_data = event.payload.get("candidate", {})
        score = candidate_data.get("highlight_score", {}).get("composite_score", 0.0)

        logger.info(
            f"Clip candidate received! Score: {score:.3f} "
            f"Signals: {candidate_data.get('trigger_signals', [])}"
        )

        # Extract clip from buffer
        clip_path = await self._extract_clip(candidate_data)

        if clip_path and os.path.exists(clip_path):
            clip_result = ClipResult(
                file_path=clip_path,
                duration_seconds=self._estimate_duration(candidate_data),
                start_time=datetime.now(timezone.utc),
                end_time=datetime.now(timezone.utc),
                highlight_score=score,
                category=self._categorize(candidate_data),
                tags=candidate_data.get("trigger_signals", []),
                metadata={
                    "candidate_id": candidate_data.get("candidate_id", ""),
                    "score_breakdown": candidate_data.get("highlight_score", {}).get("breakdown", {}),
                },
            )

            self._clips_generated += 1

            await self.event_bus.publish_quick(
                EventType.CLIP_CREATED,
                clip_result.model_dump(mode="json"),
                source_service="clip-generator",
                stream_id=event.stream_id,
            )

            logger.info(f"Clip created: {clip_path}")
        else:
            self._clips_failed += 1
            logger.warning("Clip extraction failed")

    async def _extract_clip(self, candidate_data: dict) -> Optional[str]:
        """Extract clip from rolling buffer."""
        if self.capture_service is None:
            logger.warning("No capture service available for clip extraction")
            return None

        event_time_str = candidate_data.get("event_timestamp")
        if event_time_str:
            try:
                event_time = datetime.fromisoformat(event_time_str)
            except (ValueError, TypeError):
                event_time = datetime.now(timezone.utc)
        else:
            event_time = datetime.now(timezone.utc)

        # Use capture service's clip extraction
        output_path = os.path.join(
            self.output_dir,
            f"clip_{int(time.time())}_{candidate_data.get('candidate_id', 'unknown')[:8]}.mp4"
        )

        # Extract from buffer (this is synchronous, run in executor)
        import asyncio
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self.capture_service.extract_clip(
                event_time=event_time,
                pre_seconds=5.0,
                post_seconds=5.0,
                output_path=output_path,
            )
        )

        return result

    def _estimate_duration(self, candidate_data: dict) -> float:
        return 10.0  # Default: 5s pre + 5s post

    def _categorize(self, candidate_data: dict) -> str:
        """Categorize clip based on trigger signals and score.

        Priority (highest first):
        1. donation + chat_velocity → epic_moment
        2. audio_spike + emotion_intensity → exciting
        3. donation → donation
        4. pose_gesture → celebration
        5. chat_velocity → hype
        6. chat_sentiment → funny
        7. emotion_intensity → emotional
        8. default → highlight
        """
        signals = set(candidate_data.get("trigger_signals", []))
        score = candidate_data.get("highlight_score", {}).get("composite_score", 0.0)

        # Multi-signal combos
        if "donation" in signals and "chat_velocity" in signals:
            return "epic_moment"
        if "audio_spike" in signals and "emotion_intensity" in signals:
            return "exciting"
        if "audio_spike" in signals and "chat_velocity" in signals:
            return "hype"
        if "pose_gesture" in signals and "emotion_intensity" in signals:
            return "celebration"

        # Single-signal categories
        if "donation" in signals:
            return "donation"
        if "pose_gesture" in signals:
            return "celebration"
        if "chat_velocity" in signals:
            return "hype"
        if "chat_sentiment" in signals:
            return "funny"
        if "emotion_intensity" in signals:
            return "emotional"
        if "audio_spike" in signals:
            return "loud_moment"

        # Score-based fallback
        if score >= 0.9:
            return "epic_moment"
        if score >= 0.7:
            return "exciting"

        return "highlight"

    def get_status(self) -> dict:
        return {
            "clips_generated": self._clips_generated,
            "clips_failed": self._clips_failed,
            "output_dir": self.output_dir,
            "capture_connected": self.capture_service is not None,
        }
