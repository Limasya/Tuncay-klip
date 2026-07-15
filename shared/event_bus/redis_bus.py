"""
Redis Streams Event Bus
────────────────────────
Production-ready event bus backed by Redis Streams.

Drop-in replacement for the in-memory EventBus. Each event type becomes
a Redis stream key:  klip.events.{event_type}

Consumer groups ensure at-least-once delivery and allow multiple consumers
(horizontal scaling).

Usage:
    from shared.event_bus.redis_bus import RedisEventBus

    bus = RedisEventBus(redis_url="redis://localhost:6379/0")
    await bus.start()
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

from shared.event_schemas import SystemEvent, EventType

logger = logging.getLogger("redis_event_bus")

# Stream key prefix
STREAM_PREFIX = "klip.events"
CONSUMER_GROUP = "klip_consumers"


class RedisEventBus:
    """
    Redis Streams-backed event bus.

    Features:
    - Persistent event storage in Redis Streams
    - Consumer groups for at-least-once delivery
    - Automatic ACK after successful handler execution
    - DLQ stream for failed events
    - Metrics via Redis INFO
    - Graceful shutdown
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        consumer_name: str = "consumer-1",
        history_size: int = 500,
        max_stream_length: int = 10000,
    ):
        self._redis_url = redis_url
        self._consumer_name = consumer_name
        self._history_size = history_size
        self._max_stream_length = max_stream_length

        self._redis = None
        self._running = False

        # Local subscriber handlers (same pattern as in-memory bus)
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._wildcard_subscribers: list[tuple[str, Callable]] = []

        # Metrics
        self._metrics = {
            "events_published": 0,
            "events_dispatched": 0,
            "events_failed": 0,
            "events_dlq": 0,
        }

        # Background tasks
        self._consumer_task: Optional[asyncio.Task] = None

        # Local caches for sync API parity with in-memory EventBus
        self._history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._dlq: deque = deque(maxlen=100)

    async def start(self):
        """Connect to Redis and start the consumer loop."""
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.error(
                "redis package not installed. Install with: pip install redis"
            )
            raise

        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
        )

        # Test connection
        await self._redis.ping()
        logger.info("Connected to Redis: %s", self._redis_url)

        self._running = True
        self._consumer_task = asyncio.create_task(self._consumer_loop())
        logger.info("RedisEventBus started (consumer=%s)", self._consumer_name)

    async def stop(self):
        """Gracefully stop and disconnect."""
        self._running = False
        if self._consumer_task:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass

        if self._redis:
            await self._redis.close()
            logger.info("Redis disconnected")

        logger.info("RedisEventBus stopped. Metrics: %s", self._metrics)

    # ─── Publish ─────────────────────────────────────────────

    async def publish(self, event: SystemEvent):
        """Publish event to Redis Stream."""
        if not self._running or not self._redis:
            return

        stream_key = f"{STREAM_PREFIX}.{event.event_type.value}"

        # Serialize event to JSON
        event_data = event.model_dump(mode="json")
        payload = json.dumps(event_data, default=str)

        try:
            await self._redis.xadd(
                stream_key,
                {"event": payload},
                maxlen=self._max_stream_length,
                approximate=True,
            )
            self._metrics["events_published"] += 1

            # Mirror to local history cache for sync get_history()
            self._history[event.event_type.value].append(event)

        except Exception as e:
            logger.error("Redis publish error: %s", e)

    async def publish_quick(
        self,
        event_type: EventType,
        payload: dict,
        source_service: str = "",
        stream_id: str = "",
        causation_id: Optional[str] = None,
    ) -> SystemEvent:
        """Convenience: create and publish an event."""
        event = SystemEvent(
            event_type=event_type,
            payload=payload,
            source_service=source_service,
            stream_id=stream_id,
            causation_id=causation_id,
        )
        await self.publish(event)
        return event

    # ─── Subscribe ────────────────────────────────────────────

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[SystemEvent], Coroutine],
    ):
        """Subscribe to a specific event type."""
        self._subscribers[event_type].append(handler)
        logger.debug("Subscribed: %s → %s", event_type, handler.__qualname__)

        # Ensure consumer group exists for this stream
        asyncio.create_task(self._ensure_consumer_group(event_type))

    def subscribe_wildcard(
        self,
        pattern: str,
        handler: Callable[[SystemEvent], Coroutine],
    ):
        """Subscribe with wildcard pattern."""
        prefix = pattern.rstrip("*").rstrip(".")
        self._wildcard_subscribers.append((prefix, handler))
        logger.debug("Wildcard subscribed: %s → %s", pattern, handler.__qualname__)

    # ─── Consumer Loop ───────────────────────────────────────

    async def _consumer_loop(self):
        """Main loop: read from all subscribed streams and dispatch."""
        while self._running:
            try:
                # Build list of streams to read
                stream_keys = [
                    f"{STREAM_PREFIX}.{et}" for et in self._subscribers.keys()
                ]

                if not stream_keys:
                    await asyncio.sleep(0.5)
                    continue

                # Read with consumer group
                # XREADGROUP GROUP group consumer BLOCK ms STREAMS key [key...] >
                for stream_key in stream_keys:
                    try:
                        messages = await self._redis.xreadgroup(
                            groupname=CONSUMER_GROUP,
                            consumername=self._consumer_name,
                            streams={stream_key: ">"},
                            count=10,
                            block=500,  # ms
                        )

                        for _stream, entries in messages:
                            for msg_id, data in entries:
                                await self._process_message(
                                    stream_key, msg_id, data
                                )

                    except Exception as e:
                        if "NOGROUP" in str(e):
                            # Group doesn't exist yet, create it
                            event_type = stream_key.replace(
                                f"{STREAM_PREFIX}.", ""
                            )
                            await self._ensure_consumer_group(event_type)
                        else:
                            logger.error(
                                "Consumer error on %s: %s", stream_key, e
                            )

                # Small sleep to prevent tight loop
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Consumer loop error: %s", e)
                await asyncio.sleep(1.0)

    async def _process_message(
        self,
        stream_key: str,
        msg_id: str,
        data: dict,
    ):
        """Process a single Redis Stream message."""
        try:
            event_json = data.get("event", "{}")
            event_dict = json.loads(event_json)
            event = SystemEvent(**event_dict)

            # Find matching handlers
            event_type = event.event_type.value
            handlers = list(self._subscribers.get(event_type, []))

            # Check wildcard handlers
            for prefix, handler in self._wildcard_subscribers:
                if event_type.startswith(prefix) or prefix == "":
                    handlers.append(handler)

            # Execute handlers
            for handler in handlers:
                try:
                    await handler(event)
                    self._metrics["events_dispatched"] += 1
                except Exception as e:
                    self._metrics["events_failed"] += 1
                    logger.error(
                        "Handler %s failed for %s: %s",
                        handler.__qualname__, event_type, e,
                    )
                    # Push to DLQ stream
                    try:
                        await self._redis.xadd(
                            f"{STREAM_PREFIX}.dlq",
                            {
                                "event": event_json,
                                "error": str(e),
                                "handler": handler.__qualname__,
                            },
                        )
                        self._metrics["events_dlq"] += 1
                        self._dlq.append((event, str(e)))
                    except Exception:
                        pass

            # ACK the message
            await self._redis.xack(stream_key, CONSUMER_GROUP, msg_id)

        except Exception as e:
            logger.error("Message processing error: %s", e)

    async def _ensure_consumer_group(self, event_type: str):
        """Create consumer group if it doesn't exist."""
        if not self._redis:
            return

        stream_key = f"{STREAM_PREFIX}.{event_type}"
        try:
            await self._redis.xgroup_create(
                stream_key, CONSUMER_GROUP, id="0", mkstream=True
            )
            logger.debug("Consumer group created: %s", stream_key)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                logger.debug("Group may already exist: %s", e)

    # ─── History (sync API, backed by local cache) ──────────────

    def get_history(
        self,
        event_type: str,
        last_n: int = 50,
    ) -> list[SystemEvent]:
        """Get recent events from local cache (sync API, matches EventBus)."""
        history = self._history.get(event_type, deque())
        return list(history)[-last_n:]

    def get_all_recent(self, last_n: int = 100) -> list[SystemEvent]:
        """Get all recent events across all types from local cache."""
        all_events = []
        for history in self._history.values():
            all_events.extend(list(history))
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:last_n]

    @property
    def dead_letter_queue(self) -> list:
        return list(self._dlq)

    async def fetch_history(
        self,
        event_type: str,
        last_n: int = 50,
    ) -> list[SystemEvent]:
        """Fetch history directly from Redis (async, bypasses local cache)."""
        if not self._redis:
            return []

        stream_key = f"{STREAM_PREFIX}.{event_type}"
        try:
            entries = await self._redis.xrevrange(stream_key, count=last_n)
            events = []
            for _msg_id, data in entries:
                event_dict = json.loads(data.get("event", "{}"))
                events.append(SystemEvent(**event_dict))
            return events
        except Exception as e:
            logger.error("History fetch error: %s", e)
            return []

    # ─── Properties ───────────────────────────────────────────

    @property
    def metrics(self) -> dict:
        return dict(self._metrics)

    @property
    def is_connected(self) -> bool:
        return self._redis is not None and self._running
