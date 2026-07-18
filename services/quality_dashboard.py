"""
Quality Dashboard — Kalite Trendi Dashboard + Haftalık Rapor
────────────────────────────────────────────────────────────
FAZ-4.1: İçerik kalitesi trendleri, haftalık raporlar, kalite metrikleri.

Features:
  - Quality score trend tracking (zaman serisi)
  - Platform bazında kalite karşılaştırması
  - Haftalık/aylık otomatik rapor üretimi
  - Kalite uyarıları (kalite düşüşü tespiti)
  - AI Critic dimension trend analizi
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("quality_dashboard")


# ── Data Models ──

class QualitySnapshot(BaseModel):
    """Tek bir kalite ölçümü anlık görüntüsü."""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    clip_id: str = ""
    overall_score: float = 0.0
    dimension_scores: Dict[str, float] = Field(default_factory=dict)
    platform: str = ""
    critic_rounds: int = 0
    auto_fixes_applied: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QualityTrend(BaseModel):
    """Kalite trendi verisi."""
    period: str = ""  # "daily", "weekly", "monthly"
    date: str = ""
    avg_score: float = 0.0
    min_score: float = 0.0
    max_score: float = 0.0
    clip_count: int = 0
    dimension_averages: Dict[str, float] = Field(default_factory=dict)
    improvement_pct: float = 0.0  # önceki perioda göre


class QualityAlert(BaseModel):
    """Kalite uyarısı."""
    alert_id: str = ""
    alert_type: str = ""  # "quality_drop", "consistently_low", "trend_down"
    severity: str = "warning"  # "info", "warning", "critical"
    message: str = ""
    metric_name: str = ""
    current_value: float = 0.0
    threshold: float = 0.0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WeeklyReport(BaseModel):
    """Haftalık kalite raporu."""
    report_id: str = ""
    period_start: str = ""
    period_end: str = ""
    total_clips: int = 0
    avg_quality_score: float = 0.0
    quality_trend: str = ""  # "improving", "stable", "declining"
    dimension_summary: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    top_clips: List[Dict[str, Any]] = Field(default_factory=list)
    worst_clips: List[Dict[str, Any]] = Field(default_factory=list)
    platform_breakdown: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    alerts: List[QualityAlert] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


# ── Quality Dashboard Engine ──

class QualityDashboard:
    """
    Kalite trendi izleme ve raporlama sistemi.
    """

    # Kalite eşikleri
    QUALITY_DROP_THRESHOLD = 1.0  # ortalamanın 1 puan altı
    CONSISTENTLY_LOW_THRESHOLD = 5.0
    TREND_WINDOW_DAYS = 7

    def __init__(self, state_path: str | Path | None = None):
        self._snapshots: List[QualitySnapshot] = []
        self._alerts: List[QualityAlert] = []
        self._state_path = Path(state_path or "data/quality_dashboard_state.json")

        # Real-time tracking
        self._recent_scores: deque = deque(maxlen=500)

    def record_snapshot(self, snapshot: QualitySnapshot):
        """Yeni bir kalite ölçümü kaydet."""
        self._snapshots.append(snapshot)
        self._recent_scores.append(snapshot.overall_score)

        # Kalite kontrolü
        self._check_alerts(snapshot)

    def record_from_critic_report(
        self,
        clip_id: str,
        report: Dict[str, Any],
        platform: str = "",
    ):
        """AI Critic raporundan kalite ölçümü oluştur."""
        snapshot = QualitySnapshot(
            clip_id=clip_id,
            overall_score=report.get("score", 0),
            dimension_scores=report.get("dimension_scores", {}),
            platform=platform,
            critic_rounds=report.get("critic_rounds", 0),
            auto_fixes_applied=report.get("applied_fixes", []),
        )
        self.record_snapshot(snapshot)

    def _check_alerts(self, snapshot: QualitySnapshot):
        """Kalite uyarılarını kontrol et."""
        if not self._recent_scores or len(self._recent_scores) < 10:
            return

        avg = statistics.mean(self._recent_scores)

        # Kalite düşüşü
        if snapshot.overall_score < avg - self.QUALITY_DROP_THRESHOLD:
            alert = QualityAlert(
                alert_id=f"alert_{len(self._alerts) + 1}",
                alert_type="quality_drop",
                severity="warning",
                message=f"Kalite düştü: {snapshot.overall_score:.1f} (ortalama: {avg:.1f})",
                metric_name="overall_score",
                current_value=snapshot.overall_score,
                threshold=avg - self.QUALITY_DROP_THRESHOLD,
            )
            self._alerts.append(alert)

        # Tutarlı düşük kalite
        recent_10 = list(self._recent_scores)[-10:]
        if len(recent_10) >= 10:
            avg_10 = statistics.mean(recent_10)
            if avg_10 < self.CONSISTENTLY_LOW_THRESHOLD:
                alert = QualityAlert(
                    alert_id=f"alert_{len(self._alerts) + 1}",
                    alert_type="consistently_low",
                    severity="critical",
                    message=f"Tutarlı düşük kalite: Son 10 clip ortalaması {avg_10:.1f}",
                    metric_name="avg_10_clips",
                    current_value=avg_10,
                    threshold=self.CONSISTENTLY_LOW_THRESHOLD,
                )
                self._alerts.append(alert)

    # ── Trend Analysis ──

    def get_daily_trend(self, days: int = 30) -> List[QualityTrend]:
        """Günlük kalite trendi."""
        now = datetime.now(timezone.utc)
        trends = []

        for i in range(days):
            day = now - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)

            day_snapshots = [
                s for s in self._snapshots
                if self._parse_timestamp(s.timestamp) and
                day_start <= self._parse_timestamp(s.timestamp) < day_end
            ]

            if not day_snapshots:
                continue

            scores = [s.overall_score for s in day_snapshots]
            dim_avgs = self._average_dimensions(day_snapshots)

            trend = QualityTrend(
                period="daily",
                date=day_start.strftime("%Y-%m-%d"),
                avg_score=round(statistics.mean(scores), 2),
                min_score=round(min(scores), 2),
                max_score=round(max(scores), 2),
                clip_count=len(day_snapshots),
                dimension_averages=dim_avgs,
            )
            trends.append(trend)

        # İyileşme yüzdesini hesapla
        for i in range(1, len(trends)):
            prev_avg = trends[i - 1].avg_score
            curr_avg = trends[i].avg_score
            if prev_avg > 0:
                trends[i].improvement_pct = round(
                    ((curr_avg - prev_avg) / prev_avg) * 100, 2
                )

        return sorted(trends, key=lambda t: t.date)

    def get_weekly_trend(self, weeks: int = 12) -> List[QualityTrend]:
        """Haftalık kalite trendi."""
        now = datetime.now(timezone.utc)
        trends = []

        for i in range(weeks):
            week_end = now - timedelta(weeks=i)
            week_start = week_end - timedelta(days=7)

            week_snapshots = [
                s for s in self._snapshots
                if self._parse_timestamp(s.timestamp) and
                week_start <= self._parse_timestamp(s.timestamp) < week_end
            ]

            if not week_snapshots:
                continue

            scores = [s.overall_score for s in week_snapshots]
            dim_avgs = self._average_dimensions(week_snapshots)

            trend = QualityTrend(
                period="weekly",
                date=week_start.strftime("%Y-%m-%d"),
                avg_score=round(statistics.mean(scores), 2),
                min_score=round(min(scores), 2),
                max_score=round(max(scores), 2),
                clip_count=len(week_snapshots),
                dimension_averages=dim_avgs,
            )
            trends.append(trend)

        return sorted(trends, key=lambda t: t.date)

    def _average_dimensions(
        self, snapshots: List[QualitySnapshot]
    ) -> Dict[str, float]:
        """Snapshot listesinin boyut ortalamalarını hesapla."""
        dim_sums: Dict[str, float] = defaultdict(float)
        dim_counts: Dict[str, int] = defaultdict(int)

        for s in snapshots:
            for dim, score in s.dimension_scores.items():
                dim_sums[dim] += score
                dim_counts[dim] += 1

        return {
            dim: round(dim_sums[dim] / max(1, dim_counts[dim]), 3)
            for dim in dim_sums
        }

    def _parse_timestamp(self, ts: str) -> Optional[datetime]:
        """ISO timestamp'ı parse et."""
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None

    # ── Weekly Report ──

    async def generate_weekly_report(self) -> WeeklyReport:
        """Haftalık kalite raporu üret."""
        now = datetime.now(timezone.utc)
        week_start = now - timedelta(days=7)

        week_snapshots = [
            s for s in self._snapshots
            if self._parse_timestamp(s.timestamp) and
            self._parse_timestamp(s.timestamp) >= week_start
        ]

        if not week_snapshots:
            return WeeklyReport(
                report_id=f"weekly_{now.strftime('%Y%m%d')}",
                period_start=week_start.isoformat(),
                period_end=now.isoformat(),
                total_clips=0,
            )

        scores = [s.overall_score for s in week_snapshots]
        avg_score = statistics.mean(scores)

        # Trend belirleme
        first_half = scores[:len(scores) // 2] if len(scores) > 2 else scores
        second_half = scores[len(scores) // 2:] if len(scores) > 2 else scores
        first_avg = statistics.mean(first_half) if first_half else 0
        second_avg = statistics.mean(second_half) if second_half else 0

        if second_avg > first_avg + 0.3:
            trend = "improving"
        elif second_avg < first_avg - 0.3:
            trend = "declining"
        else:
            trend = "stable"

        # Platform bazında analiz
        platform_data: Dict[str, List[float]] = defaultdict(list)
        for s in week_snapshots:
            if s.platform:
                platform_data[s.platform].append(s.overall_score)

        platform_breakdown = {}
        for plat, plat_scores in platform_data.items():
            platform_breakdown[plat] = {
                "avg": round(statistics.mean(plat_scores), 2),
                "min": round(min(plat_scores), 2),
                "max": round(max(plat_scores), 2),
                "count": len(plat_scores),
            }

        # En iyi/kötü klipler
        sorted_by_score = sorted(week_snapshots, key=lambda s: s.overall_score, reverse=True)
        top_clips = [
            {"clip_id": s.clip_id, "score": s.overall_score, "platform": s.platform}
            for s in sorted_by_score[:5]
        ]
        worst_clips = [
            {"clip_id": s.clip_id, "score": s.overall_score, "platform": s.platform}
            for s in sorted_by_score[-5:]
        ]

        # Boyut özeti
        dim_summary = {}
        dim_avgs = self._average_dimensions(week_snapshots)
        for dim, avg in dim_avgs.items():
            dim_summary[dim] = {"avg": avg}

        # Öneriler
        recommendations = self._generate_recommendations(
            avg_score, dim_avgs, trend
        )

        return WeeklyReport(
            report_id=f"weekly_{now.strftime('%Y%m%d')}",
            period_start=week_start.isoformat(),
            period_end=now.isoformat(),
            total_clips=len(week_snapshots),
            avg_quality_score=round(avg_score, 2),
            quality_trend=trend,
            dimension_summary=dim_summary,
            top_clips=top_clips,
            worst_clips=worst_clips,
            platform_breakdown=platform_breakdown,
            alerts=[a for a in self._alerts if self._parse_timestamp(a.timestamp) and
                    self._parse_timestamp(a.timestamp) >= week_start],
            recommendations=recommendations,
        )

    def _generate_recommendations(
        self,
        avg_score: float,
        dim_avgs: Dict[str, float],
        trend: str,
    ) -> List[str]:
        """Rapora göre öneriler üret."""
        recs = []

        if trend == "declining":
            recs.append("Kalite düşüş trendinde — AI Critic eşiklerini sıkılaştırın.")
        elif trend == "improving":
            recs.append("Kalite yükselişte — mevcut ayarlar iyi çalışıyor.")

        if avg_score < 6.0:
            recs.append("Ortalama kalite düşük — render pipeline'ı gözden geçirin.")

        # En zayıf boyut
        if dim_avgs:
            weakest = min(dim_avgs.items(), key=lambda x: x[1])
            if weakest[1] < 0.5:
                recs.append(
                    f"'{weakest[0]}' boyutu en zayıf ({weakest[1]:.2f}) — "
                    f"bu boyuta özel optimizasyon yapın."
                )

        # En güçlü boyut
        if dim_avgs:
            strongest = max(dim_avgs.items(), key=lambda x: x[1])
            recs.append(
                f"'{strongest[0]}' boyutu güçlü ({strongest[1]:.2f}) — "
                f"bu yaklaşımı diğer boyutlara da uygulayın."
            )

        return recs

    # ── Query ──

    def get_current_status(self) -> Dict[str, Any]:
        """Mevcut kalite durumu."""
        if not self._recent_scores:
            return {"message": "Henüz veri yok"}

        recent = list(self._recent_scores)
        return {
            "current_avg": round(statistics.mean(recent[-10:]), 2) if len(recent) >= 10 else round(statistics.mean(recent), 2),
            "overall_avg": round(statistics.mean(recent), 2),
            "overall_min": round(min(recent), 2),
            "overall_max": round(max(recent), 2),
            "total_snapshots": len(self._snapshots),
            "recent_alerts": len([a for a in self._alerts if a.severity in ("warning", "critical")]),
            "std_dev": round(statistics.stdev(recent), 3) if len(recent) >= 2 else 0,
        }

    def get_alerts(self, severity: Optional[str] = None) -> List[Dict[str, Any]]:
        alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return [a.model_dump() for a in alerts[-50:]]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_snapshots": len(self._snapshots),
            "total_alerts": len(self._alerts),
            "score_range": (
                round(min(self._recent_scores), 2) if self._recent_scores else 0,
                round(max(self._recent_scores), 2) if self._recent_scores else 0,
            ),
        }

    # ── Persistence ──

    async def save(self) -> None:
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "snapshots": [s.model_dump() for s in self._snapshots[-500:]],
            "alerts": [a.model_dump() for a in self._alerts[-100:]],
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        temp = self._state_path.with_suffix(".tmp")
        await asyncio.to_thread(
            temp.write_text,
            json.dumps(state, ensure_ascii=False, indent=2, default=str),
            "utf-8",
        )
        await asyncio.to_thread(temp.replace, self._state_path)

    async def load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = await asyncio.to_thread(self._state_path.read_text, encoding="utf-8")
            state = json.loads(data)
            self._snapshots = [QualitySnapshot(**s) for s in state.get("snapshots", [])]
            self._alerts = [QualityAlert(**a) for a in state.get("alerts", [])]
            self._recent_scores = deque(
                [s.overall_score for s in self._snapshots[-500:]],
                maxlen=500,
            )
        except Exception as e:
            logger.warning("Quality dashboard state load failed: %s", e)


# Singleton
quality_dashboard = QualityDashboard()
