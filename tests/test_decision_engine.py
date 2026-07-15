"""
Tests for false-positive reduction and tunable decision engine.
Covers:
  - ConfirmationWindow logic
  - DecisionEngineService temporal confirmation
  - Threshold floor
  - Configurable weights in ScoringEngine
  - Config-driven parameter wiring
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from shared.event_bus import EventBus
from shared.event_schemas import EventType, HighlightScore


# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def good_score():
    """Score that passes threshold + evidence."""
    return HighlightScore(
        composite_score=0.72,
        breakdown={
            "audio_spike": 0.65,
            "chat_velocity": 0.40,
            "emotion_intensity": 0.35,
        },
        timestamp=time.time(),
        active_signals=3,
    )


@pytest.fixture
def weak_score():
    """Score below threshold."""
    return HighlightScore(
        composite_score=0.30,
        breakdown={"audio_spike": 0.10},
        timestamp=time.time(),
        active_signals=1,
    )


@pytest.fixture
def one_evidence_score():
    """Passes threshold but only 1 signal above evidence threshold."""
    return HighlightScore(
        composite_score=0.60,
        breakdown={"audio_spike": 0.70, "chat_velocity": 0.10},
        timestamp=time.time(),
        active_signals=2,
    )


def make_decision_engine(
    bus=None,
    clip_threshold=0.55,
    cooldown=15.0,
    min_evidence=2,
    window=3,
    required=2,
    floor=0.35,
    evidence_threshold=0.2,
):
    from microservices.decision_engine.service import DecisionEngineService
    return DecisionEngineService(
        event_bus=bus or EventBus(),
        clip_threshold=clip_threshold,
        cooldown_seconds=cooldown,
        min_evidence_signals=min_evidence,
        confirmation_window=window,
        confirmation_required=required,
        threshold_floor=floor,
        evidence_threshold=evidence_threshold,
    )


# ─────────────────────────────────────────────────────────────
# ConfirmationWindow unit tests
# ─────────────────────────────────────────────────────────────

class TestConfirmationWindow:
    def _make_window(self, size=3, required=2):
        from microservices.decision_engine.service import ConfirmationWindow
        return ConfirmationWindow(window_size=size, required=required)

    def test_init_defaults(self):
        w = self._make_window()
        assert w.window_size == 3
        assert w.required == 2
        assert w.eval_count == 0

    def test_single_pass_not_confirmed(self):
        w = self._make_window()
        w.record(0.7, 0.55)
        assert not w.is_confirmed()  # Need 2 passes, have 1

    def test_two_passes_confirmed(self):
        w = self._make_window()
        w.record(0.7, 0.55)
        w.record(0.8, 0.55)
        assert w.is_confirmed()

    def test_fail_then_pass_not_confirmed(self):
        w = self._make_window()
        w.record(0.7, 0.55)  # pass
        w.record(0.3, 0.55)  # fail
        assert not w.is_confirmed()  # Only 1/2 passed

    def test_sliding_window_eviction(self):
        w = self._make_window(size=3, required=2)
        w.record(0.7, 0.55)   # pass (1)
        w.record(0.3, 0.55)   # fail
        w.record(0.3, 0.55)   # fail
        assert not w.is_confirmed()  # 1/3 passed
        w.record(0.8, 0.55)   # pass — evicts first (0.7)
        # Now: fail, fail, pass → 1/3 → not confirmed
        assert not w.is_confirmed()
        w.record(0.9, 0.55)   # pass — evicts first fail
        # Now: fail, pass, pass → 2/3 → confirmed
        assert w.is_confirmed()

    def test_required_capped_at_window(self):
        from microservices.decision_engine.service import ConfirmationWindow
        w = ConfirmationWindow(window_size=2, required=5)
        assert w.required == 2

    def test_min_values(self):
        from microservices.decision_engine.service import ConfirmationWindow
        w = ConfirmationWindow(window_size=0, required=0)
        assert w.window_size == 1
        assert w.required == 1

    def test_avg_score(self):
        w = self._make_window()
        w.record(0.5, 0.3)
        w.record(0.7, 0.3)
        assert abs(w.avg_score - 0.6) < 0.001

    def test_avg_score_empty(self):
        w = self._make_window()
        assert w.avg_score == 0.0

    def test_reset(self):
        w = self._make_window()
        w.record(0.7, 0.55)
        w.record(0.8, 0.55)
        assert w.is_confirmed()
        w.reset()
        assert not w.is_confirmed()
        assert w.eval_count == 0

    def test_get_status(self):
        w = self._make_window()
        w.record(0.7, 0.55)
        s = w.get_status()
        assert s["window_size"] == 3
        assert s["required"] == 2
        assert s["pass_count"] == 1
        assert s["eval_count"] == 1
        assert not s["confirmed"]


# ─────────────────────────────────────────────────────────────
# DecisionEngineService integration tests
# ─────────────────────────────────────────────────────────────

class TestDecisionEngineEvaluation:
    def test_below_threshold_rejected(self, bus, weak_score):
        de = make_decision_engine(bus)
        result = de.evaluate(weak_score)
        assert result.decision == "REJECT"
        assert "threshold" in result.reason.lower() or "Score" in result.reason

    def test_good_score_passes_after_confirmation(self, bus, good_score):
        de = make_decision_engine(bus, window=3, required=2, cooldown=0)
        # First evaluation: 1 pass, need 2 → REJECT
        result1 = de.evaluate(good_score)
        assert result1.decision == "REJECT"
        # Second evaluation: 2 passes → confirmed → CREATE_CLIP
        result2 = de.evaluate(good_score)
        assert result2.decision == "CREATE_CLIP"

    def test_good_score_rejected_without_confirmation(self, bus, good_score):
        de = make_decision_engine(bus, window=3, required=3)
        # First evaluation — only 1 pass, need 3
        result = de.evaluate(good_score)
        assert result.decision == "REJECT"
        assert "Confirmation" in result.reason or "confirmation" in result.reason

    def test_cooldown_blocks_clip(self, bus, good_score):
        de = make_decision_engine(bus, cooldown=999.0, window=1, required=1)
        de._last_clip_time = time.time()  # Just created a clip
        result = de.evaluate(good_score)
        assert result.decision == "REJECT"
        assert "Cooldown" in result.reason

    def test_no_cooldown_after_expired(self, bus, good_score):
        de = make_decision_engine(bus, cooldown=1.0, window=1, required=1)
        de._last_clip_time = time.time() - 2.0  # 2s ago, cooldown=1s
        result = de.evaluate(good_score)
        assert result.decision == "CREATE_CLIP"

    def test_one_evidence_rejected(self, bus, one_evidence_score):
        de = make_decision_engine(bus, min_evidence=2, window=1, required=1)
        result = de.evaluate(one_evidence_score)
        assert result.decision == "REJECT"
        assert "evidence" in result.reason.lower()

    def test_combo_fast_track_relaxes_evidence(self, bus):
        de = make_decision_engine(bus, min_evidence=2, window=1, required=1)
        score = HighlightScore(
            composite_score=0.70,
            breakdown={
                "audio_spike": 0.60,
                "chat_velocity": 0.10,  # below evidence threshold
                "emotion_intensity": 0.10,
                "pose_gesture": 0.10,
            },
            timestamp=time.time(),
            active_signals=4,  # 4+ → relax by 1 → need only 1
        )
        result = de.evaluate(score)
        assert result.decision == "CREATE_CLIP"


class TestThresholdFloor:
    def test_floor_prevents_low_threshold(self, bus, good_score):
        """Even with 0.6x multiplier, threshold can't go below floor."""
        de = make_decision_engine(bus, clip_threshold=0.55, floor=0.35, window=1, required=1)
        # 0.55 * 0.6 = 0.33 → floored to 0.35
        result = de.evaluate(good_score, threshold_multiplier=0.6)
        assert result.decision == "CREATE_CLIP"  # 0.72 > 0.35

    def test_floor_blocks_very_low_multiplier(self, bus):
        de = make_decision_engine(bus, clip_threshold=0.55, floor=0.50, window=1, required=1)
        score = HighlightScore(
            composite_score=0.40,
            breakdown={"audio_spike": 0.60, "chat_velocity": 0.30},
            timestamp=time.time(),
            active_signals=2,
        )
        # 0.55 * 0.6 = 0.33 → floored to 0.50 → 0.40 < 0.50
        result = de.evaluate(score, threshold_multiplier=0.6)
        assert result.decision == "REJECT"

    def test_no_floor_when_multiplier_high(self, bus, good_score):
        de = make_decision_engine(bus, clip_threshold=0.55, floor=0.35, window=1, required=1)
        result = de.evaluate(good_score, threshold_multiplier=1.2)
        # 0.55 * 1.2 = 0.66 → above floor → use 0.66
        assert result.decision == "CREATE_CLIP"  # 0.72 > 0.66


