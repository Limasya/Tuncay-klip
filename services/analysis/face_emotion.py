"""
Yüz algılama ve duygu analizi servisi.
- SSD/MTCNN ile yüz tespiti
- CNN tabanlı duygu sınıflandırma (mutlu, üzgün, kızgın, şaşkın vb.)
- Gerçek zamanlı kare-bazlı analiz
"""
import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Duygu etiketleri
EMOTION_LABELS = [
    "angry", "disgust", "fear", "happy",
    "sad", "surprise", "neutral"
]

# Heyecan verici duygular (klip tetikleyici)
EXCITING_EMOTIONS = {"happy", "surprise", "angry"}


class FaceDetector:
    """
    OpenCV DNN veya Haar Cascade ile yüz algılama.
    """

    def __init__(self, method: str = "dnn"):
        self.method = method
        self._net = None
        self._face_cascade = None

    def _load_dnn(self):
        """OpenCV DNN tabanlı SSD yüz dedektörü yükle."""
        try:
            import cv2
            model_file = "models/res10_300x300_ssd_iter_140000.caffemodel"
            config_file = "models/deploy.prototxt"

            if not __import__("os").path.exists(model_file):
                logger.warning(
                    "DNN model dosyası bulunamadı. Haar Cascade kullanılıyor."
                )
                self.method = "haar"
                return

            self._net = cv2.dnn.readNetFromCaffe(config_file, model_file)
            logger.info("DNN yüz dedektörü yüklendi.")
        except Exception as e:
            logger.warning("DNN yüklenemedi, Haar'a geçiliyor: %s", e)
            self.method = "haar"

    def _load_haar(self):
        """Haar Cascade yüz dedektörü yükle."""
        import cv2
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )

    def detect(self, frame: np.ndarray) -> List[Tuple[int, int, int, int]]:
        """
        Frame'deki yüzleri tespit eder.
        Returns: [(x, y, w, h), ...] yüz bounding box listesi.
        """
        import cv2

        if self.method == "dnn" and self._net is None:
            self._load_dnn()
        if self.method == "haar" and self._face_cascade is None:
            self._load_haar()

        h, w = frame.shape[:2]

        if self.method == "dnn" and self._net:
            blob = cv2.dnn.blobFromImage(
                cv2.resize(frame, (300, 300)), 1.0, (300, 300),
                (104.0, 177.0, 123.0)
            )
            self._net.setInput(blob)
            detections = self._net.forward()

            faces = []
            for i in range(detections.shape[2]):
                confidence = detections[0, 0, i, 2]
                if confidence > 0.5:
                    box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
                    x1, y1, x2, y2 = box.astype("int")
                    faces.append((x1, y1, x2 - x1, y2 - y1))
            return faces

        else:
            # Haar Cascade
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = self._face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )
            if len(faces) == 0:
                return []
            return [(int(x), int(y), int(fw), int(fh))
                    for x, y, fw, fh in faces]


