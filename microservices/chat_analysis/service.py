"""
Chat Analysis Microservice v2 (AI-Powered)
───────────────────────────────────────────
Analyzes chat messages with NLP transformer models.

Upgrades from v1 keyword-based:
  - Transformer sentiment analysis (multilingual)
  - Toxicity/hate speech detection
  - Language detection (TR/EN/Mixed)
  - Hype moment detection
  - Trend/meme tracking
  - Spam/bot detection patterns

Flow: Chat Message → NLP Sentiment → Toxicity → Hype → Spike → Events
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from typing import Optional

import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, SentimentResult, ChatSpikeEvent,
)

logger = logging.getLogger("chat_analysis")

try:
    from services.chat_ai import (
        NLPSentimentAnalyzer,
        ToxicityDetector,
        LanguageDetector,
        HypeDetector,
        ChatTrendDetector,
    )
    _CHAT_AI_AVAILABLE = True
except ImportError as e:
    logger.warning("Chat AI module not available: %s", e)
    _CHAT_AI_AVAILABLE = False


class ChatSpikeDetector:
    """Detect sudden increases in chat message rate."""

    def __init__(self, window_seconds: int = 10, spike_threshold: float = 3.0):
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
    """Keyword-based sentiment fallback (Turkish + English gaming/streaming)."""

    POSITIVE_WORDS = {
        "pog", "pogchamp", "hype", "gg", "nice", "amazing", "wow",
        "lets go", "let's go", "insane", "epic", "love", "best",
        "fire", "goat", "w", "win", "victory", "clutch",
        "legendary", "god", "godlike", "based", "sigma",
        "helal", "bravo", "süper", "super", "harika", "mükemmel", "mukemmel",
        "efsane", "baba", "kral", "kanka", "müthis", "muhtesem",
        "asıl", "asil", "adam", "deli", "ateş", "ates", "müthis",
        "eyw", "eyvallah", "çok iyi", "cok iyi", "büyük", "buyuk",
        "güzel", "guzel", "mükemmel", "muhteşem", "harika",
        "yakışıklı", "aşk", "ask", "seviyorum",
        "eşşiz", "essiz", "inanılmaz", "inanilmaz",
        "aferin", "helal olsun", "adamsın", "kralısın",
    }
    NEGATIVE_WORDS = {
        "lul", "l", "lose", "fail", "bad", "cringe", "rip",
        "cope", "ratio", "mad", "angry", "rage", "toxic",
        "ez", "trash", "dog water", "washed",
        "kötü", "kotu", "berbat", "rezalet", "saçma", "sacma",
        "bok", "lanet", "siktir", "sikeyim", "amk",
        "bırak", "birak", "yeter", "sıkıcı", "sikici",
        "korkak", "ezik", "zayıf", "zayif", "boktan",
        "kötüsün", "kotusun", "rezaletsin", "yapma",
        "sinir", "kızgın", "kizgin", "moral bozuk",
    }
    HIGH_WEIGHT_WORDS = {
        "pogchamp": 2.0, "pog": 1.5, "clutch": 1.5,
        "efsane": 2.0, "helal": 1.5, "kral": 1.5,
        "amk": 2.0, "siktir": 2.0, "rezalet": 2.0,
        "godlike": 2.0, "insane": 1.5,
    }

    def analyze(self, text: str) -> SentimentResult:
        text_lower = text.lower()
        pos_score = sum(self.HIGH_WEIGHT_WORDS.get(w, 1.0) for w in self.POSITIVE_WORDS if w in text_lower)
        neg_score = sum(self.HIGH_WEIGHT_WORDS.get(w, 1.0) for w in self.NEGATIVE_WORDS if w in text_lower)
        total = pos_score + neg_score
        if total == 0:
            return SentimentResult(label="NEUTRAL", score=0.0, confidence=0.5)
        score = (pos_score - neg_score) / total
        if score > 0.1:
            return SentimentResult(label="POSITIVE", score=score, confidence=0.7)
        elif score < -0.1:
            return SentimentResult(label="NEGATIVE", score=score, confidence=0.7)
        return SentimentResult(label="NEUTRAL", score=score, confidence=0.5)


class ChatAnalysisService:
    """Main chat analysis service v2 - NLP-powered."""

    def __init__(self, event_bus: Optional[EventBus] = None):
        self.event_bus = event_bus or get_event_bus()
        self.spike_detector = ChatSpikeDetector()
        self.sentiment_fallback = SentimentAnalyzer()

        if _CHAT_AI_AVAILABLE:
            self.nlp_sentiment = NLPSentimentAnalyzer()
            self.toxicity_detector = ToxicityDetector()
            self.language_detector = LanguageDetector()
            self.hype_detector = HypeDetector()
            self.trend_detector = ChatTrendDetector()
        else:
            self.nlp_sentiment = None
            self.toxicity_detector = None
            self.language_detector = None
            self.hype_detector = None
            self.trend_detector = None

        self._sentiment_window: deque[float] = deque(maxlen=100)
        self._metrics = {
            "messages_analyzed": 0, "spikes_detected": 0,
            "avg_sentiment": 0.0, "toxic_detected": 0, "hype_moments": 0,
        }

    async def process_message(self, text: str, user: str = "") -> SentimentResult:
        now = time.time()

        donation = self._detect_donation(text, user)
        if donation:
            await self.event_bus.publish_quick(
                EventType.DONATION_RECEIVED, donation, source_service="chat-analysis")
            sentiment = SentimentResult(label="POSITIVE", score=1.0, confidence=0.95)
        else:
            if self.nlp_sentiment is not None:
                nlp = self.nlp_sentiment.analyze(text)
                sentiment = SentimentResult(
                    label=nlp["label"].upper(), score=nlp["score"],
                    confidence=nlp["confidence"])
            else:
                sentiment = self.sentiment_fallback.analyze(text)
        self._sentiment_window.append(sentiment.score)

        lang_info = None
        if self.language_detector is not None:
            lang_info = self.language_detector.detect(text)

        if self.toxicity_detector is not None:
            tox = self.toxicity_detector.detect(text, {
                "label": sentiment.label.lower(), "score": sentiment.score})
            if tox.get("toxic"):
                self._metrics["toxic_detected"] += 1
                await self.event_bus.publish_quick(
                    EventType.CHAT_TOXICITY,
                    {"user": user, "text": text[:200], "toxicity": tox},
                    source_service="chat-analysis")

        if self.hype_detector is not None:
            hype = self.hype_detector.analyze(text, {
                "label": sentiment.label.lower(), "score": sentiment.score}, now)
            if hype.get("is_hype_moment"):
                self._metrics["hype_moments"] += 1

        if self.trend_detector is not None:
            self.trend_detector.add_message(text)

        self.spike_detector.add_message(now)
        spike = self.spike_detector.check_spike(now)
        if spike:
            self._metrics["spikes_detected"] += 1
            await self.event_bus.publish_quick(
                EventType.CHAT_SPIKE, spike.model_dump(mode="json"),
                source_service="chat-analysis")

        await self.event_bus.publish_quick(
            EventType.CHAT_SENTIMENT,
            {"user": user, "text": text[:200],
             "sentiment": sentiment.model_dump(mode="json"),
             "language": lang_info},
            source_service="chat-analysis")

        self._metrics["messages_analyzed"] += 1
        self._metrics["avg_sentiment"] = (
            self._metrics["avg_sentiment"] * 0.95 + sentiment.score * 0.05)
        return sentiment

    @staticmethod
    def _detect_donation(text: str, user: str) -> Optional[dict]:
        text_lower = text.lower()
        amount_patterns = [
            r'\$(\d+(?:\.\d+)?)', r'(\d+(?:\.\d+)?)\s*(?:tl|try|₺)',
            r'(\d+(?:\.\d+)?)\s*(?:usd|eur|€)', r'donated\s+(\d+(?:\.\d+)?)',
            r'tip(?:ped)?\s+(\d+(?:\.\d+)?)', r'ba(?:ğ|g)ı(?:ş|s)\s+(\d+)',
        ]
        for pat in amount_patterns:
            m = re.search(pat, text_lower)
            if m:
                try:
                    amount = float(m.group(1))
                except (ValueError, IndexError):
                    continue
                return {
                    "user": user, "amount": amount,
                    "currency": "USD" if "$" in text else "TRY" if "tl" in text_lower or "₺" in text else "OTHER",
                    "message": text[:200]}
        donation_kw = {"donation", "tip", "bağış", "bagis", "support", "destek"}
        if any(kw in text_lower for kw in donation_kw):
            return {"user": user, "amount": 0.0, "currency": "UNKNOWN", "message": text[:200]}
        return None

    def get_sentiment_trend(self) -> dict:
        if len(self._sentiment_window) < 5:
            return {"trend": "insufficient_data", "score": 0.0}
        s = list(self._sentiment_window)
        avg = float(np.mean(s))
        recent_avg = float(np.mean(s[-20:]))
        older_avg = float(np.mean(s[-40:-20])) if len(s) >= 40 else float(np.mean(s[:20]))
        slope = recent_avg - older_avg
        trend = "improving" if slope > 0.05 else "declining" if slope < -0.05 else "stable"
        return {"trend": trend, "score": avg, "slope": slope, "count": len(s)}

    def get_status(self) -> dict:
        status = {**dict(self._metrics), "sentiment_trend": self.get_sentiment_trend()}
        if self.nlp_sentiment is not None:
            status["nlp_model"] = getattr(self.nlp_sentiment, 'model_name', 'loaded')
        if self.toxicity_detector is not None:
            status["toxicity"] = self.toxicity_detector.get_status()
        if self.hype_detector is not None:
            status["hype"] = self.hype_detector.get_status()
        if self.trend_detector is not None:
            status["trends"] = self.trend_detector.get_status()
        return status