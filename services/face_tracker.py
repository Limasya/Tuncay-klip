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
                        
                        # Face size relative to frame
                        face_size = max(bbox.width, bbox.height)
                        
                        # Sinirlar disina cikmasini onle
                        center_x = max(0.0, min(1.0, center_x))
                        center_y = max(0.0, min(1.0, center_y))

                        face_positions.append({
                            "time": round(timestamp_sec, 2),
                            "x": center_x,
                            "y": center_y,
                            "size": face_size
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

    def _smooth_trajectory(self, positions: List[Dict], alpha: float = 0.15) -> List[Dict]:
        """
        Kamera hareketini yumuşatmak için Exponential Smoothing uygular.
        Ayrica yuz boyutuna (size) gore dinamik 'zoom' degeri hesaplar.
        alpha degeri dusuk oldukca kamera hareketi daha yavas (smooth) olur.
        """
        if not positions:
            return []

        smoothed = []
        
        # Initial states
        curr_x = positions[0]["x"]
        curr_y = positions[0]["y"]
        curr_size = positions[0].get("size", 0.3)
        
        TARGET_FACE_SIZE = 0.35 # Yuzun ekranda kaplamasini istedigimiz oran
        
        for p in positions:
            # Exponential smoothing: S(t) = alpha * X(t) + (1-alpha) * S(t-1)
            curr_x = alpha * p["x"] + (1 - alpha) * curr_x
            curr_y = alpha * p["y"] + (1 - alpha) * curr_y
            curr_size = alpha * p.get("size", 0.3) + (1 - alpha) * curr_size
            
            # Dinamik Zoom Hesaplama:
            # Yuz uzaksa (size kucukse) zoom in, yakinsa zoom out.
            # Min 1.0 (zoom out yok), Max 2.5 (cok pixel atlamasin)
            ideal_zoom = TARGET_FACE_SIZE / max(0.05, curr_size)
            zoom_factor = max(1.0, min(2.5, ideal_zoom))
            
            smoothed.append({
                "time": p["time"],
                "x": round(curr_x, 3),
                "y": round(curr_y, 3),
                "zoom": round(zoom_factor, 2)
            })
            
        return smoothed

# Singleton
face_tracker = FaceTracker()