class EmotionClassifier:
    """
    CNN tabanlı duygu sınıflandırma.
    FER2013 veya özel eğitimli model ile 7 temel duygu.
    """

    def __init__(self):
        self._model = None
        self._pipeline = None

    def _load_model(self):
        """
        HuggingFace transformers pipeline veya özel PyTorch modeli yükle.
        """
        try:
            from transformers import pipeline
            self._pipeline = pipeline(
                "image-classification",
                model="trpakov/vit-face-expression",
                device=-1,  # CPU; GPU için 0
            )
            logger.info("HuggingFace duygu modeli yüklendi (ViT).")
        except Exception as e:
            logger.warning(
                "HuggingFace modeli yüklenemedi, basit sınıflandırıcı "
                "kullanılacak: %s", e
            )
            self._load_simple_model()

    def _load_simple_model(self):
        """
        Basit histogram-tabanlı duygu tahmini (fallback).
        Gerçek projede eğitilmiş CNN modeli kullanılmalı.
        """
        logger.info("Basit duygu sınıflandırıcı aktif (fallback modu).")

    def classify(self, face_crop: np.ndarray) -> Dict[str, float]:
        """
        Yüz görüntüsünden duygu skorları döndürür.
        Returns: {"happy": 0.8, "sad": 0.05, ...}
        """
        if self._pipeline is None and self._model is None:
            self._load_model()

        if self._pipeline:
            return self._classify_huggingface(face_crop)
        return self._classify_simple(face_crop)

    def _classify_huggingface(self, face_crop: np.ndarray) -> Dict[str, float]:
        """HuggingFace pipeline ile sınıflandırma."""
        from PIL import Image

        pil_img = Image.fromarray(face_crop[:, :, ::-1])  # BGR -> RGB
        results = self._pipeline(pil_img)

        emotions = {label: 0.0 for label in EMOTION_LABELS}
        for item in results:
            label = item["label"].lower()
            score = item["score"]
            # Etiket eşleştirme
            if label in emotions:
                emotions[label] = score
            elif "neutral" in label:
                emotions["neutral"] = score
            elif "contempt" in label:
                emotions["disgust"] = max(emotions["disgust"], score)

        return emotions

    def _classify_simple(self, face_crop: np.ndarray) -> Dict[str, float]:
        """
        Basit parlaklık/kontrast bazlı tahmin (demo amaçlı).
        Gerçek kullanımda eğitilmiş model ile değiştirilmeli.
        """
        gray = np.mean(face_crop)
        # Basit heuristic: parlak yüz = mutlu, karanlık = üzgün
        emotions = {label: 0.0 for label in EMOTION_LABELS}
        if gray > 140:
            emotions["happy"] = 0.6
            emotions["surprise"] = 0.2
            emotions["neutral"] = 0.2
        elif gray > 100:
            emotions["neutral"] = 0.7
            emotions["happy"] = 0.2
            emotions["sad"] = 0.1
        else:
            emotions["sad"] = 0.4
            emotions["angry"] = 0.3
            emotions["neutral"] = 0.3

        return emotions


class FaceEmotionAnalyzer:
    """
    Yüz tespiti + duygu sınıflandırma pipeline'ı.
    Her karede yüzleri bulur, duygu skorlarını hesaplar.
    """

    def __init__(self):
        self.face_detector = FaceDetector()
        self.emotion_classifier = EmotionClassifier()

    def analyze_frame(self, frame: np.ndarray) -> Dict:
        """
        Tek bir kareyi analiz eder.

        Returns:
            {
                "face_detected": bool,
                "face_count": int,
                "faces": [
                    {
                        "bbox": (x, y, w, h),
                        "emotions": {"happy": 0.8, ...},
                        "dominant_emotion": "happy",
                        "confidence": 0.8
                    }
                ],
                "dominant_emotion": str,
                "emotion_confidence": float,
                "is_exciting": bool
            }
        """
        import cv2

        faces = self.face_detector.detect(frame)
        result = {
            "face_detected": len(faces) > 0,
            "face_count": len(faces),
            "faces": [],
            "dominant_emotion": None,
            "emotion_confidence": 0.0,
            "is_exciting": False,
        }

        if not faces:
            return result

        all_emotions = []
        for bbox in faces:
            x, y, w, h = bbox
            # Yüz bölgesini kırp (padding ile)
            fh, fw = frame.shape[:2]
            pad = int(max(w, h) * 0.1)
            x1 = max(0, x - pad)
            y1 = max(0, y - pad)
            x2 = min(fw, x + w + pad)
            y2 = min(fh, y + h + pad)
            face_crop = frame[y1:y2, x1:x2]

            if face_crop.size == 0:
                continue

            # Resize to model input size
            face_resized = cv2.resize(face_crop, (224, 224))
            emotions = self.emotion_classifier.classify(face_resized)
            dominant = max(emotions, key=emotions.get)
            confidence = emotions[dominant]

            all_emotions.append(emotions)
            result["faces"].append({
                "bbox": bbox,
                "emotions": emotions,
                "dominant_emotion": dominant,
                "confidence": confidence,
            })

        # Aggregate: ortalama duygu skorları
        if all_emotions:
            avg_emotions = {}
            for label in EMOTION_LABELS:
                avg_emotions[label] = np.mean(
                    [e[label] for e in all_emotions]
                )
            dominant = max(avg_emotions, key=avg_emotions.get)
            result["dominant_emotion"] = dominant
            result["emotion_confidence"] = float(avg_emotions[dominant])
            result["is_exciting"] = (
                dominant in EXCITING_EMOTIONS
                and avg_emotions[dominant] >= settings.emotion_threshold
            )

        return result


# Singleton
face_emotion_analyzer = FaceEmotionAnalyzer()