class TestConfirmationReset:
    def test_window_resets_after_clip(self, bus, good_score):
        de = make_decision_engine(bus, window=3, required=2, cooldown=0)
        # Fill window and get clip (cooldown=0 so no cooldown block)
        de.evaluate(good_score)  # 1 pass
        result = de.evaluate(good_score)  # 2 passes → confirmed → CREATE_CLIP
        assert result.decision == "CREATE_CLIP"
        # Window should be reset — next eval needs fresh confirmations
        result = de.evaluate(good_score)
        assert result.decision == "REJECT"  # Only 1 pass after reset, need 2


class TestEventDrivenIntegration:
    @pytest.mark.asyncio
    async def test_scored_event_triggers_clip(self, bus):
        await bus.start()
        de = make_decision_engine(bus, window=1, required=1)
        captured = []
        bus.subscribe(
            "decision.clip_candidate",
            lambda e: captured.append(e),
        )

        await bus.publish_quick(
            EventType.EVENT_SCORED,
            {
                "score": {
                    "composite_score": 0.72,
                    "breakdown": {
                        "audio_spike": 0.65,
                        "chat_velocity": 0.40,
                        "emotion_intensity": 0.35,
                    },
                    "timestamp": time.time(),
                    "active_signals": 3,
                },
                "threshold_multiplier": 1.0,
            },
            source_service="test",
        )
        await asyncio.sleep(0.1)
        await bus.stop()

        assert len(captured) == 1
        assert "candidate" in captured[0].payload

    @pytest.mark.asyncio
    async def test_scored_event_rejected_without_confirmation(self, bus):
        await bus.start()
        de = make_decision_engine(bus, window=3, required=3)
        captured = []
        bus.subscribe(
            "decision.clip_candidate",
            lambda e: captured.append(e),
        )

        # Only 1 event — not enough for 3/3 confirmation
        await bus.publish_quick(
            EventType.EVENT_SCORED,
            {
                "score": {
                    "composite_score": 0.72,
                    "breakdown": {
                        "audio_spike": 0.65,
                        "chat_velocity": 0.40,
                    },
                    "timestamp": time.time(),
                    "active_signals": 2,
                },
                "threshold_multiplier": 1.0,
            },
            source_service="test",
        )
        await asyncio.sleep(0.1)
        await bus.stop()

        assert len(captured) == 0

    @pytest.mark.asyncio
    async def test_multiple_events_build_confirmation(self, bus):
        await bus.start()
        de = make_decision_engine(bus, window=3, required=2)
        captured = []
        bus.subscribe(
            "decision.clip_candidate",
            lambda e: captured.append(e),
        )

        payload = {
            "score": {
                "composite_score": 0.72,
                "breakdown": {
                    "audio_spike": 0.65,
                    "chat_velocity": 0.40,
                },
                "timestamp": time.time(),
                "active_signals": 2,
            },
            "threshold_multiplier": 1.0,
        }

        # First event: 1 pass → not confirmed
        await bus.publish_quick(
            EventType.EVENT_SCORED, payload, source_service="test",
        )
        await asyncio.sleep(0.1)
        assert len(captured) == 0

        # Second event: 2 passes → confirmed → CLIP_CANDIDATE
        await bus.publish_quick(
            EventType.EVENT_SCORED, payload, source_service="test",
        )
        await asyncio.sleep(0.1)
        await bus.stop()

        assert len(captured) == 1


