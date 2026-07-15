"""
Event Detector Microservice
────────────────────────────
Aggregates signals from all analysis services and computes
a composite highlight score.

This is the BRAIN of the system.

Signals:
  audio_spike     (0.20) — Screaming/yelling
  chat_velocity   (0.18) — Audience reaction
  emotion_intensity(0.15) — Facial expressions
  emotion_change  (0.10) — Sudden shifts
  pose_gesture    (0.12) — Physical reactions
  pose_motion     (0.08) — Body movement
  chat_sentiment  (0.07) — Audience mood
  viewer_delta    (0.05) — Audience growth
  ocr_keyword     (0.03) — On-screen text
  speech_content  (0.02) — Transcription keywords
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Optional

import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, HighlightScore, StreamState,
)

logger = logging.getLogger("event_detector")


class ScoringEngine:
    """
    Computes composite highlight score from multiple signals.
    Uses temporal decay — recent events matter more.
    """

    WEIGHTS = {
        "audio_spike": 0.20,
        "chat_velocity": 0.18,
        "emotion_intensity": 0.15,
        "emotion_change": 0.10,
        "pose_gesture": 0.12,
        "pose_motion": 0.08,
        "chat_sentiment": 0.05,
        "viewer_delta": 0.03,
        "ocr_keyword": 0.02,
        "speech_content": 0.02,
        "donation": 0.05,
    }

    DECAY_HALFLIFE = 5.0  # seconds

    def __init__(self):
        self._signal_history: dict[str, deque] = {
            signal: deque(maxlen=120)
            for signal in self.WEIGHTS
        }

    def update_signal(self, signal_name: str, value: float):
        if signal_name in self._signal_history:
            self._signal_history[signal_name].append((time.time(), value))

    def compute_score(self, window_seconds: float = 10.0) -> HighlightScore:
        now = time.time()
        composite = 0.0
        breakdown = {}
        active_count = 0

        for signal_name, weight in self.WEIGHTS.items():
            history = self._signal_history.get(signal_name, deque())
            window_values = [
                (ts, val) for ts, val in history
                if now - ts <= window_seconds
            ]

            if not window_values:
                breakdown[signal_name] = 0.0
                continue

            # Temporal decay
            decayed_sum = 0.0
            for ts, val in window_values:
                age = now - ts
                decay = 2 ** (-age / self.DECAY_HALFLIFE)
                decayed_sum += val * decay

            signal_score = min(decayed_sum / max(len(window_values), 1), 1.0)
            breakdown[signal_name] = round(signal_score, 4)
            composite += signal_score * weight

            if signal_score > 0.2:
                active_count += 1

        return HighlightScore(
            composite_score=round(self._apply_combo_boost(composite, active_count), 4),
            breakdown=breakdown,
            timestamp=now,
            active_signals=active_count,
        )

    @staticmethod
    def _apply_combo_boost(score: float, active_signals: int) -> float:
        """
        When 3+ signals fire simultaneously, apply a combo multiplier.
        This captures moments where audio + chat + emotion all spike at once
        — typically the best clips.

        2 active: no boost
        3 active: 1.15x
        4 active: 1.30x
        5+ active: 1.50x (capped)
        """
        if active_signals >= 5:
            return min(score * 1.50, 1.0)
        elif active_signals >= 4:
            return min(score * 1.30, 1.0)
        elif active_signals >= 3:
            return min(score * 1.15, 1.0)
        return score


class StreamStateMachine:
    """
    Tracks stream state. State affects clip threshold.

    OFFLINE → STARTING → WARMING_UP → STEADY ←→ HIGH_ENERGY → PEAK
                                                    ↓
                                               COOLING_DOWN → STEADY
                                                              ↓
                                                           ENDING → OFFLINE
    """

    THRESHOLD_ADJUSTMENTS = {
        StreamState.OFFLINE: 1.0,
        StreamState.STARTING: 1.0,
        StreamState.WARMING_UP: 1.2,
        StreamState.STEADY: 1.0,
        StreamState.HIGH_ENERGY: 0.8,
        StreamState.PEAK_MOMENT: 0.6,
        StreamState.COOLING_DOWN: 1.1,
        StreamState.ENDING: 1.3,
    }

    # Time in current state before considering auto-transition
    WARMING_UP_DURATION = 120.0      # 2 min warm-up after start
    COOLING_DOWN_DURATION = 30.0     # 30s cooling after energy drop
    ENDING_DETECTION_WINDOW = 60.0   # 60s of near-zero activity = ending

    def __init__(self):
        self.state = StreamState.OFFLINE
        self._entered_at = 0.0
        self._peak_score_history: list[tuple[float, float]] = []  # (time, score)

    def transition(self, new_state: StreamState):
        if new_state != self.state:
            old = self.state
            self.state = new_state
            self._entered_at = time.time()
            logger.info(f"Stream state: {old.value} → {new_state.value}")

    def update_from_score(self, score: float):
        """
        Update state based on composite score + time.

        Logic:
          - After STARTING, auto-transition to WARMING_UP
          - WARMING_UP lasts WARMING_UP_DURATION seconds → STEADY
          - Score > 0.8 → PEAK_MOMENT
          - Score > 0.5 → HIGH_ENERGY
          - Score drops below 0.3 from HIGH_ENERGY/PEAK → COOLING_DOWN
          - COOLING_DOWN lasts COOLING_DOWN_DURATION → STEADY
          - Near-zero activity for ENDING_DETECTION_WINDOW → ENDING
        """
        now = time.time()
        self._peak_score_history.append((now, score))
        # Keep last 120 entries
        self._peak_score_history = self._peak_score_history[-120:]

        time_in_state = now - self._entered_at if self._entered_at else 0

        # STARTING → WARMING_UP (automatic after 10s)
        if self.state == StreamState.STARTING and time_in_state > 10:
            self.transition(StreamState.WARMING_UP)
            return

        # WARMING_UP → STEADY (after warm-up period)
        if self.state == StreamState.WARMING_UP and time_in_state > self.WARMING_UP_DURATION:
            self.transition(StreamState.STEADY)
            return

        # COOLING_DOWN → STEADY (after cooling period)
        if self.state == StreamState.COOLING_DOWN and time_in_state > self.COOLING_DOWN_DURATION:
            self.transition(StreamState.STEADY)
            return

        # Score-based transitions
        if score > 0.8:
            if self.state not in (StreamState.PEAK_MOMENT,):
                self.transition(StreamState.PEAK_MOMENT)
        elif score > 0.5:
            if self.state not in (StreamState.HIGH_ENERGY, StreamState.PEAK_MOMENT):
                self.transition(StreamState.HIGH_ENERGY)
        elif score < 0.2 and self.state in (
            StreamState.HIGH_ENERGY, StreamState.PEAK_MOMENT
        ):
            # Energy dropped significantly → cooling down
            self.transition(StreamState.COOLING_DOWN)
        elif score < 0.1 and self.state == StreamState.STEADY:
            # Check for ending: sustained near-zero activity
            recent = [
                s for t, s in self._peak_score_history
                if now - t < self.ENDING_DETECTION_WINDOW
            ]
            if len(recent) >= 5 and all(s < 0.1 for s in recent):
                self.transition(StreamState.ENDING)

    def get_threshold_multiplier(self) -> float:
        return self.THRESHOLD_ADJUSTMENTS.get(self.state, 1.0)


class EventDetectorService:
    """
    Main event detector service.
    Subscribes to all analysis events and produces highlight scores.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        score_threshold: float = 0.5,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.scoring = ScoringEngine()
        self.state_machine = StreamStateMachine()
        self.score_threshold = score_threshold

        self._last_score_time = 0.0
        self._score_interval = 2.0  # Compute score every 2 seconds

        self._metrics = {
            "events_processed": 0,
            "high_scores": 0,
            "current_score": 0.0,
            "stream_state": StreamState.OFFLINE.value,
        }

        # Subscribe to all analysis events
        self._subscribe_all()

    def _subscribe_all(self):
        """Subscribe to all relevant event types."""
        handlers = {
            EventType.AUDIO_SPIKE.value: self._on_audio_spike,
            EventType.AUDIO_FEATURES.value: self._on_audio_features,
            EventType.EMOTION_DETECTED.value: self._on_emotion,
            EventType.POSE_DETECTED.value: self._on_pose,
            EventType.FACE_DETECTED.value: self._on_face,
            EventType.CHAT_SPIKE.value: self._on_chat_spike,
            EventType.CHAT_SENTIMENT.value: self._on_chat_sentiment,
            EventType.TEXT_DETECTED.value: self._on_text,
            EventType.VIEWER_COUNT.value: self._on_viewer,
            EventType.STREAM_STARTED.value: self._on_stream_start,
            EventType.STREAM_ENDED.value: self._on_stream_end,
            EventType.DONATION_RECEIVED.value: self._on_donation,
        }
        for event_type, handler in handlers.items():
            self.event_bus.subscribe(event_type, handler)

    async def _on_audio_spike(self, event: SystemEvent):
        magnitude = event.payload.get("peak_magnitude", 0.5)
        self.scoring.update_signal("audio_spike", min(magnitude, 1.0))
        self._metrics["events_processed"] += 1
        await self._maybe_emit_score()

    async def _on_audio_features(self, event: SystemEvent):
        spike_mag = event.payload.get("spike_magnitude", 0.0)
        if spike_mag > 0.3:
            self.scoring.update_signal("audio_spike", spike_mag)
        self._metrics["events_processed"] += 1

    async def _on_emotion(self, event: SystemEvent):
        emotions = event.payload.get("emotions", [])
        highlight_emotions = {"happy", "surprise", "fear", "angry"}
        max_intensity = 0.0

        for e in emotions:
            label = e.get("label", "neutral")
            conf = e.get("confidence", 0.0)
            if label in highlight_emotions:
                intensity = conf * 1.5
            else:
                intensity = conf * 0.5
            max_intensity = max(max_intensity, intensity)

        self.scoring.update_signal("emotion_intensity", min(max_intensity, 1.0))
        self._metrics["events_processed"] += 1
        await self._maybe_emit_score()

    async def _on_pose(self, event: SystemEvent):
        poses = event.payload.get("poses", [])
        max_gesture = 0.0
        max_motion = 0.0

        for p in poses:
            gestures = p.get("gestures", [])
            if gestures:
                max_gesture = max(max_gesture, 0.7 + len(gestures) * 0.1)
            motion = p.get("motion_score", 0.0)
            max_motion = max(max_motion, min(motion * 5, 1.0))

        self.scoring.update_signal("pose_gesture", min(max_gesture, 1.0))
        self.scoring.update_signal("pose_motion", min(max_motion, 1.0))
        self._metrics["events_processed"] += 1
        await self._maybe_emit_score()

    async def _on_face(self, event: SystemEvent):
        self._metrics["events_processed"] += 1

    async def _on_chat_spike(self, event: SystemEvent):
        ratio = event.payload.get("spike_ratio", 1.0)
        normalized = min(ratio / 10.0, 1.0)
        self.scoring.update_signal("chat_velocity", normalized)
        self._metrics["events_processed"] += 1
        await self._maybe_emit_score()

    async def _on_chat_sentiment(self, event: SystemEvent):
        sentiment = event.payload.get("sentiment", {})
        score = abs(sentiment.get("score", 0.0))
        self.scoring.update_signal("chat_sentiment", min(score, 1.0))
        self._metrics["events_processed"] += 1

    async def _on_text(self, event: SystemEvent):
        if event.payload.get("is_highlight_keyword"):
            self.scoring.update_signal("ocr_keyword", 0.8)
        self._metrics["events_processed"] += 1

    async def _on_viewer(self, event: SystemEvent):
        delta = event.payload.get("delta", 0)
        normalized = min(abs(delta) / 100.0, 1.0)
        self.scoring.update_signal("viewer_delta", normalized)
        self._metrics["events_processed"] += 1

    async def _on_stream_start(self, event: SystemEvent):
        self.state_machine.transition(StreamState.STARTING)
        self._metrics["stream_state"] = self.state_machine.state.value

    async def _on_stream_end(self, event: SystemEvent):
        self.state_machine.transition(StreamState.OFFLINE)
        self._metrics["stream_state"] = self.state_machine.state.value

    async def _on_donation(self, event: SystemEvent):
        """Donation = strong highlight signal."""
        amount = event.payload.get("amount", 0.0)
        # Scale: $1 = 0.3, $5 = 0.6, $10+ = 1.0
        value = min(amount / 10.0, 1.0) if amount > 0 else 0.5
        self.scoring.update_signal("donation", max(value, 0.5))
        self._metrics["events_processed"] += 1
        await self._maybe_emit_score()

    async def _maybe_emit_score(self):
        """Emit score if enough time has passed since last emission."""
        now = time.time()
        if now - self._last_score_time < self._score_interval:
            return

        self._last_score_time = now
        score = self.scoring.compute_score()

        # Update state using full state machine logic
        self.state_machine.update_from_score(score.composite_score)

        self._metrics["current_score"] = score.composite_score
        self._metrics["stream_state"] = self.state_machine.state.value

        if score.composite_score >= self.score_threshold:
            self._metrics["high_scores"] += 1

        # Publish scored event
        await self.event_bus.publish_quick(
            EventType.EVENT_SCORED,
            {
                "score": score.model_dump(mode="json"),
                "stream_state": self.state_machine.state.value,
                "threshold_multiplier": self.state_machine.get_threshold_multiplier(),
            },
            source_service="event-detector",
        )

    def get_latest_score(self) -> HighlightScore:
        return self.scoring.compute_score()

    def get_status(self) -> dict:
        score = self.scoring.compute_score()
        return {
            **self._metrics,
            "current_score": score.composite_score,
            "breakdown": score.breakdown,
            "active_signals": score.active_signals,
        }
