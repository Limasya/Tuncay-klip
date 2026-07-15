# Otomatik Klip Yakalama ve Duygu-Hareket Analizi Sistemi

Tek bir yayinci icin canli yayinlardan otomatik klip yakalama, gercek zamanli duygu/hareket analizi, altyazi olusturma ve sosyal medya yayinlama sistemi.

## Ozellikler

- **Gercek Zamanli Analiz**: Yuz/duygu tespiti (CNN/ViT), hareket analizi (Optical Flow + MediaPipe Pose), ses enerjisi analizi
- **Otomatik Klip Yakalama**: Ring buffer ile surekli kayit, olay tespit edildiginde otomatik klip olusturma
- **Coklu Platform Destegi**: Kick, Twitch, YouTube'dan canli yayin/VOD indirme (yt-dlp)
- **AI Baslik/Hashtag**: Otomatik baslik, aciklama ve platform-optimze hashtag uretimi
- **Altyazi**: OpenAI Whisper ile otomatik Turkce/Ingilizce altyazi
- **Coklu Format**: MP4, MOV, MKV, WebM, AVI, WMV cikti destegi
- **Aspect Ratio**: 16:9, 9:16 (TikTok/Reels), 1:1 (Instagram), 4:5
- **Otomatik Yayinlama**: YouTube, TikTok, Instagram, Twitter'a yukleme
- **Web Paneli**: Gercek zamanli durum izleme, klip yonetimi, tercihler
- **Docker**: Tek komutla calistirma

## Hizli Baslangic

### Yerel Kurulum

```bash
# 1. Bagimliliklari yukle
python -m pip install -r requirements.txt

# 2. Ortam degiskenlerini ayarla
cp .env.example .env
# .env dosyasini duzenle (Kick API bilgileri vb.)

# 3. Web sunucusunu baslat
python main.py
# Tarayicida ac: http://localhost:8000
```

### Docker ile Kurulum

```bash
# Her sey dahil baslat
docker-compose up --build

# Arka planda calistir
docker-compose up -d
```

### CLI Kullanimi

```bash
# Yayin bilgisi gor
python src/main.py info "https://kick.com/kanal_adi"

# Canli yayin kaydet (60 saniye)
python src/main.py download "https://kick.com/kanal_adi" --live --duration 60

# VOD indir
python src/main.py download "https://youtube.com/watch?v=..." --quality 720p

# Enerji bazli klip cikar
python src/main.py extract video.mp4 --method energy --top 5

# Sahne degisikligi bazli klip cikar
python src/main.py extract video.mp4 --method scene

# AI baslik/hashtag olustur
python src/main.py generate --category funny --streamer "Tuncay" --platform tiktok

# Klip yayinla
python src/main.py publish klip.mp4 --platform youtube --privacy private
```

## API Kullanimi

### Sistem Kontrolu

```bash
# Durum
GET /api/system/status

# Baslat
POST /api/system/start

# Durdur
POST /api/system/stop
```

### Klip Yonetimi

```bash
# Klipleri listele
GET /api/clips/?page=1&page_size=20&category=exciting

# Klip detayi
GET /api/clips/{id}

# Manuel klip olustur
POST /api/clips/

# Dosya yukle
POST /api/clips/{id}/upload

# Favori ekle/kaldir
PATCH /api/clips/{id}/favorite

# Disa aktar (9:16, MP4)
POST /api/clips/{id}/export?resolution=portrait&format=mp4

# Sil
DELETE /api/clips/{id}
```

### Tercihler

```bash
# Tercihleri getir
GET /api/preferences/

# Tercihleri guncelle
PUT /api/preferences/
{
    "emotion_sensitivity": 0.7,
    "auto_subtitle": true,
    "export_format": "mp4",
    "export_resolution": "1080p"
}
```

## Proje Yapisi