# ─────────────────────────────────────────────────────────────
# ScoringEngine configurable weights
# ─────────────────────────────────────────────────────────────

class TestScoringEngineWeights:
    def test_default_weights_load(self):
        from microservices.event_detector.service import ScoringEngine
        se = ScoringEngine()
        total = sum(se.WEIGHTS.values())
        assert abs(total - 1.0) < 0.001
        assert len(se.WEIGHTS) == 11

    def test_custom_weights_normalized(self):
        from microservices.event_detector.service import ScoringEngine
        custom = {"audio_spike": 0.50, "chat_velocity": 0.50}
        se = ScoringEngine(weights=custom)
        assert abs(se.WEIGHTS["audio_spike"] - 0.5) < 0.001
        assert abs(se.WEIGHTS["chat_velocity"] - 0.5) < 0.001
        assert len(se.WEIGHTS) == 2

    def test_zero_weights_fallback(self):
        from microservices.event_detector.service import ScoringEngine
        custom = {"audio_spike": 0.0, "chat_velocity": 0.0}
        se = ScoringEngine(weights=custom)
        # Should fall back to DEFAULT_WEIGHTS
        assert len(se.WEIGHTS) == 11
        assert abs(sum(se.WEIGHTS.values()) - 1.0) < 0.001

    def test_custom_decay_halflife(self):
        from microservices.event_detector.service import ScoringEngine
        se = ScoringEngine(decay_halflife=10.0)
        assert se.DECAY_HALFLIFE == 10.0

    def test_new_signal_extension(self):
        """Adding a new signal via weights dict works seamlessly."""
        from microservices.event_detector.service import ScoringEngine
        custom = {
            "audio_spike": 0.30,
            "chat_velocity": 0.30,
            "new_custom_signal": 0.40,  # New signal!
        }
        se = ScoringEngine(weights=custom)
        assert "new_custom_signal" in se.WEIGHTS
        assert "new_custom_signal" in se._signal_history
        se.update_signal("new_custom_signal", 0.8)
        score = se.compute_score()
        assert score.composite_score > 0


