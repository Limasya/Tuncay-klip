"""
Görsel Aksiyon Algılama Servisi (YOLOv8)
──────────────────────────────────────
Videoyu analiz edip ekrandaki nesneleri (insan, araç, vs.) tespit eder.
Ekranda çok fazla nesne veya hareket varsa videonun aksiyon
skorunu yükseltir. En heyecanlı sahnelerin (örn: 1v4 clutch) 
bulunmasını sağlar.
"""
import asyncio
import logging
from typing import Dict, Any, List

import cv2
import numpy as np

# Ultralytics (YOLO) yüklü değilse hata fırlatmasını önleyelim
try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None

logger = logging.getLogger("action_recognizer")

class ActionRecognizer:
    def __init__(self, model_name: str = "yolov8n.pt"):
        self.model_name = model_name
        self.model = None

    def _load_model(self):
        if not YOLO:
            return False
        if self.model is None:
            # YOLOv8 nano modelini indirip yukler (hafif ve hizlidir)
            logger.info("Loading YOLOv8 model: %s", self.model_name)
            self.model = YOLO(self.model_name)
        return True

    async def calculate_action_score(self, video_path: str, sample_fps: float = 1.0) -> Dict[str, Any]:
        """
        Videoyu saniyede 'sample_fps' kare (frame) hızında tarar.
        Ekranda tespit edilen nesne sayısına göre bir aksiyon grafiği döndürür.
        """
        if not self._load_model():
            logger.warning("YOLO/Ultralytics is missing. Action recognition disabled.")
            return {"error": "yolo_missing"}

        logger.info("Starting visual action recognition for %s", video_path)
        
        # CPU/GPU blocking islem oldugu icin thread pool'da calistiralim
        return await asyncio.to_thread(self._analyze_video, video_path, sample_fps)

    def _analyze_video(self, video_path: str, sample_fps: float) -> Dict[str, Any]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"error": "cannot_open_video"}

        video_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if video_fps == 0 or total_frames == 0:
            return {"error": "invalid_video"}

        frame_interval = max(1, int(video_fps / sample_fps))
        
        action_timeline = []
        current_frame = 0
        total_objects_detected = 0

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            if current_frame % frame_interval == 0:
                # Modeli calistir (sadece guvenilir tahminleri al, conf=0.5)
                # verbose=False yaparak log kirliligini onluyoruz
                results = self.model(frame, conf=0.5, verbose=False)
                timestamp_sec = current_frame / video_fps
                
                object_count = 0
                if results and len(results) > 0:
                    # boxes.cls -> tespit edilen siniflar (0: person, 2: car vb)
                    boxes = results[0].boxes
                    if boxes is not None:
                        object_count = len(boxes.cls)
                
                total_objects_detected += object_count
                action_timeline.append({
                    "time": round(timestamp_sec, 2),
                    "object_count": object_count
                })

            current_frame += 1

        cap.release()
        
        # Ortalama objeden daha yüksek objelerin oldugu saniyeleri
        # aksiyon zirvesi (spike) olarak belirle
        avg_objects = total_objects_detected / max(1, len(action_timeline))
        action_spikes = []
        
        for item in action_timeline:
            if item["object_count"] > avg_objects * 1.5:  # Ortalamanin %50 ustundeyse spike
                action_spikes.append(item["time"])

        # Yanyana olan spike'lari birlestir
        merged_spikes = self._merge_spikes(action_spikes)

        return {
            "success": True,
            "avg_objects_per_frame": round(avg_objects, 2),
            "action_spikes": merged_spikes,
            "samples": len(action_timeline)
        }
        
    def _merge_spikes(self, times: List[float], max_gap: float = 2.0) -> List[Dict[str, float]]:
        if not times:
            return []
            
        merged = []
        start = times[0]
        end = times[0]
        
        for t in times[1:]:
            if t - end <= max_gap:
                end = t
            else:
                merged.append({"start": start, "end": end})
                start = t
                end = t
                
        merged.append({"start": start, "end": end})
        return merged

# Singleton
action_recognizer = ActionRecognizer()
