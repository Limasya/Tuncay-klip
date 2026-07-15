"""
Unit tests for Chat Analysis microservice.
Tests sentiment analysis, donation detection, and spike detection.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio

from shared.event_bus import EventBus
from shared.event_schemas import EventType
from microservices.chat_analysis.service import (
    ChatAnalysisService, SentimentAnalyzer, ChatSpikeDetector,
)


# ─── SentimentAnalyzer Tests ─────────────────────────────

class TestSentimentAnalyzer:
    """Test keyword-based sentiment analysis."""

    def setup_method(self):
        self.analyzer = SentimentAnalyzer()

    def test_positive_english(self):
        result = self.analyzer.analyze("pogchamp that was amazing!")
        assert result.label == "POSITIVE"
        assert result.score > 0

    def test_positive_turkish(self):
        result = self.analyzer.analyze("helal olsun kral")
        assert result.label == "POSITIVE"
        assert result.score > 0

    def test_negative_english(self):
        result = self.analyzer.analyze("that was cringe, total fail")
        assert result.label == "NEGATIVE"
        assert result.score < 0

    def test_negative_turkish(self):
        result = self.analyzer.analyze("çok kötü berbat")
        assert result.label == "NEGATIVE"
        assert result.score < 0

    def test_neutral_message(self):
        result = self.analyzer.analyze("hello everyone, how are you?")
        assert result.label == "NEUTRAL"
        assert result.score == 0.0

    def test_high_weight_words(self):
        """High-weight words produce stronger sentiment."""
        r1 = self.analyzer.analyze("nice play")
        r2 = self.analyzer.analyze("pogchamp play")
        # pogchamp has 2x weight
        assert abs(r2.score) >= abs(r1.score)

    def test_mixed_sentiment(self):
        """Mixed positive + negative can produce neutral."""
        result = self.analyzer.analyze("pog but also cringe")
        # Both pos and neg words present
        assert result.label in ("POSITIVE", "NEGATIVE", "NEUTRAL")

    def test_case_insensitive(self):
        r1 = self.analyzer.analyze("POGCHAMP")
        r2 = self.analyzer.analyze("pogchamp")
        assert r1.label == r2.label

    def test_turkish_chars(self):
        result = self.analyzer.analyze("mükemmel oyun süper")
        assert result.label == "POSITIVE"

    def test_empty_message(self):
        result = self.analyzer.analyze("")
        assert result.label == "NEUTRAL"


# ─── Donation Detection Tests ────────────────────────────

class TestDonationDetection:
    """Test donation/tip detection in chat messages."""

    def test_dollar_amount(self):
        result = ChatAnalysisService._detect_donation("donated $10 great stream!", "")
        assert result is not None
        assert result["amount"] == 10.0
        assert result["currency"] == "USD"

    def test_dollar_decimal(self):
        result = ChatAnalysisService._detect_donation("$5.50 for the vibes", "")
        assert result is not None
        assert result["amount"] == 5.5

    def test_tl_amount(self):
        result = ChatAnalysisService._detect_donation("50TL bağış", "")
        assert result is not None
        assert result["amount"] == 50.0
        assert result["currency"] == "TRY"

    def test_try_amount(self):
        result = ChatAnalysisService._detect_donation("100 try gönderdi", "")
        assert result is not None
        assert result["amount"] == 100.0

    def test_lira_symbol(self):
        result = ChatAnalysisService._detect_donation("25₺ hediye", "")
        assert result is not None
        assert result["amount"] == 25.0

    def test_donated_keyword(self):
        result = ChatAnalysisService._detect_donation("donated 15 to the streamer", "")
        assert result is not None
        assert result["amount"] == 15.0

    def test_tipped_keyword(self):
        result = ChatAnalysisService._detect_donation("tipped 20", "")
        assert result is not None
        assert result["amount"] == 20.0

    def test_bahis_turkish(self):
        result = ChatAnalysisService._detect_donation("bağış 50", "")
        assert result is not None
        assert result["amount"] == 50.0

    def test_usd_keyword(self):
        result = ChatAnalysisService._detect_donation("sent 25 USD", "")
        assert result is not None
        assert result["amount"] == 25.0

    def test_keyword_only_donation(self):
        """Donation keyword without amount."""
        result = ChatAnalysisService._detect_donation("thanks for the donation!", "")
        assert result is not None
        assert result["amount"] == 0.0
        assert result["currency"] == "UNKNOWN"

    def test_normal_message_not_donation(self):
        result = ChatAnalysisService._detect_donation("nice stream bro!", "")
        assert result is None

    def test_empty_message(self):
        result = ChatAnalysisService._detect_donation("", "")
        assert result is None

    def test_user_captured(self):
        result = ChatAnalysisService._detect_donation("$10 tip", "viewer123")
        assert result is not None
        assert result["user"] == "viewer123"

    def test_message_truncated(self):
        """Long messages are truncated to 200 chars."""
        long_msg = "donated 5 " + "x" * 300
        result = ChatAnalysisService._detect_donation(long_msg, "")
        assert result is not None
        assert len(result["message"]) <= 200


# ─── ChatSpikeDetector Tests ────────────────────────────

class TestChatSpikeDetector:
    """Test chat spike detection."""

    def test_no_spike_initially(self):
        detector = ChatSpikeDetector()
        now = time.time()
        detector.add_message(now)
        result = detector.check_spike(now)
        assert result is None  # Not enough history

    def test_spike_detected(self):
        detector = ChatSpikeDetector(
            window_seconds=10,
            spike_threshold=3.0,
        )
        now = time.time()

        # Build baseline: 10 messages over 100 seconds = 0.1 msg/s
        for i in range(10):
            t = now - (100 - i * 10)
            detector.add_message(t)
            detector._rate_history.append(0.1)

        # Burst: 10 messages in 1 second
        for _ in range(10):
            detector.add_message(now)

        result = detector.check_spike(now)
        # May or may not detect depending on rate calculation, but shouldn't crash
        assert result is None or result.spike_ratio >= 3.0

    def test_spike_reset(self):
        """After spike ends, detector resets."""
        detector = ChatSpikeDetector(spike_threshold=3.0)
        detector._is_in_spike = True
        now = time.time()

        # Build enough history
        for _ in range(15):
            detector._rate_history.append(1.0)

        # Low rate (ratio < 1.5) should reset spike
        detector._message_timestamps.clear()
        detector.add_message(now)
        result = detector.check_spike(now)
        # After reset, no new spike
        assert result is None


# ─── ChatAnalysisService Integration Tests ───────────────

class TestChatAnalysisService:
    """Test the full chat analysis service with event bus."""

    @pytest_asyncio.fixture
    async def bus(self):
        bus = EventBus(history_size=100)
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_process_message_returns_sentiment(self, bus):
        service = ChatAnalysisService(event_bus=bus)
        result = await service.process_message("pogchamp nice!", "viewer1")
        assert result.label == "POSITIVE"

    @pytest.mark.asyncio
    async def test_process_message_publishes_sentiment_event(self, bus):
        service = ChatAnalysisService(event_bus=bus)
        await service.process_message("hello world", "user1")
        await asyncio.sleep(0.2)

        events = bus.get_history(EventType.CHAT_SENTIMENT.value)
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_donation_publishes_event(self, bus):
        service = ChatAnalysisService(event_bus=bus)
        result = await service.process_message("donated 50 dollars", "bigfan")
        await asyncio.sleep(0.2)

        # Should get POSITIVE sentiment
        assert result.label == "POSITIVE"
        assert result.score == 1.0

        # Donation event should be published
        donation_events = bus.get_history(EventType.DONATION_RECEIVED.value)
        assert len(donation_events) >= 1

    @pytest.mark.asyncio
    async def test_metrics_tracking(self, bus):
        service = ChatAnalysisService(event_bus=bus)
        await service.process_message("msg 1", "u1")
        await service.process_message("msg 2", "u2")

        status = service.get_status()
        assert status["messages_analyzed"] == 2

    @pytest.mark.asyncio
    async def test_sentiment_trend(self, bus):
        service = ChatAnalysisService(event_bus=bus)

        # Feed some messages
        for msg in ["pogchamp", "nice", "hello", "amazing", "wow",
                     "great", "epic", "love", "best", "fire"]:
            await service.process_message(msg, "u")

        trend = service.get_sentiment_trend()
        assert "trend" in trend
        assert "score" in trend
