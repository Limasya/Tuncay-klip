"""
Chat Signal Producer — Kick chat polling → EventBus chat.spike events
=====================================================================
Kick chat mesajlarını polling ile çeker, velocity spike tespit eder,
EventBus'a chat.spike event'i yayınlar.

Cloudflare Risk Azaltma:
  - Jitter: Polling aralığına rastgele ±0.3s eklenir
  - Exponential Backoff: HTTP hatalarında 2s→4s→8s→...→30s (cap)
  - Max 5 consecutive error sonrası poll interval'ı artır

Akış:
  Kick chat HTTP polling (2s + jitter)
       │
       ▼
  Velocity hesaplama (messages/sec son 30s vs baseline son 300s)
       │
       spike_ratio > 2.0 → chat.spike event → EventBus
       │
       ▼
  EventDetectorService._on_chat_spike() → scoring.update_signal("chat_velocity", ...)
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("chat_signal_producer")


class BackoffState:
    """Exponential backoff state tracker."""

    def __init__(
        self,
        base_delay: float = 2.0,
        max_delay: float = 30.0,
        max_retries: int = 5,
    ):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries
        self._consecutive_errors = 0

    def record_success(self):
        """Successful request — reset counter."""
        self._consecutive_errors = 0

    def record_error(self) -> float:
        """Failed request — return delay before next attempt."""
        self._consecutive_errors += 1
        if self._consecutive_errors >= self.max_retries:
            logger.warning(
                "Chat polling backoff: %d consecutive errors, "
                "polling interval increased",
                self._consecutive_errors,
            )
        return min(
            self.base_delay * (2 ** (self._consecutive_errors - 1)),
            self.max_delay,
        )

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def is_degraded(self) -> bool:
        return self._consecutive_errors >= self.max_retries


class ChatVelocityTracker:
    """
    Chat velocity'yi takip eder.
    Son N saniyelik mesaj sayısını sayar, spike tespit eder.
    """

    def __init__(
        self,
        short_window: float = 30.0,
        long_window: float = 300.0,
        spike_threshold: float = 2.0,
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.spike_threshold = spike_threshold
        self._message_times: deque = deque()
        self._total_messages: int = 0

    def record_message(self, timestamp: float | None = None):
        """Yeni mesaj kaydet."""
        ts = timestamp or time.time()
        self._message_times.append(ts)
        self._total_messages += 1
        self._cleanup_old(timestamp=ts)

    def _cleanup_old(self, timestamp: float):
        """Eski mesajları temizle."""
        cutoff = timestamp - self.long_window
        while self._message_times and self._message_times[0] < cutoff:
            self._message_times.popleft()

    def get_velocity(self) -> Dict[str, float]:
        """
        Mevcut velocity hesapla.
        short_rate: Son 30s'de mesaj/saniye
        long_rate: Son 300s'de mesaj/saniye
        spike_ratio: short_rate / max(long_rate, 0.01)
        """
        now = time.time()
        short_cutoff = now - self.short_window
        long_cutoff = now - self.long_window

        short_count = sum(1 for t in self._message_times if t > short_cutoff)
        long_count = sum(1 for t in self._message_times if t > long_cutoff)

        short_rate = short_count / max(self.short_window, 0.1)
        long_rate = long_count / max(self.long_window, 0.1)

        spike_ratio = short_rate / max(long_rate, 0.01)

        return {
            "short_count": short_count,
            "long_count": long_count,
            "short_rate": short_rate,
            "long_rate": long_rate,
            "spike_ratio": spike_ratio,
            "is_spike": spike_ratio >= self.spike_threshold,
        }

    @property
    def total_messages(self) -> int:
        return self._total_messages


class ChatSignalProducer:
    """
    Kick chat polling → EventBus chat.spike producer.

    Cloudflare Risk Azaltma:
      - Jitter: ±0.3s rastgele offset
      - Exponential Backoff: HTTP hatalarında 2s→30s
      - Degraded mode: 5+ hata sonrası polling yavaşlar

    Usage:
        producer = ChatSignalProducer()
        await producer.start(stream_id="tuncay", poll_interval=2.0)

    Her spike tespit ettiğinde EventBus'a chat.spike event'i yayınlar.
    EventDetectorService bu event'i alıp scoring'a ekler.
    """

    JITTER_RANGE = 0.3  # ±0.3s

    def __init__(self):
        self._tracker = ChatVelocityTracker()
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None
        self._on_spike_callbacks: list = []
        self._stream_id: str = "default"
        self._last_spike_time: float = 0.0
        self._spike_cooldown: float = 5.0  # saniye
        self._backoff = BackoffState()
        self._base_poll_interval: float = 2.0

    async def start(
        self,
        stream_id: str = "default",
        poll_interval: float = 2.0,
        chatroom_id: Optional[int] = None,
    ):
        """Chat polling'i başlat."""
        self._running = True
        self._stream_id = stream_id
        self._base_poll_interval = poll_interval

        try:
            from services.kick_api import kick_service
            self._kick_service = kick_service
        except ImportError:
            logger.error("kick_api mevcut değil, chat signal üretilemiyor")
            return

        self._poll_task = asyncio.create_task(
            self._poll_loop(poll_interval, chatroom_id)
        )
        logger.info(
            "Chat signal producer başlatıldı: stream=%s, interval=%.1fs (+jitter±%.1fs)",
            stream_id, poll_interval, self.JITTER_RANGE,
        )

    async def stop(self):
        """Polling'i durdur."""
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Chat signal producer durduruldu.")

    def _jittered_sleep(self, base_interval: float) -> float:
        """Polling aralığına jitter ekle."""
        jitter = random.uniform(-self.JITTER_RANGE, self.JITTER_RANGE)
        return max(0.1, base_interval + jitter)

    async def _poll_loop(self, interval: float, chatroom_id: Optional[int]):
        """Periyodik chat polling döngüsü + backoff + jitter."""
        cursor = None
        while self._running:
            sleep_time = self._jittered_sleep(interval)

            # Backoff: consecutive error varsa bekleme süresini artır
            if self._backoff.is_degraded:
                backoff_delay = self._backoff.record_error()
                sleep_time = max(sleep_time, backoff_delay)
                logger.debug(
                    "Chat polling degraded: sleep=%.1fs (errors=%d)",
                    sleep_time, self._backoff.consecutive_errors,
                )

            try:
                data = await self._kick_service.get_chat_messages(cursor)
                messages = data.get("data", [])
                cursor = data.get("meta", {}).get("cursor")

                for msg in messages:
                    self._tracker.record_message()
                    await self._process_message(msg)

                velocity = self._tracker.get_velocity()
                if velocity["is_spike"]:
                    await self._emit_spike(velocity)

                self._backoff.record_success()

            except Exception as e:
                logger.error("Chat polling hatası: %s", e)
                backoff_delay = self._backoff.record_error()
                sleep_time = max(sleep_time, backoff_delay)

            await asyncio.sleep(sleep_time)

    async def _process_message(self, msg: Dict[str, Any]):
        """Tek bir chat mesajını işle."""
        pass

    async def _emit_spike(self, velocity: Dict[str, float]):
        """Chat spike event'i yayınla."""
        now = time.time()
        if now - self._last_spike_time < self._spike_cooldown:
            return

        self._last_spike_time = now

        event_data = {
            "spike_ratio": velocity["spike_ratio"],
            "short_rate": velocity["short_rate"],
            "long_rate": velocity["long_rate"],
            "short_count": velocity["short_count"],
            "total_messages": self._tracker.total_messages,
        }

        try:
            from shared.event_bus import EventBus, EventType, SystemEvent
            bus = EventBus()
            event = SystemEvent(
                event_type=EventType.CHAT_SPIKE,
                payload=event_data,
                source_service="chat_signal_producer",
                stream_id=self._stream_id,
            )
            await bus.publish(event)
            logger.info(
                "Chat spike yayınlandı: ratio=%.2f, short=%d msgs, long=%d msgs",
                velocity["spike_ratio"],
                velocity["short_count"],
                velocity["long_count"],
            )
        except ImportError:
            logger.warning("EventBus mevcut değil, spike sadece loglanıyor")
        except Exception as e:
            logger.error("Chat spike yayınlanamadı: %s", e)

        for cb in self._on_spike_callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(velocity)
                else:
                    cb(velocity)
            except Exception as e:
                logger.error("Chat spike callback hatası: %s", e)

    def on_spike(self, callback: Callable):
        """Spike callback'i kaydet."""
        self._on_spike_callbacks.append(callback)

    def get_status(self) -> Dict[str, Any]:
        velocity = self._tracker.get_velocity()
        return {
            "running": self._running,
            "stream_id": self._stream_id,
            "total_messages": self._tracker.total_messages,
            "velocity": velocity,
            "backoff": {
                "consecutive_errors": self._backoff.consecutive_errors,
                "is_degraded": self._backoff.is_degraded,
            },
        }


# Singleton
chat_signal_producer = ChatSignalProducer()
