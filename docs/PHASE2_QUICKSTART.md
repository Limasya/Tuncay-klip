# FAZE 2: Hızlı Başlangıç Rehberi

## ⚡ 5 Dakikada Başla

### Adım 1: Temel Kurulum
```bash
# Gerekli kütüphaneleri kur
pip install opencv-python numpy

# FFmpeg kur
sudo apt-get install ffmpeg  # Linux
brew install ffmpeg          # macOS

# yt-dlp kur
pip install yt-dlp
```

### Adım 2: Pipeline'ı Oluştur
```python
from src.pipeline import ClipsPipeline

# Pipeline'ı başlat
pipeline = ClipsPipeline()
print("✓ Pipeline hazır")
```

### Adım 3: Kanal Ekle
```python
# Takip edilecek kanalı ekle
pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
print("✓ Kanal eklendi")
```

### Adım 4: Callback Ekle
```python
def on_stream_online(channel, info):
    print(f"🔴 Yayında: {channel}")

pipeline.monitor.register_callback("online", on_stream_online)
print("✓ Callback kaydedildi")
```

### Adım 5: Başlat
```python
pipeline.start()
print("✓ Pipeline çalışıyor - Yayınları takip ediyor...")
```

---

## 🎯 Yaygın Kullanım Durumları

### Kullanım Durumu 1: Tek Kanal Takibi
```python
from src.pipeline import ClipsPipeline

pipeline = ClipsPipeline()

# Tuncay'ı takip et
pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")

# Yayın başladığında otomatik işlemler yapılacak
pipeline.start()

# Durumu kontrol et
while True:
    status = pipeline.get_status()
    print(f"Online: {status['monitor']['online']}")
    time.sleep(60)
```

### Kullanım Durumu 2: Birden Fazla Kanal
```python
from src.pipeline import ClipsPipeline

pipeline = ClipsPipeline()

# Birden fazla kanal ekle
channels = {
    "tuncay": "https://twitch.tv/tuncay",
    "channel2": "https://twitch.tv/channel2",
    "channel3": "https://twitch.tv/channel3"
}

for name, url in channels.items():
    pipeline.add_channel(name, url)

pipeline.start()
```

### Kullanım Durumu 3: Özel Klip Ayarları
```python
from src.pipeline import ClipsPipeline
from src.clipper import DetectionMethod

pipeline = ClipsPipeline()

# Klip ayarlarını özelleştir
pipeline.config.update({
    "min_clip_duration": 5.0,      # Minimum 5 saniye
    "max_clip_duration": 120.0,    # Maksimum 2 dakika
    "scene_change_threshold": 0.25, # Daha hassas
    "motion_threshold": 10.0        # Daha az hareket
})
pipeline.save_config()

pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
pipeline.start()
```

### Kullanım Durumu 4: Sadece Analiz (İndir + Klip)
```python
from src.downloader import StreamDownloader
from src.clipper import VideoClipper, DetectionMethod

# Video'yu indir
downloader = StreamDownloader()
video_path = downloader.download_stream(
    "https://twitch.tv/tuncay",
    "tuncay"
)

# Klipleri analiz et
clipper = VideoClipper()
clips = clipper.analyze_video(
    video_path,
    methods=[
        DetectionMethod.SCENE_CHANGE,
        DetectionMethod.MOTION
    ]
)

# Klipleri çıkart
extracted = clipper.batch_extract_clips(
    video_path,
    clips,
    "tuncay_clips"
)

print(f"{len(extracted)} klip çıkartıldı")
```

### Kullanım Durumu 5: Custom Event Handling
```python
from src.pipeline import ClipsPipeline
import datetime

pipeline = ClipsPipeline()

def on_online(channel, info):
    print(f"\n{'='*50}")
    print(f"🔴 {channel.upper()} YAYINDA!")
    print(f"{'='*50}")
    print(f"Başlangıç: {datetime.datetime.now()}")
    print(f"İndirme ve klip çıkarma başlıyor...")

def on_offline(channel, info):
    print(f"✗ {channel} yayını bitti")

def on_ended(channel, info):
    print(f"⊘ {channel} yayını sonlandırıldı")

pipeline.monitor.register_callback("online", on_online)
pipeline.monitor.register_callback("offline", on_offline)
pipeline.monitor.register_callback("ended", on_ended)

pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
pipeline.start()
```

---

## 🔍 Veri Dosyaları

### Dosya Yapısı
```
project/
├── data/
│   ├── raw/                 # İndirilmiş videolar
│   │   ├── tuncay_20260715_143000.mp4
│   │   └── downloads.json   # İndirme metadatası
│   │
│   ├── processed/           # Çıkartılan kliplar
│   │   ├── tuncay_20260715_143000_clip_001.mp4
│   │   ├── tuncay_20260715_143000_clip_002.mp4
│   │   └── clips.json       # Klip metadatası
│   │
│   └── logs/                # İşlem logları
│       └── tuncay_20260715_143000.json
│
├── pipeline_config.json     # Pipeline konfigürasyonu
└── pipeline_status.json     # Pipeline durumu
```

### downloads.json Yapısı
```json
[
  {
    "filename": "tuncay_20260715_143000.mp4",
    "url": "https://twitch.tv/tuncay",
    "channel": "tuncay",
    "download_time": "20260715_143000",
    "file_path": "/path/to/data/raw/tuncay_20260715_143000.mp4"
  }
]
```

### clips.json Yapısı
```json
[
  {
    "source": "/path/to/data/raw/tuncay_20260715_143000.mp4",
    "clip_path": "/path/to/data/processed/tuncay_20260715_143000_clip_001.mp4",
    "start_time": 45.3,
    "end_time": 78.9,
    "duration": 33.6,
    "quality": "720p"
  }
]
```

