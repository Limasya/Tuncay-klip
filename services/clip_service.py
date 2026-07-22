"""
Klip sınıflandırma ve meta veri servisi.
- CLIP modeli ile görsel-içerik etiketleme
- Analiz sonuçlarından kategori belirleme
- Kick API meta verilerini klip ile ilişkilendirme
- Bulut depolamaya (S3) yükleme
"""
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# Kategori eşleştirme tablosu
EMOTION_TO_CATEGORY = {
    "happy": "exciting",
    "surprise": "exciting",
    "angry": "rage",
    "sad": "emotional",
    "fear": "emotional",
    "disgust": "fail",
    "neutral": "other",
}

# CLIP zero-shot etiket adayları
CLIP_LABELS = [
    "a person celebrating with joy",
    "a person screaming in excitement",
    "a person looking angry or frustrated",
    "a person laughing",
    "a person showing surprise",
    "a person crying or emotional",
    "a victory celebration moment",
    "a gaming fail moment",
    "a funny reaction",
    "a skillful gameplay moment",
    "a wholesome heartwarming moment",
    "an intense competitive moment",
    "a person raging at the screen",
    "a calm and relaxed person",
]


class ClipClassifier:
    """
    Klip içerik sınıflandırma servisi.
    CLIP zero-shot classification + analiz sonuçları.
    """

    def __init__(self):
        self._clip_pipeline = None

    def _load_clip(self):
        """OpenAI CLIP modelini yükle."""
        try:
            from transformers import CLIPProcessor, CLIPModel
            import torch

            model_name = "openai/clip-vit-base-patch32"
            self._clip_model = CLIPModel.from_pretrained(model_name)
            self._clip_processor = CLIPProcessor.from_pretrained(model_name)
            self._clip_model.eval()
            logger.info("CLIP modeli yüklendi: %s", model_name)
        except Exception as e:
            logger.warning("CLIP modeli yüklenemedi: %s", e)
            self._clip_pipeline = None

    def classify_with_clip(self, frame) -> List[Tuple[str, float]]:
        """
        CLIP ile zero-shot görüntü sınıflandırma.
        Returns: [(label, score), ...] sıralı liste.
        """
        if not hasattr(self, '_clip_model') or self._clip_model is None:
            self._load_clip()

        if not hasattr(self, '_clip_model') or self._clip_model is None:
            return [("unknown", 0.0)]

        import torch
        from PIL import Image

        # numpy -> PIL
        if isinstance(frame, type(None)):
            return [("unknown", 0.0)]

        pil_img = Image.fromarray(frame[:, :, ::-1])  # BGR->RGB

        inputs = self._clip_processor(
            text=CLIP_LABELS,
            images=pil_img,
            return_tensors="pt",
            padding=True,
        )

        with torch.no_grad():
            outputs = self._clip_model(**inputs)
            logits = outputs.logits_per_image
            probs = logits.softmax(dim=1)[0].tolist()

        results = list(zip(CLIP_LABELS, probs))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def determine_category(
        self,
        emotion_result: Dict,
        motion_result: Dict,
        audio_result: Dict,
    ) -> str:
        """Analiz sonuçlarından klip kategorisi belirler."""
        dominant_emotion = emotion_result.get("dominant_emotion", "neutral")
        gesture = motion_result.get("pose", {}).get("gesture", "none")
        is_spike = audio_result.get("is_spike", False)

        # Jest bazlı kategoriler
        if gesture in ("hands_up", "hand_raise_left", "hand_raise_right"):
            if dominant_emotion in ("happy", "surprise"):
                return "victory"
            elif dominant_emotion == "angry":
                return "rage"

        # Ses spike + duygu kombinasyonu
        if is_spike:
            if dominant_emotion in ("happy", "surprise"):
                return "exciting"
            elif dominant_emotion == "angry":
                return "rage"

        # Duygu bazlı
        category = EMOTION_TO_CATEGORY.get(dominant_emotion, "other")

        # Hareket skoru yüksekse
        if motion_result.get("motion_score", 0) > 0.7:
            if category == "other":
                category = "skill"

        return category

    def generate_tags(
        self,
        emotion_result: Dict,
        motion_result: Dict,
        audio_result: Dict,
        clip_labels: List[Tuple[str, float]] = None,
    ) -> List[str]:
        """Klip için etiket listesi oluşturur."""
        tags = []

        # Duygu etiketi
        dominant = emotion_result.get("dominant_emotion")
        if dominant:
            tags.append(f"emotion:{dominant}")

        # Hareket etiketleri
        if motion_result.get("is_significant_event"):
            tags.append("significant_motion")
        gesture = motion_result.get("pose", {}).get("gesture", "none")
        if gesture != "none":
            tags.append(f"gesture:{gesture}")

        # Ses etiketleri
        if audio_result.get("is_spike"):
            tags.append("audio_spike")
        if audio_result.get("speech_detected"):
            tags.append("speech")

        # CLIP etiketleri (top 3)
        if clip_labels:
            for label, score in clip_labels[:3]:
                if score > 0.1:
                    tags.append(f"clip:{label}")

        return tags


