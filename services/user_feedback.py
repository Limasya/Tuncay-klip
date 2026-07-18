"""
User Feedback — Kullanıcı Geri Bildirim Arayüzü
─────────────────────────────────────────────────
FAZ-4.3: Kullanıcı geri bildirimi toplama ve AI Critic kalibrasyonu.

Features:
  - Thumbs up/down feedback for clips
  - Dimension-specific feedback
  - Feedback → AI Critic calibration loop
  - Sentiment aggregation
  - Feedback-driven weight adjustment
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from enum import Enum

from pydantic import BaseModel, Field

logger = logging.getLogger("user_feedback")


# ── Data Models ──

class FeedbackType(str, Enum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    RATING = "rating"  # 1-5
    DIMENSION_FEEDBACK = "dimension"  # belirli boyut için


class FeedbackEntry(BaseModel):
    """Tek bir geri bildirim kaydı."""
    feedback_id: str = ""
    clip_id: str = ""
    feedback_type: str = "thumbs_up"
    rating: float = 0.0  # 1-5 (rating için)
    dimension: str = ""  # hangi boyut için (opening, subtitle, zoom, thumbnail, cut)
    dimension_score: float = 0.0  # AI'ın bu boyut için verdiği skor
    user_comment: str = ""
    source: str = "api"  # "api", "dashboard", "telegram"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FeedbackAggregate(BaseModel):
    """Geri bildirim aggregation sonucu."""
    clip_id: str = ""
    total_feedback: int = 0
    thumbs_up: int = 0
    thumbs_down: int = 0
    avg_rating: float = 0.0
    sentiment: str = ""  # "positive", "negative", "neutral"
    dimension_feedback: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class CalibrationAdjustment(BaseModel):
    """AI Critic kalibrasyon ayarlaması."""
    dimension: str = ""
    adjustment: float = 0.0  # eklenecek/çıkarılacak skor
    reason: str = ""
    confidence: float = 0.0
    sample_size: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── User Feedback Engine ──

class UserFeedback:
    """
    Kullanıcı geri bildirim toplama ve AI Critic kalibrasyon sistemi.
    """

    # Kalibrasyon için minimum geri bildirim sayısı
    MIN_FEEDBACK_FOR_CALIBRATION = 5

    def __init__(self, state_path: str | Path | None = None):
        self._feedback: List[FeedbackEntry] = []
        self._calibration_adjustments: List[CalibrationAdjustment] = []
        self._state_path = Path(state_path or "data/user_feedback_state.json")

    # ── Feedback Recording ──

    def record_thumbs(
        self,
        clip_id: str,
        is_up: bool,
        source: str = "api",
        comment: str = "",
    ) -> FeedbackEntry:
        """Thumbs up/down geri bildirimi kaydet."""
        entry = FeedbackEntry(
            feedback_id=f"fb_{uuid.uuid4().hex[:10]}",
            clip_id=clip_id,
            feedback_type="thumbs_up" if is_up else "thumbs_down",
            user_comment=comment,
            source=source,
        )
        self._feedback.append(entry)
        logger.info("Feedback: %s → %s", clip_id[:8], "👍" if is_up else "👎")
        return entry

    def record_rating(
        self,
        clip_id: str,
        rating: float,
        source: str = "api",
        comment: str = "",
    ) -> FeedbackEntry:
        """1-5 arası puanlama geri bildirimi kaydet."""
        rating = max(1.0, min(5.0, rating))
        entry = FeedbackEntry(
            feedback_id=f"fb_{uuid.uuid4().hex[:10]}",
            clip_id=clip_id,
            feedback_type="rating",
            rating=rating,
            user_comment=comment,
            source=source,
        )
        self._feedback.append(entry)
        return entry

    def record_dimension_feedback(
        self,
        clip_id: str,
        dimension: str,
        ai_score: float,
        user_agrees: bool,
        source: str = "api",
        comment: str = "",
    ) -> FeedbackEntry:
        """Boyut bazında geri bildirim kaydet."""
        entry = FeedbackEntry(
            feedback_id=f"fb_{uuid.uuid4().hex[:10]}",
            clip_id=clip_id,
            feedback_type="dimension",
            dimension=dimension,
            dimension_score=ai_score,
            user_comment=comment,
            source=source,
            metadata={"user_agrees": user_agrees},
        )
        self._feedback.append(entry)
        return entry

    # ── Aggregation ──

    def get_clip_feedback(self, clip_id: str) -> FeedbackAggregate:
        """Bir klibin tüm geri bildirimlerini topla."""
        clip_fb = [f for f in self._feedback if f.clip_id == clip_id]
        if not clip_fb:
            return FeedbackAggregate(clip_id=clip_id)

        thumbs_up = sum(1 for f in clip_fb if f.feedback_type == "thumbs_up")
        thumbs_down = sum(1 for f in clip_fb if f.feedback_type == "thumbs_down")
        ratings = [f.rating for f in clip_fb if f.feedback_type == "rating" and f.rating > 0]

        # Sentiment
        if thumbs_up > thumbs_down:
            sentiment = "positive"
        elif thumbs_down > thumbs_up:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # Boyut bazında feedback
        dim_feedback = defaultdict(lambda: {"agree": 0, "disagree": 0, "scores": []})
        for f in clip_fb:
            if f.feedback_type == "dimension" and f.dimension:
                agrees = f.metadata.get("user_agrees", True)
                if agrees:
                    dim_feedback[f.dimension]["agree"] += 1
                else:
                    dim_feedback[f.dimension]["disagree"] += 1
                dim_feedback[f.dimension]["scores"].append(f.dimension_score)

        dimension_summary = {}
        for dim, data in dim_feedback.items():
            total = data["agree"] + data["disagree"]
            dimension_summary[dim] = {
                "agree_rate": round(data["agree"] / max(1, total), 3),
                "avg_ai_score": round(
                    sum(data["scores"]) / max(1, len(data["scores"])), 3
                ),
                "total": total,
            }

        return FeedbackAggregate(
            clip_id=clip_id,
            total_feedback=len(clip_fb),
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
            avg_rating=round(sum(ratings) / max(1, len(ratings)), 2) if ratings else 0.0,
            sentiment=sentiment,
            dimension_feedback=dimension_summary,
        )

    def get_overall_sentiment(self) -> Dict[str, Any]:
        """Genel kullanıcı sentimenti."""
        total = len(self._feedback)
        if total == 0:
            return {"message": "Henüz geri bildirim yok"}

        thumbs_up = sum(1 for f in self._feedback if f.feedback_type == "thumbs_up")
        thumbs_down = sum(1 for f in self._feedback if f.feedback_type == "thumbs_down")
        ratings = [f.rating for f in self._feedback if f.feedback_type == "rating" and f.rating > 0]

        return {
            "total_feedback": total,
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "approval_rate": round(thumbs_up / max(1, thumbs_up + thumbs_down) * 100, 1),
            "avg_rating": round(sum(ratings) / max(1, len(ratings)), 2) if ratings else None,
            "by_source": dict(self._count_by_source()),
        }

    def _count_by_source(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for f in self._feedback:
            counts[f.source] += 1
        return dict(counts)

    # ── AI Critic Calibration ──

    async def compute_calibration_adjustments(self) -> List[CalibrationAdjustment]:
        """
        Geri bildirimlere göre AI Critic kalibrasyon ayarlamaları hesapla.
        Eğer kullanıcılar bir boyutun AI skorunu genelde yanlış buluyorsa,
        o boyut için kalibrasyon ayarlaması öner.
        """
        adjustments = []

        # Boyut bazında analiz
        dim_stats: Dict[str, Dict] = defaultdict(lambda: {
            "disagree_count": 0,
            "total_count": 0,
            "score_diffs": [],
        })

        for f in self._feedback:
            if f.feedback_type != "dimension" or not f.dimension:
                continue

            dim_stats[f.dimension]["total_count"] += 1
            agrees = f.metadata.get("user_agrees", True)
            if not agrees:
                dim_stats[f.dimension]["disagree_count"] += 1
                # Kullanıcı katılmıyorsa, AI skoru muhtemelen yüksek
                dim_stats[f.dimension]["score_diffs"].append(f.dimension_score)

        for dim, stats in dim_stats.items():
            total = stats["total_count"]
            if total < self.MIN_FEEDBACK_FOR_CALIBRATION:
                continue

            disagree_rate = stats["disagree_count"] / total

            if disagree_rate > 0.4:
                # %40+ yanlış — ayarlama gerekli
                avg_diff = (
                    sum(stats["score_diffs"]) / max(1, len(stats["score_diffs"]))
                    if stats["score_diffs"] else 0
                )
                # Ayarlama: Kullanıcıların şikayet ettiği yönünde negatif skor
                adjustment = -0.1 if avg_diff > 0.5 else 0.1

                cal = CalibrationAdjustment(
                    dimension=dim,
                    adjustment=round(adjustment, 3),
                    reason=f"Yüksek yanlış oranı: %{disagree_rate * 100:.0f}",
                    confidence=min(0.9, 0.3 + total * 0.05),
                    sample_size=total,
                )
                adjustments.append(cal)

        self._calibration_adjustments.extend(adjustments)
        return adjustments

    def get_calibration_history(self) -> List[Dict[str, Any]]:
        return [a.model_dump() for a in self._calibration_adjustments[-50:]]

    # ── Query ──

    def get_all_feedback(
        self,
        clip_id: Optional[str] = None,
        feedback_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        fb = self._feedback
        if clip_id:
            fb = [f for f in fb if f.clip_id == clip_id]
        if feedback_type:
            fb = [f for f in fb if f.feedback_type == feedback_type]
        return [f.model_dump() for f in fb[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_feedback": len(self._feedback),
            "total_clips_rated": len(set(f.clip_id for f in self._feedback)),
            "total_calibrations": len(self._calibration_adjustments),
            "by_type": dict(self._count_by_type()),
        }

    def _count_by_type(self) -> Dict[str, int]:
        counts = defaultdict(int)
        for f in self._feedback:
            counts[f.feedback_type] += 1
        return dict(counts)

    # ── Persistence ──

    async def save(self) -> None:
        state = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "feedback": [f.model_dump() for f in self._feedback[-1000:]],
            "calibrations": [c.model_dump() for c in self._calibration_adjustments[-100:]],
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
            self._feedback = [FeedbackEntry(**f) for f in state.get("feedback", [])]
            self._calibration_adjustments = [
                CalibrationAdjustment(**c) for c in state.get("calibrations", [])
            ]
        except Exception as e:
            logger.warning("User feedback state load failed: %s", e)


# Singleton
user_feedback = UserFeedback()
