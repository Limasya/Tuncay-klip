"""
Tests for multi-stream support across the pipeline.
Covers:
  - EventDetectorService per-stream scoring + state machine
  - DecisionEngineService per-stream confirmation + cooldown
  - PipelineOrchestrator multi-stream lifecycle
"""
import asyncio
import time
import pytest

from shared.event_bus import EventBus
from shared.event_schemas import EventType, HighlightScore, SystemEvent


# ─────────────────────────────────────────────────────────────
# EventDetectorService multi-stream
# ─────────────────────────────────────────────────────────────

class TestEventDetectorMultiStream:
    @pytest.mark.asyncio
    async def test_separate_scoring_per_stream(self):
        """Each stream_id gets its own ScoringEngine."""
        from microservices.event_detector.service import EventDetectorService
        bus = EventBus()
        det = EventDetectorService(event_bus=bus)

        # Feed signals to stream A
        scoring_a = det._get_stream_scoring("stream-a")
        scoring_a.update_signal("audio_spike", 0.9)

        # Feed different signals to stream B
        scoring_b = det._get_stream_scoring("stream-b")
        scoring_b.update_signal("chat_velocity", 0.8)

        # Scores should be independent
        score_a = scoring_a.compute_score()
        score_b = scoring_b.compute_score()
        assert score_a.breakdown.get("audio_spike", 0) > 0
        assert score_a.breakdown.get("chat_velocity", 0) == 0
        assert score_b.breakdown.get("chat_velocity", 0) > 0
        assert score_b.breakdown.get("audio_spike", 0) == 0

    @pytest.mark.asyncio
    async def test_stream_state_per_stream(self):
        """Each stream_id gets its own StreamStateMachine."""
        from microservices.event_detector.service import EventDetectorService
        from microservices.event_detector.service import StreamState
        bus = EventBus()
        det = EventDetectorService(event_bus=bus)

        sm_a = det._get_stream_state("stream-a")
        sm_b = det._get_stream_state("stream-b")

        sm_a.transition(StreamState.PEAK_MOMENT)
        assert sm_a.state == StreamState.PEAK_MOMENT
        assert sm_b.state == StreamState.OFFLINE  # untouched

    @pytest.mark.asyncio
    async def test_event_with_stream_id(self):
        """Events with stream_id route to correct scoring engine."""
        from microservices.event_detector.service import EventDetectorService
        bus = EventBus()
        await bus.start()
        det = EventDetectorService(event_bus=bus)

        event = SystemEvent(
            event_type=EventType.AUDIO_SPIKE,
            payload={"peak_magnitude": 0.9},
            source_service="test",
            stream_id="stream-x",
        )
        await det._on_audio_spike(event)

        scoring = det._get_stream_scoring("stream-x")
        score = scoring.compute_score()
        assert score.breakdown.get("audio_spike", 0) > 0
        await bus.stop()

    def test_default_stream_backward_compat(self):
        """scoring and state_machine properties use 'default' stream."""
        from microservices.event_detector.service import EventDetectorService
        bus = EventBus()
        det = EventDetectorService(event_bus=bus)
        # Accessing .scoring should work (backward compat)
        det.scoring.update_signal("audio_spike", 0.5)
        score = det.scoring.compute_score()
        assert score.breakdown.get("audio_spike", 0) > 0

    def test_active_streams_count(self):
        from microservices.event_detector.service import EventDetectorService
        bus = EventBus()
        det = EventDetectorService(event_bus=bus)
        det._get_stream_scoring("s1")
        det._get_stream_scoring("s2")
        det._get_stream_scoring("s3")
        status = det.get_status()
        # get_status accesses DEFAULT_STREAM too, so 4 total
        assert status["active_streams"] >= 3
        assert "s1" in status["streams"]
        assert "s2" in status["streams"]
        assert "s3" in status["streams"]


# ─────────────────────────────────────────────────────────────
# DecisionEngineService multi-stream
# ─────────────────────────────────────────────────────────────

