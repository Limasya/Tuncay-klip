"""
Chat duygu analizi servisi.
Kick chat mesajlarını analiz ederek sentiment skoru üretir.
"""
import logging
from typing import Dict, Optional, List
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Basit Türkçe/İngilizce sentiment kelimeleri
POSITIVE_WORDS = {
    "gg", "nice", "lol", "lmao", "haha", "wow", "amazing", "insane",
    "pog", "poggers", "let's go", "lets go", "clutch", "epic", "god",
    "harika", "güzel", "mükemmel", "süper", "efsane", "helal",
    "bravo", "muhteşem", "wow", "adam", "kral", "abi",
}

NEGATIVE_WORDS = {
    "fail", "cringe", "bruh", "noob", "trash", "bad", "wtf",
    "kötü", "berbat", "rezalet", "saçma", "yazık", "boş",
    "cringe", "mid", "L", "ratio", "cope",
}


class ChatSentimentAnalyzer:
    """Chat mesajları için duygu analizi."""

    def __init__(self):
        self._nlp_pipeline = None

    def _load_model(self):
        """HuggingFace sentiment pipeline yükle."""
        try:
            from transformers import pipeline
            self._nlp_pipeline = pipeline(
                "sentiment-analysis",
                model="cardiffnlp/twitter-roberta-base-sentiment-latest",
                tokenizer="cardiffnlp/twitter-roberta-base-sentiment-latest",
                max_length=128,
                truncation=True,
            )
            logger.info("Chat sentiment modeli yüklendi.")
        except Exception as e:
            logger.warning("Sentiment modeli yüklenemedi, kural tabanlı analiz: %s", e)

    def analyze_message(self, message: str) -> Dict:
        """
        Tek bir chat mesajının duygu analizini yapar.

        Returns:
            {"score": float [-1, 1], "label": str, "confidence": float}
        """
        if self._nlp_pipeline is None:
            self._load_model()

        if self._nlp_pipeline:
            return self._analyze_ml(message)
        return self._analyze_rule_based(message)

    def _analyze_ml(self, message: str) -> Dict:
        """ML modeli ile sentiment analizi."""
        try:
            result = self._nlp_pipeline(message)[0]
            label = result["label"]  # positive, negative, neutral
            score = result["score"]

            # Normalize to [-1, 1]
            if label == "positive":
                normalized = score
            elif label == "negative":
                normalized = -score
            else:
                normalized = 0.0

            return {
                "score": normalized,
                "label": label,
                "confidence": score,
            }
        except Exception as e:
            logger.error("ML sentiment hatası: %s", e)
            return self._analyze_rule_based(message)

    def _analyze_rule_based(self, message: str) -> Dict:
        """Kural tabanlı basit sentiment analizi."""
        msg_lower = message.lower()
        words = set(msg_lower.split())

        pos_count = len(words & POSITIVE_WORDS)
        neg_count = len(words & NEGATIVE_WORDS)
        total = pos_count + neg_count

        if total == 0:
            return {"score": 0.0, "label": "neutral", "confidence": 0.5}

        score = (pos_count - neg_count) / total
        label = "positive" if score > 0 else "negative" if score < 0 else "neutral"

        return {
            "score": score,
            "label": label,
            "confidence": min(total / 3.0, 1.0),
        }

    def analyze_batch(self, messages: List[str]) -> Dict:
        """Toplu mesaj analizi - ortalama sentiment."""
        if not messages:
            return {"avg_score": 0.0, "label": "neutral", "message_count": 0}

        results = [self.analyze_message(msg) for msg in messages]
        avg_score = sum(r["score"] for r in results) / len(results)

        label = "positive" if avg_score > 0.1 else "negative" if avg_score < -0.1 else "neutral"

        return {
            "avg_score": avg_score,
            "label": label,
            "message_count": len(messages),
            "details": results,
        }


# Singleton
chat_sentiment = ChatSentimentAnalyzer()
