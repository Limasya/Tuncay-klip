"""
Duygu yayılımı efektleri motoru (emotion arc).
Zaman içindeki duygu değişimlerini görsel efektlere çevirir.
"""
import logging
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class EmotionPoint:
    """Tek bir zaman noktasındaki duygu durumu."""
    time: float
    emotion: str
    intensity: float     # 0-1 arası
    valence: float       # -1 (olumsuz) ile +1 (olumsuz) arası
    arousal: float       # 0 (sakin) ile 1 (heyecanlı) arası


@dataclass
class EmotionArc:
    """Duygu yayılımı (zaman serisi)."""
    points: List[EmotionPoint]
    duration: float
    dominant_emotion: str
    peak_intensity: float
    average_valence: float
    average_arousal: float


class EmotionArcEngine:
    """
    Duygu yayılımı efekt motoru.
    Duygu değişimlerini FFmpeg filter'larına çevirir.
    """

    # Duygu → görsel parametre mapping
    EMOTION_PARAMS = {
        "happy": {
            "saturation": 1.2, "contrast": 1.05, "brightness": 0.02,
            "temperature": 0.1, "vignette": 0.0, "speed": 1.0,
        },
        "excited": {
            "saturation": 1.4, "contrast": 1.1, "brightness": 0.03,
            "temperature": 0.15, "vignette": 0.1, "speed": 1.2,
        },
        "angry": {
            "saturation": 0.9, "contrast": 1.3, "brightness": -0.03,
            "temperature": -0.1, "vignette": 0.3, "speed": 1.0,
        },
        "sad": {
            "saturation": 0.7, "contrast": 0.95, "brightness": -0.05,
            "temperature": -0.2, "vignette": 0.2, "speed": 0.8,
        },
        "fear": {
            "saturation": 0.6, "contrast": 1.2, "brightness": -0.08,
            "temperature": -0.15, "vignette": 0.4, "speed": 0.9,
        },
        "surprise": {
            "saturation": 1.1, "contrast": 1.1, "brightness": 0.02,
            "temperature": 0.05, "vignette": 0.1, "speed": 1.1,
        },
        "neutral": {
            "saturation": 1.0, "contrast": 1.0, "brightness": 0.0,
            "temperature": 0.0, "vignette": 0.0, "speed": 1.0,
        },
        "disgust": {
            "saturation": 0.5, "contrast": 1.15, "brightness": -0.04,
            "temperature": -0.1, "vignette": 0.3, "speed": 0.9,
        },
    }

    def __init__(self):
        self._params = dict(self.EMOTION_PARAMS)

    def build_emotion_arc(
        self,
        emotion_segments: List[Dict],
        total_duration: float,
    ) -> EmotionArc:
        """
        Duygu segmentlerinden emotion arc oluşturur.

        emotion_segments: [
            {"start": 0, "end": 5, "emotion": "happy", "intensity": 0.8},
            {"start": 5, "end": 10, "emotion": "sad", "intensity": 0.6},
            ...
        ]
        """
        points = []
        for seg in emotion_segments:
            emotion = seg.get("emotion", "neutral")
            intensity = seg.get("intensity", 0.5)
            start = seg.get("start", 0)
            end = seg.get("end", start + 1)

            # Valence ve arousal hesapla
            valence, arousal = self._emotion_to_valence_arousal(emotion, intensity)

            # Ortaya nokta ekle
            mid_time = (start + end) / 2
            points.append(EmotionPoint(
                time=mid_time,
                emotion=emotion,
                intensity=intensity,
                valence=valence,
                arousal=arousal,
            ))

        # İstatistikler
        if points:
            dominant = max(
                set(p.emotion for p in points),
                key=lambda e: sum(1 for p in points if p.emotion == e)
            )
            peak = max(p.intensity for p in points)
            avg_val = sum(p.valence for p in points) / len(points)
            avg_aro = sum(p.arousal for p in points) / len(points)
        else:
            dominant = "neutral"
            peak = 0.0
            avg_val = 0.0
            avg_aro = 0.0

        return EmotionArc(
            points=points,
            duration=total_duration,
            dominant_emotion=dominant,
            peak_intensity=peak,
            average_valence=avg_val,
            average_arousal=avg_aro,
        )

    def generate_emotion_color_filter(self, arc: EmotionArc) -> str:
        """
        Emotion arc'ten FFmpeg eq filter uretir.
        Zaman icinde renk degisimi — her emotion point icin ayri enable araligi.
        """
        if not arc.points:
            return "null"

        duration = arc.duration or (arc.points[-1].time + 1.0)
        filters = []

        for i, point in enumerate(arc.points):
            params = self._params.get(point.emotion, self._params["neutral"])
            intensity = point.intensity

            sat = 1.0 + (params["saturation"] - 1.0) * intensity
            con = 1.0 + (params["contrast"] - 1.0) * intensity
            bright = params["brightness"] * intensity

            # Zaman araligi: bu noktadan sonraki noktaya kadar
            t_start = point.time
            if i + 1 < len(arc.points):
                t_end = arc.points[i + 1].time
            else:
                t_end = duration

            filters.append(
                f"eq=brightness={bright:.3f}:"
                f"contrast={con:.3f}:"
                f"saturation={sat:.3f}:"
                f"enable='between(t,{t_start:.2f},{t_end:.2f})'"
            )

        if filters:
            return ",".join(filters)

        return "null"

    def generate_emotion_speed_filter(self, arc: EmotionArc) -> str:
        """
        Emotion arc'ten hiz filter'i uretir.
        Heyecan anlarinda hizlanma, sakin anlarda yavaslama — zaman bazli.
        """
        if not arc.points:
            return "null"

        duration = arc.duration or (arc.points[-1].time + 1.0)
        segments = []

        for i, point in enumerate(arc.points):
            arousal = point.arousal

            if arousal > 0.7:
                speed = 1.1
            elif arousal < 0.3:
                speed = 0.9
            else:
                speed = 1.0

            if speed != 1.0:
                t_start = point.time
                if i + 1 < len(arc.points):
                    t_end = arc.points[i + 1].time
                else:
                    t_end = duration
                segments.append(
                    f"setpts={1.0/speed}*PTS:enable='between(t,{t_start:.2f},{t_end:.2f})'"
                )

        return ",".join(segments) if segments else "null"

    def generate_emotion_vignette_filter(self, arc: EmotionArc) -> str:
        """
        Emotion arc'ten vignette filter'i uretir.
        Olumsuz duygularda daha guclu vignette — zaman bazli.
        """
        if not arc.points:
            return "null"

        duration = arc.duration or (arc.points[-1].time + 1.0)
        segments = []

        for i, point in enumerate(arc.points):
            valence = point.valence

            if valence < -0.3:
                vig_angle = "PI/3"
            elif valence > 0.3:
                vig_angle = None
            else:
                vig_angle = "PI/4"

            if vig_angle:
                t_start = point.time
                if i + 1 < len(arc.points):
                    t_end = arc.points[i + 1].time
                else:
                    t_end = duration
                segments.append(
                    f"vignette={vig_angle}:enable='between(t,{t_start:.2f},{t_end:.2f})'"
                )

        return ",".join(segments) if segments else "null"

    def generate_emotion_combined_filter(
        self,
        arc: EmotionArc,
    ) -> str:
        """
        Tüm emotion efektlerini tek filter chain'de birleştirir.
        """
        filters = []

        # Color grading
        color = self.generate_emotion_color_filter(arc)
        if color != "null":
            filters.append(color)

        # Speed
        speed = self.generate_emotion_speed_filter(arc)
        if speed != "null":
            filters.append(speed)

        # Vignette
        vig = self.generate_emotion_vignette_filter(arc)
        if vig != "null":
            filters.append(vig)

        return ",".join(filters) if filters else "null"

    def interpolate_emotion(
        self,
        arc: EmotionArc,
        time: float,
    ) -> EmotionPoint:
        """
        Belirli bir zamandaki emotion durumunu interpolasyon ile bulur.
        """
        if not arc.points:
            return EmotionPoint(time, "neutral", 0.5, 0.0, 0.5)

        # İki nokta arasında interpolasyon yap
        for i in range(len(arc.points) - 1):
            p1 = arc.points[i]
            p2 = arc.points[i + 1]

            if p1.time <= time <= p2.time:
                # Dogrusal interpolasyon — yumusak gecis
                t_ratio = (time - p1.time) / max(p2.time - p1.time, 0.001)
                # Emotion gecisi: yogunluga gore yumusak karar
                if t_ratio < 0.3:
                    emotion = p1.emotion
                elif t_ratio > 0.7:
                    emotion = p2.emotion
                else:
                    emotion = p1.emotion if p1.intensity >= p2.intensity else p2.emotion

                return EmotionPoint(
                    time=time,
                    emotion=emotion,
                    intensity=p1.intensity + (p2.intensity - p1.intensity) * t_ratio,
                    valence=p1.valence + (p2.valence - p1.valence) * t_ratio,
                    arousal=p1.arousal + (p2.arousal - p1.arousal) * t_ratio,
                )

        # Son noktanın ötesinde
        last = arc.points[-1]
        return EmotionPoint(
            time=time,
            emotion=last.emotion,
            intensity=last.intensity,
            valence=last.valence,
            arousal=last.arousal,
        )

    def _emotion_to_valence_arousal(
        self, emotion: str, intensity: float
    ) -> Tuple[float, float]:
        """Duyguyu valence-arousal uzayına çevirir."""
        mapping = {
            "happy": (0.8, 0.6),
            "excited": (0.7, 0.9),
            "angry": (-0.6, 0.8),
            "sad": (-0.7, 0.2),
            "fear": (-0.5, 0.8),
            "surprise": (0.3, 0.8),
            "neutral": (0.0, 0.3),
            "disgust": (-0.6, 0.5),
        }
        base = mapping.get(emotion, (0.0, 0.3))
        return base[0] * intensity, base[1] * intensity

    def get_arc_summary(self, arc: EmotionArc) -> Dict:
        """
        Emotion arc'in özetini döndürür.
        """
        if not arc.points:
            return {"dominant": "neutral", "segments": 0}

        return {
            "dominant": arc.dominant_emotion,
            "peak_intensity": arc.peak_intensity,
            "average_valence": arc.average_valence,
            "average_arousal": arc.average_arousal,
            "segments": len(arc.points),
            "duration": arc.duration,
            "emotions": list(set(p.emotion for p in arc.points)),
        }


# Singleton
emotion_arc = EmotionArcEngine()
