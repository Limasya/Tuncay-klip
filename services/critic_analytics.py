"""
Critic Analytics — A/B Ölçüm ve Geri Bildirim Döngüsü
─────────────────────────────────────────────────────
1. Auto-fix A/B ölçümü: auto-fix'li vs auto-fix'siz skor farkını loglar
2. Gerçek performans geri bildirimi: yayınlanan klip performansı ile
   critic_score arasındaki korelasyonu ölçer
3. Dimension bazında auto-fix etkinliği analizi

Veri akışı:
  master_pipeline → critic_analytics.record_round()
  platform API    → critic_analytics.record_performance()
  raporlama       → critic_analytics.get_ab_report()
"""
from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("critic_analytics")


# ── Data Models ──

class CriticRoundRecord(BaseModel):
    """Tek bir auto-fix turunun kaydı."""
    clip_id: str
    round_idx: int
    video_path: str = ""
    # Boyut bazında skorlar (0-1)
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    # Toplam skor (0-10)
    total_score: float = 0.0
    # Hangi fix'ler uygulandı?
    applied_fixes: List[str] = Field(default_factory=list)
    # Bu turda skor iyileşmesi
    score_delta: float = 0.0
    # Hangi boyutlarda iyileşme var?
    dimension_deltas: Dict[str, float] = Field(default_factory=dict)
    passed: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ClipPerformanceRecord(BaseModel):
    """Yayınlanan klibin gerçek platform performansı."""
    clip_id: str
    platform: str = ""  # youtube, tiktok, instagram
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    watch_time_seconds: float = 0.0
    avg_watch_percentage: float = 0.0
    # AI Critic'in tahmin ettiği skor
    predicted_score: float = 0.0
    # Auto-fix uygulandı mı?
    auto_fix_applied: bool = False
    # Hangi fix'ler?
    fixes: List[str] = Field(default_factory=list)
    # Engagement rate
    engagement_rate: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ABTestResult(BaseModel):
    """A/B test sonucu: auto-fix'li vs'siz."""
    dimension: str
    with_fix_avg_delta: float = 0.0
    without_fix_avg_delta: float = 0.0
    improvement: float = 0.0  # fix'li - fix'siz
    sample_size: int = 0
    confidence: str = "low"  # low, medium, high


# ── Analytics Engine ──

