# FAZE 2: Stream Takibi, İndirme ve Klip Çıkarma

## 📋 Genel Bakış

FAZE 2, Tuncay-klip projesinin çekirdeğini oluşturan otomatik klip çıkarma sistemidir. Bu faz, aşağıdaki temel işlevleri sağlar:

1. **Stream Monitoring** - Canlı yayınları gerçek zamanlı olarak takip etme
2. **Video Download** - Twitch/YouTube yayınlarını otomatik indirme
3. **Clip Detection** - Videodan önemli anları tespit etme
4. **Clip Extraction** - Klipleri otomatik çıkartma

---

## 🏗️ Mimarisi

```
┌─────────────────────────────────────────────────────┐
│          ClipsPipeline (Orchestrator)               │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  StreamMonitor                               │  │
│  │  - Kanal takibi                             │  │
│  │  - Status kontrolü (her 5 dakika)           │  │
│  │  - Event callback'ler                       │  │
│  └──────────────────────────────────────────────┘  │
│                     ↓                               │
│  ┌──────────────────────────────────────────────┐  │
│  │  StreamDownloader                            │  │
│  │  - HLS/DASH stream indirme                  │  │
│  │  - yt-dlp + FFmpeg kullanımı                │  │
│  │  - Metadata kayıt                           │  │
│  └──────────────────────────────────────────────┘  │
│                     ↓                               │
│  ┌──────────────────────────────────────────────┐  │
│  │  VideoClipper                                │  │
│  │  - Scene change detection                   │  │
│  │  - Motion detection                         │  │
│  │  - Klip segmentasyonu                       │  │
│  │  - FFmpeg ile klip çıkarma                  │  │
│  └──────────────────────────────────────────────┘  │
│                     ↓                               │
│  ┌──────────────────────────────────────────────┐  │
│  │  Output                                      │  │
│  │  📁 data/raw/           - İndirilmiş videolar  │  │
│  │  📁 data/processed/     - Çıkartılan kliplar  │  │
│  │  📁 data/logs/          - İşlem logları        │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

---

## 📦 Modüller

### 1. **pipeline.py** - Ana Orchestrator
Pipeline, tüm modülleri koordine eden ana bileşendir.

```python
from src.pipeline import ClipsPipeline

# Pipeline'ı oluştur
pipeline = ClipsPipeline()

# Kanal ekle
pipeline.add_channel("tuncay", "https://twitch.tv/tuncay")

# Yayın başladığında otomatik işlemler yapılacak
pipeline.start()
```

**Önemli Özellikler:**
- Modülleri birleştirme
- Callback yönetimi
- Konfigürasyon yönetimi
- Status tracking

---

### 2. **stream_monitor.py** - Yayın Takibi
Belirtilen kanalları izleyen ve yayın durumu değişikliklerini algılayan modül.

```python
from src.stream_monitor import StreamMonitor, StreamStatus

monitor = StreamMonitor(check_interval=300)  # 5 dakika

# Kanal ekle
monitor.add_stream("tuncay", "https://twitch.tv/tuncay")

# Callback kaydet
def on_online(channel, info):
    print(f"{channel} yayında!")

monitor.register_callback("online", on_online)

# Monitoring başlat
monitor.start_monitoring()
```

**Desteklenen Events:**
- `online` - Yayın başladığında
- `offline` - Yayın bittiğinde
- `ended` - Yayın sonlandırıldığında

---

### 3. **downloader.py** - Video İndirme
Twitch/YouTube yayınlarını HLS/DASH protocol ile indiren modül.

```python
from src.downloader import StreamDownloader

downloader = StreamDownloader(output_dir="data/raw")

# Yayını indir
video_path = downloader.download_stream(
    "https://twitch.tv/tuncay",
    "tuncay"
)

# Stream info al
info = downloader.get_stream_info("https://twitch.tv/tuncay")
```

**Bağımlılıklar:**
- `yt-dlp` - Video indirme
- `ffmpeg` - Format dönüştürme

---

### 4. **clipper.py** - Klip Çıkarma
Videodan klip segmentlerini tespit edip çıkaran modül.

```python
from src.clipper import VideoClipper, DetectionMethod

clipper = VideoClipper(output_dir="data/processed")

# Video'yu analiz et
clips = clipper.analyze_video(
    "data/raw/video.mp4",
    methods=[
        DetectionMethod.SCENE_CHANGE,
        DetectionMethod.MOTION
    ]
)

# Klipleri çıkart
extracted = clipper.batch_extract_clips(
    "data/raw/video.mp4",
    clips,
    output_prefix="tuncay_20260715"
)
```

**Deteksyon Yöntemleri:**
- `SCENE_CHANGE` - Ani sahne değişiklikleri (%30+ değişim)
- `MOTION` - Hareket analizi
- `AUDIO_SPIKE` - Ses pikleri (future)
- `FACE_DETECTION` - Yüz tanıma (future)

---

## 🔧 Konfigürasyon

`pipeline_config.json` dosyasında ayarlar tutulur:

```json
{
  "clip_detection_methods": ["scene_change", "motion"],
  "min_clip_duration": 3.0,
  "max_clip_duration": 60.0,
  "scene_change_threshold": 0.3,
  "motion_threshold": 15.0,
  "auto_extract": true
}
```

**Parameterler:**
- `min_clip_duration` - Minimum klip süresi (saniye)
- `max_clip_duration` - Maksimum klip süresi (saniye)
- `scene_change_threshold` - Scene change hassasiyeti (0-1)
- `motion_threshold` - Motion hassasiyeti (piksel farklılığı)
- `auto_extract` - Otomatik klip çıkarma

---

## 📊 Veri Akışı

### 1. Yayın Başladığında
```
StreamMonitor (online event)
        ↓
    Pipeline._on_stream_online()
        ↓
    StreamDownloader.download_stream()
        ↓
    video_path (data/raw/channel_20260715_143000.mp4)
