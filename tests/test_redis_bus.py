"""
Tests for Redis Streams event bus integration and factory pattern.
Covers:
  - Factory pattern (in-memory vs Redis selection)
  - RedisEventBus API parity with EventBus
  - RedisEventBus publish/subscribe with mocked Redis
  - get_history / get_all_recent / dead_letter_queue sync API
  - set_event_bus / init_event_bus
"""
import asyncio
import json
import time
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.event_bus import EventBus, get_event_bus, set_event_bus, init_event_bus
try:
    from shared.event_bus.redis_bus import RedisEventBus
    import redis.asyncio as _aioredis
    _HAS_REDIS = True
except ImportError:
    RedisEventBus = None
    _HAS_REDIS = False
from shared.event_schemas import EventType, SystemEvent


# ─────────────────────────────────────────────────────────────
# Factory pattern tests
# ─────────────────────────────────────────────────────────────

class TestEventBusFactory:
    @pytest.mark.asyncio
    async def test_default_backend_is_memory(self):
        """Default backend should be in-memory EventBus."""
        bus = await init_event_bus()
        assert isinstance(bus, EventBus)
        assert not (RedisEventBus is not None and isinstance(bus, RedisEventBus))
        await bus.stop()

    @pytest.mark.asyncio
    async def test_memory_backend_explicit(self):
        with patch("config.get_settings") as mock_settings:
            s = MagicMock()
            s.event_bus_backend = "memory"
            mock_settings.return_value = s
            bus = await init_event_bus()
            assert isinstance(bus, EventBus)
            await bus.stop()

    @pytest.mark.skipif(not _HAS_REDIS, reason="redis not installed")
    @pytest.mark.asyncio
    async def test_redis_backend_creates_redis_bus(self):
        """Redis backend should create RedisEventBus (mocked)."""
        mock_redis_instance = AsyncMock()
        mock_redis_instance.ping = AsyncMock()
        mock_redis_instance.close = AsyncMock()

        with patch("config.get_settings") as mock_settings:
            s = MagicMock()
            s.event_bus_backend = "redis"
            s.redis_url = "redis://localhost:6379/0"
            mock_settings.return_value = s

            with patch("redis.asyncio.from_url", return_value=mock_redis_instance):
                bus = await init_event_bus()
                assert isinstance(bus, RedisEventBus)
                await bus.stop()

    def test_set_event_bus(self):
        """set_event_bus replaces the global singleton."""
        custom_bus = EventBus()
        set_event_bus(custom_bus)
        assert get_event_bus() is custom_bus
        # Reset to fresh bus for other tests
        set_event_bus(None)

    @pytest.mark.asyncio
    async def test_fallback_on_config_error(self):
        """If config fails to load, falls back to memory."""
        with patch.dict("sys.modules", {"config": None}):
            bus = await init_event_bus()
            assert isinstance(bus, EventBus)
            await bus.stop()


# ─────────────────────────────────────────────────────────────
# RedisEventBus API parity tests
# ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_REDIS, reason="redis not installed")
class TestRedisBusAPIParity:
    """Verify RedisEventBus has the same sync API as EventBus."""

    def test_get_history_sync(self):
        bus = RedisEventBus()
        # Should return empty list without error
        result = bus.get_history("some.event", last_n=10)
        assert result == []

    def test_get_all_recent_sync(self):
        bus = RedisEventBus()
        result = bus.get_all_recent(last_n=100)
        assert result == []

    def test_dead_letter_queue_property(self):
        bus = RedisEventBus()
        assert bus.dead_letter_queue == []

    def test_metrics_property(self):
        bus = RedisEventBus()
        m = bus.metrics
        assert "events_published" in m
        assert "events_dispatched" in m
        assert "events_failed" in m
        assert "events_dlq" in m


