"""
Decision Engine Microservice
─────────────────────────────
Makes the final clip/no-clip decision based on highlight scores.

Architecture:
  Layer 1: Threshold Gate (score > adjusted threshold?)
  Layer 2: Cooldown Check (enough time since last clip?)
  Layer 3: Minimum Evidence (at least N signals active?)
  Layer 4: Temporal Confirmation (score sustained over window?)
  Layer 5: (Optional) LLM Validation

Multi-stream aware: each stream_id gets its own confirmation window
and cooldown timer.

All parameters are configurable via config.py:
  - decision_clip_threshold
  - decision_cooldown_seconds
  - decision_min_evidence
  - decision_confirmation_window
  - decision_confirmation_required
  - decision_threshold_floor
  - decision_evidence_threshold
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import datetime
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, HighlightScore,
    ClipCandidate, DecisionResult,
)

logger = logging.getLogger("decision_engine")


class ConfirmationWindow:
    """
    Temporal confirmation window for false-positive reduction.

    Instead of creating a clip the instant a single score exceeds
    the threshold, we require the score to stay above threshold for
    at least `required` out of the last `window_size` evaluations.

    Example (window=3, required=2):
        Eval 1: score=0.62, threshold=0.55 → PASS
        Eval 2: score=0.40, threshold=0.55 → FAIL
        Eval 3: score=0.68, threshold=0.55 → PASS  → CONFIRMED (2/3 passed)

    This filters out transient spikes (a single loud noise, a one-off
    chat burst) while still catching genuine sustained highlights.
    """

    def __init__(self, window_size: int = 3, required: int = 2):
        self.window_size = max(1, window_size)
        self.required = max(1, min(required, self.window_size))
        self._history: deque[tuple[float, bool]] = deque(
            maxlen=self.window_size,
        )

    def record(self, score: float, threshold: float) -> None:
        """Record an evaluation result."""
        passed = score >= threshold
        self._history.append((score, passed))

    def is_confirmed(self) -> bool:
        """Check if enough evaluations in the window passed."""
        if len(self._history) < self.required:
            return False
        passes = sum(1 for _, p in self._history if p)
        return passes >= self.required

    @property
    def pass_count(self) -> int:
        return sum(1 for _, p in self._history if p)

    @property
    def eval_count(self) -> int:
        return len(self._history)

    @property
    def avg_score(self) -> float:
        if not self._history:
            return 0.0
        return sum(s for s, _ in self._history) / len(self._history)

    def get_status(self) -> dict:
        return {
            "window_size": self.window_size,
            "required": self.required,
            "pass_count": self.pass_count,
            "eval_count": self.eval_count,
            "avg_score": round(self.avg_score, 4),
            "confirmed": self.is_confirmed(),
        }

    def reset(self) -> None:
        """Clear window history (e.g., after clip creation or stream change)."""
        self._history.clear()


class DecisionEngineService:
    """
    Makes clip/no-clip decisions with temporal confirmation.

    Subscribes to EVENT_SCORED events from EventDetector.
    Publishes CLIP_CANDIDATE or CLIP_REJECTED events.

    Multi-stream aware: each stream_id gets its own:
      - ConfirmationWindow
      - Cooldown timer

    Decision layers:
      1. Threshold gate with state-adjusted multiplier + floor
      2. Cooldown (minimum time between clips, per-stream)
      3. Minimum evidence (N signals above evidence_threshold)
      4. Temporal confirmation (score sustained over window, per-stream)
    """

    DEFAULT_STREAM = "default"

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        clip_threshold: float = 0.55,
        cooldown_seconds: float = 15.0,
        min_evidence_signals: int = 2,
        confirmation_window: int = 3,
        confirmation_required: int = 2,
        threshold_floor: float = 0.35,
        evidence_threshold: float = 0.2,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.clip_threshold = clip_threshold
        self.cooldown_seconds = cooldown_seconds
        self.min_evidence_signals = min_evidence_signals
        self.threshold_floor = threshold_floor
        self.evidence_threshold = evidence_threshold

        self._window_size = confirmation_window
        self._window_required = confirmation_required

        # Per-stream state
        self._stream_confirmation: dict[str, ConfirmationWindow] = {}
        self._stream_last_clip: dict[str, Optional[float]] = {}

        self._clips_created = 0
        self._clips_rejected = 0
        self._confirmation_rejects = 0

        # Subscribe to scored events
        self.event_bus.subscribe(
            EventType.EVENT_SCORED.value,
            self._on_scored_event,
        )

    def _get_confirmation(self, stream_id: str) -> ConfirmationWindow:
        """Get or create ConfirmationWindow for a stream."""
        if stream_id not in self._stream_confirmation:
            self._stream_confirmation[stream_id] = ConfirmationWindow(
                window_size=self._window_size,
                required=self._window_required,
            )
            self._stream_last_clip[stream_id] = None
        return self._stream_confirmation[stream_id]

    def _get_last_clip_time(self, stream_id: str) -> Optional[float]:
        self._get_confirmation(stream_id)  # ensures entry exists
        return self._stream_last_clip[stream_id]

    # Backward-compatible property (uses "default" stream)
    @property
    def _confirmation(self) -> ConfirmationWindow:
        return self._get_confirmation(self.DEFAULT_STREAM)

    @property
    def _last_clip_time(self) -> Optional[float]:
        return self._get_last_clip_time(self.DEFAULT_STREAM)

    @_last_clip_time.setter
    def _last_clip_time(self, value: Optional[float]):
        self._get_confirmation(self.DEFAULT_STREAM)
        self._stream_last_clip[self.DEFAULT_STREAM] = value

    async def _on_scored_event(self, event: SystemEvent):
        """Evaluate each scored event for clip creation."""
        stream_id = event.stream_id or self.DEFAULT_STREAM
        score_data = event.payload.get("score", {})
        threshold_mult = event.payload.get("threshold_multiplier", 1.0)

        score = HighlightScore(
            composite_score=score_data.get("composite_score", 0.0),
            breakdown=score_data.get("breakdown", {}),
            timestamp=score_data.get("timestamp", time.time()),
            active_signals=score_data.get("active_signals", 0),
        )

        decision = self.evaluate(score, threshold_mult, stream_id=stream_id)
        confirmation = self._get_confirmation(stream_id)

        if decision.decision == "CREATE_CLIP":
            candidate = ClipCandidate(
                stream_id=event.stream_id,
                event_timestamp=datetime.utcnow(),
                start_time=datetime.utcnow(),
                end_time=datetime.utcnow(),
                highlight_score=score,
                trigger_signals=[
                    k for k, v in score.breakdown.items()
                    if v > self.evidence_threshold
                ],
                priority=score.composite_score,
            )

            self._clips_created += 1
            self._stream_last_clip[stream_id] = time.time()

            await self.event_bus.publish_quick(
                EventType.CLIP_CANDIDATE,
                {
                    "candidate": candidate.model_dump(mode="json"),
                    "decision": decision.model_dump(mode="json"),
                    "confirmation": confirmation.get_status(),
                },
                source_service="decision-engine",
                stream_id=event.stream_id,
            )
        else:
            if "confirmation" in decision.reason.lower() or "Confirmation" in decision.reason:
                self._confirmation_rejects += 1
            self._clips_rejected += 1

    def evaluate(
        self,
        score: HighlightScore,
        threshold_multiplier: float = 1.0,
        stream_id: str = "default",
    ) -> DecisionResult:
        """
        Multi-layer decision evaluation.

        Returns DecisionResult with CREATE_CLIP or REJECT.
        """
        confirmation = self._get_confirmation(stream_id)
        last_clip = self._get_last_clip_time(stream_id)

        # Layer 1: Threshold gate (with floor)
        adjusted_threshold = max(
            self.clip_threshold * threshold_multiplier,
            self.threshold_floor,
        )

        # Record in confirmation window
        confirmation.record(score.composite_score, adjusted_threshold)

        if score.composite_score < adjusted_threshold:
            return DecisionResult(
                decision="REJECT",
                reason=(
                    f"Score {score.composite_score:.3f} < "
                    f"threshold {adjusted_threshold:.3f} "
                    f"(floor={self.threshold_floor})"
                ),
                score=score,
            )

        # Layer 2: Cooldown check (per-stream)
        now = time.time()
        if last_clip is not None:
            elapsed = now - last_clip
            if elapsed < self.cooldown_seconds:
                return DecisionResult(
                    decision="REJECT",
                    reason=f"Cooldown: {elapsed:.1f}s < {self.cooldown_seconds}s",
                    score=score,
                )

        # Layer 3: Minimum evidence
        evidence_count = sum(
            1 for v in score.breakdown.values()
            if v > self.evidence_threshold
        )
        # Combo fast-track: 4+ active signals = relax evidence requirement
        required_evidence = (
            max(1, self.min_evidence_signals - 1)
            if score.active_signals >= 4
            else self.min_evidence_signals
        )
        if evidence_count < required_evidence:
            return DecisionResult(
                decision="REJECT",
                reason=(
                    f"Only {evidence_count} evidence signals "
                    f"(need {required_evidence})"
                ),
                score=score,
            )

        # Layer 4: Temporal confirmation window (per-stream)
        if not confirmation.is_confirmed():
            return DecisionResult(
                decision="REJECT",
                reason=(
                    f"Confirmation pending: "
                    f"{confirmation.pass_count}/"
                    f"{confirmation.required} passed "
                    f"(window={confirmation.window_size})"
                ),
                score=score,
            )

        # APPROVED
        confirmation.reset()
        self._stream_last_clip[stream_id] = time.time()
        return DecisionResult(
            decision="CREATE_CLIP",
            reason=(
                f"Score {score.composite_score:.3f} confirmed with "
                f"{evidence_count} signals "
                f"({confirmation.pass_count}/"
                f"{confirmation.eval_count} window passes)"
            ),
            score=score,
            priority=score.composite_score,
        )

    def get_status(self) -> dict:
        default_conf = self._get_confirmation(self.DEFAULT_STREAM)
        default_last = self._get_last_clip_time(self.DEFAULT_STREAM)
        return {
            "clip_threshold": self.clip_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "min_evidence_signals": self.min_evidence_signals,
            "threshold_floor": self.threshold_floor,
            "evidence_threshold": self.evidence_threshold,
            "clips_created": self._clips_created,
            "clips_rejected": self._clips_rejected,
            "confirmation_rejects": self._confirmation_rejects,
            "last_clip_time": default_last,
            "time_since_last_clip": (
                round(time.time() - default_last, 1)
                if default_last else None
            ),
            "confirmation_window": default_conf.get_status(),
            "active_streams": list(self._stream_confirmation.keys()),
        }
