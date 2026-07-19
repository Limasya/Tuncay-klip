"""
Signal Fusion — Sinyal Füzyon Ablation ve Ağırlık Optimizasyonu
─────────────────────────────────────────────────────────────────
FAZ-2.1: Çoklu sinyal füzyonu için ablation analizi ve otomatik ağırlık optimizasyonu.

Features:
  - Ablation studies: Her sinyali tek tek kapatarak etki analizi
  - Weight optimization: Bayesian-style greedy weight tuning
  - Spam/emoji detection: Chat sinyallerinden gürültü temizleme
  - Signal correlation matrix: Sinyaller arası korelasyon analizi
  - Adaptive weights: Zamana göre ağırlık otomatik ayarlama
"""
from __future__ import annotations

import logging
import math
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field
from shared.utils.json_state import JsonStateStore

logger = logging.getLogger("signal_fusion")


# ── Data Models ──

class AblationResult(BaseModel):
    """Tek bir sinyalin ablation sonucu."""
    signal_name: str
    score_without: float = 0.0
    score_with: float = 0.0
    impact: float = 0.0  # score_with - score_without
    impact_pct: float = 0.0
    correlation_with_others: Dict[str, float] = Field(default_factory=dict)


class WeightUpdate(BaseModel):
    """Ağırlık güncelleme kaydı."""
    signal_name: str
    old_weight: float
    new_weight: float
    reason: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SpamDetectionResult(BaseModel):
    """Chat mesajı spam/emoji analiz sonucu."""
    message: str
    is_spam: bool = False
    is_emoji_only: bool = False
    spam_type: str = ""  # "repetition", "link", "caps_flood", "emoji_only", "bot"
    confidence: float = 0.0
    cleaned_message: str = ""


class SignalCorrelation(BaseModel):
    """İki sinyal arasındaki korelasyon."""
    signal_a: str
    signal_b: str
    correlation: float = 0.0
    co_activation_rate: float = 0.0  # İkisi birden ne sıklıkla aktif?
    sample_size: int = 0


# ── Spam & Emoji Detection ──

# Spam patternleri
_SPAM_PATTERNS = [
    re.compile(r'(https?://\S+)', re.IGNORECASE),  # URL'ler
    re.compile(r'(.)\1{5,}'),  # 6+ tekrarlayan karakter
    re.compile(r'^[A-Z\s!?.]{10,}$'),  # ALL CAPS flood
    re.compile(r'(sub|follow|raid|donate|giveaway)\s*(me|now|please)', re.IGNORECASE),
]

_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE,
)

_BOT_KEYWORDS = {"bot", "nightbot", "streamElements", "moobot", "command"}


