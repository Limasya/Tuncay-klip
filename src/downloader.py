"""
Video İndirme Modülü
Twitch/YouTube canlı yayınları indirmek için
"""

import os
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StreamDownloader:
    """Canlı yayın indirme işlemleri"""
    
    def __init__(self, output_dir: str = "data/raw"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_file = self.output_dir / "downloads.json"
        self.load_metadata()
    
    def load_metadata(self):
        """İndirilen videoların metadatasını yükle"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        else:
            self.metadata = []
    
    def save_metadata(self):
        """Metadata'yı dosyaya kaydet"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, ensure_ascii=False, indent=2)
    
    def check_stream_online(self, stream_url: str) -> bool:
        """
        Yayının aktif olup olmadığını kontrol et
        
        Args:
            stream_url: Twitch/YouTube URL
            
        Returns:
            bool: Yayın aktifse True
        """
        try:
            # yt-dlp ile yayın kontrolü
            result = subprocess.run(
                ["yt-dlp", "--check-formats", stream_url],
                capture_output=True,
                timeout=10,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Stream kontrol hatası: {e}")
            return False
    
    def download_stream(
        self, 
        stream_url: str, 
        channel_name: str,
        duration: Optional[int] = None
    ) -> Optional[str]:
        """
        Canlı yayını indir
        
        Args:
            stream_url: Twitch/YouTube stream URL
            channel_name: Kanal adı (dosya adı için)
            duration: Maksimum indirme süresi (saniye)
            
        Returns:
            str: İndirilen dosyanın yolu
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{channel_name}_{timestamp}.mp4"
            output_path = self.output_dir / filename
            
            logger.info(f"İndirme başlıyor: {stream_url}")
            logger.info(f"Hedef: {output_path}")
            
            # yt-dlp komutu
            cmd = [
                "yt-dlp",
                "-f", "best[height<=720]",  # 720p en iyi format
                "-o", str(output_path),
                stream_url
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logger.info(f"İndirme tamamlandı: {filename}")
                
                # Metadata'ya kaydet
                meta = {
                    "filename": filename,
                    "url": stream_url,
                    "channel": channel_name,
                    "download_time": timestamp,
                    "file_path": str(output_path)
                }
                self.metadata.append(meta)
                self.save_metadata()
                
                return str(output_path)
            else:
                logger.error(f"İndirme hatası: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("İndirme zaman aşımına uğradı")
            return None
        except Exception as e:
            logger.error(f"Beklenmeyen hata: {e}")
            return None
    
    def download_hls_stream(
        self,
        m3u8_url: str,
        channel_name: str,
        segment_timeout: int = 3600
    ) -> Optional[str]:
        """
        HLS stream'i segment bazında indir
        
        Args:
            m3u8_url: HLS playlist URL
            channel_name: Kanal adı
            segment_timeout: Segment indirme zaman aşımı (saniye)
            
        Returns:
            str: Tampon dosya yolu
        """
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{channel_name}_hls_{timestamp}.mp4"
            output_path = self.output_dir / filename
            
            cmd = [
                "ffmpeg",
                "-i", m3u8_url,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                str(output_path)
            ]
            
            logger.info(f"HLS indirme başlıyor: {filename}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=segment_timeout)
            
            if result.returncode == 0:
                logger.info(f"HLS indirme tamamlandı: {filename}")
                return str(output_path)
            else:
                logger.error(f"HLS hatası: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.error("HLS indirme zaman aşımına uğradı")
            return None
        except Exception as e:
            logger.error(f"HLS hatası: {e}")
            return None
    
    def get_stream_info(self, stream_url: str) -> Optional[Dict]:
        """
        Yayın bilgilerini al (süre, çözünürlük vb.)
        
        Args:
            stream_url: Stream URL
            
        Returns:
            dict: Yayın metadatası
        """
        try:
            result = subprocess.run(
                [
                    "yt-dlp",
                    "-j",
                    "--no-warnings",
                    stream_url
                ],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                return json.loads(result.stdout)
            return None
            
        except Exception as e:
            logger.error(f"Info alma hatası: {e}")
            return None


if __name__ == "__main__":
    # Test
    downloader = StreamDownloader()
    print("Downloader modülü hazır")