### Processing Log Yapısı
```json
{
  "timestamp": "2026-07-15T14:30:00",
  "channel": "tuncay",
  "source_video": "/path/to/data/raw/tuncay_20260715_143000.mp4",
  "detected_clips": 5,
  "extracted_clips": 5,
  "clip_files": [
    "/path/to/data/processed/tuncay_20260715_143000_clip_001.mp4",
    "/path/to/data/processed/tuncay_20260715_143000_clip_002.mp4"
  ],
  "details": [
    {
      "start": 45.3,
      "end": 78.9,
      "duration": 33.6,
      "method": "scene_change",
      "confidence": 0.85
    }
  ]
}
```

---

## 🚀 Önemli Bilgiler

### Monitoring Döngüsü
```
StreamMonitor._monitor_loop() çalışır
    ↓
Her 5 dakikada (check_interval)
    ↓
Her kanal için check_stream_status() çağrı
    ↓
Durum değişimi algılanırsa callback çağrı
    ↓
Pipeline._on_stream_online() (yayın başladıysa)
    ↓
_process_stream() → İndir → Analiz → Klip Çıkar
```

### Thread Model
- **Main thread**: Pipeline kontrol ve CLI
- **Monitor thread**: Stream status kontrolü (arka planda)
- **Worker threads**: Video işleme (FFmpeg alt işlem)

### Performans İpuçları

1. **Video işleme hızı:**
   - Scene change detection: 0.5x normal hız
   - Motion detection: 1x normal hız
   - Ikisi birden: 1-1.5x normal hız

2. **CPU Kullanımı:**
   ```
   Video analizi sırasında: ~60-80% single core
   Standby sırasında: <1%
   ```

3. **Disk Alanı:**
   ```
   1 saat 1080p video: ~1.5GB
   Processed klip (1 dakika): ~50-100MB
   ```

### Resource Yönetimi
```python
# Video analizi tamamlandığında dosyayı sil (opsiyonel)
import os
os.remove(video_path)

# Metadata'yı düzenli olarak temizle
# data/logs/ eski logları saklamak istersen:
import shutil
shutil.rmtree("data/logs", ignore_errors=True)
```

---

## 🆘 Sorun Giderme

### Sorun: "FFmpeg komutu bulunamadı"
**Çözüm:**
```bash
# FFmpeg'i kur
sudo apt-get install ffmpeg  # Debian/Ubuntu
brew install ffmpeg          # macOS
choco install ffmpeg         # Windows (chocolatey)

# Kontrol et
ffmpeg -version
```

### Sorun: "yt-dlp hatası: 403 Forbidden"
**Çözüm:**
```bash
# yt-dlp'yi güncelle
pip install --upgrade yt-dlp

# Proxy kullan (gerekirse)
yt-dlp --proxy "socks5://127.0.0.1:1080" <URL>
```

### Sorun: "Video indirme başarısız"
**Debug:**
```python
from src.downloader import StreamDownloader

downloader = StreamDownloader()

# URL geçerli mi kontrol et
is_online = downloader.check_stream_online("https://twitch.tv/tuncay")
print(f"Stream online: {is_online}")

# Stream info al
info = downloader.get_stream_info("https://twitch.tv/tuncay")
print(f"Stream info: {info}")
```

### Sorun: "Klip deteksyon çalışmıyor"
**Çözüm:**
```python
# Eşikleri ayarla
pipeline.config['scene_change_threshold'] = 0.2  # Daha hassas
pipeline.config['motion_threshold'] = 10.0       # Daha düşük
pipeline.save_config()

# Her iki yöntemi de kullan
pipeline.config['clip_detection_methods'] = ["scene_change", "motion"]
```

### Sorun: "Memory hatası"
**Çözüm:**
```bash
# Daha az bellek kullanan ayarlar
# video'yu parçalara böl:
split_size_mb = 500  # 500MB parçalar

# Config'te:
pipeline.config['max_video_size'] = split_size_mb * 1024 * 1024
```

---

## 📊 Monitoring Dashboard (Örnek)

```python
import time
from src.pipeline import ClipsPipeline

def dashboard():
    pipeline = ClipsPipeline()
    pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")
    pipeline.start()
    
    try:
        while True:
            status = pipeline.get_status()
            print("\n" + "="*60)
            print(f"Pipeline Status: {status['state'].upper()}")
            print(f"Timestamp: {status['timestamp']}")
            print("-"*60)
            
            monitor_status = status['monitor']
            print(f"Total Channels: {monitor_status['total']}")
            print(f"Online: {monitor_status['online']}")
            print(f"Offline: {monitor_status['offline']}")
            
            for channel, info in monitor_status['streams'].items():
                status_emoji = "🔴" if info['status'] == 'online' else "⚫"
                print(f"  {status_emoji} {channel}: {info['status']}")
            
            time.sleep(60)
    except KeyboardInterrupt:
        pipeline.stop()
        print("\nPipeline durduruldu")

if __name__ == "__main__":
    dashboard()
```

---

## 📚 Daha Fazla Bilgi

- **API Referansı**: [docs/PHASE2.md](./PHASE2.md)
- **Konfigürasyon Detayları**: [docs/CONFIG.md](./CONFIG.md)
- **Sorun Giderme**: [docs/TROUBLESHOOTING.md](./TROUBLESHOOTING.md)
- **Örnekler**: [examples/phase2_examples.py](../examples/phase2_examples.py)

