"""
Birleşik analiz pipeline'ı.
Yüz/duygu, hareket ve ses analizlerini birleştirerek
olay tespiti ve klip tetikleme kararları üretir.
"""
import logging
import asyncio
import numpy as np
from typing import Dict, Optional, Callable, Awaitable, List
from datetime import datetime
from config import get_settings
from services.analysis.face_emotion import face_emotion_analyzer
from services.analysis.motion_detection import motion_analyzer
from services.analysis.audio_analysis import audio_analyzer

logger = logging.getLogger(__name__)
settings = get_settings()


class EventDetector:
    """
    Olay tespit motoru.
    Birden fazla analiz sinyalini birleştirerek (composite score)
    klip yakalama tetikleyicisi üretir.
    """

    def __init__(self):
        self.cooldown_seconds = 10.0  # İki olay arası min bekleme
        self._last_trigger_time: float = 0.0
        self._event_callbacks: List[Callable] = []
        self._emotion_weight = 0.4
        self._motion_weight = 0.35
        self._audio_weight = 0.25

    def on_event(self, callback: Callable):
        """Olay tespit edildiğinde çağrılacak callback."""
        self._event_callbacks.append(callback)

    def compute_composite_score(
        self,
        emotion_result: Dict,
        motion_result: Dict,
        audio_result: Dict,
    ) -> float:
        """
        Ağırlıklı bileşik skor hesaplar [0, 1].
        """
        # Duygu skoru
        emotion_score = 0.0
        if emotion_result.get("is_exciting"):
            emotion_score = emotion_result.get("emotion_confidence", 0.0)

        # Hareket skoru
        motion_score = motion_result.get("motion_score", 0.0)
        if motion_result.get("is_significant_event"):
            motion_score = min(motion_score + 0.3, 1.0)

        # Ses skoru
        audio_score = 0.0
        if audio_result.get("is_spike"):
            audio_score = min(audio_result.get("spike_ratio", 0.0) / 5.0, 1.0)
        elif audio_result.get("speech_detected"):
            audio_score = 0.2

        composite = (
            self._emotion_weight * emotion_score
            + self._motion_weight * motion_score
            + self._audio_weight * audio_score
        )

        return min(composite, 1.0)

    def should_trigger(
        self,
        composite_score: float,
        current_time: float,
    ) -> bool:
        """Skor eşiği ve cooldown'a göre tetikleme kararı."""
        threshold = settings.emotion_threshold * 0.8  # ~0.56 varsayılan
        if composite_score < threshold:
            return False

        if current_time - self._last_trigger_time < self.cooldown_seconds:
            return False

        return True

    async def evaluate(
        self,
        frame: np.ndarray,
        timestamp: float,
    ) -> Optional[Dict]:
        """
        Bir frame için tam analiz + olay değerlendirmesi yapar.
        Tetikleme gerekirse event bilgisi döndürür, yoksa None.
        """
        # Paralel analiz
        emotion_result = face_emotion_analyzer.analyze_frame(frame)
        motion_result = motion_analyzer.analyze_frame(frame)
        audio_result = audio_analyzer.get_current_analysis()

        composite = self.compute_composite_score(
            emotion_result, motion_result, audio_result
        )

        result = {
            "timestamp": timestamp,
            "composite_score": composite,
            "emotion": emotion_result,
            "motion": motion_result,
            "audio": audio_result,
            "triggered": False,
        }

        if self.should_trigger(composite, timestamp):
            self._last_trigger_time = timestamp
            result["triggered"] = True
            result["trigger_type"] = self._determine_trigger_type(
                emotion_result, motion_result, audio_result
            )

            # Callback'leri çağır
            for cb in self._event_callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(result)
                    else:
                        cb(result)
                except Exception as e:
                    logger.error("Event callback hatası: %s", e)

        return result

    def _determine_trigger_type(
        self,
        emotion: Dict,
        motion: Dict,
        audio: Dict,
    ) -> str:
        """Hangi sinyal baskınsa tetikleyici tipini belirler."""
        scores = {
            "emotion": emotion.get("emotion_confidence", 0) if emotion.get("is_exciting") else 0,
            "motion": motion.get("motion_score", 0),
            "audio": audio.get("spike_ratio", 0) / 5.0 if audio.get("is_spike") else 0,
        }
        dominant = max(scores, key=scores.get)
        if scores[dominant] < 0.3:
            return "composite"
        return dominant

    def reset(self):
        motion_analyzer.reset()


class AnalysisPipeline:
    """
    Gerçek zamanlı analiz pipeline yöneticisi.
    Stream'den gelen her frame'i EventDetector'a yönlendirir.
    """

    def __init__(self):
        self.event_detector = EventDetector()
        self.is_running = False
        self._processed_frames = 0
        self._events_triggered = 0

    def on_clip_trigger(self, callback: Callable):
        """Klip yakalama tetikleyicisi callback'i."""
        self.event_detector.on_event(callback)

    async def process_frame(self, frame: np.ndarray, timestamp: float):
        """Stream capture'dan gelen her frame için çağrılır."""
        if not self.is_running:
            return

        try:
            result = await self.event_detector.evaluate(frame, timestamp)
            self._processed_frames += 1

            if result and result.get("triggered"):
                self._events_triggered += 1
                logger.info(
                    "OLAY TESPİT: score=%.2f, type=%s, emotion=%s",
                    result["composite_score"],
                    result.get("trigger_type"),
                    result["emotion"].get("dominant_emotion"),
                )

        except Exception as e:
            logger.error("Frame analiz hatası: %s", e)

    async def start(self):
        self.is_running = True
        logger.info("Analiz pipeline başladı.")

    async def stop(self):
        self.is_running = False
        self.event_detector.reset()
        logger.info("Analiz pipeline durdu. Frames=%d, Events=%d",
                     self._processed_frames, self._events_triggered)

    @property
    def stats(self) -> Dict:
        return {
            "processed_frames": self._processed_frames,
            "events_triggered": self._events_triggered,
            "is_running": self.is_running,
        }


# Singleton
analysis_pipeline = AnalysisPipeline()