class CriticAnalytics:
    """
    AI Critic A/B ölçüm ve geri bildirim analizi.
    """

    def __init__(self, state_path: str | Path | None = None):
        self._rounds: List[CriticRoundRecord] = []
        self._performance: List[ClipPerformanceRecord] = []
        self._state_path = Path(state_path or "data/critic_analytics_state.json")

    # ── Round Recording ──

    def record_round(
        self,
        clip_id: str,
        round_idx: int,
        video_path: str = "",
        dimension_scores: Optional[Dict[str, float]] = None,
        total_score: float = 0.0,
        applied_fixes: Optional[List[str]] = None,
        previous_scores: Optional[Dict[str, float]] = None,
        passed: bool = False,
    ) -> CriticRoundRecord:
        """
        Auto-fix turunu kaydet. Önceki turun skorlarıyla farkı hesapla.
        """
        delta = 0.0
        dim_deltas: Dict[str, float] = {}
        if previous_scores and dimension_scores:
            prev_total = sum(
                previous_scores.get(d, 0) * w
                for d, w in _dimension_weights().items()
            ) * 10.0
            delta = total_score - prev_total

            for dim, score in dimension_scores.items():
                prev_dim = previous_scores.get(dim, score)
                dim_deltas[dim] = round(score - prev_dim, 4)

        record = CriticRoundRecord(
            clip_id=clip_id,
            round_idx=round_idx,
            video_path=video_path,
            dimension_scores=dimension_scores or {},
            total_score=total_score,
            applied_fixes=applied_fixes or [],
            score_delta=round(delta, 3),
            dimension_deltas=dim_deltas,
            passed=passed,
        )
        self._rounds.append(record)
        return record

    # ── Performance Recording ──

    def record_performance(
        self,
        clip_id: str,
        platform: str = "",
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        watch_time_seconds: float = 0.0,
        avg_watch_percentage: float = 0.0,
        predicted_score: float = 0.0,
        auto_fix_applied: bool = False,
        fixes: Optional[List[str]] = None,
    ) -> ClipPerformanceRecord:
        """Gerçek platform performansını kaydet."""
        engagement_rate = 0.0
        if views > 0:
            engagement_rate = ((likes + comments + shares) / views) * 100

        record = ClipPerformanceRecord(
            clip_id=clip_id,
            platform=platform,
            views=views,
            likes=likes,
            comments=comments,
            shares=shares,
            watch_time_seconds=watch_time_seconds,
            avg_watch_percentage=avg_watch_percentage,
            predicted_score=predicted_score,
            auto_fix_applied=auto_fix_applied,
            fixes=fixes or [],
            engagement_rate=round(engagement_rate, 2),
        )
        self._performance.append(record)
        return record

    # ── A/B Report ──

    def get_ab_report(self, last_n: int = 50) -> Dict[str, Any]:
        """
        Son N klipte auto-fix etkinliği raporu.
        Dimension bazında: fix uygulanan turlarda ortalama skor iyileşmesi.
        """
        recent = self._rounds[-last_n:] if self._rounds else []

        if not recent:
            return {"message": "Yeterli veri yok", "total_rounds": 0}

        # Boyut bazında analiz
        dim_fix_deltas: Dict[str, List[float]] = defaultdict(list)
        dim_no_fix_deltas: Dict[str, List[float]] = defaultdict(list)

        for record in recent:
            fixed_dims = set(record.applied_fixes)
            for dim, delta in record.dimension_deltas.items():
                if dim in fixed_dims:
                    dim_fix_deltas[dim].append(delta)
                else:
                    dim_no_fix_deltas[dim].append(delta)

        dimension_results = {}
        for dim in set(list(dim_fix_deltas.keys()) + list(dim_no_fix_deltas.keys())):
            fix_deltas = dim_fix_deltas.get(dim, [])
            no_fix_deltas = dim_no_fix_deltas.get(dim, [])

            fix_avg = sum(fix_deltas) / len(fix_deltas) if fix_deltas else 0
            no_fix_avg = sum(no_fix_deltas) / len(no_fix_deltas) if no_fix_deltas else 0
            improvement = fix_avg - no_fix_avg

            sample_size = len(fix_deltas)
            confidence = "low"
            if sample_size >= 10:
                confidence = "high"
            elif sample_size >= 5:
                confidence = "medium"

            dimension_results[dim] = ABTestResult(
                dimension=dim,
                with_fix_avg_delta=round(fix_avg, 4),
                without_fix_avg_delta=round(no_fix_avg, 4),
                improvement=round(improvement, 4),
                sample_size=sample_size,
                confidence=confidence,
            )

        # Genel istatistikler
        total_rounds = len(recent)
        rounds_with_fix = [r for r in recent if r.applied_fixes]
        avg_score_delta = sum(r.score_delta for r in recent) / max(1, total_rounds)
        avg_fix_delta = (
            sum(r.score_delta for r in rounds_with_fix) / max(1, len(rounds_with_fix))
            if rounds_with_fix else 0
        )

        return {
            "total_rounds": total_rounds,
            "rounds_with_fix": len(rounds_with_fix),
            "avg_score_delta": round(avg_score_delta, 3),
            "avg_fix_score_delta": round(avg_fix_delta, 3),
            "dimensions": {
                dim: {
                    "improvement": r.improvement,
                    "sample_size": r.sample_size,
                    "confidence": r.confidence,
                    "with_fix_delta": r.with_fix_avg_delta,
                    "without_fix_delta": r.without_fix_avg_delta,
                }
                for dim, r in dimension_results.items()
            },
            "recommendations": self._build_recommendations(dimension_results),
        }

    # ── Correlation Analysis ──

    def get_correlation_report(self) -> Dict[str, Any]:
        """
        AI Critic skoru ile gerçek performans arasındaki korelasyonu ölçer.
        Amaç: AI Critic'in tahminlerinin izleyici tepkisiyle ne kadar örtüştüğünü
        anlamak ve heuristik ağırlıkları buna göre ayarlamak.
        """
        if not self._performance:
            return {"message": "Henüz performans verisi yok"}

        # Her klibin en son round'undaki skoru bul
        clip_scores: Dict[str, float] = {}
        clip_fixes: Dict[str, bool] = {}
        for r in self._rounds:
            clip_scores[r.clip_id] = r.total_score
            clip_fixes[r.clip_id] = bool(r.applied_fixes)

        # Performans ile eşleştir
        matched = []
        for p in self._performance:
            predicted = clip_scores.get(p.clip_id, p.predicted_score)
            if predicted > 0:
                matched.append({
                    "clip_id": p.clip_id,
                    "predicted_score": predicted,
                    "engagement_rate": p.engagement_rate,
                    "views": p.views,
                    "auto_fix_applied": clip_fixes.get(p.clip_id, False),
                    "platform": p.platform,
                })

        if not matched:
            return {"message": "Eşleşen veri bulunamadı"}

        # Basit korelasyon (Pearson)
        n = len(matched)
        if n < 3:
            return {
                "message": f"Yeterli veri değil ({n} klibe ihtiyaç var)",
                "matched_clips": n,
            }

        xs = [m["predicted_score"] for m in matched]
        ys = [m["engagement_rate"] for m in matched]
        correlation = _pearson(xs, ys)

        # Auto-fix etkisi
        fixed = [m for m in matched if m["auto_fix_applied"]]
        unfixed = [m for m in matched if not m["auto_fix_applied"]]
        fixed_avg_eng = (
            sum(m["engagement_rate"] for m in fixed) / len(fixed) if fixed else 0
        )
        unfixed_avg_eng = (
            sum(m["engagement_rate"] for m in unfixed) / len(unfixed) if unfixed else 0
        )

        return {
            "matched_clips": n,
            "correlation": round(correlation, 3),
            "correlation_strength": _correlation_strength(correlation),
            "auto_fix_effect": {
                "fixed_avg_engagement": round(fixed_avg_eng, 2),
                "unfixed_avg_engagement": round(unfixed_avg_eng, 2),
                "fix_improvement": round(fixed_avg_eng - unfixed_avg_eng, 2),
                "fixed_count": len(fixed),
                "unfixed_count": len(unfixed),
            },
            "clips": matched[:20],
        }

    # ── Dimension Effectiveness ──

    def get_dimension_effectiveness(self) -> Dict[str, Any]:
        """Hangi auto-fix boyutu gerçekten işe yarıyor?"""
        dim_stats: Dict[str, Dict] = defaultdict(lambda: {
            "applied": 0, "improved": 0, "total_delta": 0.0,
        })

        for record in self._rounds:
            for fix in record.applied_fixes:
                dim_stats[fix]["applied"] += 1
                delta = record.dimension_deltas.get(fix, 0)
                dim_stats[fix]["total_delta"] += delta
                if delta > 0.01:
                    dim_stats[fix]["improved"] += 1

        result = {}
        for dim, stats in dim_stats.items():
            applied = stats["applied"]
            improved = stats["improved"]
            avg_delta = stats["total_delta"] / max(1, applied)
            result[dim] = {
                "applied_count": applied,
                "improved_count": improved,
                "improvement_rate": round(improved / max(1, applied), 2),
                "avg_score_delta": round(avg_delta, 4),
                "effective": avg_delta > 0.01,
            }

        return result

    # ── Recommendations ──

    def _build_recommendations(
        self, dimension_results: Dict[str, ABTestResult]
    ) -> List[str]:
        """A/B sonuçlarına göre öneriler üret."""
        recs = []
        for dim, r in dimension_results.items():
            if r.sample_size < 5:
                recs.append(
                    f"{dim}: Yeterli örnek yok ({r.sample_size}), daha fazla veri topla."
                )
            elif r.improvement > 0.05:
                recs.append(
                    f"{dim}: Auto-fix etkili (+{r.improvement:.2f} skor iyileşmesi)."
                )
            elif r.improvement < -0.02:
                recs.append(
                    f"{dim}: Auto-fix zararlı ({r.improvement:.2f}), devre dışı bırakılmalı."
                )
            else:
                recs.append(
                    f"{dim}: Auto-fix nötr etki ({r.improvement:+.2f})."
                )
        return recs

    # ── Persistence ──

    async def save(self) -> None:
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "rounds": [r.model_dump() for r in self._rounds[-500:]],
            "performance": [p.model_dump() for p in self._performance[-200:]],
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._state_path.with_suffix(".tmp")
        await asyncio.to_thread(
            temp.write_text,
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            "utf-8",
        )
        await asyncio.to_thread(temp.replace, self._state_path)
        logger.info(
            "Critic analytics saved: %d rounds, %d performance records",
            len(self._rounds), len(self._performance),
        )

    async def load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = await asyncio.to_thread(self._state_path.read_text, encoding="utf-8")
            state = json.loads(data)
            self._rounds = [CriticRoundRecord(**r) for r in state.get("rounds", [])]
            self._performance = [ClipPerformanceRecord(**p) for p in state.get("performance", [])]
            logger.info(
                "Critic analytics loaded: %d rounds, %d perf",
                len(self._rounds), len(self._performance),
            )
        except Exception as e:
            logger.warning("Critic analytics load failed: %s", e)


# ── Helpers ──

def _dimension_weights() -> Dict[str, float]:
    from services.ai_critic import DIMENSION_WEIGHTS
    return DIMENSION_WEIGHTS


def _pearson(xs: List[float], ys: List[float]) -> float:
    """Basit Pearson korelasyon katsayısı."""
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


def _correlation_strength(r: float) -> str:
    ar = abs(r)
    if ar >= 0.7:
        return "strong"
    if ar >= 0.4:
        return "moderate"
    if ar >= 0.2:
        return "weak"
    return "negligible"


import asyncio

# Singleton
critic_analytics = CriticAnalytics()