# ─────────────────────────────────────────────────────────────
# RedisEventBus publish/subscribe with mocked Redis
# ─────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_REDIS, reason="redis not installed")
class TestRedisBusPublishSubscribe:
    @pytest.fixture
    def mock_redis(self):
        r = AsyncMock()
        r.ping = AsyncMock()
        r.xadd = AsyncMock(return_value="1234-0")
        r.xack = AsyncMock()
        r.xgroup_create = AsyncMock()
        r.xrevrange = AsyncMock(return_value=[])
        r.close = AsyncMock()
        return r

    @pytest.fixture
    def redis_bus(self, mock_redis):
        bus = RedisEventBus(redis_url="redis://fake:6379/0")
        bus._redis = mock_redis
        bus._running = True
        return bus

    @pytest.mark.asyncio
    async def test_publish_writes_to_redis(self, redis_bus, mock_redis):
        event = SystemEvent(
            event_type=EventType.AUDIO_SPIKE,
            payload={"test": True},
            source_service="test",
        )
        await redis_bus.publish(event)
        mock_redis.xadd.assert_called_once()
        assert redis_bus.metrics["events_published"] == 1

    @pytest.mark.asyncio
    async def test_publish_populates_local_history(self, redis_bus):
        event = SystemEvent(
            event_type=EventType.CHAT_MESSAGE,
            payload={"message": "hello"},
            source_service="test",
        )
        await redis_bus.publish(event)
        history = redis_bus.get_history(EventType.CHAT_MESSAGE.value)
        assert len(history) == 1
        assert history[0].payload["message"] == "hello"

    @pytest.mark.asyncio
    async def test_publish_quick_creates_event(self, redis_bus, mock_redis):
        event = await redis_bus.publish_quick(
            EventType.AUDIO_FEATURES,
            {"rms": 0.5},
            source_service="test",
        )
        assert event.event_type == EventType.AUDIO_FEATURES
        mock_redis.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_when_not_running(self, mock_redis):
        bus = RedisEventBus()
        bus._running = False
        bus._redis = mock_redis
        event = SystemEvent(
            event_type=EventType.AUDIO_SPIKE,
            payload={},
            source_service="test",
        )
        await bus.publish(event)
        mock_redis.xadd.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscribe_registers_handler(self, redis_bus):
        async def handler(event): pass
        redis_bus.subscribe(EventType.CHAT_SPIKE.value, handler)
        assert handler in redis_bus._subscribers[EventType.CHAT_SPIKE.value]

    def test_subscribe_wildcard_registers_handler(self, redis_bus):
        async def handler(event): pass
        redis_bus.subscribe_wildcard("analysis.*", handler)
        assert len(redis_bus._wildcard_subscribers) == 1

    @pytest.mark.asyncio
    async def test_process_message_dispatches_to_handler(self, redis_bus, mock_redis):
        handler_calls = []
        async def handler(event): handler_calls.append(event)
        redis_bus.subscribe(EventType.AUDIO_SPIKE.value, handler)

        event = SystemEvent(
            event_type=EventType.AUDIO_SPIKE,
            payload={"volume": 0.9},
            source_service="test",
        )
        event_data = json.dumps(event.model_dump(mode="json"), default=str)

        await redis_bus._process_message(
            "klip.events.audio.spike",
            "1234-0",
            {"event": event_data},
        )

        assert len(handler_calls) == 1
        mock_redis.xack.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_message_handler_error_goes_to_dlq(
        self, redis_bus, mock_redis
    ):
        async def handler(event): raise ValueError("boom")
        redis_bus.subscribe(EventType.CHAT_MESSAGE.value, handler)

        event = SystemEvent(
            event_type=EventType.CHAT_MESSAGE,
            payload={"text": "test"},
            source_service="test",
        )
        event_data = json.dumps(event.model_dump(mode="json"), default=str)

        await redis_bus._process_message(
            "klip.events.chat.message",
            "1234-0",
            {"event": event_data},
        )

        assert redis_bus.metrics["events_failed"] == 1
        assert redis_bus.metrics["events_dlq"] == 1
        assert len(redis_bus.dead_letter_queue) == 1

    @pytest.mark.asyncio
    async def test_get_all_recent_across_types(self, redis_bus):
        for i in range(5):
            await redis_bus.publish(SystemEvent(
                event_type=EventType.AUDIO_SPIKE,
                payload={"i": i},
                source_service="test",
            ))
        for i in range(3):
            await redis_bus.publish(SystemEvent(
                event_type=EventType.CHAT_MESSAGE,
                payload={"i": i},
                source_service="test",
            ))

        recent = redis_bus.get_all_recent(last_n=100)
        assert len(recent) == 8

    @pytest.mark.asyncio
    async def test_history_maxlen_respected(self):
        bus = RedisEventBus(history_size=5)
        bus._redis = AsyncMock()
        bus._redis.xadd = AsyncMock(return_value="1-0")
        bus._running = True

        for i in range(10):
            await bus.publish(SystemEvent(
                event_type=EventType.AUDIO_SPIKE,
                payload={"i": i},
                source_service="test",
            ))

        history = bus.get_history(EventType.AUDIO_SPIKE.value, last_n=100)
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_fetch_history_from_redis(self, redis_bus, mock_redis):
        event = SystemEvent(
            event_type=EventType.CHAT_SENTIMENT,
            payload={"score": 0.8},
            source_service="test",
        )
        event_data = json.dumps(event.model_dump(mode="json"), default=str)
        mock_redis.xrevrange = AsyncMock(
            return_value=[("1-0", {"event": event_data})]
        )

        results = await redis_bus.fetch_history(
            EventType.CHAT_SENTIMENT.value, last_n=10
        )
        assert len(results) == 1
        assert results[0].event_type == EventType.CHAT_SENTIMENT

    @pytest.mark.asyncio
    async def test_wildcard_handler_dispatched(self, redis_bus, mock_redis):
        handler_calls = []
        async def handler(event): handler_calls.append(event)
        redis_bus.subscribe_wildcard("analysis.*", handler)

        event = SystemEvent(
            event_type=EventType.EMOTION_DETECTED,
            payload={"emotion": "happy"},
            source_service="test",
        )
        event_data = json.dumps(event.model_dump(mode="json"), default=str)

        await redis_bus._process_message(
            "klip.events.analysis.emotion_detected",
            "1-0",
            {"event": event_data},
        )

        assert len(handler_calls) == 1


# ─────────────────────────────────────────────────────────────
# Config wiring
# ─────────────────────────────────────────────────────────────

class TestConfigBackend:
    def test_config_has_backend_setting(self):
        from config import get_settings
        s = get_settings()
        assert hasattr(s, "event_bus_backend")
        assert s.event_bus_backend in ("memory", "redis")
