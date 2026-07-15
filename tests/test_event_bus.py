"""
Unit tests for Event Bus and Event Schemas.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio

from shared.event_bus import EventBus, init_event_bus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, HighlightScore, BoundingBox,
    FaceDetection, EmotionResult, SentimentResult, StreamState,
    ClipCandidate, DecisionResult,
)


# ─── EventBus Tests ────────────────────────────────────

class TestEventBus:
    """Test the in-memory async event bus."""

    @pytest_asyncio.fixture
    async def bus(self):
        bus = EventBus(history_size=100)
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self, bus):
        """Publishing an event triggers the correct subscriber."""
        received = []

        async def handler(event: SystemEvent):
            received.append(event)

        bus.subscribe(EventType.CHAT_MESSAGE.value, handler)

        await bus.publish_quick(
            EventType.CHAT_MESSAGE,
            {"text": "hello", "user": "test"},
            source_service="test",
        )

        # Wait for dispatch
        await asyncio.sleep(0.2)

        assert len(received) == 1
        assert received[0].payload["text"] == "hello"

    @pytest.mark.asyncio
    async def test_wildcard_subscription(self, bus):
        """Wildcard 'audio.*' matches AUDIO_SPIKE."""
        received = []

        async def handler(event: SystemEvent):
            received.append(event)

        bus.subscribe_wildcard("audio.*", handler)

        await bus.publish_quick(EventType.AUDIO_SPIKE, {"magnitude": 0.9})
        await bus.publish_quick(EventType.AUDIO_FEATURES, {"rms": 0.5})
        await bus.publish_quick(EventType.CHAT_MESSAGE, {"text": "no match"})

        await asyncio.sleep(0.3)

        # Should get 2 audio events, not the chat event
        assert len(received) == 2
        types = [e.event_type for e in received]
        assert EventType.AUDIO_SPIKE in types
        assert EventType.AUDIO_FEATURES in types

    @pytest.mark.asyncio
    async def test_event_history(self, bus):
        """Events are stored in history."""
        for i in range(5):
            await bus.publish_quick(
                EventType.CHAT_SENTIMENT,
                {"score": i * 0.1},
            )

        await asyncio.sleep(0.3)

        history = bus.get_history(EventType.CHAT_SENTIMENT.value, last_n=10)
        assert len(history) == 5
        # Most recent last
        assert history[-1].payload["score"] == 0.4

    @pytest.mark.asyncio
    async def test_history_respects_maxlen(self, bus):
        """History deque respects maxlen."""
        for i in range(150):  # history_size=100
            await bus.publish_quick(EventType.CHAT_MESSAGE, {"i": i})

        await asyncio.sleep(0.5)

        history = bus.get_history(EventType.CHAT_MESSAGE.value, last_n=200)
        assert len(history) <= 100

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, bus):
        """Metrics are updated on publish/dispatch."""
        received = []

        async def handler(event: SystemEvent):
            received.append(event)

        bus.subscribe(EventType.FACE_DETECTED.value, handler)
        await bus.publish_quick(EventType.FACE_DETECTED, {"faces": 1})
        await asyncio.sleep(0.2)

        metrics = bus.metrics
        assert metrics["events_published"] >= 1
        assert metrics["events_dispatched"] >= 1

    @pytest.mark.asyncio
    async def test_failed_handler_goes_to_dlq(self, bus):
        """A handler that raises goes to the dead-letter queue."""

        async def bad_handler(event: SystemEvent):
            raise ValueError("intentional failure")

        bus.subscribe(EventType.CLIP_CREATED.value, bad_handler)
        await bus.publish_quick(EventType.CLIP_CREATED, {"clip_id": "test"})
        await asyncio.sleep(0.2)

        metrics = bus.metrics
        assert metrics["events_failed"] >= 1
        assert len(bus.dead_letter_queue) >= 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self, bus):
        """Multiple subscribers all receive the event."""
        results = {"a": [], "b": []}

        async def handler_a(event: SystemEvent):
            results["a"].append(event)

        async def handler_b(event: SystemEvent):
            results["b"].append(event)

        bus.subscribe(EventType.EMOTION_DETECTED.value, handler_a)
        bus.subscribe(EventType.EMOTION_DETECTED.value, handler_b)

        await bus.publish_quick(EventType.EMOTION_DETECTED, {"emotions": []})
        await asyncio.sleep(0.2)

        assert len(results["a"]) == 1
        assert len(results["b"]) == 1

    @pytest.mark.asyncio
    async def test_get_all_recent(self, bus):
        """get_all_recent returns events sorted by timestamp."""
        for et in [EventType.CHAT_MESSAGE, EventType.AUDIO_SPIKE, EventType.FACE_DETECTED]:
            await bus.publish_quick(et, {"test": True})

        await asyncio.sleep(0.3)

        recent = bus.get_all_recent(last_n=100)
        assert len(recent) == 3


# ─── Event Schema Tests ─────────────────────────────────

class TestEventSchemas:
    """Test Pydantic models for event schemas."""

    def test_system_event_defaults(self):
        event = SystemEvent(event_type=EventType.STREAM_STARTED)
        assert event.event_id  # auto-generated
        assert event.timestamp
        assert event.payload == {}
        assert event.source_service == ""

    def test_system_event_age(self):
        from datetime import datetime, timedelta
        event = SystemEvent(
            event_type=EventType.STREAM_STARTED,
            timestamp=datetime.utcnow() - timedelta(seconds=10),
        )
        assert event.age_seconds() >= 9.0

    def test_bounding_box_properties(self):
        box = BoundingBox(x1=10, y1=20, x2=50, y2=80)
        assert box.width == 40
        assert box.height == 60
        assert box.area == 2400
        assert box.center == (30.0, 50.0)

    def test_emotion_result_highlight(self):
        for label in ["happy", "surprise", "fear", "angry"]:
            e = EmotionResult(face_id="f1", label=label, confidence=0.9)
            assert e.is_highlight_emotion()

        e = EmotionResult(face_id="f2", label="neutral", confidence=0.9)
        assert not e.is_highlight_emotion()

    def test_highlight_score(self):
        score = HighlightScore(
            composite_score=0.75,
            breakdown={"audio_spike": 0.8, "chat_velocity": 0.5},
            active_signals=3,
        )
        assert score.composite_score == 0.75
        assert score.active_signals == 3

    def test_clip_candidate(self):
        candidate = ClipCandidate(
            stream_id="stream_1",
            trigger_signals=["audio_spike", "emotion_intensity"],
            priority=0.85,
        )
        assert candidate.candidate_id
        assert len(candidate.trigger_signals) == 2

    def test_decision_result(self):
        d = DecisionResult(decision="CREATE_CLIP", reason="High score", priority=0.8)
        assert d.decision == "CREATE_CLIP"

    def test_stream_state_enum(self):
        assert StreamState.OFFLINE.value == "offline"
        assert StreamState.PEAK_MOMENT.value == "peak_moment"