class ClipMetadataService:
    """
    Klip meta verilerini toplar ve yönetir.
    Kick API'den yayın bilgileri, izleyici sayısı vb.
    """

    def __init__(self):
        self._stream_info_cache: Dict = {}
        self._cache_time: Optional[datetime] = None

    async def get_stream_metadata(self) -> Dict:
        """Kick API'den güncel yayın meta verilerini çeker."""
        from services.kick_api import kick_service

        try:
            info = await kick_service.get_livestream_info()
            self._stream_info_cache = info
            self._cache_time = datetime.now(timezone.utc)
            return info
        except Exception as e:
            logger.warning("Stream metadata alınamadı, cache kullanılıyor: %s", e)
            return self._stream_info_cache

    async def build_clip_metadata(
        self,
        emotion_result: Dict,
        motion_result: Dict,
        audio_result: Dict,
        clip_labels: List[Tuple[str, float]] = None,
    ) -> Dict:
        """Klip için tam meta veri paketi oluşturur."""
        stream_info = await self.get_stream_metadata()

        return {
            "stream": {
                "title": stream_info.get("title", ""),
                "category": stream_info.get("category", ""),
                "viewer_count": stream_info.get("viewer_count", 0),
                "is_live": stream_info.get("is_live", False),
            },
            "analysis": {
                "dominant_emotion": emotion_result.get("dominant_emotion"),
                "emotion_confidence": emotion_result.get("emotion_confidence"),
                "motion_score": motion_result.get("motion_score"),
                "audio_energy": audio_result.get("rms_energy"),
                "audio_spike": audio_result.get("is_spike"),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "clip_labels": clip_labels[:5] if clip_labels else [],
        }


class StorageService:
    """Bulut depolama (S3) veya yerel dosya yönetimi."""

    def __init__(self):
        self._s3_client = None

    def _get_s3(self):
        if self._s3_client is None:
            import boto3
            self._s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=settings.aws_region,
            )
        return self._s3_client

    async def upload_clip(self, local_path: str, remote_key: str = None) -> Optional[str]:
        """Klip dosyasını S3'e yükler."""
        if not remote_key:
            remote_key = f"clips/{Path(local_path).name}"

        try:
            s3 = self._get_s3()
            s3.upload_file(local_path, settings.s3_bucket_name, remote_key)
            url = f"https://{settings.s3_bucket_name}.s3.{settings.aws_region}.amazonaws.com/{remote_key}"
            logger.info("Klip S3'e yüklendi: %s", url)
            return url
        except Exception as e:
            logger.error("S3 yükleme hatası: %s", e)
            return None

    async def upload_thumbnail(self, local_path: str) -> Optional[str]:
        """Thumbnail dosyasını S3'e yükler."""
        remote_key = f"thumbnails/{Path(local_path).name}"
        return await self.upload_clip(local_path, remote_key)


# Singleton'lar
clip_classifier = ClipClassifier()
clip_metadata = ClipMetadataService()
storage_service = StorageService()
