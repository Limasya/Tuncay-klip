"""
Engagement Analiz Servisi — Multi-Signal Highlight Detection
autoclipper projesinden adaptasyon:
  - YouTube retention peak analizi
  - Comment timestamp analizi
  - Chat volume spike detection (Twitch/Kick)

Coklu sinyal birlestirerek viral anlari tespit eder.
"""
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple, Any

logger = logging.getLogger(__name__)


@dataclass
class HighlightWindow:
    """Tespit edilen bir highlight anina ait zaman araligi."""
    start: float
    end: float
    source: str
    confidence: float = 1.0


@dataclass
class CommentTimestamp:
    """Yorumlarda tespit edilen populer zaman damgasi."""
    timestamp_sec: float
    mention_count: int


class RetentionPeakAnalyzer:
    """
    YouTube retention verisinden peak analizi.
    audience_retention_data: [{"ratio": float, "elapsed_time_ratio": float}, ...]
    threshold: Ortalamanin kac katini astigini belirler (default 1.5x).
    """

    def analyze(
        self,
        video_duration: float,
        retention_data: Optional[List[Dict[str, Any]]] = None,
        threshold: float = 1.5,
    ) -> List[HighlightWindow]:
        if not retention_data or video_duration <= 0:
            return []

        ratios = [d.get("ratio", 0) for d in retention_data]
        if not ratios:
            return []

        avg = sum(ratios) / len(ratios)
        peaks: List[HighlightWindow] = []

        in_peak = False
        peak_start = 0.0

        for i, d in enumerate(retention_data):
            t = d.get("elapsed_time_ratio", 0) * video_duration
            r = d.get("ratio", 0)

            if r > avg * threshold:
                if not in_peak:
                    peak_start = t
                    in_peak = True
            else:
                if in_peak:
                    peaks.append(HighlightWindow(
                        start=max(0, peak_start - 2),
                        end=min(video_duration, t + 3),
                        source="retention_peak",
                        confidence=min(r / avg, 3.0) if avg > 0 else 1.0,
                    ))
                    in_peak = False

        if in_peak:
            peaks.append(HighlightWindow(
                start=max(0, peak_start - 2),
                end=min(video_duration, retention_data[-1].get("elapsed_time_ratio", 1) * video_duration + 3),
                source="retention_peak",
                confidence=1.5,
            ))

        return peaks


class CommentTimestampAnalyzer:
    """
    Yorumlarda mm:ss pattern'lerini sayarak populer anlari tespit eder.
    top_n: Kac tane peak dondursun (default 3).
    window_before: Timestamp'ten once (saniye).
    window_after: Timestamp'ten sonra (saniye).
    """

    def __init__(self, top_n: int = 3, window_before: float = 5.0, window_after: float = 10.0):
        self.top_n = top_n
        self.window_before = window_before
        self.window_after = window_after

    def analyze(
        self,
        comments: List[str],
        video_duration: float = 0,
    ) -> List[HighlightWindow]:
        times: Dict[float, int] = {}
        pattern = re.compile(r"(\d+):(\d{2})")

        for text in comments:
            for match in pattern.finditer(text):
                sec = int(match.group(1)) * 60 + int(match.group(2))
                times[sec] = times.get(sec, 0) + 1

        top = sorted(times.items(), key=lambda kv: kv[1], reverse=True)[:self.top_n]

        windows: List[HighlightWindow] = []
        for ts, count in top:
            windows.append(HighlightWindow(
                start=max(0, ts - self.window_before),
                end=min(video_duration, ts + self.window_after) if video_duration > 0 else ts + self.window_after,
                source="comment_timestamp",
                confidence=min(count / 3.0, 3.0),
            ))
        return windows


class ChatSpikeDetector:
    """
    Gercek zamanli chat volume spike detection.
    Sliding-window pattern — autoclipper twitch.py'den adaptasyon.

    baseline: Beklenen mesaj sayisi (30sn icinde).
    threshold: Spike esigi carpani (default 2.5x).
    window_seconds: Pencere boyutu.
    cooldown: Spike sonrasi bekleme suresi (sn).
    """

    def __init__(
        self,
        baseline: int = 10,
        threshold: float = 2.5,
        window_seconds: float = 30.0,
        cooldown: float = 60.0,
    ):
        self.baseline = baseline
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.cooldown = cooldown
        self._timestamps: deque = deque()
        self._cooldown_until: float = 0

    def record_message(self) -> Optional[HighlightWindow]:
        """Mesaj kaydet, spike algilandiysa HighlightWindow dondur."""
        now = time.time()
        self._timestamps.append(now)
        self._evict(now)

        if now < self._cooldown_until:
            return None

        if len(self._timestamps) > self.baseline * self.threshold:
            self._cooldown_until = now + self.cooldown
            return HighlightWindow(
                start=now - 15,
                end=now + 15,
                source="chat_spike",
                confidence=len(self._timestamps) / (self.baseline * self.threshold),
            )
        return None

    @property
    def current_rate(self) -> float:
        now = time.time()
        self._evict(now)
        return len(self._timestamps) / max(self.window_seconds, 1.0)

    def _evict(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()


class MultiSignalHighlightDetector:
    """
    Coklu sinyal birlestirerek highlight tespiti.
    retention_peak + comment_timestamp + chat_spike sinyallerini fuse eder.
    """

    def __init__(self):
        self.retention_analyzer = RetentionPeakAnalyzer()
        self.comment_analyzer = CommentTimestampAnalyzer()
        self.chat_detector = ChatSpikeDetector()

    def merge_windows(
        self,
        windows: List[HighlightWindow],
        merge_gap: float = 10.0,
    ) -> List[HighlightWindow]:
        """Ayni zaman araligindaki pencereleri birlestir."""
        if not windows:
            return []

        sorted_wins = sorted(windows, key=lambda w: w.start)
        merged: List[HighlightWindow] = [sorted_wins[0]]

        for w in sorted_wins[1:]:
            last = merged[-1]
            if w.start <= last.end + merge_gap:
                merged[-1] = HighlightWindow(
                    start=last.start,
                    end=max(last.end, w.end),
                    source=f"{last.source}+{w.source}",
                    confidence=max(last.confidence, w.confidence),
                )
            else:
                merged.append(w)

        return merged

    def detect(
        self,
        video_duration: float = 0,
        retention_data: Optional[List[Dict]] = None,
        comments: Optional[List[str]] = None,
    ) -> List[HighlightWindow]:
        """Tum sinyalleri birlestirerek highlight'lari dondur."""
        all_windows: List[HighlightWindow] = []

        ret_windows = self.retention_analyzer.analyze(video_duration, retention_data)
        all_windows.extend(ret_windows)

        if comments:
            com_windows = self.comment_analyzer.analyze(comments, video_duration)
            all_windows.extend(com_windows)

        return self.merge_windows(all_windows)