class TestStateMachineThreshold:
    def test_get_adjusted_threshold_floor(self):
        from microservices.event_detector.service import (
            StreamStateMachine, StreamState,
        )
        sm = StreamStateMachine()
        sm.state = StreamState.PEAK_MOMENT  # 0.6x multiplier
        # 0.55 * 0.6 = 0.33 → floored to 0.35
        adjusted = sm.get_adjusted_threshold(0.55)
        assert adjusted == 0.35

    def test_get_adjusted_threshold_no_floor(self):
        from microservices.event_detector.service import (
            StreamStateMachine, StreamState,
        )
        sm = StreamStateMachine()
        sm.state = StreamState.STEADY  # 1.0x multiplier
        adjusted = sm.get_adjusted_threshold(0.55)
        assert abs(adjusted - 0.55) < 0.001

    def test_warming_up_raises_threshold(self):
        from microservices.event_detector.service import (
            StreamStateMachine, StreamState,
        )
        sm = StreamStateMachine()
        sm.state = StreamState.WARMING_UP  # 1.2x multiplier
        adjusted = sm.get_adjusted_threshold(0.55)
        assert abs(adjusted - 0.66) < 0.001


# ─────────────────────────────────────────────────────────────
# Config wiring
# ─────────────────────────────────────────────────────────────

class TestConfigWiring:
    def test_settings_has_decision_params(self):
        from config import get_settings
        s = get_settings()
        assert hasattr(s, "decision_clip_threshold")
        assert hasattr(s, "decision_cooldown_seconds")
        assert hasattr(s, "decision_confirmation_window")
        assert hasattr(s, "decision_confirmation_required")
        assert hasattr(s, "decision_threshold_floor")
        assert hasattr(s, "decision_evidence_threshold")
        assert hasattr(s, "decision_score_interval")
        assert hasattr(s, "decision_decay_halflife")

    def test_settings_has_signal_weights(self):
        from config import get_settings
        s = get_settings()
        assert hasattr(s, "weight_audio_spike")
        assert hasattr(s, "weight_chat_velocity")
        assert hasattr(s, "weight_emotion_intensity")
        assert hasattr(s, "weight_donation")
        # Sum should be close to 1.0
        total = (
            s.weight_audio_spike + s.weight_chat_velocity
            + s.weight_emotion_intensity + s.weight_emotion_change
            + s.weight_pose_gesture + s.weight_pose_motion
            + s.weight_chat_sentiment + s.weight_viewer_delta
            + s.weight_ocr_keyword + s.weight_speech_content
            + s.weight_donation
        )
        assert abs(total - 1.0) < 0.001

    def test_decision_engine_status_includes_confirmation(self, bus, good_score):
        de = make_decision_engine(bus)
        de.evaluate(good_score)
        status = de.get_status()
        assert "confirmation_window" in status
        assert "pass_count" in status["confirmation_window"]
        assert "threshold_floor" in status
