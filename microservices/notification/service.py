"""
Notification Microservice
─────────────────────────
Sends webhook notifications (Discord, Telegram, generic webhook)
when clips are created or other events occur.

Flow: CLIP_CREATED / Custom Event → Format Message → HTTP POST → Webhook
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from datetime import datetime
from enum import Enum
from typing import Any, Optional

import httpx

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("notification")


class WebhookType(str, Enum):
    DISCORD = "discord"
    TELEGRAM = "telegram"
    GENERIC = "generic"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class WebhookConfig:
    """Configuration for a single webhook endpoint."""

    def __init__(
        self,
        url: str,
        webhook_type: WebhookType = WebhookType.GENERIC,
        secret: str = "",
        enabled: bool = True,
        events: Optional[list[str]] = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        label: str = "",
    ):
        self.url = url
        self.webhook_type = webhook_type
        self.secret = secret
        self.enabled = enabled
        self.events = events or [EventType.CLIP_CREATED.value]
        self.priority = priority
        self.label = label or webhook_type.value

    def should_send(self, event_type: str) -> bool:
        return self.enabled and event_type in self.events

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "webhook_type": self.webhook_type.value,
            "enabled": self.enabled,
            "events": self.events,
            "priority": self.priority.value,
            "label": self.label,
        }


class MessageFormatter:
    """Formats event data into webhook messages for different platforms."""

    @staticmethod
    def format_discord(event_type: str, payload: dict, stream_id: str = "") -> dict:
        """Format as Discord webhook embed."""
        title = MessageFormatter._event_title(event_type)
        color = MessageFormatter._event_color(event_type)

        fields = []

        if event_type == EventType.CLIP_CREATED.value:
            fields.append({"name": "Score", "value": f"{payload.get('highlight_score', 0):.2f}", "inline": True})
            fields.append({"name": "Duration", "value": f"{payload.get('duration_seconds', 0):.1f}s", "inline": True})
            fields.append({"name": "Category", "value": payload.get("category", "highlight"), "inline": True})
            tags = payload.get("tags", [])
            if tags:
                fields.append({"name": "Signals", "value": ", ".join(tags), "inline": False})
            file_path = payload.get("file_path", "")
            if file_path:
                fields.append({"name": "File", "value": f"`{file_path}`", "inline": False})

        elif event_type == EventType.CLIP_CANDIDATE.value:
            candidate = payload.get("candidate", {})
            score = candidate.get("highlight_score", {}).get("composite_score", 0)
            fields.append({"name": "Score", "value": f"{score:.2f}", "inline": True})
            signals = candidate.get("trigger_signals", [])
            if signals:
                fields.append({"name": "Signals", "value": ", ".join(signals), "inline": False})

        elif event_type == EventType.DONATION_RECEIVED.value:
            fields.append({"name": "Amount", "value": payload.get("amount", "unknown"), "inline": True})
            fields.append({"name": "User", "value": payload.get("username", "unknown"), "inline": True})

        if stream_id:
            fields.append({"name": "Stream", "value": stream_id, "inline": True})

        embed = {
            "title": title,
            "color": color,
            "fields": fields,
            "timestamp": datetime.utcnow().isoformat(),
            "footer": {"text": "Klip Yakalama Sistemi"},
        }

        return {"embeds": [embed]}

    @staticmethod
    def format_telegram(event_type: str, payload: dict, stream_id: str = "") -> dict:
        """Format as Telegram message (HTML parse mode)."""
        title = MessageFormatter._event_title(event_type)
        lines = [f"<b>{title}</b>", ""]

        if event_type == EventType.CLIP_CREATED.value:
            lines.append(f"🎬 Score: <b>{payload.get('highlight_score', 0):.2f}</b>")
            lines.append(f"⏱ Duration: {payload.get('duration_seconds', 0):.1f}s")
            lines.append(f"🏷 Category: {payload.get('category', 'highlight')}")
            tags = payload.get("tags", [])
            if tags:
                lines.append(f"📡 Signals: {', '.join(tags)}")

        elif event_type == EventType.DONATION_RECEIVED.value:
            lines.append(f"💰 Amount: {payload.get('amount', 'unknown')}")
            lines.append(f"👤 User: {payload.get('username', 'unknown')}")

        if stream_id:
            lines.append(f"📺 Stream: {stream_id}")

        lines.append(f"\n<i>{datetime.utcnow().strftime('%H:%M:%S UTC')}</i>")

        return {
            "text": "\n".join(lines),
            "parse_mode": "HTML",
        }

    @staticmethod
    def format_generic(event_type: str, payload: dict, stream_id: str = "") -> dict:
        """Format as generic JSON payload."""
        return {
            "event": event_type,
            "title": MessageFormatter._event_title(event_type),
            "stream_id": stream_id,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
            "source": "klip-yakalama-sistemi",
        }

    @staticmethod
    def _event_title(event_type: str) -> str:
        titles = {
            EventType.CLIP_CREATED.value: "🎬 New Clip Created!",
            EventType.CLIP_CANDIDATE.value: "🔍 Clip Candidate Detected",
            EventType.DONATION_RECEIVED.value: "💰 Donation Detected!",
            EventType.STREAM_STARTED.value: "📺 Stream Started",
            EventType.STREAM_ENDED.value: "📺 Stream Ended",
            EventType.AUDIO_SPIKE.value: "🔊 Audio Spike!",
            EventType.CHAT_SPIKE.value: "💬 Chat Spike!",
        }
        return titles.get(event_type, f"📢 Event: {event_type}")

    @staticmethod
    def _event_color(event_type: str) -> int:
        colors = {
            EventType.CLIP_CREATED.value: 0x00FF00,
            EventType.DONATION_RECEIVED.value: 0xFFD700,
            EventType.AUDIO_SPIKE.value: 0xFF4500,
            EventType.CHAT_SPIKE.value: 0x1E90FF,
        }
        return colors.get(event_type, 0x808080)


class NotificationService:
    """
    Webhook notification service.

    Manages multiple webhook endpoints (Discord, Telegram, generic).
    Subscribes to configured events and sends formatted messages.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        webhooks: Optional[list[WebhookConfig]] = None,
        rate_limit_per_minute: int = 30,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.webhooks: list[WebhookConfig] = webhooks or []
        self.rate_limit_per_minute = rate_limit_per_minute

        self._sent_count = 0
        self._failed_count = 0
        self._rate_window: list[float] = []
        self._http_client: Optional[httpx.AsyncClient] = None

        # Subscribe to all unique events from webhooks
        subscribed_events = set()
        for wh in self.webhooks:
            for evt in wh.events:
                if evt not in subscribed_events:
                    subscribed_events.add(evt)
                    self.event_bus.subscribe(evt, self._on_event)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True,
            )
        return self._http_client

    async def _on_event(self, event: SystemEvent):
        """Handle incoming events — send to matching webhooks."""
        for wh in self.webhooks:
            if not wh.should_send(event.event_type):
                continue

            if self._is_rate_limited():
                logger.warning("Rate limit reached, skipping notification")
                return

            await self._send_notification(wh, event)

    async def _send_notification(self, config: WebhookConfig, event: SystemEvent):
        """Send a notification to a single webhook."""
        if not self._check_rate_limit():
            logger.warning(f"Rate limited: {config.label}")
            return

        try:
            payload = self._format_message(config, event)
            headers = self._build_headers(config, payload)

            client = await self._get_client()
            resp = await client.post(config.url, json=payload, headers=headers)

            if resp.status_code in (200, 204):
                self._sent_count += 1
                logger.info(f"Notification sent: {config.label} ({event.event_type})")
            else:
                self._failed_count += 1
                logger.warning(f"Notification failed: {config.label} -> {resp.status_code}")

        except httpx.TimeoutException:
            self._failed_count += 1
            logger.error(f"Notification timeout: {config.label}")
        except Exception as e:
            self._failed_count += 1
            logger.error(f"Notification error: {config.label} -> {e}")

    def _format_message(self, config: WebhookConfig, event: SystemEvent) -> dict:
        if config.webhook_type == WebhookType.DISCORD:
            return MessageFormatter.format_discord(event.event_type, event.payload, event.stream_id)
        elif config.webhook_type == WebhookType.TELEGRAM:
            return MessageFormatter.format_telegram(event.event_type, event.payload, event.stream_id)
        else:
            return MessageFormatter.format_generic(event.event_type, event.payload, event.stream_id)

    def _build_headers(self, config: WebhookConfig, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if config.secret:
            body = json.dumps(payload, separators=(",", ":"))
            signature = hmac.new(
                config.secret.encode(), body.encode(), hashlib.sha256
            ).hexdigest()
            headers["X-Webhook-Signature"] = f"sha256={signature}"
        return headers

    def _check_rate_limit(self) -> bool:
        now = time.time()
        self._rate_window = [t for t in self._rate_window if now - t < 60]
        return len(self._rate_window) < self.rate_limit_per_minute

    def _is_rate_limited(self) -> bool:
        return not self._check_rate_limit()

    # --- Public API ---

    def add_webhook(self, config: WebhookConfig):
        """Add a new webhook and subscribe to its events."""
        self.webhooks.append(config)
        for evt in config.events:
            self.event_bus.subscribe(evt, self._on_event)
        logger.info(f"Webhook added: {config.label} ({config.webhook_type.value})")

    def remove_webhook(self, label: str) -> bool:
        """Remove a webhook by label."""
        before = len(self.webhooks)
        self.webhooks = [w for w in self.webhooks if w.label != label]
        removed = len(self.webhooks) < before
        if removed:
            logger.info(f"Webhook removed: {label}")
        return removed

    def list_webhooks(self) -> list[dict]:
        return [w.to_dict() for w in self.webhooks]

    async def send_test(self, label: str) -> bool:
        """Send a test notification to a specific webhook."""
        for wh in self.webhooks:
            if wh.label == label:
                test_event = SystemEvent(
                    event_type=EventType.CLIP_CREATED.value,
                    payload={
                        "file_path": "data/clips/test_clip.mp4",
                        "highlight_score": 0.85,
                        "duration_seconds": 12.5,
                        "category": "test",
                        "tags": ["test", "debug"],
                    },
                    source_service="notification-test",
                    stream_id="test-stream",
                )
                await self._send_notification(wh, test_event)
                return True
        return False

    async def close(self):
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    def auto_configure_from_settings(self):
        """Auto-configure webhooks from environment config."""
        try:
            from config import get_settings
            s = get_settings()

            clip_events = [EventType.CLIP_CREATED.value, EventType.DONATION_RECEIVED.value]

            if s.discord_webhook_url:
                self.add_webhook(WebhookConfig(
                    url=s.discord_webhook_url,
                    webhook_type=WebhookType.DISCORD,
                    secret=s.webhook_secret,
                    events=clip_events,
                    label="discord-auto",
                ))

            if s.telegram_bot_token and s.telegram_chat_id:
                url = f"https://api.telegram.org/bot{s.telegram_bot_token}/sendMessage?chat_id={s.telegram_chat_id}"
                self.add_webhook(WebhookConfig(
                    url=url,
                    webhook_type=WebhookType.TELEGRAM,
                    events=clip_events,
                    label="telegram-auto",
                ))

            if s.generic_webhook_url:
                self.add_webhook(WebhookConfig(
                    url=s.generic_webhook_url,
                    webhook_type=WebhookType.GENERIC,
                    secret=s.webhook_secret,
                    events=clip_events,
                    label="generic-auto",
                ))

            logger.info("Auto-configured webhooks from env (%d total)", len(self.webhooks))
        except Exception as e:
            logger.warning("Auto-configure webhooks failed: %s", e)

    def get_status(self) -> dict:
        return {
            "webhooks_count": len(self.webhooks),
            "webhooks": [w.to_dict() for w in self.webhooks],
            "notifications_sent": self._sent_count,
            "notifications_failed": self._failed_count,
            "rate_limit_per_minute": self.rate_limit_per_minute,
        }
