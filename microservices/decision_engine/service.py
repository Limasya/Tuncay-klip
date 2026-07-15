"""
Decision Engine Microservice
─────────────────────────────
Makes the final clip/no-clip decision based on highlight scores.

Architecture:
  Layer 1: Threshold Gate (score > threshold?)
  Layer 2: Cooldown Check (enough time since last clip?)
  Layer 3: Minimum Evidence (at least 2 signals active?)
  Layer 4: (Optional) LLM Validation
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, HighlightScore,
    ClipCandidate, DecisionResult,
)

logger = logging.getLogger("decision_engine")


class DecisionEngineService:
    """
    Makes clip/no-clip decisions.

    Subscribes to EVENT_SCORED events from EventDetector.
    Publishes CLIP_CANDIDATE or CLIP_REJECTED events.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        clip_threshold: float = 0.55,
        cooldown_seconds: float = 15.0,
        min_evidence_signals: int = 2,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.clip_threshold = clip_threshold
        self.cooldown_seconds = cooldown_seconds
        self.min_evidence_signals = min_evidence_signals

        self._last_clip_time: Optional[float] = None
        self._clips_created = 0
        self._clips_rejected = 0

        # Subscribe to scored events
        self.event_bus.subscribe(
            EventType.EVENT_SCORED.value,
            self._on_scored_event,
        )

    async def _on_scored_event(self, event: SystemEvent):
        """Evaluate each scored event for clip creation."""
        score_data = event.payload.get("score", {})
        threshold_mult = event.payload.get("threshold_multiplier", 1.0)

        score = HighlightScore(
            composite_score=score_data.get("composite_score", 0.0),
            breakdown=score_data.get("breakdown", {}),
            timestamp=score_data.get("timestamp", time.time()),
            active_signals=score_data.get("active_signals", 0),
        )

        decision = self.evaluate(score, threshold_mult)

        if decision.decision == "CREATE_CLIP":
            candidate = ClipCandidate(
                stream_id=event.stream_id,
                event_timestamp=datetime.utcnow(),
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                highlight_score=score,
                trigger_signals=[
                    k for k, v in score.breakdown.items() if v > 0.2
                ],
                priority=score.composite_score,
            )

            self._clips_created += 1
            self._last_clip_time = time.time()

            await self.event_bus.publish_quick(
                EventType.CLIP_CANDIDATE,
                {
                    "candidate": candidate.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                },
                source_service="decision-engine",
                stream_id=event.stream_id,
            )
        else:
            self._clips_rejected += 1

    def evaluate(
        self,
        score: HighlightScore,
        threshold_multiplier: float = 1.0,
    ) -> DecisionResult:
        """
        Multi-layer decision evaluation.

        Returns DecisionResult with CREATE_CLIP or REJECT.
        """
        adjusted_threshold = self.clip_threshold * threshold_multiplier

        # Layer 1: Threshold gate
        if score.composite_score < adjusted_threshold:
            return DecisionResult(
                decision="REJECT",
                reason=f"Score {score.composite_score:.3f} < threshold {adjusted_threshold:.3f}",
                score=score,
            )

        # Layer 2: Cooldown check
        now = time.time()
        if self._last_clip_time is not None:
            elapsed = now - self._last_clip_time
            if elapsed < self.cooldown_seconds:
                return DecisionResult(
                    decision="REJECT",
                    reason=f"Cooldown: {elapsed:.1f}s < {self.cooldown_seconds}s",
                    score=score,
                )

        # Layer 3: Minimum evidence
        evidence_count = sum(
            1 for v in score.breakdown.values() if v > 0.2
        )
        if evidence_count < self.min_evidence_signals:
            return DecisionResult(
                decision="REJECT",
                reason=f"Only {evidence_count} evidence signals (need {self.min_evidence_signals})",
                score=score,
            )

        # APPROVED
        return DecisionResult(
            decision="CREATE_CLIP",
            reason=f"Score {score.composite_score:.3f} with {evidence_count} signals",
            score=score,
            priority=score.composite_score,
        )

    def get_status(self) -> dict:
        return {
            "clip_threshold": self.clip_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "min_evidence_signals": self.min_evidence_signals,
            "clips_created": self._clips_created,
            "clips_rejected": self._clips_rejected,
            "last_clip_time": self._last_clip_time,
            "time_since_last_clip": (
                round(time.time() - self._last_clip_time, 1)
                if self._last_clip_time else None
            ),
        }
