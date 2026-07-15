"""
Otomatik Klip Çıkarma Modülü
Video'dan önemli anları tespit edip klip çıkartma
"""

import cv2
import numpy as np
import logging
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from dataclasses import dataclass
from enum import Enum
import subprocess
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DetectionMethod(Enum):
    """Klip deteksyon yöntemleri"""
    SCENE_CHANGE = "scene_change"      # Ani sahne değişiklikleri
    MOTION = "motion"                   # Hareket analizi
    AUDIO_SPIKE = "audio_spike"         # Ses yükselmesi
    FACE_DETECTION = "face_detection"   # Yüz deteksyonu
    COLOR_HISTOGRAM = "color_histogram" # Renk histogramı


@dataclass
class ClipSegment:
    """Klip bölümü"""
    start_frame: int
    end_frame: int
    start_time: float
    end_time: float
    confidence: float
    method: DetectionMethod
    thumbnail: Optional[np.ndarray] = None


class VideoClipper:
    """Video klip çıkarıcı"""
    
    def __init__(self, output_dir: str = "data/processed"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.output_dir / "clips.json"
        self.clips_metadata = self._load_metadata()
    
    def _load_metadata(self) -> list:
        """Klip metadatasını yükle"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    
    def _save_metadata(self):
        """Metadata'yı kaydet"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.clips_metadata, f, ensure_ascii=False, indent=2)
    
    def detect_scene_changes(
        self, 
        video_path: str, 
        threshold: float = 0.3,
        sample_rate: int = 10
    ) -> List[ClipSegment]:
        """
        Sahne değişikliklerini tespit et
        
        Args:
            video_path: Video dosyasının yolu
            threshold: Değişim eşiği (0-1)
            sample_rate: Her N frame'i kontrol et
            
        Returns:
            List[ClipSegment]: Tespit edilen klip bölümleri
        """
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            logger.info(f"Sahne değişikliği analizi: {Path(video_path).name}")
            logger.info(f"FPS: {fps}, Toplam frame: {total_frames}")
            
            clips = []
            prev_frame = None
            prev_hist = None
            frame_count = 0
            clip_start = 0
            in_clip = False
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                if frame_count % sample_rate == 0:
                    # Frame'i küçült (hız için)
                    frame_small = cv2.resize(frame, (160, 90))
                    gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
                    
                    if prev_frame is not None:
                        # Frameler arasındaki farkı hesapla
                        diff = cv2.absdiff(prev_frame, gray)
                        change_score = np.mean(diff) / 255.0
                        
                        if change_score > threshold:
                            # Sahne değişimi tespit edildi
                            if not in_clip:
                                clip_start = frame_count
                                in_clip = True
                                logger.debug(f"Klip başladı: Frame {clip_start}")
                        else:
                            # Sahne kararlı
                            if in_clip and frame_count - clip_start > fps * 2:  # Min 2 saniye
                                # Klip bitişi
                                clip_end = frame_count
                                start_time = clip_start / fps
                                end_time = clip_end / fps
                                
                                clip = ClipSegment(
                                    start_frame=clip_start,
                                    end_frame=clip_end,
                                    start_time=start_time,
                                    end_time=end_time,
                                    confidence=min(change_score, 1.0),
                                    method=DetectionMethod.SCENE_CHANGE
                                )
                                clips.append(clip)
                                logger.debug(f"Klip eklendi: {start_time:.1f}s - {end_time:.1f}s")
                                in_clip = False
                    
                    prev_frame = gray
                
                frame_count += 1
            
            cap.release()
            logger.info(f"Bulunan klip: {len(clips)}")
            return clips
            
        except Exception as e:
            logger.error(f"Sahne deteksyon hatası: {e}")
            return []
    
    def detect_motion(
        self,
        video_path: str,
        threshold: float = 15.0,
        min_duration: float = 1.0
    ) -> List[ClipSegment]:
        """
        Hareket analizi ile klip tespit et
        
        Args:
            video_path: Video dosyasının yolu
            threshold: Hareket eşiği
            min_duration: Minimum klip süresi (saniye)
            
        Returns:
            List[ClipSegment]: Tespit edilen klip bölümleri
        """
        try:
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            
            logger.info(f"Hareket analizi: {Path(video_path).name}")
            
            clips = []
            prev_frame = None
            frame_count = 0
            motion_frames = []
            
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_small = cv2.resize(frame, (320, 180))
                gray = cv2.cvtColor(frame_small, cv2.COLOR_BGR2GRAY)
                gray_blur = cv2.GaussianBlur(gray, (21, 21), 0)
                
                if prev_frame is not None:
                    diff = cv2.absdiff(prev_frame, gray_blur)
                    thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)[1]
                    motion_value = np.sum(thresh) / 255
                    
                    if motion_value > threshold:
                        motion_frames.append(frame_count)
                
                prev_frame = gray_blur
                frame_count += 1
            
            # Motion frames'leri kliplere dönüştür
            if motion_frames:
                clip_start = motion_frames[0]
                for i in range(1, len(motion_frames)):
                    if motion_frames[i] - motion_frames[i-1] > fps:
                        # Klip bitişi
                        clip_end = motion_frames[i-1]
                        duration = (clip_end - clip_start) / fps
                        
                        if duration >= min_duration:
                            clip = ClipSegment(
                                start_frame=clip_start,
                                end_frame=clip_end,
                                start_time=clip_start / fps,
                                end_time=clip_end / fps,
                                confidence=0.7,
                                method=DetectionMethod.MOTION
                            )
                            clips.append(clip)
                        
                        clip_start = motion_frames[i]
            
            cap.release()
            logger.info(f"Hareket klipleri: {len(clips)}")
            return clips
            
        except Exception as e:
            logger.error(f"Hareket deteksyon hatası: {e}")
            return []
    
    def extract_clip(
        self,
        video_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        quality: str = "720p"
    ) -> bool:
        """
        Video'dan klip çıkart
        
        Args:
            video_path: Kaynak video
            output_path: Çıktı dosyası
            start_time: Başlangıç zamanı (saniye)
            end_time: Bitiş zamanı (saniye)
            quality: Çıktı kalitesi
            
        Returns:
            bool: Başarılı olup olmadığı
        """
        try:
            logger.info(f"Klip çıkartılıyor: {start_time:.1f}s - {end_time:.1f}s")
            
            # FFmpeg ile klip çıkart
            cmd = [
                "ffmpeg",
                "-i", video_path,
                "-ss", str(start_time),
                "-to", str(end_time),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-y",
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"Klip başarıyla çıkartıldı: {output_path}")
                
                # Metadata'ya kaydet
                meta = {
                    "source": video_path,
                    "clip_path": output_path,
                    "start_time": start_time,
                    "end_time": end_time,
                    "duration": end_time - start_time,
                    "quality": quality
                }
                self.clips_metadata.append(meta)
                self._save_metadata()
                
                return True
            else:
                logger.error(f"FFmpeg hatası: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"Klip çıkartma hatası: {e}")
            return False
    
    def batch_extract_clips(
        self,
        video_path: str,
        segments: List[ClipSegment],
        output_prefix: str
    ) -> List[str]:
        """
        Birden fazla klip çıkart
        
        Args:
            video_path: Kaynak video
            segments: Klip bölümleri
            output_prefix: Çıktı dosya öneki
            
        Returns:
            List[str]: Çıkartılan dosyaların yolları
        """
        extracted = []
        
        for i, segment in enumerate(segments):
            output_name = f"{output_prefix}_clip_{i+1:03d}.mp4"
            output_path = self.output_dir / output_name
            
            if self.extract_clip(
                video_path,
                str(output_path),
                segment.start_time,
                segment.end_time
            ):
                extracted.append(str(output_path))
        
        return extracted
    
    def analyze_video(
        self,
        video_path: str,
        methods: Optional[List[DetectionMethod]] = None
    ) -> List[ClipSegment]:
        """
        Video'yu analiz et ve tüm klipleri bulun
        
        Args:
            video_path: Video dosyasının yolu
            methods: Kullanılacak deteksyon yöntemleri
            
        Returns:
            List[ClipSegment]: Bulunan tüm klip bölümleri
        """
        if methods is None:
            methods = [
                DetectionMethod.SCENE_CHANGE,
                DetectionMethod.MOTION
            ]
        
        all_clips = []
        
        if DetectionMethod.SCENE_CHANGE in methods:
            all_clips.extend(self.detect_scene_changes(video_path))
        
        if DetectionMethod.MOTION in methods:
            all_clips.extend(self.detect_motion(video_path))
        
        # Çakışan klipleri birleştir ve sırala
        all_clips = sorted(all_clips, key=lambda x: x.start_frame)
        
        logger.info(f"Toplam {len(all_clips)} klip tespit edildi")
        return all_clips


if __name__ == "__main__":
    # Test
    clipper = VideoClipper()
    print("Clipper modülü hazır")
