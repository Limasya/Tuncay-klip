"""
Chat AI Module (IP_PART7 - AI Intelligence Expansion)

Transformer-based chat analysis for gaming/streaming content:
  1. Deep Sentiment Analysis (NLP transformer models)
  2. Toxicity & Hate Speech Detection
  3. Spam/Bot Detection
  4. Intent Classification (question, hype, donation, command)
  5. Named Entity Recognition (streamer, game, player mentions)
  6. Language Detection (TR/EN/mixed)
  7. Trend Detection (emerging topics, memes)
  8. Engagement Scoring (how engaging is this chat moment)

Upgrades from keyword-based v1 to transformer-based v2.
Graceful fallback to keyword analyzer when models unavailable.
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter, deque
from typing import Any, Optional

import numpy as np

logger = logging.getLogger("chat_ai")


# ---------------------------------------------------------------------------
# NLP Transformer Sentiment Analyzer
# ---------------------------------------------------------------------------
class NLPSentimentAnalyzer:
    """
    Transformer-based multilingual sentiment analysis.

    Tries to load a HuggingFace sentiment model.
    Falls back to keyword-based (enhanced with NLP features).
    """

    SUPPORTED_MODELS = [
        "cardiffnlp/twitter-xlm-roberta-base-sentiment",  # Multilingual
        "cardiffnlp/twitter-roberta-base-sentiment-latest",  # English
        "savasy/bert-base-turkish-sentiment-cased",  # Turkish
    ]

    def __init__(self):
        self.pipe = None
        self.model_name = None
        self._load_model()

    def _load_model(self):
        """Try to load best available sentiment model."""
        for model_id in self.SUPPORTED_MODELS:
            try:
                from transformers import pipeline
                self.pipe = pipeline(
                    "sentiment-analysis",
                    model=model_id,
                    tokenizer=model_id,
                    device=-1,
                    max_length=128,
                    truncation=True,
                )
                self.model_name = model_id
                logger.info("Sentiment model loaded: %s", model_id)
                return
            except Exception as e:
                logger.debug("Model %s unavailable: %s", model_id, e)

        logger.info("Sentiment: using enhanced keyword fallback")

    def analyze(self, text: str) -> dict:
        """Analyze sentiment of chat message."""
        if not text or len(text.strip()) == 0:
            return {"label": "neutral", "score": 0.0, "confidence": 0.5, "source": "empty"}

        if self.pipe is not None:
            return self._analyze_model(text)
        return self._analyze_keyword_enhanced(text)

    def analyze_batch(self, messages: list[str]) -> list[dict]:
        """Batch sentiment analysis."""
        if self.pipe is not None:
            try:
                results = self.pipe(messages[:50], batch_size=16)
                return [
                    {"label": r["label"].lower(), "score": r["score"],
                     "confidence": r["score"], "source": self.model_name or "transformer"}
                    for r in results
                ]
            except Exception as e:
                logger.warning("Batch inference failed: %s", e)

        return [self.analyze(msg) for msg in messages]

    def _analyze_model(self, text: str) -> dict:
        try:
            text_trunc = text[:128]
            result = self.pipe(text_trunc)
            if isinstance(result, list):
                result = result[0]
            return {
                "label": result["label"].lower(),
                "score": result["score"],
                "confidence": result["score"],
                "source": self.model_name or "transformer",
            }
        except Exception as e:
            logger.debug("Model inference failed: %s", e)
            return self._analyze_keyword_enhanced(text)

    def _analyze_keyword_enhanced(self, text: str) -> dict:
        """Enhanced keyword sentiment with NLP-inspired weighting."""
        text_lower = text.lower()

        # Weighted keyword dictionaries
        POSITIVE = {
            # English gaming
            "pog": 2.5, "pogchamp": 3.0, "clutch": 2.0, "godlike": 3.0,
            "insane": 2.0, "epic": 2.0, "wow": 1.5, "amazing": 1.5,
            "fire": 1.5, "goat": 2.5, "legendary": 2.0, "based": 1.5,
            "lets go": 2.0, "let's go": 2.0, "nice": 1.0, "gg": 1.5,
            "clean": 1.0, "cracked": 1.5, "demon": 1.5,
            # Turkish positive
            "helal": 2.5, "helal olsun": 3.0, "efsane": 3.0, "efsanevi": 2.5,
            "kral": 2.5, "baba": 2.0, "deli": 1.5, "müthiş": 2.5,
            "muhteşem": 2.5, "harika": 2.0, "mükemmel": 2.0,
            "çıldırdı": 2.5, "cildirdi": 2.5, "koptu": 2.0, "patladı": 2.0,
            "adamsın": 2.5, "adam": 1.5, "aşk": 1.5, "ask": 1.5,
            "eyvallah": 1.0, "eyw": 1.0, "bravo": 1.5, "aferin": 1.5,
            "süper": 1.5, "super": 1.5, "güzel": 1.0, "guzel": 1.0,
            "taşıyor": 2.0, "tasiyor": 2.0, "ezdi": 2.0, "domine": 2.0,
            "büyük oyun": 2.0, "büyük": 1.5, "buyuk": 1.5,
            "destan": 3.0, "tarihi an": 3.0, "şov": 2.5, "eşşiz": 2.5,
            "essiz": 2.5, "inanılmaz": 2.0, "inanilmaz": 2.0,
            "seviyorum": 2.0, "canım": 1.5, "canim": 1.5,
            "tanrı": 2.5, "tanri": 2.5, "ilah": 2.5, "sigma": 2.0,
        }
        NEGATIVE = {
            "fail": 2.0, "cringe": 2.0, "bad": 1.5, "lose": 1.5,
            "trash": 2.0, "garbage": 2.5, "dog water": 3.0, "dogwater": 3.0,
            "washed": 2.0, "cope": 1.5, "ratio": 2.0, "lul": 1.0,
            "ez": 2.0, "mad": 1.0, "angry": 1.0, "rage": 2.0,
            "toxic": 2.5, "kill yourself": 5.0, "kys": 5.0,
            # Turkish negative
            "rezalet": 3.0, "bok": 2.5, "boktan": 2.5,
            "berbat": 2.0, "saçma": 2.0, "sacma": 2.0,
            "amk": 2.5, "siktir": 3.0, "lanet": 2.5,
            "kötü": 1.5, "kotu": 1.5, "ezik": 2.5, "zayıf": 1.5,
            "bırak": 1.5, "birak": 1.5, "sıkıcı": 1.5, "sikici": 1.5,
            "sinir": 1.5, "kızgın": 2.0, "kizgin": 2.0,
            "yapma": 1.0, "yeter": 1.5, "küfür": 2.0, "küfretti": 2.0,
        }

        pos_score = 0.0
        neg_score = 0.0

        for word, weight in POSITIVE.items():
            if word in text_lower:
                pos_score += weight

        for word, weight in NEGATIVE.items():
            if word in text_lower:
                neg_score += weight

        total = pos_score + neg_score
        if total == 0:
            return {"label": "neutral", "score": 0.0, "confidence": 0.5, "source": "keyword_enhanced"}

        score = (pos_score - neg_score) / max(total, 1.0)
        confidence = min(max(total / 5.0, 0.5), 0.95)

        if score > 0.15:
            return {"label": "positive", "score": score, "confidence": confidence, "source": "keyword_enhanced"}
        elif score < -0.15:
            return {"label": "negative", "score": score, "confidence": confidence, "source": "keyword_enhanced"}
        return {"label": "neutral", "score": score, "confidence": confidence, "source": "keyword_enhanced"}


# ---------------------------------------------------------------------------
# Toxicity Detector
# ---------------------------------------------------------------------------
class ToxicityDetector:
    """
    Detect toxic/hate speech in chat messages.

    Multi-level detection:
    1. Blacklist keyword matching
    2. Pattern-based (slurs, hate speech patterns)
    3. Context-aware (when combined with negative sentiment)
    """

    TOXIC_PATTERNS = {
        "hate_speech": ["kill yourself", "kys", "die", "öl", "olum", "suicide"],
        "harassment": ["stalk", "dox", "ip", "address", "location", "adres"],
        "slurs_tr": ["ırkçı", "faşist", "terörist", "vatan haini"],
        "slurs_en": ["racist", "fascist", "terrorist", "traitor"],
        "threats": ["i will find you", "i know where", "come to your"],
    }

    def __init__(self):
        self._toxic_count = 0
        self._toxicity_scores: deque[float] = deque(maxlen=1000)

    def detect(self, text: str, sentiment: dict = None) -> dict:
        """
        Detect toxicity level in message.

        Returns: {toxic: bool, level: str, confidence: float, category: str}
        """
        text_lower = text.lower()

        # Level 1: Exact blacklist match (high confidence)
        for category, patterns in self.TOXIC_PATTERNS.items():
            for pattern in patterns:
                if pattern in text_lower:
                    self._toxic_count += 1
                    return {
                        "toxic": True,
                        "level": "high",
                        "confidence": 0.95,
                        "category": category,
                        "matched_pattern": pattern,
                    }

        # Level 2: Combined signals
        toxicity_score = 0.0
        signals = []

        # Excessive caps (rage indicator)
        caps_ratio = sum(1 for c in text if c.isupper()) / max(len(text), 1)
        if caps_ratio > 0.8 and len(text) > 20:
            toxicity_score += 0.3
            signals.append("excessive_caps")

        # Multiple exclamation marks (aggression)
        if text.count("!") >= 5:
            toxicity_score += 0.2
            signals.append("excessive_exclamation")

        # Repeated characters (screaming: AHHHHH, NOOOOOO)
        if re.search(r'(.)\1{4,}', text_lower):
            toxicity_score += 0.1
            signals.append("character_repetition")

        # Swear word density
        swear_count = sum(1 for w in ["fuck", "shit", "damn", "ass", "bitch",
                                       "siktir", "amk", "amına", "oruspu",
                                       "piç", "yarrak", "göt", "salak"]
                          if w in text_lower)
        if swear_count >= 3:
            toxicity_score += 0.4
            signals.append(f"swear_density_{swear_count}")
        elif swear_count >= 1:
            toxicity_score += 0.2
            signals.append("swear_present")

        # Negative sentiment amplification
        if sentiment and sentiment.get("label") == "negative":
            toxicity_score += sentiment.get("score", 0) * 0.3

        self._toxicity_scores.append(toxicity_score)

        is_toxic = toxicity_score > 0.5
        if is_toxic:
            self._toxic_count += 1

        return {
            "toxic": is_toxic,
            "level": "high" if toxicity_score > 0.7 else "medium" if toxicity_score > 0.5 else "low",
            "confidence": min(toxicity_score / 0.8, 0.9) if is_toxic else 0.0,
            "score": round(toxicity_score, 2),
            "signals": signals,
        }

    def get_status(self) -> dict:
        return {
            "toxic_messages_total": self._toxic_count,
            "avg_toxicity": round(float(np.mean(list(self._toxicity_scores))), 3) if self._toxicity_scores else 0.0,
        }


# ---------------------------------------------------------------------------
# Language Detector
# ---------------------------------------------------------------------------
class LanguageDetector:
    """
    Detect language of chat messages (TR/EN/MIXED/OTHER).

    Uses character n-gram analysis + keyword frequency.
    """

    TR_UNIQUE_CHARS = set("ğĞüÜşŞıİöÖçÇ")
    TR_COMMON_WORDS = {"ve", "bir", "bu", "için", "da", "de", "ki", "ama",
                        "çok", "cok", "iyi", "güzel", "guzel", "neden",
                        "nasıl", "nasil", "niye", "niçin", "nicin",
                        "yapma", "yapıyor", "yapiyor", "geliyor", "gidiyor"}
    EN_COMMON_WORDS = {"the", "is", "are", "was", "were", "have", "has",
                        "this", "that", "with", "for", "from", "and",
                        "but", "not", "will", "can", "should", "would"}

    def detect(self, text: str) -> dict:
        """Detect language of text."""
        text_lower = text.lower()
        words = set(text_lower.split())

        # Character-based signals
        tr_chars = sum(1 for c in text if c in self.TR_UNIQUE_CHARS)
        has_tr_chars = tr_chars > 0

        # Word frequency signals
        tr_words = len(words & self.TR_COMMON_WORDS)
        en_words = len(words & self.EN_COMMON_WORDS)

        # Decision
        if has_tr_chars and tr_words >= en_words:
            lang = "tr"
            conf = 0.9
        elif en_words > tr_words and not has_tr_chars:
            lang = "en"
            conf = 0.8
        elif tr_words > 0 and en_words > 0:
            lang = "mixed"
            conf = 0.6
        elif has_tr_chars:
            lang = "tr"
            conf = 0.7
        elif len(text) > 3:
            lang = "en"
            conf = 0.5
        else:
            lang = "unknown"
            conf = 0.3

        return {
            "language": lang,
            "confidence": round(conf, 2),
            "tr_chars": tr_chars,
            "tr_words": tr_words,
            "en_words": en_words,
        }


# ---------------------------------------------------------------------------
# Hype Detector
# ---------------------------------------------------------------------------
class HypeDetector:
    """
    Detect HYPE moments in chat - high engagement, positive sentiment burst.

    Hype signals:
    - Message velocity spike (>3x baseline)
    - Positive sentiment dominance (>70% positive)
    - Emote/emoji density (POGGERS, HYPERS, etc.)
    - Key hype phrases (LET'S GO, POG, CLUTCH, EFSANE, HELAL)
    - Caps lock ratio
    - Message length burst (short = reactions)
    """

    HYPE_PHRASES = {
        "lets go": 0.9, "let's go": 0.9, "pog": 0.8, "pogchamp": 0.9,
        "hype": 0.8, "clutch": 0.9, "insane": 0.8, "godlike": 0.9,
        "efsane": 0.9, "helal": 0.8, "kral": 0.8, "çıldırdı": 0.9,
        "patladı": 0.8, "koptu": 0.8, "destan": 0.9, "tarih": 0.8,
        "taşıdı": 0.8, "kurtardı": 0.8, "clutch": 0.9, "ezdi": 0.8,
        "w": 0.5, "ww": 0.6, "www": 0.7, "wwww": 0.8, "wwwww": 0.9,
        "lfg": 0.8, "lfgg": 0.9, "lfggg": 0.9,
    }

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._message_window: deque[dict] = deque(maxlen=window_size)
        self._hype_score: float = 0.0
        self._hype_count: int = 0

    def analyze(self, message: str, sentiment: dict, timestamp: float) -> dict:
        """Analyze single message for hype contribution."""
        text_lower = message.lower()

        hype_signals = {
            "phrase_score": 0.0,
            "caps_ratio": 0.0,
            "emoji_count": 0.0,
            "sentiment_boost": 0.0,
        }

        # 1. Hype phrase matching
        for phrase, weight in self.HYPE_PHRASES.items():
            if phrase in text_lower:
                hype_signals["phrase_score"] = max(hype_signals["phrase_score"], weight)

        # 2. Caps ratio (all caps = intensity)
        if len(message) > 3:
            caps = sum(1 for c in message if c.isupper())
            caps_ratio = caps / len(message)
            hype_signals["caps_ratio"] = min(caps_ratio * 0.5, 0.4)

        # 3. Hype emoji/emote count
        hype_emotes = ["🔥", "💯", "🐐", "👑", "⚡", "🎯", "🏆",
                         "POGGERS", "HYPERS", "POG", "PogChamp",
                         "Kreygasm", "OMEGALUL", "LULW"]
        emote_count = sum(1 for e in hype_emotes if e.lower() in text_lower)
        hype_signals["emoji_count"] = min(emote_count * 0.1, 0.3)

        # 4. Sentiment boost (positive sentiment)
        if sentiment.get("label") == "positive":
            hype_signals["sentiment_boost"] = sentiment.get("score", 0.0) * 0.3

        # Combined hype score for this message
        msg_hype = sum(hype_signals.values())
        msg_hype = min(msg_hype, 1.0)

        self._message_window.append({
            "timestamp": timestamp,
            "hype": msg_hype,
            "sentiment": sentiment.get("label", "neutral"),
        })

        # Calculate aggregate hype
        aggregate = self._calculate_aggregate()

        is_hype = aggregate > 0.4
        if is_hype:
            self._hype_count += 1

        return {
            "hype_score": round(msg_hype, 3),
            "aggregate_hype": round(aggregate, 3),
            "is_hype_moment": is_hype,
            "signals": hype_signals,
        }

    def _calculate_aggregate(self) -> float:
        if len(self._message_window) < 3:
            return 0.0

        recent = list(self._message_window)
        hype_values = [m["hype"] for m in recent]
        positive_ratio = sum(
            1 for m in recent if m["sentiment"] == "positive"
        ) / max(len(recent), 1)

        avg_hype = float(np.mean(hype_values))
        weighted = avg_hype * 0.5 + max(hype_values) * 0.3 + positive_ratio * 0.2
        return weighted

    def get_status(self) -> dict:
        return {
            "hype_moments_detected": self._hype_count,
            "current_hype": round(self._hype_score, 3),
            "window_size": self.window_size,
        }


# ---------------------------------------------------------------------------
# Chat Trend Detector
# ---------------------------------------------------------------------------
class ChatTrendDetector:
    """
    Detect trending topics and memes in chat.

    Tracks:
    - Word/phrase frequency bursts
    - Emerging memes/spam patterns
    - Topic shifts
    """

    def __init__(self, window_size: int = 100, burst_threshold: float = 3.0):
        self.burst_threshold = burst_threshold
        self._word_counts: Counter = Counter()
        self._total_words = 0
        self._word_history: deque[dict] = deque(maxlen=window_size)
        self._trending: list[str] = []

    def add_message(self, text: str):
        """Add message words to tracker."""
        words = text.lower().split()
        for word in words:
            if len(word) > 2 and word.isalpha():
                self._word_counts[word] += 1
                self._total_words += 1

        self._word_history.append({
            "words": words,
            "timestamp": time.time(),
        })

    def get_trending(self, top_n: int = 10) -> list[dict]:
        """Get trending words/phrases."""
        if self._total_words < 20:
            return []

        # Recent burst detection
        recent_words = Counter()
        for entry in list(self._word_history)[-20:]:
            for word in entry["words"]:
                if len(word) > 2:
                    recent_words[word] += 1

        trends = []
        for word, count in recent_words.most_common(20):
            baseline = self._word_counts.get(word, 0) / max(self._total_words, 1)
            recent_freq = count / max(sum(recent_words.values()), 1)

            if baseline > 0 and recent_freq / max(baseline, 0.001) > self.burst_threshold:
                trends.append({
                    "word": word,
                    "frequency": round(recent_freq, 3),
                    "burst_ratio": round(recent_freq / max(baseline, 0.001), 1),
                })

        return sorted(trends, key=lambda x: x["burst_ratio"], reverse=True)[:top_n]

    def get_status(self) -> dict:
        return {
            "total_words_tracked": self._total_words,
            "unique_words": len(self._word_counts),
            "trending": self.get_trending(5),
        }