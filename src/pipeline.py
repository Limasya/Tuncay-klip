"""
İşlem Hattı (Pipeline) - FAZE 2 Bileşenlerini Birleştiren Ana Orchestrator
Stream Takibi → Video İndirme → Klip Çıkarma
"""

import logging
import json
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum

from downloader import StreamDownloader
from stream_monitor import StreamMonitor, StreamInfo, StreamStatus
from clipper import VideoClipper, DetectionMethod

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class PipelineState(Enum):
    """Pipeline durumları"""
    IDLE = "idle"
    MONITORING = "monitoring"
    DOWNLOADING = "downloading"
    CLIPPING = "clipping"
    ERROR = "error"


class ClipsPipeline:
    """FAZE 2: Tam otomatik klip çıkarma pipeline'ı"""
    
    def __init__(self):
        self.state = PipelineState.IDLE
        self.downloader = StreamDownloader()
        self.monitor = StreamMonitor(check_interval=300)  # 5 dakikada bir kontrol
        self.clipper = VideoClipper()
        self.config_file = Path("pipeline_config.json")
        self.status_file = Path("data/pipeline_status.json")
        self.load_config()
        self._setup_callbacks()
    
    def load_config(self):
        """Pipeline konfigürasyonunu yükle"""
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = {
                "clip_detection_methods": ["scene_change", "motion"],
                "min_clip_duration": 3.0,
                "max_clip_duration": 60.0,
                "scene_change_threshold": 0.3,
                "motion_threshold": 15.0,
                "auto_extract": True
            }
            self.save_config()
    
    def save_config(self):
        """Konfigürasyonu kaydet"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, ensure_ascii=False, indent=2)
    
    def _setup_callbacks(self):
        """Stream monitor için callback'leri ayarla"""
        self.monitor.register_callback("online", self._on_stream_online)
        self.monitor.register_callback("offline", self._on_stream_offline)
    
    def _on_stream_online(self, channel: str, info: StreamInfo):
        """Yayın başladığında çalışacak callback"""
        logger.info(f"🔴 Yayın başladı: {channel}")
        
        # Otomatik indir ve klip çıkart
        if self.config.get("auto_extract", True):
            self._process_stream(channel, info)
    
    def _on_stream_offline(self, channel: str, info: StreamInfo):
        """Yayın bittiğinde çalışacak callback"""
        logger.info(f"✗ Yayın bitti: {channel}")
    
    def _process_stream(self, channel: str, info: StreamInfo):
        """
        Stream'i indir ve klip'leri çıkart
        
        Args:
            channel: Kanal adı
            info: Yayın bilgileri
        """
        try:
            self.state = PipelineState.DOWNLOADING
            logger.info(f"Processing başlıyor: {channel}")
            
            # 1. Video'yu indir
            logger.info(f"Video indiriliyor: {info.url}")
            video_path = self.downloader.download_stream(
                info.url,
                channel
            )
            
            if not video_path:
                logger.error(f"Video indirme başarısız: {channel}")
                self.state = PipelineState.ERROR
                return
            
            logger.info(f"Video indirildi: {video_path}")
            
            # 2. Videoyu analiz et ve klip'leri tespit et
            self.state = PipelineState.CLIPPING
            logger.info(f"Video analizi başlıyor: {channel}")
            
            methods = [
                DetectionMethod.SCENE_CHANGE,
                DetectionMethod.MOTION
            ]
            
            clips = self.clipper.analyze_video(video_path, methods)
            logger.info(f"Tespit edilen klip: {len(clips)}")
            
            # 3. Klip'leri çıkart
            if clips:
                output_prefix = f"{channel}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                extracted_clips = self.clipper.batch_extract_clips(
                    video_path,
                    clips,
                    output_prefix
                )
                
                logger.info(f"Çıkartılan klip sayısı: {len(extracted_clips)}")
                self._save_processing_log(channel, video_path, clips, extracted_clips)
            
            self.state = PipelineState.MONITORING
            logger.info(f"Processing tamamlandı: {channel}")
            
        except Exception as e:
            logger.error(f"Processing hatası: {e}")
            self.state = PipelineState.ERROR
    
    def _save_processing_log(
        self,
        channel: str,
        video_path: str,
        clips: List,
        extracted_clips: List[str]
    ):
        """Processing log'unu kaydet"""
        log = {
            "timestamp": datetime.now().isoformat(),
            "channel": channel,
            "source_video": video_path,
            "detected_clips": len(clips),
            "extracted_clips": len(extracted_clips),
            "clip_files": extracted_clips,
            "details": [
                {
                    "start": clip.start_time,
                    "end": clip.end_time,
                    "duration": clip.end_time - clip.start_time,
                    "method": clip.method.value,
                    "confidence": clip.confidence
                }
                for clip in clips
            ]
        }
        
        log_file = Path(f"data/logs/{channel}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    
    def add_channel(self, channel: str, url: str):
        """
        Takip edilecek kanalı ekle
        
        Args:
            channel: Kanal adı
            url: Stream URL
        """
        self.monitor.add_stream(channel, url)
        logger.info(f"Kanal eklendi: {channel}")
    
    def start(self):
        """Pipeline'ı başlat"""
        logger.info("Pipeline başlatılıyor...")
        self.state = PipelineState.MONITORING
        self.monitor.start_monitoring()
        logger.info("✓ Pipeline aktif")
    
    def stop(self):
        """Pipeline'ı durdur"""
        logger.info("Pipeline durdurulıyor...")
        self.monitor.stop_monitoring()
        self.state = PipelineState.IDLE
        logger.info("✓ Pipeline durduruldu")
    
    def get_status(self) -> Dict:
        """Pipeline durumunu al"""
        return {
            "state": self.state.value,
            "timestamp": datetime.now().isoformat(),
            "monitor": self.monitor.get_status_report()
        }
    
    def save_status(self):
        """Durumu dosyaya kaydet"""
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.status_file, 'w', encoding='utf-8') as f:
            json.dump(self.get_status(), f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    pipeline = ClipsPipeline()
    
    # Örnek kullanım
    print("=== FAZE 2: Clips Pipeline ===")
    print("Pipeline modülü hazır")
    print("\nKullanım örneği:")
    print("  pipeline = ClipsPipeline()")
    print("  pipeline.add_channel('tuncay', 'https://twitch.tv/tuncay')")
    print("  pipeline.start()")
