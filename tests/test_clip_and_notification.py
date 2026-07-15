"""
Tests for Clip Generator + Transcription Microservices
────────────────────────────────────────────────────────
Covers ClipGeneratorService categorization, TranscriptionService status,
and NotificationService message formatting.
"""
import asyncio
import time

import pytest

from shared.event_bus import EventBus
from shared.event_schemas import EventType, SystemEvent
from microservices.clip_generator.service import ClipGeneratorService
from microservices.transcription.service import TranscriptionService
from microservices.notification.service import (
    NotificationService,
    WebhookConfig,
    WebhookType,
    MessageFormatter,
    NotificationPriority,
)


# ── ClipGeneratorService ─────────────────────────────────────


class TestClipGeneratorCategorization:

    def _make_service(self) -> ClipGeneratorService:
        bus = EventBus()
        return ClipGeneratorService(event_bus=bus, capture_service=None, output_dir="/tmp/test_clips")

    def test_donation_plus_chat_velocity(self):
        svc = self._make_service()
        data = {"trigger_signals": ["donation", "chat_velocity"], "highlight_score": {"composite_score": 0.8}}
        assert svc._categorize(data) == "epic_moment"

    def test_audio_spike_plus_emotion(self):
        svc = self._make_service()
        data = {"trigger_signals": ["audio_spike", "emotion_intensity"], "highlight_score": {"composite_score": 0.7}}
        assert svc._categorize(data) == "exciting"

    def test_audio_spike_plus_chat_velocity(self):
        svc = self._make_service()
        data = {"trigger_signals": ["audio_spike", "chat_velocity"], "highlight_score": {"composite_score": 0.6}}
        assert svc._categorize(data) == "hype"

    def test_pose_plus_emotion(self):
        svc = self._make_service()
        data = {"trigger_signals": ["pose_gesture", "emotion_intensity"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "celebration"

    def test_donation_only(self):
        svc = self._make_service()
        data = {"trigger_signals": ["donation"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "donation"

    def test_pose_gesture_only(self):
        svc = self._make_service()
        data = {"trigger_signals": ["pose_gesture"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "celebration"

    def test_chat_velocity_only(self):
        svc = self._make_service()
        data = {"trigger_signals": ["chat_velocity"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "hype"

    def test_chat_sentiment_only(self):
        svc = self._make_service()
        data = {"trigger_signals": ["chat_sentiment"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "funny"

    def test_emotion_only(self):
        svc = self._make_service()
        data = {"trigger_signals": ["emotion_intensity"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "emotional"

    def test_audio_spike_only(self):
        svc = self._make_service()
        data = {"trigger_signals": ["audio_spike"], "highlight_score": {"composite_score": 0.5}}
        assert svc._categorize(data) == "loud_moment"

    def test_no_signals_high_score(self):
        svc = self._make_service()
        data = {"trigger_signals": [], "highlight_score": {"composite_score": 0.95}}
        assert svc._categorize(data) == "epic_moment"

    def test_no_signals_medium_score(self):
        svc = self._make_service()
        data = {"trigger_signals": [], "highlight_score": {"composite_score": 0.75}}
        assert svc._categorize(data) == "exciting"

    def test_no_signals_low_score(self):
        svc = self._make_service()
        data = {"trigger_signals": [], "highlight_score": {"composite_score": 0.3}}
        assert svc._categorize(data) == "highlight"

    def test_empty_signals(self):
        svc = self._make_service()
        data = {"trigger_signals": [], "highlight_score": {"composite_score": 0.0}}
        assert svc._categorize(data) == "highlight"


class TestClipGeneratorStatus:

    def test_initial_status(self):
        bus = EventBus()
        svc = ClipGeneratorService(event_bus=bus, capture_service=None, output_dir="/tmp/test_clips2")
        status = svc.get_status()
        assert status["clips_generated"] == 0
        assert status["clips_failed"] == 0
        assert status["capture_connected"] is False

    def test_estimate_duration(self):
        bus = EventBus()
        svc = ClipGeneratorService(event_bus=bus, capture_service=None, output_dir="/tmp/test_clips3")
        assert svc._estimate_duration({}) == 10.0


# ── TranscriptionService ─────────────────────────────────────


class TestTranscriptionService:

    def test_initial_status(self):
        bus = EventBus()
        svc = TranscriptionService(event_bus=bus, model_size="tiny")
        status = svc.get_status()
        assert status["model_size"] == "tiny"
        assert status["model_loaded"] is False
        assert status["clips_transcribed"] == 0
        assert status["clips_failed"] == 0

    def test_status_with_language(self):
        bus = EventBus()
        svc = TranscriptionService(event_bus=bus, model_size="base", language="tr")
        status = svc.get_status()
        assert status["language"] == "tr"

    @pytest.mark.asyncio
    async def test_transcribe_without_model(self):
        bus = EventBus()
        svc = TranscriptionService(event_bus=bus)
        result = await svc.transcribe("/nonexistent/audio.wav")
        assert result["text"] == ""
        assert result["segments"] == []


# ── MessageFormatter ─────────────────────────────────────


class TestMessageFormatter:

    def test_format_discord_clip(self):
        msg = MessageFormatter.format_discord(
            EventType.CLIP_CREATED.value,
            {"highlight_score": 0.85, "duration_seconds": 12.0, "category": "exciting", "tags": ["audio_spike"], "file_path": "/data/clip.mp4"},
            stream_id="stream-1",
        )
        assert "embeds" in msg
        embed = msg["embeds"][0]
        assert embed["title"] == "🎬 New Clip Created!"
        assert embed["color"] == 0x00FF00
        assert len(embed["fields"]) >= 3

    def test_format_discord_donation(self):
        msg = MessageFormatter.format_discord(
            EventType.DONATION_RECEIVED.value,
            {"amount": "$50.00", "username": "viewer1"},
        )
        embed = msg["embeds"][0]
        assert embed["color"] == 0xFFD700
        assert any(f["name"] == "Amount" for f in embed["fields"])

    def test_format_telegram_clip(self):
        msg = MessageFormatter.format_telegram(
            EventType.CLIP_CREATED.value,
            {"highlight_score": 0.75, "duration_seconds": 10.0, "category": "hype", "tags": ["chat_velocity"]},
            stream_id="stream-2",
        )
        assert "text" in msg
        assert "<b>" in msg["text"]
        assert msg["parse_mode"] == "HTML"
        assert "Score" in msg["text"]

    def test_format_telegram_donation(self):
        msg = MessageFormatter.format_telegram(
            EventType.DONATION_RECEIVED.value,
            {"amount": "100 TL", "username": "donor"},
        )
        assert "100 TL" in msg["text"]
        assert "donor" in msg["text"]

    def test_format_generic(self):
        msg = MessageFormatter.format_generic(
            EventType.CLIP_CREATED.value,
            {"highlight_score": 0.9},
            stream_id="s1",
        )
        assert msg["event"] == EventType.CLIP_CREATED.value
        assert msg["source"] == "klip-yakalama-sistemi"
        assert msg["stream_id"] == "s1"

    def test_event_title_unknown(self):
        title = MessageFormatter._event_title("unknown.event")
        assert "unknown.event" in title

    def test_event_color_unknown(self):
        color = MessageFormatter._event_color("unknown.event")
        assert color == 0x808080


# ── WebhookConfig ─────────────────────────────────────


class TestWebhookConfig:

    def test_should_send_enabled(self):
        wh = WebhookConfig(
            url="https://example.com/hook",
            events=[EventType.CLIP_CREATED.value],
            enabled=True,
        )
        assert wh.should_send(EventType.CLIP_CREATED.value) is True

    def test_should_send_disabled(self):
        wh = WebhookConfig(url="https://x.com", enabled=False)
        assert wh.should_send(EventType.CLIP_CREATED.value) is False

    def test_should_send_wrong_event(self):
        wh = WebhookConfig(
            url="https://x.com",
            events=[EventType.DONATION_RECEIVED.value],
            enabled=True,
        )
        assert wh.should_send(EventType.CLIP_CREATED.value) is False

    def test_to_dict(self):
        wh = WebhookConfig(url="https://x.com", label="test_hook", webhook_type=WebhookType.DISCORD)
        d = wh.to_dict()
        assert d["url"] == "https://x.com"
        assert d["webhook_type"] == "discord"
        assert d["label"] == "test_hook"

    def test_default_label(self):
        wh = WebhookConfig(url="https://x.com", webhook_type=WebhookType.TELEGRAM)
        assert wh.label == "telegram"


# ── NotificationService ─────────────────────────────────────


class TestNotificationService:

    def test_initial_status(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        status = svc.get_status()
        assert status["webhooks_count"] == 0
        assert status["notifications_sent"] == 0
        assert status["notifications_failed"] == 0

    def test_add_webhook(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        wh = WebhookConfig(url="https://x.com", label="test", events=[EventType.CLIP_CREATED.value])
        svc.add_webhook(wh)
        assert len(svc.list_webhooks()) == 1
        assert svc.list_webhooks()[0]["label"] == "test"

    def test_remove_webhook(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        wh = WebhookConfig(url="https://x.com", label="removeme")
        svc.add_webhook(wh)
        assert svc.remove_webhook("removeme") is True
        assert len(svc.list_webhooks()) == 0

    def test_remove_nonexistent(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        assert svc.remove_webhook("nonexistent") is False

    def test_multiple_webhooks(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        svc.add_webhook(WebhookConfig(url="https://a.com", label="a"))
        svc.add_webhook(WebhookConfig(url="https://b.com", label="b"))
        assert svc.get_status()["webhooks_count"] == 2

    @pytest.mark.asyncio
    async def test_send_test_nonexistent(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        result = await svc.send_test("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_close_no_error(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus)
        await svc.close()  # Should not raise

    def test_rate_limit(self):
        bus = EventBus()
        svc = NotificationService(event_bus=bus, rate_limit_per_minute=2)
        assert svc._check_rate_limit() is True
        svc._rate_window = [time.time(), time.time()]
        assert svc._check_rate_limit() is False
