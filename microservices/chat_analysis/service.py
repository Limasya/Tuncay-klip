"""
Chat Analysis Microservice
────────────────────────────
Analyzes chat messages: sentiment, spike detection, toxicity.

Flow: Chat Message → Sentiment → Spike Check → Events
"""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Optional

import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, SentimentResult, ChatSpikeEvent,
)

logger = logging.getLogger("chat_analysis")


class ChatSpikeDetector:
    """
    Detect sudden increases in chat message rate.
    Chat spike + positive sentiment = HYPE moment.
    """

    def __init__(
        self,
        window_seconds: int = 10,
        spike_threshold: float = 3.0,
    ):
        self.window_seconds = window_seconds
        self.spike_threshold = spike_threshold
        self._message_timestamps: deque[float] = deque(maxlen=1000)
        self._rate_history: deque[float] = deque(maxlen=60)
        self._is_in_spike = False

    def add_message(self, timestamp: float):
        self._message_timestamps.append(timestamp)

    def check_spike(self, current_time: float) -> Optional[ChatSpikeEvent]:
        cutoff = current_time - self.window_seconds
        while self._message_timestamps and self._message_timestamps[0] < cutoff:
            self._message_timestamps.popleft()

        current_rate = len(self._message_timestamps) / self.window_seconds
        self._rate_history.append(current_rate)

        if len(self._rate_history) < 10:
            return None

        baseline_rate = float(np.median(list(self._rate_history)))
        if baseline_rate < 0.1:
            return None

        ratio = current_rate / max(baseline_rate, 0.1)

        if ratio >= self.spike_threshold and not self._is_in_spike:
            self._is_in_spike = True
            return ChatSpikeEvent(
                timestamp=current_time,
                messages_per_second=current_rate,
                baseline_rate=baseline_rate,
                spike_ratio=ratio,
            )
        elif ratio < self.spike_threshold * 0.5:
            self._is_in_spike = False

        return None


class SentimentAnalyzer:
    """Simple keyword-based sentiment (replace with model in production)."""

    POSITIVE_WORDS = {
        "pog", "pogchamp", "hype", "gg", "nice", "amazing", "wow",
        "lets go", "let's go", "insane", "epic", "love", "best",
        "fire", "goat", "w", "win", "victory", "clutch",
    }
    NEGATIVE_WORDS = {
        "lul", "l", "lose", "fail", "bad", "cringe", "rip",
        "cope", "ratio", "mad", "angry", "rage", "toxic",
    }

    def analyze(self, text: str) -> SentimentResult:
        text_lower = text.lower()

        pos_count = sum(1 for w in self.POSITIVE_WORDS if w in text_lower)
        neg_count = sum(1 for w in self.NEGATIVE_WORDS if w in text_lower)

        total = pos_count + neg_count
        if total == 0:
            return SentimentResult(label="NEUTRAL", score=0.0, confidence=0.5)

        score = (pos_count - neg_count) / total
        if score > 0.1:
            return SentimentResult(label="POSITIVE", score=score, confidence=0.7)
        elif score < -0.1:
            return SentimentResult(label="NEGATIVE", score=score, confidence=0.7)
        return SentimentResult(label="NEUTRAL", score=score, confidence=0.5)


class ChatAnalysisService:
    """Main chat analysis service."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or get_event_bus()
        self.spike_detector = ChatSpikeDetector()
        self.sentiment_analyzer = SentimentAnalyzer()

        self._sentiment_window: deque[float] = deque(maxlen=100)
        self._metrics = {
            "messages_analyzed": 0,
            "spikes_detected": 0,
            "avg_sentiment": 0.0,
        }

    async def process_message(self, text: str, user: str = "") -> SentimentResult:
        now = time.time()

        # Sentiment analysis
        sentiment = self.sentiment_analyzer.analyze(text)
        self._sentiment_window.append(sentiment.score)

        # Chat spike detection
        self.spike_detector.add_message(now)
        spike = self.spike_detector.check_spike(now)

        if spike:
            self._metrics["spikes_detected"] += 1
            await self.event_bus.publish_quick(
                EventType.CHAT_SPIKE,
                spike.model_dump(mode="json"),
                source_service="chat-analysis",
            )

        # Publish sentiment
        await self.event_bus.publish_quick(
            EventType.CHAT_SENTIMENT,
            {
                "user": user,
                "text": text[:200],
                "sentiment": sentiment.model_dump(mode="json"),
            },
            source_service="chat-analysis",
        )

        self._metrics["messages_analyzed"] += 1
        self._metrics["avg_sentiment"] = (
            self._metrics["avg_sentiment"] * 0.95 + sentiment.score * 0.05
        )

        return sentiment

    def get_sentiment_trend(self) -> dict:
        if len(self._sentiment_window) < 5:
            return {"trend": "insufficient_data", "score": 0.0}

        sentiments = list(self._sentiment_window)
        avg = float(np.mean(sentiments))
        recent = sentiments[-20:]
        older = sentiments[-40:-20] if len(sentiments) >= 40 else sentiments[:20]

        recent_avg = float(np.mean(recent))
        older_avg = float(np.mean(older))
        slope = recent_avg - older_avg

        if slope > 0.05:
            trend = "improving"
        elif slope < -0.05:
            trend = "declining"
        else:
            trend = "stable"

        return {"trend": trend, "score": avg, "slope": slope, "count": len(sentiments)}

    def get_status(self) -> dict:
        return {**dict(self._metrics), "sentiment_trend": self.get_sentiment_trend()}
