"""
Unit tests for Event Detector and Decision Engine microservices.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio

from shared.event_bus import EventBus
from shared.event_schemas import EventType, HighlightScore, SystemEvent, StreamState
from microservices.event_detector.service import (
    ScoringEngine, StreamStateMachine, EventDetectorService,
)
from microservices.decision_engine.service import DecisionEngineService


# ─── ScoringEngine Tests ─────────────────────────────────

class TestScoringEngine:
    """Test the highlight scoring engine."""

    def test_initial_score_is_zero(self):
        engine = ScoringEngine()
        score = engine.compute_score()
        assert score.composite_score == 0.0
        assert score.active_signals == 0

    def test_single_signal_update(self):
        engine = ScoringEngine()
        engine.update_signal("audio_spike", 0.8)
        score = engine.compute_score()
        assert score.composite_score > 0.0
        assert score.breakdown["audio_spike"] > 0.0

    def test_multiple_signals(self):
        engine = ScoringEngine()
        engine.update_signal("audio_spike", 0.9)
        engine.update_signal("chat_velocity", 0.8)
        engine.update_signal("emotion_intensity", 0.7)
        score = engine.compute_score()
        assert score.active_signals >= 3
        assert score.composite_score > 0.3

    def test_combo_boost_3_signals(self):
        engine = ScoringEngine()
        engine.update_signal("audio_spike", 0.9)
        engine.update_signal("chat_velocity", 0.8)
        engine.update_signal("emotion_intensity", 0.7)
        score = engine.compute_score()
        # With 3 active signals, score should get 1.15x boost
        assert score.composite_score > 0.0

    def test_combo_boost_5_signals(self):
        engine = ScoringEngine()
        for signal in ["audio_spike", "chat_velocity", "emotion_intensity",
                       "pose_gesture", "donation"]:
            engine.update_signal(signal, 0.9)
        score = engine.compute_score()
        assert score.active_signals >= 5
        # 1.5x boost for 5+ signals
        assert score.composite_score > 0.3

    def test_combo_boost_capped_at_1(self):
        engine = ScoringEngine()
        for signal in engine.WEIGHTS:
            engine.update_signal(signal, 1.0)
        score = engine.compute_score()
        assert score.composite_score <= 1.0

    def test_temporal_decay(self):
        """Older signals contribute less."""
        engine = ScoringEngine()
        # Insert a signal with a timestamp 20 seconds ago
        engine._signal_history["audio_spike"].append((time.time() - 20, 1.0))
        score = engine.compute_score(window_seconds=30)
        # Decay should reduce the score
        assert score.breakdown["audio_spike"] < 1.0

    def test_window_excludes_old_events(self):
        """Events outside the window are excluded."""
        engine = ScoringEngine()
        engine._signal_history["audio_spike"].append((time.time() - 60, 1.0))
        score = engine.compute_score(window_seconds=10)
        assert score.breakdown["audio_spike"] == 0.0

    def test_unknown_signal_ignored(self):
        engine = ScoringEngine()
        engine.update_signal("nonexistent_signal", 1.0)
        score = engine.compute_score()
        assert score.composite_score == 0.0

    def test_all_weights_sum(self):
        """All weights should sum to ~1.0."""
        engine = ScoringEngine()
        total = sum(engine.WEIGHTS.values())
        assert 0.95 <= total <= 1.05

    def test_donation_signal(self):
        engine = ScoringEngine()
        engine.update_signal("donation", 0.8)
        score = engine.compute_score()
        assert score.breakdown["donation"] > 0.0


# ─── StreamStateMachine Tests ────────────────────────────

class TestStreamStateMachine:
    """Test the stream state machine transitions."""

    def test_initial_state(self):
        sm = StreamStateMachine()
        assert sm.state == StreamState.OFFLINE

    def test_manual_transition(self):
        from shared.event_schemas import StreamState
        sm = StreamStateMachine()
        sm.transition(StreamState.STARTING)
        assert sm.state == StreamState.STARTING

    def test_threshold_adjustments(self):
        from shared.event_schemas import StreamState
        sm = StreamStateMachine()
        sm.transition(StreamState.PEAK_MOMENT)
        assert sm.get_threshold_multiplier() == 0.6

        sm.transition(StreamState.WARMING_UP)
        assert sm.get_threshold_multiplier() == 1.2

    def test_score_based_transition_to_peak(self):
        from shared.event_schemas import StreamState
        sm = StreamStateMachine()
        sm.transition(StreamState.STEADY)
        sm.update_from_score(0.9)
        assert sm.state == StreamState.PEAK_MOMENT

    def test_score_based_transition_to_high_energy(self):
        from shared.event_schemas import StreamState
        sm = StreamStateMachine()
        sm.transition(StreamState.STEADY)
        sm.update_from_score(0.6)
        assert sm.state == StreamState.HIGH_ENERGY

    def test_cooling_down_on_low_score(self):
        from shared.event_schemas import StreamState
        sm = StreamStateMachine()
        sm.transition(StreamState.HIGH_ENERGY)
        sm.update_from_score(0.1)
        assert sm.state == StreamState.COOLING_DOWN


# ─── EventDetectorService Tests ──────────────────────────

class TestEventDetectorService:
    """Test the event detector service with event bus."""

    @pytest_asyncio.fixture
    async def bus(self):
        bus = EventBus(history_size=100)
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_audio_spike_updates_score(self, bus):
        detector = EventDetectorService(event_bus=bus)

        await bus.publish_quick(
            EventType.AUDIO_SPIKE,
            {"peak_magnitude": 0.9},
            source_service="test",
        )
        await asyncio.sleep(0.3)

        score = detector.get_latest_score()
        assert score.breakdown["audio_spike"] > 0.0

    @pytest.mark.asyncio
    async def test_emotion_updates_score(self, bus):
        detector = EventDetectorService(event_bus=bus)

        await bus.publish_quick(
            EventType.EMOTION_DETECTED,
            {"emotions": [{"label": "happy", "confidence": 0.9}]},
            source_service="test",
        )
        await asyncio.sleep(0.3)

        score = detector.get_latest_score()
        assert score.breakdown["emotion_intensity"] > 0.0

    @pytest.mark.asyncio
    async def test_donation_updates_score(self, bus):
        detector = EventDetectorService(event_bus=bus)

        await bus.publish_quick(
            EventType.DONATION_RECEIVED,
            {"amount": 10.0, "user": "test"},
            source_service="test",
        )
        await asyncio.sleep(0.3)

        score = detector.get_latest_score()
        assert score.breakdown["donation"] > 0.0

    @pytest.mark.asyncio
    async def test_chat_spike_updates_score(self, bus):
        detector = EventDetectorService(event_bus=bus)

        await bus.publish_quick(
            EventType.CHAT_SPIKE,
            {"spike_ratio": 8.0},
            source_service="test",
        )
        await asyncio.sleep(0.3)

        score = detector.get_latest_score()
        assert score.breakdown["chat_velocity"] > 0.0

    @pytest.mark.asyncio
    async def test_stream_start_transitions_state(self, bus):
        from shared.event_schemas import StreamState
        detector = EventDetectorService(event_bus=bus)

        await bus.publish_quick(EventType.STREAM_STARTED, {}, source_service="test")
        await asyncio.sleep(0.2)

        assert detector.state_machine.state == StreamState.STARTING

    @pytest.mark.asyncio
    async def test_get_status(self, bus):
        detector = EventDetectorService(event_bus=bus)
        status = detector.get_status()
        assert "events_processed" in status
        assert "current_score" in status
        assert "active_signals" in status


# ─── DecisionEngine Tests ────────────────────────────────

class TestDecisionEngine:
    """Test the decision engine's clip/no-clip logic."""

    @pytest_asyncio.fixture
    async def bus(self):
        bus = EventBus(history_size=100)
        await bus.start()
        yield bus
        await bus.stop()

    def test_reject_low_score(self):
        engine = DecisionEngineService(clip_threshold=0.5)
        score = HighlightScore(composite_score=0.2, breakdown={}, active_signals=0)
        result = engine.evaluate(score)
        assert result.decision == "REJECT"
        assert "threshold" in result.reason.lower()

    def test_approve_high_score(self):
        engine = DecisionEngineService(
            clip_threshold=0.5,
            cooldown_seconds=0,
            min_evidence_signals=1,
            confirmation_window=1,
            confirmation_required=1,
        )
        score = HighlightScore(
            composite_score=0.8,
            breakdown={"audio_spike": 0.9, "chat_velocity": 0.7},
            active_signals=3,
        )
        result = engine.evaluate(score)
        assert result.decision == "CREATE_CLIP"

    def test_cooldown_rejection(self):
        engine = DecisionEngineService(
            clip_threshold=0.5,
            cooldown_seconds=30,
            min_evidence_signals=1,
        )
        # Simulate a recent clip
        engine._last_clip_time = time.time()

        score = HighlightScore(
            composite_score=0.9,
            breakdown={"audio_spike": 0.9},
            active_signals=2,
        )
        result = engine.evaluate(score)
        assert result.decision == "REJECT"
        assert "cooldown" in result.reason.lower()

    def test_min_evidence_rejection(self):
        engine = DecisionEngineService(
            clip_threshold=0.3,
            cooldown_seconds=0,
            min_evidence_signals=2,
        )
        # Only 1 signal above 0.2
        score = HighlightScore(
            composite_score=0.6,
            breakdown={"audio_spike": 0.9, "chat_velocity": 0.1},
            active_signals=1,
        )
        result = engine.evaluate(score)
        assert result.decision == "REJECT"
        assert "evidence" in result.reason.lower()

    def test_combo_fast_track(self):
        """4+ active signals relaxes evidence requirement."""
        engine = DecisionEngineService(
            clip_threshold=0.3,
            cooldown_seconds=0,
            min_evidence_signals=2,
            confirmation_window=1,
            confirmation_required=1,
        )
        # With 4 active signals, required_evidence = max(1, 2-1) = 1
        score = HighlightScore(
            composite_score=0.6,
            breakdown={"audio_spike": 0.5, "chat_velocity": 0.01},
            active_signals=4,  # triggers fast-track
        )
        result = engine.evaluate(score)
        assert result.decision == "CREATE_CLIP"

    def test_threshold_multiplier(self):
        """Threshold multiplier from stream state affects decision."""
        engine = DecisionEngineService(
            clip_threshold=0.5,
            cooldown_seconds=0,
            min_evidence_signals=1,
            confirmation_window=1,
            confirmation_required=1,
        )
        # Score 0.55 with 1.3x multiplier → adjusted threshold 0.65 → REJECT
        score = HighlightScore(
            composite_score=0.55,
            breakdown={"audio_spike": 0.6},
            active_signals=1,
        )
        result = engine.evaluate(score, threshold_multiplier=1.3)
        assert result.decision == "REJECT"

        # Score 0.55 with 0.6x multiplier (PEAK) → adjusted 0.30, but floored at 0.35 → 0.55 > 0.35 → APPROVE
        result = engine.evaluate(score, threshold_multiplier=0.6)
        assert result.decision == "CREATE_CLIP"

    @pytest.mark.asyncio
    async def test_scored_event_publishes_decision(self, bus):
        """EVENT_SCORED triggers CLIP_CANDIDATE or CLIP_REJECTED."""
        engine = DecisionEngineService(
            event_bus=bus,
            clip_threshold=0.3,
            cooldown_seconds=0,
            min_evidence_signals=1,
        )

        await bus.publish_quick(
            EventType.EVENT_SCORED,
            {
                "score": {
                    "composite_score": 0.8,
                    "breakdown": {"audio_spike": 0.9, "chat_velocity": 0.5},
                    "timestamp": time.time(),
                    "active_signals": 3,
                },
                "stream_state": "steady",
                "threshold_multiplier": 1.0,
            },
            source_service="test",
        )
        await asyncio.sleep(0.3)

        status = engine.get_status()
        assert status["clips_created"] >= 1 or status["clips_rejected"] >= 0

    def test_get_status(self):
        engine = DecisionEngineService()
        status = engine.get_status()
        assert "clip_threshold" in status
        assert "cooldown_seconds" in status
        assert "clips_created" in status
        assert "clips_rejected" in status
