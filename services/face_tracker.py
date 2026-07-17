"""
Yüz Takip (Auto-Reframe) Servisi
────────────────────────────────
MediaPipe ve OpenCV kullanarak videodaki yüzü tespit eder ve
takip eder. Dikey video kesimleri için en uygun FFmpeg crop 
koordinatlarını hesaplar (yumuşatılmış kamera hareketiyle).
"""
import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
import json
import tempfile
import os

import cv2
import numpy as np

# MediaPipe bazen sisteme yüklü olmayabilir, 
# hata fırlatmasını önlemek için try-except kullanıyoruz.
try:
    import mediapipe as mp
except ImportError:
    mp = None

logger = logging.getLogger("face_tracker")


class FaceTracker:
    def __init__(self):
        self.mp_face_detection = mp.solutions.face_detection if mp else None

    async def get_face_trajectory(self, video_path: str, fps: int = 2) -> Dict[str, Any]:
        """
        Videodaki yüzü analiz edip, her analiz karesi için
        yüzün x,y merkez koordinatlarını (0.0 - 1.0 arası) döndürür.
        """
        if not self.mp_face_detection:
            logger.warning("MediaPipe is not installed. Face tracking disabled.")
            return {"error": "mediapipe_missing"}

        logger.info("Starting face tracking for %s (FPS: %d)", video_path, fps)

        # OpenCV IO blocking olabilir, Thread havuzunda calistiralim
        return await asyncio.to_thread(self._analyze_video, video_path, fps)

    def _analyze_video(self, video_path: str, sample_fps: int) -> Dict[str, Any]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"error": "cannot_open_video"}

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if video_fps == 0 or total_frames == 0:
            return {"error": "invalid_video_metadata"}

        frame_interval = max(1, int(video_fps / sample_fps))
        
        face_positions = []
        current_frame = 0

        # MediaPipe modeli baslat
        with self.mp_face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        ) as face_detection:
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break

                if current_frame % frame_interval == 0:
                    # BGR -> RGB
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    results = face_detection.process(frame_rgb)

                    timestamp_sec = current_frame / video_fps
                    
                    if results.detections:
                        # En yüksek skora sahip yüzü al (genelde yayıncı ekrana yakındır)
                        best_det = max(results.detections, key=lambda d: d.score[0])
                        bbox = best_det.location_data.relative_bounding_box
                        
                        center_x = bbox.xmin + bbox.width / 2
                        center_y = bbox.ymin + bbox.height / 2
                        
                        # Sinirlar disina cikmasini onle
                        center_x = max(0.0, min(1.0, center_x))
                        center_y = max(0.0, min(1.0, center_y))

                        face_positions.append({
                            "time": round(timestamp_sec, 2),
                            "x": round(center_x, 3),
                            "y": round(center_y, 3)
                        })

                current_frame += 1

        cap.release()

        # Konumları yumuşat (Smoothing)
        smoothed = self._smooth_trajectory(face_positions)

        return {
            "success": True,
            "trajectory": smoothed,
            "samples": len(smoothed)
        }

    def _smooth_trajectory(self, positions: List[Dict], window_size: int = 5) -> List[Dict]:
        """Kamera hareketini yumuşatmak için Hareketli Ortalama (Moving Average) uygular."""
        if len(positions) < window_size:
            return positions

        smoothed = []
        for i in range(len(positions)):
            start_idx = max(0, i - window_size // 2)
            end_idx = min(len(positions), i + window_size // 2 + 1)
            
            window = positions[start_idx:end_idx]
            avg_x = sum(p["x"] for p in window) / len(window)
            avg_y = sum(p["y"] for p in window) / len(window)
            
            smoothed.append({
                "time": positions[i]["time"],
                "x": round(avg_x, 3),
                "y": round(avg_y, 3)
            })
            
        return smoothed

# Singleton
face_tracker = FaceTracker()