class TestDecisionEngineMultiStream:
    def _make_engine(self, **kwargs):
        from microservices.decision_engine.service import DecisionEngineService
        defaults = dict(
            clip_threshold=0.5,
            cooldown_seconds=0,
            min_evidence_signals=1,
            confirmation_window=1,
            confirmation_required=1,
        )
        defaults.update(kwargs)
        return DecisionEngineService(event_bus=EventBus(), **defaults)

    def _good_score(self):
        return HighlightScore(
            composite_score=0.8,
            breakdown={"audio_spike": 0.9, "chat_velocity": 0.5},
            active_signals=2,
        )

    def test_independent_confirmation_per_stream(self):
        """Stream A confirmed doesn't affect Stream B."""
        de = self._make_engine(confirmation_window=3, confirmation_required=3)
        score = self._good_score()

        # Stream A: 1 pass → not confirmed
        r = de.evaluate(score, stream_id="stream-a")
        assert r.decision == "REJECT"

        # Stream B: 1 pass → also not confirmed (independent window)
        r = de.evaluate(score, stream_id="stream-b")
        assert r.decision == "REJECT"

        # Stream A: 2nd and 3rd pass → confirmed
        de.evaluate(score, stream_id="stream-a")
        r = de.evaluate(score, stream_id="stream-a")
        assert r.decision == "CREATE_CLIP"

        # Stream B: still only 1 pass → not confirmed (need 3)
        r = de.evaluate(score, stream_id="stream-b")
        assert r.decision == "REJECT"

    def test_independent_cooldown_per_stream(self):
        """Cooldown on stream A doesn't block stream B."""
        de = self._make_engine(cooldown_seconds=999)
        score = self._good_score()

        # Stream A creates clip
        r = de.evaluate(score, stream_id="a")
        assert r.decision == "CREATE_CLIP"

        # Stream A blocked by cooldown
        r = de.evaluate(score, stream_id="a")
        assert r.decision == "REJECT"
        assert "Cooldown" in r.reason

        # Stream B unaffected — its own cooldown is clear
        r = de.evaluate(score, stream_id="b")
        assert r.decision == "CREATE_CLIP"

    def test_default_stream_backward_compat(self):
        """evaluate() without stream_id uses 'default'."""
        de = self._make_engine()
        score = self._good_score()
        r = de.evaluate(score)
        assert r.decision == "CREATE_CLIP"

    def test_status_includes_active_streams(self):
        de = self._make_engine()
        score = self._good_score()
        de.evaluate(score, stream_id="x")
        de.evaluate(score, stream_id="y")
        status = de.get_status()
        assert "active_streams" in status
        assert "x" in status["active_streams"]
        assert "y" in status["active_streams"]

    @pytest.mark.asyncio
    async def test_scored_event_uses_stream_id(self):
        """_on_scored_event routes to correct stream state."""
        from microservices.decision_engine.service import DecisionEngineService
        bus = EventBus()
        await bus.start()

        de = DecisionEngineService(
            event_bus=bus,
            clip_threshold=0.3,
            cooldown_seconds=0,
            min_evidence_signals=1,
            confirmation_window=1,
            confirmation_required=1,
        )

        captured = []
        bus.subscribe("decision.clip_candidate", lambda e: captured.append(e))

        await bus.publish_quick(
            EventType.EVENT_SCORED,
            {
                "score": {
                    "composite_score": 0.8,
                    "breakdown": {"audio_spike": 0.9},
                    "timestamp": time.time(),
                    "active_signals": 1,
                },
                "threshold_multiplier": 1.0,
            },
            source_service="test",
            stream_id="live-stream-1",
        )
        await asyncio.sleep(0.1)
        await bus.stop()

        assert len(captured) == 1
        assert captured[0].stream_id == "live-stream-1"


# ─────────────────────────────────────────────────────────────
# Integration: event detector → decision engine multi-stream
# ─────────────────────────────────────────────────────────────

class TestMultiStreamIntegration:
    @pytest.mark.asyncio
    async def test_two_streams_independent_decisions(self):
        """Two streams can independently reach clip decisions."""
        from microservices.event_detector.service import EventDetectorService
        from microservices.decision_engine.service import DecisionEngineService

        bus = EventBus()
        await bus.start()

        det = EventDetectorService(
            event_bus=bus,
            score_interval=0,  # emit every time
        )
        de = DecisionEngineService(
            event_bus=bus,
            clip_threshold=0.1,
            cooldown_seconds=0,
            min_evidence_signals=1,
            confirmation_window=1,
            confirmation_required=1,
            threshold_floor=0.0,
        )

        captured = []
        bus.subscribe("decision.clip_candidate", lambda e: captured.append(e))

        # High score on stream A
        scoring_a = det._get_stream_scoring("stream-a")
        scoring_a.update_signal("audio_spike", 0.9)
        await det._maybe_emit_score("stream-a")

        # Low score on stream B
        scoring_b = det._get_stream_scoring("stream-b")
        scoring_b.update_signal("audio_spike", 0.1)
        await det._maybe_emit_score("stream-b")

        await asyncio.sleep(0.2)
        await bus.stop()

        # Only stream A should produce a clip candidate
        clip_streams = [e.stream_id for e in captured]
        assert "stream-a" in clip_streams
        assert "stream-b" not in clip_streams
