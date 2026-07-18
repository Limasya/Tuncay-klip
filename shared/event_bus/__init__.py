"""
Event Bus — the backbone of the microservice architecture.

Local dev: In-memory pub/sub (no dependencies)
Production: Swap to Redis Streams or Kafka

Every microservice publishes and subscribes through this bus.
"""
from __future__ import annotations
import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Callable, Coroutine, Optional

from shared.event_schemas import SystemEvent, EventType

logger = logging.getLogger("event_bus")


class EventBus:
    """
    Async in-memory event bus.

    Architecture:
    ┌────────────┐     publish      ┌───────────┐     dispatch     ┌──────────────┐
    │  Producer   │ ─────────────► │ Event Bus │ ──────────────► │  Consumer     │
    │  (service)  │                 │           │                  │  (service)    │
    └────────────┘                  └───────────┘                  └──────────────┘

    Features:
    - Async pub/sub with type-based routing
    - Wildcard subscriptions ("analysis.*")
    - Event history (last N events per topic)
    - Dead-letter queue for failed handlers
    - Metrics (events published, consumed, errors)
    - Graceful shutdown with drain
    """

    def __init__(self, history_size: int = 500):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._wildcard_subscribers: list[tuple[str, Callable]] = []
        self._history: dict[str, deque] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._dlq: deque = deque(maxlen=100)  # Dead-letter queue
        self._running = True
        self._dispatch_queue: asyncio.Queue = asyncio.Queue(maxsize=10000)

        # Metrics
        self._metrics = {
            "events_published": 0,
            "events_dispatched": 0,
            "events_failed": 0,
            "events_dlq": 0,
        }

        # Track dispatch tasks
        self._dispatch_task: Optional[asyncio.Task] = None

    async def start(self):
        """Start the event bus dispatch loop."""
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop())
        logger.info("EventBus started")

    async def stop(self):
        """Gracefully stop the event bus."""
        self._running = False
        # Drain remaining events
        while not self._dispatch_queue.empty():
            try:
                self._dispatch_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        if self._dispatch_task:
            self._dispatch_task.cancel()
            try:
                await self._dispatch_task
            except asyncio.CancelledError:
                pass
        logger.info(f"EventBus stopped. Metrics: {self._metrics}")

    async def publish(self, event: SystemEvent):
        """
        Publish an event to the bus.

        This is non-blocking — events are queued and dispatched async.
        """
        if not self._running:
            return

        # Store in history
        self._history[event.event_type.value].append(event)

        # Queue for dispatch
        try:
            self._dispatch_queue.put_nowait(event)
            self._metrics["events_published"] += 1
        except asyncio.QueueFull:
            logger.warning(
                f"Event bus queue full! Dropping event: {event.event_type}"
            )
            self._metrics["events_dlq"] += 1
            self._dlq.append((event, "queue_full"))

    async def publish_quick(
        self,
        event_type: EventType,
        payload: dict,
        source_service: str = "",
        stream_id: str = "",
        causation_id: Optional[str] = None,
    ) -> SystemEvent:
        """Convenience method to create and publish an event quickly."""
        event = SystemEvent(
            event_type=event_type,
            payload=payload,
            source_service=source_service,
            stream_id=stream_id,
            causation_id=causation_id,
        )
        await self.publish(event)
        return event

    def subscribe(
        self,
        event_type: str,
        handler: Callable[[SystemEvent], Coroutine],
    ):
        """
        Subscribe to a specific event type.

        Args:
            event_type: Exact match (e.g., "analysis.face_detected")
            handler: Async function called with SystemEvent
        """
        self._subscribers[event_type].append(handler)
        logger.debug(f"Subscribed to {event_type}: {handler.__qualname__}")

    def subscribe_wildcard(
        self,
        pattern: str,
        handler: Callable[[SystemEvent], Coroutine],
    ):
        """
        Subscribe with wildcard pattern.

        Pattern: "analysis.*" matches all analysis events
        Pattern: "*" matches everything
        """
        prefix = pattern.rstrip("*").rstrip(".")
        self._wildcard_subscribers.append((prefix, handler))
        logger.debug(f"Wildcard subscribed to {pattern}: {handler.__qualname__}")

    def get_history(
        self,
        event_type: str,
        last_n: int = 50,
    ) -> list[SystemEvent]:
        """Get recent events of a specific type."""
        history = self._history.get(event_type, deque())
        return list(history)[-last_n:]

    def get_all_recent(self, last_n: int = 100) -> list[SystemEvent]:
        """Get all recent events across all types."""
        all_events = []
        for history in self._history.values():
            all_events.extend(list(history))
        all_events.sort(key=lambda e: e.timestamp, reverse=True)
        return all_events[:last_n]

    @property
    def metrics(self) -> dict:
        return dict(self._metrics)

    @property
    def dead_letter_queue(self) -> list:
        return list(self._dlq)

    async def _dispatch_loop(self):
        """Main dispatch loop — routes events to subscribers."""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._dispatch_queue.get(),
                    timeout=0.5,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            await self._dispatch_event(event)

    async def _dispatch_event(self, event: SystemEvent):
        """Dispatch a single event to matching subscribers."""
        event_type = event.event_type.value
        handlers: list[Callable] = []

        # Exact match subscribers
        if event_type in self._subscribers:
            handlers.extend(self._subscribers[event_type])

        # Wildcard match subscribers
        for prefix, handler in self._wildcard_subscribers:
            if event_type.startswith(prefix) or prefix == "":
                handlers.append(handler)

        # Execute all handlers concurrently
        for handler in handlers:
            try:
                await handler(event)
                self._metrics["events_dispatched"] += 1
            except Exception as e:
                self._metrics["events_failed"] += 1
                logger.error(
                    f"Handler {handler.__qualname__} failed for "
                    f"{event_type}: {e}",
                    exc_info=True,
                )
                self._dlq.append((event, str(e)))


# ─── Singleton Instance & Factory ─────────────────────────────

_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus singleton."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(bus) -> None:
    """Replace the global event bus (used by factory/tests)."""
    global _event_bus
    _event_bus = bus


async def init_event_bus():
    """Initialize and start the event bus.

    Chooses backend based on config:
      - 'memory' (default): in-memory EventBus
      - 'redis': RedisEventBus backed by Redis Streams
    """
    try:
        from config import get_settings
        settings = get_settings()
        backend = settings.event_bus_backend
    except Exception as e:
        logger.debug("Event bus config unavailable, falling back to memory: %s", e)
        backend = "memory"

    if backend == "redis":
        from shared.event_bus.redis_bus import RedisEventBus
        bus = RedisEventBus(redis_url=settings.redis_url)
        logger.info("Using Redis Streams event bus: %s", settings.redis_url)
    else:
        bus = EventBus()
        logger.info("Using in-memory event bus")

    set_event_bus(bus)
    await bus.start()
    return bus