```

### 2. Video Analizi
```
VideoClipper.analyze_video(video_path)
        ↓
  Detect Scene Changes  +  Detect Motion
        ↓                     ↓
   ClipSegment[]         ClipSegment[]
        ↓                     ↓
   Merge & Sort (by start_frame)
        ↓
   ClipSegment[] (final)
```

### 3. Klip Çıkarma
```
VideoClipper.batch_extract_clips()
        ↓
For each ClipSegment:
  FFmpeg: video.mp4 [start:end] → clip_001.mp4
        ↓
extracted_clips[] (output_dir/processed/)
        ↓
Metadata & Logs (output_dir/logs/)
```

---

## 🔌 API Referansı

### ClipsPipeline

```python
class ClipsPipeline:
    def __init__(self)
    def add_channel(self, channel: str, url: str)
    def start(self)
    def stop(self)
    def get_status(self) -> Dict
    def save_status(self)
    def load_config(self)
    def save_config(self)
```

### StreamMonitor

```python
class StreamMonitor:
    def __init__(self, check_interval: int = 300)
    def add_stream(self, channel: str, url: str) -> StreamInfo
    def remove_stream(self, channel: str) -> bool
    def register_callback(self, event: str, callback: Callable)
    def start_monitoring(self)
    def stop_monitoring(self)
    def get_all_streams(self) -> Dict[str, StreamInfo]
    def get_online_streams(self) -> List[str]
    def get_status_report(self) -> Dict
```

### StreamDownloader

```python
class StreamDownloader:
    def __init__(self, output_dir: str = "data/raw")
    def download_stream(self, stream_url: str, channel_name: str, 
                       duration: Optional[int] = None) -> Optional[str]
    def download_hls_stream(self, m3u8_url: str, channel_name: str,
                           segment_timeout: int = 3600) -> Optional[str]
    def check_stream_online(self, stream_url: str) -> bool
    def get_stream_info(self, stream_url: str) -> Optional[Dict]
```

### VideoClipper

```python
class VideoClipper:
    def __init__(self, output_dir: str = "data/processed")
    def analyze_video(self, video_path: str,
                     methods: Optional[List[DetectionMethod]] = None) -> List[ClipSegment]
    def detect_scene_changes(self, video_path: str, threshold: float = 0.3,
                            sample_rate: int = 10) -> List[ClipSegment]
    def detect_motion(self, video_path: str, threshold: float = 15.0,
                     min_duration: float = 1.0) -> List[ClipSegment]
    def extract_clip(self, video_path: str, output_path: str,
                    start_time: float, end_time: float,
                    quality: str = "720p") -> bool
    def batch_extract_clips(self, video_path: str,
                           segments: List[ClipSegment],
                           output_prefix: str) -> List[str]
```

---

## 🧪 Test Etme

```bash
# Tüm testleri çalıştır
python tests/test_phase2.py

# Spesifik test çalıştır
python -m pytest tests/test_phase2.py::TestStreamMonitor -v

# Örnekleri çalıştır
python examples/phase2_examples.py
```

---

## 📈 Performans Notları

**Video Analizi Zamanı:**
- 1 saat video: ~2-3 dakika (scene + motion)
- Scene change detection: ~0.5x speed (pause, replay hızı)
- Motion detection: ~1x speed

**Depolama:**
- 1 saat HD video: ~500MB-1GB
- 1 dakikalık klip: ~50-100MB (720p)
- Metadata: ~100KB per video

**Öneriler:**
- Videos için SSD kullan
- Streaming buffer'ı ayarla: `check_interval=300`
- Paralel processing için multiprocessing kullan (future)

---

## 🐛 Hata Ayıklama

### Common Issues

**1. FFmpeg hatası:**
```bash
# FFmpeg'i kur
sudo apt-get install ffmpeg  # Linux
brew install ffmpeg          # macOS
choco install ffmpeg         # Windows
```

**2. yt-dlp hatası:**
```bash
pip install --upgrade yt-dlp
```

**3. Video bulunamadı:**
```python
# Log'u kontrol et
pipeline.save_status()  # Status dosyasını kaydet
# Ardından data/pipeline_status.json'u kontrol et
```

---

## 📝 Sonraki Adımlar (FAZE 3)

FAZE 2 tamamlandıktan sonra, FAZE 3'te şunlar yapılacak:

- Otomatik YouTube Shorts yükleme
- Otomatik TikTok yükleme  
- Otomatik Instagram Reels yükleme
- AI-generated başlıklar ve hashtag'ler
- Analytics dashboard

---

## 📚 İlgili Belgeler

- [FAZE 1: Proje Altyapısı](../docs/PHASE1.md)
- [FAZE 3: Otomatik Yayınlama](../docs/PHASE3.md)
- [Konfigürasyon Rehberi](../docs/CONFIG.md)
- [API Referansı](./API_REFERENCE.md)

