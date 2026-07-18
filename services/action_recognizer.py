"""
Görsel Aksiyon Algılama Servisi (Torchvision - Faster R-CNN)
──────────────────────────────────────
Videoyu analiz edip ekrandaki nesneleri (insan, araç, vs.) tespit eder.
Ekranda çok fazla nesne veya hareket varsa videonun aksiyon
skorunu yükseltir. En heyecanlı sahnelerin (örn: 1v4 clutch) 
bulunmasını sağlar.
Zero-cost ve permissive (BSD) lisanslı yapıya (Seçenek C) geçilmiştir.
"""
import asyncio
import logging
from typing import Dict, Any, List

import cv2
import numpy as np

# Torchvision yuklu degilse hata firlatmasini onleyelim
try:
    import torch
    import torchvision
    from torchvision.models.detection import fasterrcnn_mobilenet_v3_large_320_fpn, FasterRCNN_MobileNet_V3_Large_320_FPN_Weights
    import torchvision.transforms.functional as F
    TORCHVISION_AVAILABLE = True
except ImportError:
    TORCHVISION_AVAILABLE = False

logger = logging.getLogger("action_recognizer")

class ActionRecognizer:
    def __init__(self):
        self.model = None
        self.device = None

    def _load_model(self):
        if not TORCHVISION_AVAILABLE:
            return False
        if self.model is None:
            logger.info("Loading Torchvision Faster R-CNN model (MobileNet v3)...")
            # GPU varsa GPU'yu kullan, yoksa CPU
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            weights = FasterRCNN_MobileNet_V3_Large_320_FPN_Weights.DEFAULT
            self.model = fasterrcnn_mobilenet_v3_large_320_fpn(weights=weights, box_score_thresh=0.5)
            self.model.to(self.device)
            self.model.eval()
        return True

    async def calculate_action_score(self, video_path: str, sample_fps: float = 1.0) -> Dict[str, Any]:
        """
        Videoyu saniyede 'sample_fps' kare (frame) hızında tarar.
        Ekranda tespit edilen nesne sayısına göre bir aksiyon grafiği döndürür.
        """
        if not self._load_model():
            logger.warning("Torchvision is missing. Action recognition disabled.")
            return {"error": "torchvision_missing"}

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
                # Görüntüyü RGB'ye cevir ve tensor yap
                img_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img_tensor = F.to_tensor(img_rgb).to(self.device)
                
                timestamp_sec = current_frame / video_fps
                
                object_count = 0
                with torch.no_grad():
                    # model([tensor]) -> dict listesi dondurur
                    predictions = self.model([img_tensor])
                    if predictions and len(predictions) > 0:
                        # box_score_thresh=0.5 yaptigimiz icin sadece guvenilirler doner
                        labels = predictions[0]['labels']
                        object_count = len(labels)

                
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
