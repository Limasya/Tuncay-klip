"""
Stream Takibi Modülü
Belirtilen kanalları izleyip yayın başlangıcını algılama
"""

import time
import logging
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Callable, Optional
import threading
from dataclasses import dataclass, asdict
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StreamStatus(Enum):
    """Yayın durumu"""
    OFFLINE = "offline"
    ONLINE = "online"
    ENDED = "ended"
    UNKNOWN = "unknown"


@dataclass
class StreamInfo:
    """Yayın bilgileri"""
    channel: str
    url: str
    status: StreamStatus
    started_at: Optional[str] = None
    title: Optional[str] = None
    game: Optional[str] = None
    viewers: Optional[int] = None
    quality: Optional[str] = None


class StreamMonitor:
    """Canlı yayın takibi"""
    
    def __init__(self, check_interval: int = 300):
        """
        Args:
            check_interval: Kontrol aralığı (saniye), default 5 dakika
        """
        self.check_interval = check_interval
        self.streams: Dict[str, StreamInfo] = {}
        self.callbacks: Dict[str, List[Callable]] = {
            "online": [],
            "offline": [],
            "ended": []
        }
        self.is_running = False
        self.monitor_thread = None
        self.config_file = Path("data/streams.json")
        self.load_streams()
    
    def load_streams(self):
        """Takip edilen stream'leri yükle"""
        if self.config_file.exists():
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for stream_data in data:
                    stream = StreamInfo(
                        channel=stream_data['channel'],
                        url=stream_data['url'],
                        status=StreamStatus.OFFLINE
                    )
                    self.streams[stream_data['channel']] = stream
        else:
            logger.info("Stream config dosyası bulunamadı")
    
    def save_streams(self):
        """Stream listesini kaydet"""
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                'channel': channel,
                'url': info.url
            }
            for channel, info in self.streams.items()
        ]
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def add_stream(self, channel: str, url: str) -> StreamInfo:
        """
        Yayını takip listesine ekle
        
        Args:
            channel: Kanal adı
            url: Stream URL
            
        Returns:
            StreamInfo: Eklenen yayın bilgileri
        """
        stream = StreamInfo(
            channel=channel,
            url=url,
            status=StreamStatus.OFFLINE
        )
        self.streams[channel] = stream
        self.save_streams()
        logger.info(f"Stream eklendi: {channel}")
        return stream
    
    def remove_stream(self, channel: str) -> bool:
        """Yayını listeden çıkar"""
        if channel in self.streams:
            del self.streams[channel]
            self.save_streams()
            logger.info(f"Stream kaldırıldı: {channel}")
            return True
        return False
    
    def register_callback(self, event: str, callback: Callable):
        """
        Olay için callback kaydet
        
        Args:
            event: 'online', 'offline', 'ended'
            callback: Çalıştırılacak fonksiyon
        """
        if event in self.callbacks:
            self.callbacks[event].append(callback)
            logger.info(f"Callback kaydedildi: {event}")
    
    def check_stream_status(self, channel: str) -> StreamStatus:
        """
        Stream durumunu kontrol et (implementation örneği)
        
        Args:
            channel: Kanal adı
            
        Returns:
            StreamStatus: Yayının durumu
        """
        try:
            stream_info = self.streams.get(channel)
            if not stream_info:
                return StreamStatus.UNKNOWN
            
            # Twitch API ile kontrol (örnek)
            # Gerçek implementasyon için Twitch API key gerekli
            
            # Bu kısım config.py içindeki API key'lerle doldurulacak
            logger.debug(f"Status kontrol: {channel}")
            return StreamStatus.UNKNOWN
            
        except Exception as e:
            logger.error(f"Status kontrol hatası ({channel}): {e}")
            return StreamStatus.UNKNOWN
    
    def update_stream_status(self, channel: str, new_status: StreamStatus, info: Optional[Dict] = None):
        """Stream durumunu güncelle ve callback'leri çağır"""
        if channel not in self.streams:
            return
        
        old_status = self.streams[channel].status
        self.streams[channel].status = new_status
        
        if info:
            if 'title' in info:
                self.streams[channel].title = info['title']
            if 'game' in info:
                self.streams[channel].game = info['game']
            if 'viewers' in info:
                self.streams[channel].viewers = info['viewers']
            if 'started_at' in info:
                self.streams[channel].started_at = info['started_at']
        
        # Status değişimi durumunda callback'leri çağır
        if old_status != new_status:
            if new_status == StreamStatus.ONLINE:
                logger.info(f"✓ ONLINE: {channel}")
                self._trigger_callbacks("online", channel)
            elif new_status == StreamStatus.OFFLINE:
                logger.info(f"✗ OFFLINE: {channel}")
                self._trigger_callbacks("offline", channel)
            elif new_status == StreamStatus.ENDED:
                logger.info(f"⊘ ENDED: {channel}")
                self._trigger_callbacks("ended", channel)
    
    def _trigger_callbacks(self, event: str, channel: str):
        """Belirtilen event için tüm callback'leri çalıştır"""
        for callback in self.callbacks.get(event, []):
            try:
                callback(channel, self.streams[channel])
            except Exception as e:
                logger.error(f"Callback hatası: {e}")
    
    def start_monitoring(self):
        """Yayın takibini başlat"""
        if self.is_running:
            logger.warning("Monitor zaten çalışıyor")
            return
        
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Stream monitoring başladı")
    
    def stop_monitoring(self):
        """Yayın takibini durdur"""
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("Stream monitoring durduruldu")
    
    def _monitor_loop(self):
        """Ana takip döngüsü"""
        while self.is_running:
            try:
                for channel in list(self.streams.keys()):
                    status = self.check_stream_status(channel)
                    self.update_stream_status(channel, status)
                
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.error(f"Monitor loop hatası: {e}")
                time.sleep(self.check_interval)
    
    def get_all_streams(self) -> Dict[str, StreamInfo]:
        """Tüm stream'leri al"""
        return self.streams.copy()
    
    def get_online_streams(self) -> List[str]:
        """Şu anda yayında olan kanalları al"""
        return [
            channel for channel, info in self.streams.items()
            if info.status == StreamStatus.ONLINE
        ]
    
    def get_status_report(self) -> Dict:
        """Durumu rapor et"""
        return {
            "total": len(self.streams),
            "online": len(self.get_online_streams()),
            "offline": len([c for c, i in self.streams.items() if i.status == StreamStatus.OFFLINE]),
            "streams": {
                channel: {
                    "status": info.status.value,
                    "title": info.title,
                    "viewers": info.viewers
                }
                for channel, info in self.streams.items()
            }
        }


if __name__ == "__main__":
    # Test
    monitor = StreamMonitor()
    
    # Test callback
    def on_stream_online(channel: str, info: StreamInfo):
        print(f"🔴 YAYINDA: {channel} - {info.title}")
    
    monitor.register_callback("online", on_stream_online)
    print("Monitor modülü hazır")
