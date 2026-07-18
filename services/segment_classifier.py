"""
Segment Classifier — Akış Segmentasyonu
────────────────────────────────────────
FAZ-2.2: Yayınu segmentlere ayırma ve her segmenti sınıflandırma.

Segment türleri:
  - game_change   : Oyun değişimi
  - chat_break    : Chat yoğunluğu değişimi
  - reaction_moment : Tepki anı (yüksek duygu/ses)
  - quiet_period  : Sessiz dönem
  - hype_moment   : Yüksek enerji anı
  - intro/outro   : Giriş/çıkış

Her segment için:
  - start_time, end_time
  - segment_type
  - confidence
  - key_signals (hangi sinyaller aktif)
  - suggested_clip (klip için uygun mu?)
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("segment_classifier")


class SegmentType(str, Enum):
    GAME_CHANGE = "game_change"
    CHAT_BREAK = "chat_break"
    REACTION_MOMENT = "reaction_moment"
    QUIET_PERIOD = "quiet_period"
    HYPE_MOMENT = "hype_moment"
    INTRO = "intro"
    OUTRO = "outro"
    UNKNOWN = "unknown"


class StreamSegment(BaseModel):
    """Bir yayın segmenti."""
    segment_id: str = ""
    segment_type: SegmentType = SegmentType.UNKNOWN
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    confidence: float = 0.0
    key_signals: Dict[str, float] = Field(default_factory=dict)
    dominant_emotion: str = ""
    avg_score: float = 0.0
    peak_score: float = 0.0
    message_count: int = 0
    suggested_clip: bool = False
    clip_priority: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "segment_id": self.segment_id,
            "segment_type": self.segment_type.value,
            "start_time": round(self.start_time, 2),
            "end_time": round(self.end_time, 2),
            "duration": round(self.duration, 2),
            "confidence": round(self.confidence, 3),
            "avg_score": round(self.avg_score, 3),
            "peak_score": round(self.peak_score, 3),
            "suggested_clip": self.suggested_clip,
            "clip_priority": round(self.clip_priority, 3),
            "dominant_emotion": self.dominant_emotion,
            "key_signals": {k: round(v, 3) for k, v in self.key_signals.items()},
        }


class SegmentClassifier:
    """
    Yayını real-time segmentlere ayırır.
    Her segmentin sonuna bir "değişim" tespit ettiğinde yeni segment başlatır.
    """

    # Segment geçiş eşikleri
    SCORE_SPIKE_THRESHOLD = 0.4  # Skor ani değişimi
    CHAT_VELOCITY_CHANGE = 2.0   # Chat hızı değişimi (katı)
    QUIET_THRESHOLD = 0.15       # Sessiz dönem eşiği
    MIN_SEGMENT_DURATION = 10.0  # Minimum segment süresi (sn)
    MAX_SEGMENT_DURATION = 300.0 # Maksimum segment süresi (sn)

    def __init__(self):
        self._segments: List[StreamSegment] = []
        self._current_segment: Optional[StreamSegment] = None
        self._score_history: deque = deque(maxlen=300)
        self._chat_history: deque = deque(maxlen=300)
        self._emotion_history: deque = deque(maxlen=300)
        self._audio_history: deque = deque(maxlen=300)
        self._segment_counter: int = 0

        # Real-time state
        self._last_signal_time: float = 0.0
        self._current_signals: Dict[str, float] = {}

    def update_signal(self, signal_name: str, value: float, timestamp: Optional[float] = None):
        """Yeni bir sinyal değeri al."""
        ts = timestamp or time.time()
        self._last_signal_time = ts
        self._current_signals[signal_name] = value

        if signal_name in ("composite_score", "highlight_score"):
            self._score_history.append((ts, value))
        elif signal_name == "chat_velocity":
            self._chat_history.append((ts, value))
        elif signal_name in ("emotion_intensity", "emotion_change"):
            self._emotion_history.append((ts, value))
        elif signal_name == "audio_spike":
            self._audio_history.append((ts, value))

        # Segment değişimi kontrolü
        self._check_transition(ts)

    def _check_transition(self, current_time: float):
        """Segment geçişi olup olmadığını kontrol et."""
        if self._current_segment is None:
            self._start_new_segment(current_time, SegmentType.UNKNOWN)
            return

        seg = self._current_segment
        duration = current_time - seg.start_time

        # Minimum süre kontrolü
        if duration < self.MIN_SEGMENT_DURATION:
            return

        # Maksimum süre aşıldı — yeni segment başlat
        if duration >= self.MAX_SEGMENT_DURATION:
            self._end_current_segment(current_time)
            self._start_new_segment(current_time, SegmentType.UNKNOWN)
            return

        # Geçiş sinyallerini kontrol et
        transition = self._detect_transition(current_time)
        if transition:
            self._end_current_segment(current_time)
            self._start_new_segment(current_time, transition)

    def _detect_transition(self, current_time: float) -> Optional[SegmentType]:
        """Mevcut durumdan bir segment geçişi tespit et."""
        if not self._score_history or len(self._score_history) < 5:
            return None

        # Son 10 skorun ortalaması vs son 30 skorun ortalaması
        recent_10 = [s for _, s in list(self._score_history)[-10:]]
        recent_30 = [s for _, s in list(self._score_history)[-30:]]
        avg_recent = sum(recent_10) / len(recent_10) if recent_10 else 0
        avg_baseline = sum(recent_30) / len(recent_30) if recent_30 else 0

        # Hype moment: Skor ani yükseldi
        if avg_recent > avg_baseline + self.SCORE_SPIKE_THRESHOLD and avg_recent > 0.5:
            return SegmentType.HYPE_MOMENT

        # Quiet period: Skor çok düştü
        if avg_recent < self.QUIET_THRESHOLD and avg_baseline > self.QUIET_THRESHOLD:
            return SegmentType.QUIET_PERIOD

        # Reaction moment: Emotion Yoğunluğu aniden arttı
        if self._emotion_history:
            recent_emotions = [v for _, v in list(self._emotion_history)[-5:]]
            if recent_emotions and max(recent_emotions) > 0.7:
                avg_emotion = sum(recent_emotions) / len(recent_emotions)
                if avg_emotion > 0.5:
                    return SegmentType.REACTION_MOMENT

        # Chat break: Chat hızı büyük değişti
        if self._chat_history and len(self._chat_history) >= 10:
            recent_chat = [v for _, v in list(self._chat_history)[-5:]]
            baseline_chat = [v for _, v in list(self._chat_history)[-20:]]
            if recent_chat and baseline_chat:
                avg_r = sum(recent_chat) / len(recent_chat)
                avg_b = sum(baseline_chat) / len(baseline_chat)
                if avg_b > 0 and abs(avg_r - avg_b) / avg_b > self.CHAT_VELOCITY_CHANGE:
                    return SegmentType.CHAT_BREAK

        return None

    def _start_new_segment(self, start_time: float, seg_type: SegmentType):
        """Yeni bir segment başlat."""
        self._segment_counter += 1
        segment = StreamSegment(
            segment_id=f"seg_{self._segment_counter:04d}",
            segment_type=seg_type,
            start_time=start_time,
            key_signals=dict(self._current_signals),
        )
        self._current_segment = segment

    def _end_current_segment(self, end_time: float):
        """Mevcut segmenti bitir ve listeye ekle."""
        if self._current_segment is None:
            return

        seg = self._current_segment
        seg.end_time = end_time
        seg.duration = end_time - seg.start_time

        # Segment istatistikleri
        seg_scores = [
            s for t, s in self._score_history
            if seg.start_time <= t <= end_time
        ]
        if seg_scores:
            seg.avg_score = sum(seg_scores) / len(seg_scores)
            seg.peak_score = max(seg_scores)

        # Sınıflandırma
        seg.segment_type = self._classify_segment(seg)
        seg.confidence = self._compute_classification_confidence(seg)
        seg.suggested_clip = self._should_suggest_clip(seg)
        seg.clip_priority = self._compute_clip_priority(seg)

        self._segments.append(seg)
        self._current_segment = None

    def _classify_segment(self, seg: StreamSegment) -> SegmentType:
        """Segment'i sinyallere göre sınıflandır."""
        signals = seg.key_signals
        avg = seg.avg_score
        peak = seg.peak_score

        if peak > 0.8 and avg > 0.5:
            return SegmentType.HYPE_MOMENT
        if avg < 0.15:
            return SegmentType.QUIET_PERIOD
        if peak > 0.7 and avg < 0.4:
            return SegmentType.REACTION_MOMENT
        if signals.get("chat_velocity", 0) > 0.6:
            return SegmentType.CHAT_BREAK
        return SegmentType.UNKNOWN

    def _compute_classification_confidence(self, seg: StreamSegment) -> float:
        """Sınıflandırma güveni."""
        if seg.segment_type == SegmentType.UNKNOWN:
            return 0.3
        if seg.segment_type == SegmentType.HYPE_MOMENT:
            return min(1.0, seg.peak_score)
        if seg.segment_type == SegmentType.QUIET_PERIOD:
            return min(1.0, 1.0 - seg.avg_score)
        return 0.6

    def _should_suggest_clip(self, seg: StreamSegment) -> bool:
        """Bu segment klip için uygun mu?"""
        if seg.segment_type == SegmentType.HYPE_MOMENT and seg.duration >= 15:
            return True
        if seg.segment_type == SegmentType.REACTION_MOMENT and seg.duration >= 10:
            return True
        if seg.avg_score > 0.5 and seg.peak_score > 0.7:
            return True
        return False

    def _compute_clip_priority(self, seg: StreamSegment) -> float:
        """Klip öncelik skoru."""
        base = seg.avg_score * 0.4 + seg.peak_score * 0.6

        type_bonus = {
            SegmentType.HYPE_MOMENT: 0.2,
            SegmentType.REACTION_MOMENT: 0.15,
            SegmentType.CHAT_BREAK: 0.05,
            SegmentType.QUIET_PERIOD: -0.1,
        }
        base += type_bonus.get(seg.segment_type, 0)

        # Süre bonusu: 15-60 saniye ideal
        if 15 <= seg.duration <= 60:
            base += 0.1
        elif seg.duration > 120:
            base -= 0.1

        return round(min(1.0, max(0.0, base)), 3)

    def finalize(self) -> List[StreamSegment]:
        """Mevcut segmenti bitir ve tüm segmentleri döndür."""
        if self._current_segment:
            self._end_current_segment(time.time())
        return list(self._segments)

    def get_segments(self, min_confidence: float = 0.0) -> List[StreamSegment]:
        """Bitmiş segmentleri getir."""
        return [
            s for s in self._segments
            if s.confidence >= min_confidence
        ]

    def get_clip_candidates(self, top_n: int = 5) -> List[StreamSegment]:
        """En yüksek öncelikli klip adaylarını getir."""
        candidates = [s for s in self._segments if s.suggested_clip]
        candidates.sort(key=lambda s: s.clip_priority, reverse=True)
        return candidates[:top_n]

    def get_stats(self) -> Dict[str, Any]:
        """Segment istatistikleri."""
        type_counts = {}
        for seg in self._segments:
            t = seg.segment_type.value
            type_counts[t] = type_counts.get(t, 0) + 1

        clip_suggestions = sum(1 for s in self._segments if s.suggested_clip)

        return {
            "total_segments": len(self._segments),
            "segment_types": type_counts,
            "clip_suggestions": clip_suggestions,
            "avg_segment_duration": (
                sum(s.duration for s in self._segments) / max(1, len(self._segments))
            ),
            "current_segment": self._current_segment.to_dict() if self._current_segment else None,
        }


# Singleton
segment_classifier = SegmentClassifier()