class SpamDetector:
    """Chat mesajlarını spam/emoji için analiz et."""

    def __init__(self, spam_threshold: float = 0.35):
        self.spam_threshold = spam_threshold
        self._user_msg_counts: Dict[str, deque] = defaultdict(lambda: deque(maxlen=30))
        self._known_bots: set = {"nightbot", "streamelements", "moobot"}

    def detect(self, message: str, username: str = "") -> SpamDetectionResult:
        msg_lower = message.lower().strip()
        result = SpamDetectionResult(message=message, cleaned_message=message)

        # Bot kontrolü
        if username.lower() in self._known_bots:
            result.is_spam = True
            result.spam_type = "bot"
            result.confidence = 1.0
            return result

        # Emoji-only kontrolü
        stripped = re.sub(r'\s+', '', message)
        emoji_chars = _EMOJI_PATTERN.findall(stripped)
        non_emoji = _EMOJI_PATTERN.sub('', stripped)
        if stripped and len(non_emoji) < 3 and len(emoji_chars) > 0:
            result.is_emoji_only = True
            result.is_spam = True
            result.spam_type = "emoji_only"
            result.confidence = 0.9
            return result

        # Pattern-based spam
        spam_score = 0.0
        for pattern in _SPAM_PATTERNS:
            if pattern.search(message):
                spam_score += 0.35
                if "http" in message.lower():
                    result.spam_type = "link"
                elif pattern.pattern.startswith('(.)'):
                    result.spam_type = "repetition"
                elif "CAPS" in pattern.pattern or pattern.pattern.startswith('^['):
                    result.spam_type = "caps_flood"
                else:
                    result.spam_type = "generic"

        # Repetition kontrolü (aynı kullanıcı hızlıca çok mesaj atarsa)
        if username:
            user_msgs = self._user_msg_counts[username]
            now = time.time()
            # Son 5 saniyede 5+ mesaj
            recent = sum(1 for t in user_msgs if now - t < 5.0)
            if recent >= 5:
                spam_score += 0.3
                if not result.spam_type:
                    result.spam_type = "repetition"
            user_msgs.append(now)

        # Temizlenmiş mesaj
        result.confidence = min(1.0, spam_score)
        result.is_spam = spam_score >= self.spam_threshold

        if not result.is_spam:
            # Mesajı temizle: link'leri kaldır, gereksiz tekrarları azalt
            cleaned = re.sub(r'https?://\S+', '[link]', message)
            cleaned = re.sub(r'(.)\1{3,}', r'\1\1\1', cleaned)
            result.cleaned_message = cleaned.strip()

        return result

    def filter_messages(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Mesaj listesinden spam'leri filtrele."""
        filtered = []
        for msg in messages:
            text = msg.get("message", msg.get("text", ""))
            username = msg.get("username", msg.get("user", ""))
            result = self.detect(text, username)
            if not result.is_spam:
                msg["cleaned_message"] = result.cleaned_message
                filtered.append(msg)
        return filtered


# ── Ablation Engine ──

class AblationEngine:
    """
    Sinyal ablation analizi: Her sinyali kapatarak toplam skora etkisini ölçer.
    Amaç: Hangi sinyaller gerçekten faydalı, hangileri gürültü?
    """

    def __init__(self, scoring_engine):
        self.scoring_engine = scoring_engine
        self._ablation_history: List[AblationResult] = []

    async def run_ablation(
        self, signal_data: Optional[Dict[str, List[Tuple[float, float]]]] = None
    ) -> List[AblationResult]:
        """
        Her sinyali tek tek kapatarak ablation çalıştır.
        signal_data: {signal_name: [(timestamp, value), ...]} — yoksa mevcut history'yi kullanır.
        """
        weights = self.scoring_engine.WEIGHTS
        signals = list(weights.keys())

        # Tüm sinyaller aktifken skor
        baseline_score = self.scoring_engine.compute_score().composite_score

        results = []
        for signal in signals:
            # Bu sinyali geçici olarak devre dışı bırak
            original_weight = weights[signal]
            weights[signal] = 0.0

            # Yeni toplamı normalize et
            total = sum(weights.values())
            if total > 0:
                normalized = {k: v / total for k, v in weights.items()}
                self.scoring_engine.WEIGHTS = normalized

            # Skor hesapla
            disabled_score = self.scoring_engine.compute_score().composite_score

            # Geri yükle
            weights[signal] = original_weight
            total = sum(weights.values())
            if total > 0:
                self.scoring_engine.WEIGHTS = {k: v / total for k, v in weights.items()}

            impact = baseline_score - disabled_score
            impact_pct = (impact / max(baseline_score, 0.001)) * 100

            result = AblationResult(
                signal_name=signal,
                score_without=round(disabled_score, 4),
                score_with=round(baseline_score, 4),
                impact=round(impact, 4),
                impact_pct=round(impact_pct, 2),
            )
            results.append(result)

        self._ablation_history.extend(results)
        return results

    def get_recommendations(self, results: List[AblationResult]) -> List[str]:
        """Ablation sonuçlarına göre ağırlık önerileri."""
        recs = []
        for r in sorted(results, key=lambda x: abs(x.impact), reverse=True):
            if abs(r.impact_pct) < 2.0:
                recs.append(
                    f"{r.signal_name}: Düşük etki ({r.impact_pct:+.1f}%) — ağırlık azaltılabilir."
                )
            elif r.impact_pct > 10.0:
                recs.append(
                    f"{r.signal_name}: Yüksek etki ({r.impact_pct:+.1f}%) — ağırlık artırılmalı."
                )
            elif r.impact_pct < -5.0:
                recs.append(
                    f"{r.signal_name}: Negatif etki ({r.impact_pct:+.1f}%) — sorunlu sinyal, incelenmeli."
                )
        return recs

    def get_history(self) -> List[Dict[str, Any]]:
        return [r.model_dump() for r in self._ablation_history[-100:]]


# ── Weight Optimizer ──

class WeightOptimizer:
    """
    Greedy weight optimizasyonu: Her sinyalin ağırlığını bir miktar artır/azalt,
    toplam skorun iyileşip iyileşmediğini test et.
    """

    def __init__(self, scoring_engine, ablation_engine: AblationEngine):
        self.scoring_engine = scoring_engine
        self.ablation_engine = ablation_engine
        self._update_history: List[WeightUpdate] = []
        self._optimization_score: float = 0.0

    async def optimize_step(
        self, ground_truth_scores: List[float], step_size: float = 0.02
    ) -> List[WeightUpdate]:
        """
        Tek bir optimizasyon adımı: Her sinyal için +step_size test et.
        ground_truth_scores: Doğrulanmış skorlar (insan değerlendirmesi veya platform metrikleri).
        """
        if not ground_truth_scores:
            return []

        updates = []
        weights = dict(self.scoring_engine.WEIGHTS)

        for signal in list(weights.keys()):
            # Orijinal ağırlıkla skor
            original_score = self.scoring_engine.compute_score().composite_score

            # Ağırlığı artır
            weights[signal] += step_size
            total = sum(weights.values())
            normalized = {k: v / total for k, v in weights.items()}
            self.scoring_engine.WEIGHTS = normalized

            new_score = self.scoring_engine.compute_score().composite_score

            # İyileşme var mı? (ground truth ile korelasyon)
            if ground_truth_scores:
                gt_avg = sum(ground_truth_scores) / len(ground_truth_scores)
                old_corr = abs(original_score - gt_avg)
                new_corr = abs(new_score - gt_avg)

                if new_corr < old_corr:
                    # İyileşme var — ağırlığı koru
                    update = WeightUpdate(
                        signal_name=signal,
                        old_weight=round(weights[signal] - step_size, 4),
                        new_weight=round(weights[signal], 4),
                        reason=f"Score improved: {old_corr:.3f} → {new_corr:.3f}",
                    )
                    updates.append(update)
                else:
                    # İyileşme yok — geri al
                    weights[signal] -= step_size
            else:
                weights[signal] -= step_size

        # Normalize et ve uygula
        total = sum(weights.values())
        if total > 0:
            self.scoring_engine.WEIGHTS = {k: v / total for k, v in weights.items()}

        self._update_history.extend(updates)
        return updates

    def get_update_history(self) -> List[Dict[str, Any]]:
        return [u.model_dump() for u in self._update_history[-50:]]


# ── Signal Correlation Analyzer ──

class SignalCorrelationAnalyzer:
    """
    Sinyaller arası korelasyon analizi.
    İki sinyal yüksek korelasyona sahipse, birinin ağırlığı azaltılabilir.
    """

    def __init__(self, scoring_engine):
        self.scoring_engine = scoring_engine

    def compute_correlation_matrix(
        self, window_seconds: float = 60.0
    ) -> Dict[str, Dict[str, float]]:
        """Tüm sinyal çiftleri için korelasyon matrisi."""
        signals = list(self.scoring_engine.WEIGHTS.keys())
        now = time.time()
        matrix: Dict[str, Dict[str, float]] = {}

        for s1 in signals:
            matrix[s1] = {}
            h1 = self.scoring_engine._signal_history.get(s1, deque())
            vals1 = [v for ts, v in h1 if now - ts <= window_seconds]

            for s2 in signals:
                if s1 == s2:
                    matrix[s1][s2] = 1.0
                    continue

                h2 = self.scoring_engine._signal_history.get(s2, deque())
                vals2 = [v for ts, v in h2 if now - ts <= window_seconds]

                if len(vals1) < 3 or len(vals2) < 3:
                    matrix[s1][s2] = 0.0
                    continue

                # Eşit uzunlukta kes
                min_len = min(len(vals1), len(vals2))
                a = vals1[-min_len:]
                b = vals2[-min_len:]
                matrix[s1][s2] = round(_pearson(a, b), 3)

        return matrix

    def get_redundant_pairs(
        self, threshold: float = 0.8
    ) -> List[SignalCorrelation]:
        """Yüksek korelasyonlu sinyal çiftlerini bul."""
        matrix = self.compute_correlation_matrix()
        signals = list(matrix.keys())
        pairs = []

        for i, s1 in enumerate(signals):
            for s2 in signals[i + 1:]:
                corr = matrix[s1].get(s2, 0)
                if abs(corr) >= threshold:
                    pairs.append(SignalCorrelation(
                        signal_a=s1,
                        signal_b=s2,
                        correlation=corr,
                    ))

        return pairs


# ── Adaptive Weight Manager ──

class AdaptiveWeightManager:
    """
    Zamana göre ağırlık otomatik ayarlama.
    Yayın süresince sinyal güvenilirliğine göre ağırlıkları günceller.
    """

    def __init__(self, scoring_engine):
        self.scoring_engine = scoring_engine
        self._signal_reliability: Dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
        self._last_adjustment: float = 0.0
        self._adjustment_interval: float = 300.0  # 5 dakikada bir

    def record_signal_accuracy(
        self, signal_name: str, was_correct: bool
    ):
        """Bir sinyalin doğru tahmin yapıp yapmadığını kaydet."""
        self._signal_reliability[signal_name].append(
            (time.time(), 1.0 if was_correct else 0.0)
        )

    def adjust_weights(self) -> Dict[str, float]:
        """Sinyal güvenilirliğine göre ağırlıkları ayarla."""
        now = time.time()
        if now - self._last_adjustment < self._adjustment_interval:
            return dict(self.scoring_engine.WEIGHTS)

        self._last_adjustment = now
        base_weights = dict(self.scoring_engine.WEIGHTS)

        for signal, history in self._signal_reliability.items():
            if signal not in base_weights or len(history) < 10:
                continue

            # Son 100 kaydın güvenilirliği
            recent = list(history)[-100:]
            reliability = sum(v for _, v in recent) / len(recent)

            # Güvenilir sinyallere %20'ye kadar bonus
            if reliability > 0.8:
                boost = min(0.2, (reliability - 0.8) * 0.5)
                base_weights[signal] *= (1.0 + boost)
            elif reliability < 0.4:
                # Güvenilir olmayan sinyalleri %30'a kadar azalt
                penalty = min(0.3, (0.4 - reliability) * 0.5)
                base_weights[signal] *= (1.0 - penalty)

        # Normalize et
        total = sum(base_weights.values())
        if total > 0:
            adjusted = {k: v / total for k, v in base_weights.items()}
            self.scoring_engine.WEIGHTS = adjusted
            return adjusted

        return dict(self.scoring_engine.WEIGHTS)


# ── Persistence ──

class SignalFusionStore:
    """Sinyal füzyon verilerini JSON'a kaydet/yükle."""

    def __init__(self, state_path: str | Path | None = None):
        self._state = JsonStateStore(state_path or "data/signal_fusion_state.json")
        self._ablation_history: List[Dict] = []
        self._weight_updates: List[Dict] = []
        self._reliability_data: Dict[str, List] = {}

    async def save(
        self,
        ablation_history: List[Dict],
        weight_updates: List[Dict],
        reliability: Dict[str, List],
    ) -> None:
        await self._state.save({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "ablation_history": ablation_history[-200:],
            "weight_updates": weight_updates[-100:],
            "reliability": {k: v[-200:] for k, v in reliability.items()},
        })

    async def load(self) -> Dict[str, Any]:
        return await self._state.load()


# ── Helper ──

def _pearson(xs: List[float], ys: List[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den_x = sum((x - mx) ** 2 for x in xs) ** 0.5
    den_y = sum((y - my) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


# ── Singletons ──

spam_detector = SpamDetector()
signal_fusion_store = SignalFusionStore()
