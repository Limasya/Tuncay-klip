"""
DeepFace Duygu Analizi Servisi
───────────────────────────────
Açık Kaynak DeepFace kütüphanesi (GitHub: serengil/deepface) ile
video karelerinden yayıncının yüz ifadesini tespit eder.
Kullanım: 
  - 'surprised' (şok anları) → viral spike
  - 'happy' (gülme, sevinç) → komik klip
  - 'angry' (sinirlenme, rage) → drama klip
Bunlar master_pipeline'daki viral skora eklenir.
"""
import asyncio
import logging
from pathlib import Path
from typing import Dict, Any, List

import cv2

try:
    from deepface import DeepFace
    DEEPFACE_AVAILABLE = True
except ImportError:
    DEEPFACE_AVAILABLE = False

logger = logging.getLogger("emotion_detector")

# Viral açıdan en güçlü duygular ve ağırlıkları
VIRAL_EMOTION_WEIGHTS = {
    "surprised": 3.0,   # "OMG" anları - en viral
    "happy":     2.5,   # Gülme/sevinç
    "angry":     2.0,   # Rage quit/sinirlenme
    "fear":      1.5,   # Korku/gerilim
    "disgust":   1.0,   # "Eek" anları
    "sad":       0.5,   # Düşük viral potansiyel
    "neutral":   0.0,   # Rutin
}


class EmotionDetector:
    def __init__(self):
        self.available = DEEPFACE_AVAILABLE
        if not self.available:
            logger.warning(
                "DeepFace kurulu değil. "
                "`pip install deepface` ile yükleyin. Duygu analizi devre dışı."
            )

    async def analyze_video_emotions(
        self, video_path: str, sample_fps: float = 0.5
    ) -> Dict[str, Any]:
        """
        Videoyu tarar, her örnekleme anındaki dominant duyguyu tespit eder.
        Viral skoru en yüksek (surprised/happy) anları döndürür.
        """
        if not self.available:
            return {"success": False, "error": "deepface_missing"}

        return await asyncio.to_thread(self._analyze, video_path, sample_fps)

    def _analyze(self, video_path: str, sample_fps: float) -> Dict[str, Any]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"success": False, "error": "cannot_open_video"}

        video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_interval = max(1, int(video_fps / sample_fps))

        timeline: List[Dict] = []
        viral_spikes: List[Dict] = []
        current_frame = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if current_frame % frame_interval == 0:
                timestamp = current_frame / video_fps
                try:
                    results = DeepFace.analyze(
                        frame,
                        actions=["emotion"],
                        enforce_detection=False,
                        silent=True,
                    )
                    # DeepFace liste döndürür (birden fazla yüz)
                    if isinstance(results, list):
                        result = results[0]
                    else:
                        result = results

                    dominant = result.get("dominant_emotion", "neutral")
                    emotions = result.get("emotion", {})
                    viral_weight = VIRAL_EMOTION_WEIGHTS.get(dominant, 0.0)

                    entry = {
                        "time": round(timestamp, 2),
                        "dominant_emotion": dominant,
                        "viral_weight": viral_weight,
                        "emotions": {k: round(v, 1) for k, v in emotions.items()},
                    }
                    timeline.append(entry)

                    if viral_weight >= 2.0:
                        viral_spikes.append(entry)

                except Exception:
                    # Yüz bulunamadıysa veya hata çıktıysa atla
                    pass

            current_frame += 1

        cap.release()

        # Temporal smoothing: 3-frame pencere ile emotion siniflandirmasini yumusat
        timeline = self._smooth_timeline(timeline, window=3)

        # Viral spike'lari birlestir (yanyana olanlari tek segment yap)
        merged_spikes = self._merge_emotion_spikes(viral_spikes)

        # Genel duygu dağılımı
        emotion_counts: Dict[str, int] = {}
        for e in timeline:
            em = e["dominant_emotion"]
            emotion_counts[em] = emotion_counts.get(em, 0) + 1

        return {
            "success": True,
            "total_samples": len(timeline),
            "emotion_distribution": emotion_counts,
            "viral_spikes": merged_spikes,
            "peak_emotion": max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral",
        }

    def _smooth_timeline(
        self, timeline: List[Dict], window: int = 3
    ) -> List[Dict]:
        """
        Temporal smoothing: hareketli pencere ile dominant emotion siniflandirmasini yumusatir.
        Tekrarlanan tek karelik dalgalanmalari onler.
        """
        if len(timeline) < window:
            return timeline

        smoothed = []
        half_w = window // 2
        for i, entry in enumerate(timeline):
            start = max(0, i - half_w)
            end = min(len(timeline), i + half_w + 1)
            neighborhood = timeline[start:end]

            # En yogun emotion'u bul
            counts: Dict[str, float] = {}
            for j, nb in enumerate(neighborhood):
                # Ortadaki noktalara daha agirlik ver
                dist = abs(i - (start + j))
                weight = 1.0 / (1.0 + dist)
                em = nb["dominant_emotion"]
                counts[em] = counts.get(em, 0.0) + weight

            best_emotion = max(counts, key=counts.get) if counts else entry["dominant_emotion"]
            smoothed.append({**entry, "dominant_emotion": best_emotion})

        return smoothed

    def _merge_emotion_spikes(
        self, spikes: List[Dict], max_gap: float = 3.0
    ) -> List[Dict]:
        """Yanyana gelen emotion spike'larını tek segment haline getirir."""
        if not spikes:
            return []

        merged = []
        start = spikes[0]["time"]
        end = spikes[0]["time"]
        dominant = spikes[0]["dominant_emotion"]
        weight = spikes[0]["viral_weight"]

        for spike in spikes[1:]:
            if spike["time"] - end <= max_gap:
                end = spike["time"]
                if spike["viral_weight"] > weight:
                    dominant = spike["dominant_emotion"]
                    weight = spike["viral_weight"]
            else:
                merged.append({
                    "start": start,
                    "end": end + 1.0,   # 1 sn buffer
                    "emotion": dominant,
                    "viral_weight": weight,
                })
                start = spike["time"]
                end = spike["time"]
                dominant = spike["dominant_emotion"]
                weight = spike["viral_weight"]

        merged.append({
            "start": start,
            "end": end + 1.0,
            "emotion": dominant,
            "viral_weight": weight,
        })
        return merged


# Singleton
emotion_detector = EmotionDetector()