```
Tuncay-klip/
├── main.py                     # FastAPI web sunucusu
├── config.py                   # Merkezi yapilandirma
├── requirements.txt            # Python bagimliliklari
├── Dockerfile                  # Docker container
├── docker-compose.yml          # Multi-service orkestrasyon
│
├── src/                        # Temel is mantigi modulleri
│   ├── main.py                 # CLI giris noktasi
│   ├── downloader.py           # yt-dlp ile video indirme
│   ├── clipper.py              # Otomatik klip cikarici
│   ├── uploader.py             # Sosyal medya yayinlama
│   ├── ai_generator.py         # AI baslik/hashtag uretici
│   └── utils.py                # Yardimci fonksiyonlar
│
├── services/                   # Mikroservisler
│   ├── kick_api.py             # Kick API entegrasyonu
│   ├── stream_capture.py       # FFmpeg HLS yakalama + ring buffer
│   ├── clip_service.py         # CLIP siniflandirma + S3
│   ├── subtitle_service.py     # Whisper altyazi
│   ├── video_editor.py         # FFmpeg video duzenleme
│   ├── chat_sentiment.py       # Chat duygu analizi
│   ├── orchestrator.py         # Ana orkestrator
│   ├── database.py             # DB baglantisi
│   └── analysis/
│       ├── face_emotion.py     # Yuz/duygu analizi
│       ├── motion_detection.py # Hareket/poz analizi
│       ├── audio_analysis.py   # Ses analizi
│       └── pipeline.py         # Birlesik analiz
│
├── api/routers/                # FastAPI endpoint'leri
│   ├── clips.py                # Klip CRUD
│   ├── system.py               # Sistem kontrolu
│   └── preferences.py          # Tercihler
│
├── models/
│   ├── database.py             # SQLAlchemy ORM
│   └── schemas.py              # Pydantic semaları
│
├── templates/
│   └── dashboard.html          # Web kontrol paneli
│
├── tests/                      # Testler
│   └── test_*.py
│
└── data/
    ├── raw/                    # Ham indirilen videolar
    ├── processed/              # Islenmis dosyalar
    ├── clips/                  # Olusturulan klipler
    ├── buffer/                 # Ring buffer gecici
    ├── subtitles/              # Altyazi dosyalari
    └── exports/                # Disa aktarilan videolar
```

## Desteklenen Formatlar

| Format | Uzanti | Aciklama |
|--------|--------|----------|
| MP4 | .mp4 | Evrensel uyumluluk - YouTube, Instagram, TikTok |
| MOV | .mov | Apple QuickTime - yuksek kalite, edit yazilimlari |
| MKV | .mkv | Matroska - coklu ses/altyazi, acik kaynak |
| WebM | .webm | Google - HTML5, web optimizasyonu |
| AVI | .avi | Microsoft - yuksek kalite, buyuk dosya |
| WMV | .wmv | Windows Media - kucuk boyut, online akis |

## Aspect Ratio'lar

| Ratio | Cozunurluk | Kullanim |
|-------|------------|----------|
| 16:9 | 1920x1080 | YouTube, Twitch |
| 9:16 | 1080x1920 | TikTok, Reels, Shorts |
| 1:1 | 1080x1080 | Instagram post |
| 4:5 | 1080x1350 | Instagram feed |

## Ortam Degiskenleri (.env)

```bash
# Kick API
KICK_CLIENT_ID=...
KICK_CLIENT_SECRET=...
KICK_BROADCASTER_USER_ID=...
KICK_CHANNEL_SLUG=...

# Stream ayarlari
STREAM_BUFFER_SECONDS=30
CLIP_PRE_SECONDS=5
CLIP_POST_SECONDS=5
ANALYSIS_FPS=2

# Duygu esikleri
EMOTION_THRESHOLD=0.7
EXCITEMENT_THRESHOLD=0.8

# AWS S3 (opsiyonel)
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
S3_BUCKET_NAME=...
```

## Testler

```bash
# Tum testleri calistir
python -m pytest tests/ -v

# Belirli test
python -m pytest tests/test_ai_generator.py -v
```

## Teknolojiler

- **Backend**: FastAPI, SQLAlchemy, Celery
- **Video**: FFmpeg, OpenCV
- **AI/ML**: PyTorch, Transformers, Whisper
- **Indirme**: yt-dlp
- **Depolama**: SQLite/PostgreSQL, AWS S3
- **Altyazi**: OpenAI Whisper
- **Container**: Docker, docker-compose

## Lisans

Bu proje kisisel kullanim icin gelistirilmistir.
