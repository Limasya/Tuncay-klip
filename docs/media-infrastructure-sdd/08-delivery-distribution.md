# 08 - Teslimat ve Dagitim Sistemi (Delivery & Distribution)

## Icindekiler

1. [Disa Aktarma Profilleri](#1-disa-aktarma-profilleri)
2. [Bulut Depolama](#2-bulut-depolama)
3. [CDN Entegrasyonu](#3-cdn-entegrasyonu)
4. [Onizleme Uretici](#4-onizleme-uretici)
5. [Kucuk Resim Uretici](#5-kucuk-resim-uretici)
6. [Proxy Medya](#6-proxy-medya)
7. [Artimli Rendering](#7-artimli-rendering)
8. [Arka Plan Rendering](#8-arka-plan-rendering)

---

## 1. Disa Aktarma Profilleri

### 1.1 Amaç

Disa aktarma profilleri, projenin farkli platformlara uyumlu bicimde disa aktarilmasini saglayan yapi katmanidir. Her platformun kendine ozgu video boyutu, sure siniri, codec tercihi ve bitrate gereksinimleri bulunmaktadir. Bu sistem, kullanicinin tek bir tiklama ile icerigini birden fazla platforma es zamanli olarak disa aktarmasini saglar.

### 1.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|                  Export Manager                            |
|                                                           |
|  +----------+    +--------------+    +---------------+     |
|  | Proje    |--->| Kodlama      |--->| Platform      |     |
|  | Kaynagi  |    | Motoru       |    | Yukleyici     |     |
|  +----------+    +--------------+    +---------------+     |
|       |                |                     |             |
|       v                v                     v             |
|  +----------+    +--------------+    +---------------+     |
|  | Export   |    | Bitrate      |    | API           |     |
|  | Profili  |    | Merdiveni    |    | Entegrasyonu  |     |
|  +----------+    +------------+    +---------------+     |
+-----------------------------------------------------------+
```

### 1.3 Platform Profilleri

Her platform icin tanimli varsayilan profiller:

| Platform | Boyut | Maks. Sure | Varsayilan Codec | Maks. Dosya | Kare Hizi |
|---|---|---|---|---|---|
| TikTok | 1080x1920 | 60 sn | H.264 High Profile | 287 MB | 30/60 fps |
| YouTube Shorts | 1080x1920 | 60 sn | H.264 High Profile | 256 MB | 30/60 fps |
| Instagram Reels | 1080x1920 | 90 sn | H.264 Main Profile | 250 MB | 30 fps |
| Instagram Feed | 1080x1080 | 60 sn | H.264 Main Profile | 250 MB | 30 fps |
| Twitter/X | 1280x720 | 140 sn (video) | H.264 Baseline | 512 MB | 30/60 fps |
| Kick Clip | 1920x1080 | 60 sn | H.264 High Profile | 500 MB | 30/60 fps |

### 1.4 Codec Profilleri

Her platform icin desteklenen codec ve ayarlari:

| Codec | Profil | Seviye | Paketleme | Kullanim Senaryosu |
|---|---|---|---|---|
| H.264 | Baseline | 3.1 | MP4 | Dusuk gecikme, genis uyumluluk |
| H.264 | Main | 4.0 | MP4 | Orta kalite, genis cihaz destegi |
| H.264 | High | 5.1 | MP4 | Yuksek kalite, profesyonel |
| H.265/HEVC | Main | 5.0 | MP4/MOV | Yuksek sikistirma, yeni cihazlar |
| H.265/HEVC | Main10 | 5.1 | MP4/MOV | HDR, 10-bit renk derinligi |
| VP9 | Profile 0 | - | WebM | YouTube oncelikli, acik kaynak |
| VP9 | Profile 2 | - | WebM | 10-bit HDR icerik |
| AV1 | Main | - | MP4/WebM | Gelecek nesil, en yuksek sikistirma |

### 1.5 Bitrate Merdiveni (ABR - Adaptive Bitrate)

Her cozunurluk icin optimize edilmis bitrate araliklari:

```
Cozunurluk       | Video Bitrate (kbps)  | Audio Bitrate (kbps) | Toplam
---------------------------------------------------------------------------
2160p (4K)       | 12000 - 18000        | 320                  | ~18 Mbps
1440p (2K)       | 6000 - 9000          | 256                  | ~9 Mbps
1080p            | 4000 - 6000          | 192                  | ~6 Mbps
720p             | 2000 - 4000          | 128                  | ~4 Mbps
480p             | 1000 - 2000          | 128                  | ~2 Mbps
360p             | 500 - 1000           | 96                   | ~1 Mbps
240p             | 250 - 500            | 64                   | ~560 kbps
144p             | 100 - 250            | 48                   | ~300 kbps
```

**ABR Mantiği:** Platform yukleyicisi, hedef platformun gereksinimlerine gore merdivenden uygun katmani secer. YouTube gibi HLS/DASH destekleyen platformlar icin tum katmanlar uretilir; TikTok gibi tek dosya yukleyen platformlar icin tek katman.

### 1.6 Two-Pass Encoding Profili

Two-pass encoding, ilk pass'ta analiz, ikinci pass'ta optimal sikistirma yapar:

```
Pass 1 (Analiz):
  - STAT dosyasi uretilir
  - Kare tipleri (I, P, B) analiz edilir
  - Hareket haritasi olusturulur
  - Karmasiklik metrikleri hesaplanir

Pass 2 (Sikistirma):
  - STAT dosyasindan okuyarak bitrate tahsisi optimize edilir
  - Sahneler arasi gecislerde bitrate dusurulur
  - Duragan sahnelerde bitrate tasarrufu yapilir
  - Hareketli sahnelerde kalite korunur
```

**Tek-Pass Karsilastirmasi:**
- Tek-pass: Hizli (~2x gercek zaman), orta kalite
- Two-pass: Yavas (~4x gercek zaman), %15-20 daha iyi kalite/boyut orani
- GUIDED three-pass: Kullanici tanimli karmasiklik haritasi ile 3. pass

### 1.7 Platform Yukleme API Entegrasyonu

#### YouTube Data API v3

```python
# YouTube video yukleme akisi
# POST https://www.googleapis.com/upload/youtube/v3/videos
# Authorization: Bearer {access_token}
#
# Adimlar:
# 1. Resumable upload baslat
# 2. Parcal halinde yukle (5MB parcalar)
# 3. Yukleme tamamla
# 4. Video metadata guncelle (baslik, aciklama, etiketler, gizlilik)
# 5. Thumbnail yukle
```

**Kota ve Sinirlamalar:**
- Gunluk 10.000 birim quota (yukleme = 1600 birim)
- Maksimum dosya boyutu: 256 GB (veya 12 saat)
- Desteklenen formatlar: MOV, MPEG4, MP4, AVI, WMV, FLV, 3GPP, WebM

#### Instagram Graph API

```
# Instagram Reels/Feed Video yukleme akisi
# POST https://graph.facebook.com/v18.0/{ig-user-id}/media
#
# Adimlar:
# 1. Video container olustur (video_url, media_type, share_to_feed)
# 2. Container durumunu kontrol et (STATUS_READY)
# 3. Medyayi yayinla (POST /{ig-user-id}/media_publish)
# 4. Yayinlanma durumunu izle
#
# Sinirlamalar:
# - Maksimum boyut: 4GB (Reels), 650MB (Feed)
# - Maksimum sure: 90 dakika (Reels), 60 dakika (Feed)
# - Aspect ratio: 9:16 (Reels), 1:1 (Feed)
```

#### TikTok API (Video Kit API)

```
# TikTok video yukleme akisi
# POST https://open.tiktokapis.com/v2/post/publish/video/init/
#
# Adimlar:
# 1. Yukleme oturumu baslat (video_size, privacy_level)
# 2. Upload URL al
# 3. Video dosyasini yukle (HTTP PUT)
# 4. Yukleme dogrulamasi
# 5. Videoyu yayinla
#
# Sinirlamalar:
# - Maksimum boyut: 512MB (API), 1GB (uygulama ici)
# - Maksimum sure: 10 dakika (API), 3 dakika (bazı bolgeler)
# - Format: MP4 veya WebM
```

### 1.8 Veri Yapilari

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class Platform(Enum):
    TIKTOK = "tiktok"
    YOUTUBE_SHORTS = "youtube_shorts"
    INSTAGRAM_REELS = "instagram_reels"
    INSTAGRAM_FEED = "instagram_feed"
    TWITTER = "twitter"
    KICK = "kick"


class Codec(Enum):
    H264_BASELINE = "h264_baseline"
    H264_MAIN = "h264_main"
    H264_HIGH = "h264_high"
    H265_MAIN = "h265_main"
    H265_MAIN10 = "h265_main10"
    VP9_PROFILE0 = "vp9_profile0"
    VP9_PROFILE2 = "vp9_profile2"
    AV1_MAIN = "av1_main"


class EncodingPass(Enum):
    SINGLE = "single"
    TWO_PASS = "two_pass"
    GUIDED = "guided"


@dataclass
class CodecProfile:
    codec: Codec
    profile: str
    level: str
    pixel_format: str = "yuv420p"
    chroma_subsampling: str = "4:2:0"
    bit_depth: int = 8
    max_bitrate_kbps: int = 6000
    buffer_size_kbps: int = 12000
    preset: str = "medium"
    tune: Optional[str] = None
    extra_flags: dict[str, str] = field(default_factory=dict)


@dataclass
class BitrateLadder:
    resolution: tuple[int, int]
    video_bitrate_kbps: tuple[int, int]  # (min, max)
    audio_bitrate_kbps: int
    fps: list[int] = field(default_factory=lambda: [30])
    keyframe_interval: int = 2
    bframes: int = 3
    reference_frames: int = 4


@dataclass
class PlatformProfile:
    platform: Platform
    max_resolution: tuple[int, int]
    max_duration_seconds: int
    max_file_size_mb: int
    supported_codecs: list[Codec]
    preferred_codec: Codec
    default_bitrate_ladder: list[BitrateLadder]
    encoding_pass: EncodingPass
    container_format: str
    supported_fps: list[int]
    audio_codecs: list[str] = field(default_factory=lambda: ["aac"])
    audio_sample_rate: int = 44100
    requires_moov_atom: bool = True
    faststart: bool = True
    max_metadata_size_bytes: int = 1048576
    watermark_position: Optional[str] = None
    caption_support: bool = False


@dataclass
class ExportProfile:
    id: str
    name: str
    platform: PlatformProfile
    codec_profile: CodecProfile
    bitrate_ladder: list[BitrateLadder]
    encoding_pass: EncodingPass
    output_path: str
    quality_preset: str
    color_space: str = "bt709"
    color_transfer: str = "bt709"
    hdr_enabled: bool = False
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    tags: list[str] = field(default_factory=list)


@dataclass
class ExportJob:
    id: str
    profile: ExportProfile
    source_project_id: str
    status: str
    progress: float = 0.0
    current_pass: int = 0
    total_passes: int = 1
    error_message: Optional[str] = None
    output_files: list[str] = field(default_factory=list)
    upload_urls: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    estimated_size_bytes: int = 0
    actual_size_bytes: int = 0
    encoding_time_seconds: float = 0.0
```

### 1.9 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Yuksek cozunurlukte encoding suresi | 4K icerik 4x+ gercek zaman | GPU hizlandirma (NVENC, VideoToolbox), paralel segment encoding |
| Platform API kota sinirlamalari | Yogun donemlerde yukleme gecikmesi | Kuyruk sistemi, retry with exponential backoff, quota monitoring |
| Codec donusum maliyeti | H.264->H.265 gecis zaman alir | Donanim hizlandirmali transcode, onceden hesaplanmis profil onbellek |
| Buyuk dosya yukleme kesintileri | Ag kopmasi sonucu yukleme basa doner | Resumable upload, chunked transfer, checksum dogrulama |
| Bitrate optimizasyonu | Fazla bitrate = gereksiz boyut | Per-scene bitrate tahsisi, VBV kisitlamalari |

---

## 2. Bulut Depolama

### 2.1 Amaç

Uretilen medya dosyalarinin guvenilir, olceklenebilir ve erisebilir bicimde depolanmasi. Depolama sistemi, sicaklik tabakali (hot/warm/cold) bir mimari ile maliyet optimizasyonu saglar ve coklu saglayici destegi ile vendor lock-in'i onler.

### 2.2 Mimari Genel Gorunum

```
+------------------------------------------------------------+
|                   Storage Abstraction Layer                 |
|                                                            |
|  +--------+  +--------+  +----------+  +------------+     |
|  |   S3   |  |  GCS   |  |  Azure   |  | Backblaze  |     |
|  |(Sicak) |  |(Sicak) |  |(Orta)    |  | B2 (Soğuk)|     |
|  +--------+  +--------+  +----------+  +------------+     |
|       |            |           |               |           |
|       +------------+-----+-----+---------------+           |
|                          v                                 |
|  +------------------------------------------------------+ |
|  |              Storage Router                           | |
|  |  - Sicaklik tabakasi yonlendirmesi                    | |
|  |  - Bolgeler arasi replikasyon                         | |
|  |  - Maliyet optimizasyonu                               | |
|  +------------------------------------------------------+ |
|       |                                                    |
|       v                                                    |
|  +------------------------------------------------------+ |
|  |         Lifecycle Manager                              | |
|  |  - Otomatik soguk depolamaya tasma                    | |
|  |  - Suresi dolan dosya temizleme                       | |
|  |  - Erisim istatistikleri tabanli kararlar             | |
|  +------------------------------------------------------+ |
+------------------------------------------------------------+
```

### 2.3 Depolama Saglayicilari

#### Amazon S3 (Sicak Katman)

```
Standart Depolama:        $0.023/GB/ay (ilk 50TB)
S3-IA (Erisim Gereken):   $0.0125/GB/ay
S3 Glacier Instant:       $0.004/GB/ay
S3 Glacier Deep Archive:  $0.00099/GB/ay

Avantajlar:
- %99.999999999 (11 nines) dayanimlilik
- S3 Transfer Acceleration (uluslararasi hiz)
- S3 Select (SQL tabanli sorgulama)
- EventBridge entegrasyonu
- Lambda ile sunucusuz isleme
```

#### Google Cloud Storage

```
Standard:                 $0.020/GB/ay
Nearline:                 $0.010/GB/ay
Coldline:                 $0.004/GB/ay
Archive:                  $0.0012/GB/ay

Avantajlar:
- BigQuery ile dogrudan analiz
- Cloud CDN entegrasyonu (built-in)
- Pub/Sub event bildirimleri
- Uniform bucket-level erisim
```

#### Azure Blob Storage

```
Hot:                      $0.018/GB/ay (LRS)
Cool:                     $0.01/GB/ay
Cold:                     $0.0036/GB/ay
Archive:                  $0.00099/GB/ay

Avantajlar:
- Azure Media Services entegrasyonu
- Azure Front Door (CDN + load balancing)
- Managed Identity ile guvenli erisim
- Blob versioning ve soft delete
```

#### Backblaze B2 (Soğuk Arşiv)

```
B2 Storage:               $0.006/GB/ay
B2 Bandwidth:             $0.01/GB (ilk 1GB ucretsiz)

Avantajlar:
- S3 uyumlu API
- En dusuk maliyetli soguk depolama
- Sinirsiz erisim ucreti yok
- Cikis (egress) maliyeti dusuk
```

### 2.4 Imzali URL Uretimi

```python
import hashlib
import hmac
import time
from urllib.parse import quote
from datetime import datetime, timedelta


class SignedURLGenerator:
    """Coklu saglayici icin imzali URL uretimi."""

    def __init__(self, config: "StorageConfig"):
        self.config = config

    def generate_s3_signed_url(
        self,
        bucket: str,
        key: str,
        expires_in: int = 3600,
        http_method: str = "GET",
    ) -> str:
        region = self.config.s3_region
        service = "s3"
        now = int(time.time())
        date_stamp = time.strftime("%Y%m%d", time.gmtime(now))
        amz_date = time.strftime(
            "%Y%m%dT%H%M%SZ", time.gmtime(now)
        )

        credential_scope = (
            f"{date_stamp}/{region}/{service}/aws4_request"
        )
        canonical_uri = "/" + "/".join(
            quote(part, safe="")
            for part in key.split("/")
        )

        canonical_querystring = (
            "X-Amz-Algorithm=AWS4-HMAC-SHA256"
            f"&X-Amz-Credential={self.config.s3_access_key}"
            f"%2F{credential_scope}"
            f"&X-Amz-Date={amz_date}"
            f"&X-Amz-Expires={expires_in}"
            "&X-Amz-SignedHeaders=host"
        )

        canonical_headers = (
            f"host:{bucket}.s3.{region}.amazonaws.com\n"
        )
        signed_headers = "host"

        canonical_request = "\n".join([
            http_method,
            canonical_uri,
            canonical_querystring,
            canonical_headers,
            signed_headers,
            "UNSIGNED-PAYLOAD",
        ])

        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(
                canonical_request.encode()
            ).hexdigest(),
        ])

        def _sign(key: bytes, msg: str) -> bytes:
            return hmac.new(
                key, msg.encode(), hashlib.sha256
            ).digest()

        signing_key = _sign(
            _sign(
                _sign(
                    _sign(
                        b"AWS4"
                        + self.config.s3_secret_key.encode(),
                        date_stamp,
                    ),
                    region,
                ),
                service,
            ),
            "aws4_request",
        )

        signature = hmac.new(
            signing_key,
            string_to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()

        return (
            f"https://{bucket}.s3.{region}.amazonaws.com"
            f"{canonical_uri}"
            f"?{canonical_querystring}"
            f"&X-Amz-Signature={signature}"
        )

    def generate_gcs_signed_url(
        self,
        bucket: str,
        object_name: str,
        expires_in: int = 3600,
        http_method: str = "GET",
    ) -> str:
        import base64

        now = int(time.time())
        expiration = now + expires_in
        resource = f"/{bucket}/{object_name}"

        string_to_sign = (
            f"{http_method}\n\n\n{expiration}\n{resource}"
        )

        signature = base64.b64encode(
            hmac.new(
                self.config.gcs_client_secret.encode(),
                string_to_sign.encode(),
                hashlib.sha1,
            ).digest()
        ).decode()

        return (
            f"https://storage.googleapis.com{resource}"
            f"?GoogleAccessId={self.config.gcs_client_email}"
            f"&Expires={expiration}"
            f"&Signature={quote(signature, safe='')}"
        )

    def generate_azure_signed_url(
        self,
        container: str,
        blob: str,
        expires_in: int = 3600,
        http_method: str = "GET",
    ) -> str:
        import base64

        now = datetime.utcnow()
        expiry = now + timedelta(seconds=expires_in)

        signed_permissions = {
            "GET": "r",
            "PUT": "rw",
            "DELETE": "d",
        }.get(http_method, "r")

        canonicalized_resource = (
            f"/blob/{self.config.azure_account_name}"
            f"/{container}/{blob}"
        )

        string_to_sign = "\n".join([
            signed_permissions,
            "",
            "",
            expiry.strftime("%Y-%m-%dT%H:%M:%SZ"),
            canonicalized_resource,
        ])

        signature = base64.b64encode(
            hmac.new(
                base64.b64decode(
                    self.config.azure_account_key
                ),
                string_to_sign.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode()

        sas_token = (
            "sv=2021-06-08&ss=b&srt=sco"
            f"&sp={signed_permissions}"
            f"&se={expiry.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&sig={quote(signature, safe='')}"
        )

        return (
            f"https://{self.config.azure_account_name}"
            f".blob.core.windows.net"
            f"/{container}/{blob}?{sas_token}"
        )
```

### 2.5 Coklu Parca Yukleme (Multipart Upload)

```python
import os
import hashlib
from concurrent.futures import (
    ThreadPoolExecutor, as_completed,
)
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class UploadPart:
    part_number: int
    offset: int
    size: int
    etag: Optional[str] = None
    status: str = "pending"
    checksum: Optional[str] = None
    retry_count: int = 0


@dataclass
class UploadProgress:
    upload_id: str
    total_parts: int
    completed_parts: int = 0
    failed_parts: int = 0
    total_bytes: int = 0
    uploaded_bytes: int = 0
    parts: list[UploadPart] = field(default_factory=list)
    speed_bps: float = 0.0
    eta_seconds: float = 0.0

    @property
    def progress_percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.uploaded_bytes / self.total_bytes) * 100

    @property
    def is_complete(self) -> bool:
        return self.completed_parts == self.total_parts

    @property
    def has_failures(self) -> bool:
        return self.failed_parts > 0


class MultipartUploader:
    """Coklu parca yukleme motoru."""

    PART_SIZE_MB = 8
    MAX_CONCURRENT_UPLOADS = 5
    MAX_RETRIES = 3
    RETRY_BACKOFF_BASE = 2

    def __init__(self, storage_config: "StorageConfig"):
        self.config = storage_config

    def upload_file(
        self,
        local_path: str,
        remote_key: str,
        bucket: str,
        content_type: str = "video/mp4",
        on_progress: Optional[callable] = None,
    ) -> UploadProgress:
        file_size = os.path.getsize(local_path)
        part_size = self.PART_SIZE_MB * 1024 * 1024
        total_parts = (file_size + part_size - 1) // part_size

        upload_id = self._initiate_multipart_upload(
            bucket, remote_key
        )

        parts = []
        for i in range(total_parts):
            offset = i * part_size
            size = min(part_size, file_size - offset)
            parts.append(UploadPart(
                part_number=i + 1,
                offset=offset,
                size=size,
            ))

        progress = UploadProgress(
            upload_id=upload_id,
            total_parts=total_parts,
            total_bytes=file_size,
            parts=parts,
        )

        try:
            self._upload_parts_concurrent(
                local_path, bucket, remote_key,
                progress, on_progress,
            )

            if progress.has_failures:
                self._retry_failed_parts(
                    local_path, bucket, remote_key,
                    progress, on_progress,
                )

            if progress.is_complete:
                self._complete_multipart_upload(
                    bucket, remote_key,
                    upload_id, progress,
                )
            else:
                self._abort_multipart_upload(
                    bucket, remote_key, upload_id
                )
                raise UploadError(
                    f"Yukleme basarisiz: "
                    f"{progress.failed_parts} parca"
                )
        except Exception:
            self._abort_multipart_upload(
                bucket, remote_key, upload_id
            )
            raise

        return progress

    def _upload_parts_concurrent(
        self, local_path, bucket, remote_key,
        progress, on_progress,
    ):
        pending = [
            p for p in progress.parts
            if p.status == "pending"
        ]

        with ThreadPoolExecutor(
            max_workers=self.MAX_CONCURRENT_UPLOADS
        ) as executor:
            futures = {}
            for part in pending:
                future = executor.submit(
                    self._upload_single_part,
                    local_path, bucket,
                    remote_key, part,
                )
                futures[future] = part

            for future in as_completed(futures):
                part = futures[future]
                try:
                    result = future.result()
                    part.etag = result["etag"]
                    part.checksum = result["checksum"]
                    part.status = "completed"
                    progress.completed_parts += 1
                    progress.uploaded_bytes += part.size
                except Exception:
                    part.status = "failed"
                    progress.failed_parts += 1

                if on_progress:
                    on_progress(progress)

    def _upload_single_part(
        self, local_path, bucket, remote_key, part,
    ) -> dict:
        with open(local_path, "rb") as f:
            f.seek(part.offset)
            data = f.read(part.size)

        checksum = hashlib.sha256(data).hexdigest()
        etag = self._put_object_part(
            bucket, remote_key, part.part_number, data
        )
        return {"etag": etag, "checksum": checksum}

    def _retry_failed_parts(
        self, local_path, bucket, remote_key,
        progress, on_progress,
    ):
        import time

        failed = [
            p for p in progress.parts
            if p.status == "failed"
        ]
        for part in failed:
            for attempt in range(self.MAX_RETRIES):
                delay = self.RETRY_BACKOFF_BASE ** attempt
                time.sleep(delay)
                try:
                    result = self._upload_single_part(
                        local_path, bucket,
                        remote_key, part,
                    )
                    part.etag = result["etag"]
                    part.checksum = result["checksum"]
                    part.status = "completed"
                    progress.completed_parts += 1
                    progress.failed_parts -= 1
                    progress.uploaded_bytes += part.size
                    break
                except Exception:
                    part.retry_count += 1
                if on_progress:
                    on_progress(progress)

    def _initiate_multipart_upload(
        self, bucket, key
    ) -> str:
        raise NotImplementedError

    def _put_object_part(
        self, bucket, key, part_number, data
    ) -> str:
        raise NotImplementedError

    def _complete_multipart_upload(
        self, bucket, key, upload_id, progress
    ):
        raise NotImplementedError

    def _abort_multipart_upload(
        self, bucket, key, upload_id
    ):
        raise NotImplementedError


class UploadError(Exception):
    pass
```

### 2.6 Depolama Yasam Dongusu Politikalari

```
DOSYA YASI           EYLEM                          HEDEF DEPOLAMA
----------------------------------------------------------------------
0 - 30 gun           Sicak depolama                 S3 Standard / GCS Standard
30 - 90 gun          Soguk depolamaya tasma         S3-IA / GCS Nearline
90 - 180 gun         Arsiv depolamaya tasma         S3 Glacier / GCS Coldline
180 - 365 gun        Derin arsiv                    S3 Deep Archive / GCS Archive
> 365 gun            Sil (eger erisilmediyse)       ---
Ozel: Proje arsivi   Proje tamamlandi + 2 yil       GCS Archive (en ucuz)
```

### 2.7 Bölgeler Arasi Replikasyon

```
Birincil Bolge:          eu-west-1 (Irlanda)
Birincil Replika:        us-east-1 (Virginia)
Ikincil Replika:         ap-southeast-1 (Singapur)
Arsiv Replika:           us-west-2 (Oregon)

Replikasyon Stratejisi:
- Aktif-Aktif: Tum bolgelerde okuma/yazma (GCS ile mumkun)
- Aktif-Pasif: Birincil yazma, digerleri okuma (S3 CRR)
- Olay Tetiklemeli: Degisiklik oldugunda otomatik replikasyon
```

### 2.8 Veri Yapilari

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


class StorageTier(Enum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"
    ARCHIVE = "archive"


class StorageBackend(Enum):
    AWS_S3 = "aws_s3"
    GOOGLE_CLOUD_STORAGE = "google_cloud_storage"
    AZURE_BLOB = "azure_blob"
    BACKBLAZE_B2 = "backblaze_b2"
    MINIO = "minio"


@dataclass
class ReplicationRule:
    source_region: str
    destination_regions: list[str]
    storage_class: str = "STANDARD"
    enabled: bool = True


@dataclass
class LifecycleRule:
    id: str
    prefix: str
    transitions: list[dict] = field(default_factory=list)
    expiration_days: Optional[int] = None
    noncurrent_expiration_days: Optional[int] = None
    abort_incomplete_multipart_days: int = 7


@dataclass
class StorageBackendConfig:
    backend: StorageBackend
    bucket: str
    region: str
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    endpoint_url: Optional[str] = None
    default_storage_class: str = "STANDARD"
    max_file_size_bytes: int = (
        5 * 1024 * 1024 * 1024
    )
    multipart_threshold_bytes: int = (
        100 * 1024 * 1024
    )


@dataclass
class StorageConfig:
    backends: list[StorageBackendConfig]
    default_backend: StorageBackend
    replication_rules: list[ReplicationRule] = field(
        default_factory=list
    )
    lifecycle_rules: list[LifecycleRule] = field(
        default_factory=list
    )
    signed_url_ttl_seconds: int = 3600
    max_concurrent_uploads: int = 10
    enable_encryption: bool = True
    encryption_key_id: Optional[str] = None
    versioning_enabled: bool = True
    access_logging_enabled: bool = True
    s3_region: str = "eu-west-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    gcs_client_secret: str = ""
    gcs_client_email: str = ""
    azure_account_name: str = ""
    azure_account_key: str = ""


@dataclass
class StorageObject:
    key: str
    bucket: str
    size_bytes: int
    content_type: str
    storage_class: str
    backend: StorageBackend
    etag: str
    checksum_sha256: Optional[str] = None
    version_id: Optional[str] = None
    last_modified: Optional[datetime] = None
    metadata: dict[str, str] = field(default_factory=dict)
    replication_status: str = "COMPLETED"
```

### 2.9 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Yuksek egress (cikis) maliyeti | Buyuk medya dosyalari icin band genisligi ucretleri | CDN ile egress azaltma, CloudFront edge caching |
| Bolge ici gecikme | Yakin bolgelerde yuksek okuma gecikmesi | S3 Transfer Acceleration, CloudFront Origin Shield |
| Buyuk dosya yukleme suresi | 4K+ projeler gigabaytlarca veri | Multipart upload, paralel yukleme, S3 Express One Zone |
| Yasam dongusu politikasi karmasasi | Yanlis silme, beklenmedik gecis maliyetleri | Tag tabanli otomasyon, lifecycle rule test ortami |
| Multi-backend senkronizasyon | Farkli saglayicilar arasinda tutarsizlik | Object versioning, checksum dogrulama, delta senkronizasyon |

---

## 3. CDN Entegrasyonu

### 3.1 Amaç

Icerik Dagitim Agi (CDN), medya dosyalarinin dunya genelindeki kullanicilara dusuk gecikme suresi ve yuksek band genisligi ile teslim edilmesini saglar. Edge sunuculari, icerigi cografi olarak yakin konumlardan sunarak yukleme surelerini optimize eder.

### 3.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|                    CDN Orkestrasyon                         |
|                                                           |
|  Kullanici --> Edge Node --> Origin Shield --> Origin      |
|     |            |               |               |        |
|     |            v               v               v        |
|     |    +------------+  +------------+  +----------+    |
|     |    | Onbellek   |  | Onbellek   |  | Ana      |    |
|     |    | Hiti       |  | Miss       |  | Depolama |    |
|     |    +------------+  +------------+  +----------+    |
|     |                                                    |
|     v                                                    |
|  +--------------------------------------------------+    |
|  |  Purge/Invalidation Manager                       |    |
|  |  - Path-based purge                               |    |
|  |  - Tag-based purge                                |    |
|  |  - Wildcard purge                                 |    |
|  +--------------------------------------------------+    |
|                                                           |
|  +--------------------------------------------------+    |
|  |  Manifest URL Manager                             |    |
|  |  - HLS master.m3u8                                |    |
|  |  - DASH manifest.mpd                              |    |
|  |  - Versioned URL'ler                              |    |
|  +--------------------------------------------------+    |
+-----------------------------------------------------------+
```

### 3.3 CDN Saglayicilari

#### Amazon CloudFront

```
Ozellikler:
- 450+ PoP (Presence Point) - 6 kitada
- Origin Shield (birincil onbellek katmani)
- Lambda@Edge ile sunucusuz hesaplama
- Field-level encryption
- Real-time logs (Kinesis)
- Signed cookies / Signed URLs

Fiyatlandirma:
- Ilk 10TB/ay: $0.085/GB (ABD)
- 50-100TB/ay: $0.080/GB
- 100TB+: ozel fiyat
- HTTPS istekleri: $0.01/10.000
- Origin Shield: $0.0075/10.000 istek

Onbellek Suresi:
- Varsayilan: 24 saat
- HLS segmentleri: 30 gun (max-age)
- DASH segmentleri: 30 gun
- Thumbnail/preview: 7 gun
- Master manifest: 60 saniye (kisa omurlu)
```

#### Cloudflare

```
Ozellikler:
- 310+ PoP - tum kitalarda
- Argo Smart Routing (akilli yonlendirme)
- Workers (sunucusuz edge hesaplama)
- Stream (entegre medya oynatici)
- R2 Storage (S3 uyumlu, egress ucreti yok)
- Image Resizing (edge-based)

Fiyatlandirma:
- Ucretsiz plan: Sinirsiz band genisligi
- Pro: $20/ay
- Business: $200/ay
- Enterprise: ozel fiyat
- Workers: 10M istek/ay ucretsiz
- Stream: $1/1000 dakika

Avantaji:
- Sifir egress ucreti (R2 storage)
- Built-in WAF ve DDoS korumasi
- HTTP/3 (QUIC) destegi
```

#### Fastly

```
Ozellikler:
- 90+ PoP - stratejik konumlar
- VCL tabanli ozellestirme
- Compute@Edge (Rust/Wasm)
- Instant purge (<150ms global)
- Origin Shield (gelismis origin korumasi)
- Image Optimizer

Fiyatlandirma:
- Ilk 10TB/ay: $0.12/GB
- 10-40TB/ay: $0.08/GB
- 40TB+: ozel fiyat
- Origin Shield: $0.0075/10.000 istek

Avantaji:
- 150ms'de global purge (digerleri 5-15 dk)
- Gercek zamanli log analizi
- Surrogate-key tabanli purge
```

### 3.4 CDN Purge ve Gecersizlestirme

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import time
import uuid


class PurgeStrategy(Enum):
    PATH = "path"
    TAG = "tag"
    WILDCARD = "wildcard"
    FULL = "full"


@dataclass
class PurgeRequest:
    id: str
    strategy: PurgeStrategy
    targets: list[str]
    provider: str
    status: str = "pending"
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    error_message: Optional[str] = None


@dataclass
class CDNConfig:
    provider: str
    distribution_id: str
    api_token: str
    zone_id: Optional[str] = None
    default_ttl_seconds: int = 86400
    max_ttl_seconds: int = 2592000
    stale_ttl_seconds: int = 604800
    origin_shield_enabled: bool = False
    origin_shield_region: Optional[str] = None
    purge_rate_limit: int = 100
    purge_cooldown_seconds: int = 5


class CDNManager:
    """Coklu CDN saglayici yonetimi."""

    def __init__(self, configs: list[CDNConfig]):
        self.configs = {
            c.provider: c for c in configs
        }
        self._purge_history: list[PurgeRequest] = []

    async def purge_paths(
        self,
        provider: str,
        paths: list[str],
    ) -> PurgeRequest:
        config = self.configs[provider]
        request = PurgeRequest(
            id=str(uuid.uuid4()),
            strategy=PurgeStrategy.PATH,
            targets=paths,
            provider=provider,
        )

        if provider == "cloudfront":
            await self._cloudfront_invalidate(
                config, paths, request
            )
        elif provider == "cloudflare":
            await self._cloudflare_purge(
                config, paths, request
            )
        elif provider == "fastly":
            await self._fastly_purge(
                config, paths, request
            )

        self._purge_history.append(request)
        return request

    async def purge_by_tag(
        self,
        provider: str,
        tags: list[str],
    ) -> PurgeRequest:
        config = self.configs[provider]
        request = PurgeRequest(
            id=str(uuid.uuid4()),
            strategy=PurgeStrategy.TAG,
            targets=tags,
            provider=provider,
        )

        if provider == "cloudflare":
            await self._cloudflare_purge_by_tag(
                config, tags, request
            )
        elif provider == "fastly":
            await self._fastly_purge_by_surrogate_key(
                config, tags, request
            )
        else:
            raise ValueError(
                f"{provider} etiket purge desteklemiyor"
            )

        self._purge_history.append(request)
        return request

    async def purge_manifest(
        self,
        provider: str,
        project_id: str,
        manifest_paths: list[str],
    ) -> list[PurgeRequest]:
        requests = []

        manifest_req = await self.purge_paths(
            provider, manifest_paths
        )
        requests.append(manifest_req)

        segment_patterns = [
            f"/projects/{project_id}/segments/*.ts",
            f"/projects/{project_id}/segments/*.m4s",
            f"/projects/{project_id}/segments/*.mp4",
        ]
        segment_req = await self.purge_paths(
            provider, segment_patterns
        )
        requests.append(segment_req)

        preview_patterns = [
            f"/projects/{project_id}/preview/*",
            f"/projects/{project_id}/thumbnails/*",
        ]
        preview_req = await self.purge_paths(
            provider, preview_patterns
        )
        requests.append(preview_req)

        return requests

    async def _cloudfront_invalidate(
        self, config, paths, request
    ):
        import boto3

        client = boto3.client("cloudfront")
        try:
            client.create_invalidation(
                DistributionId=config.distribution_id,
                InvalidationBatch={
                    "Paths": {
                        "Quantity": len(paths),
                        "Items": paths,
                    },
                    "CallerReference": request.id,
                },
            )
            request.status = "completed"
            request.completed_at = time.time()
        except Exception as e:
            request.status = "failed"
            request.error_message = str(e)

    async def _cloudflare_purge(
        self, config, urls, request
    ):
        import aiohttp

        headers = {
            "Authorization": f"Bearer {config.api_token}",
            "Content-Type": "application/json",
        }
        payload = {"files": urls}

        async with aiohttp.ClientSession() as session:
            url = (
                "https://api.cloudflare.com/client/v4"
                f"/zones/{config.zone_id}/purge_cache"
            )
            async with session.delete(
                url, headers=headers, json=payload
            ) as resp:
                data = await resp.json()
                if data.get("success"):
                    request.status = "completed"
                    request.completed_at = time.time()
                else:
                    request.status = "failed"
                    request.error_message = str(
                        data.get("errors", [])
                    )

    async def _fastly_purge(
        self, config, paths, request
    ):
        import aiohttp

        headers = {
            "Fastly-Key": config.api_token,
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            for path in paths:
                url = (
                    "https://api.fastly.com/service/"
                    f"{config.distribution_id}"
                    f"/purge/{path}"
                )
                async with session.post(
                    url, headers=headers
                ) as resp:
                    if resp.status != 200:
                        request.status = "failed"
                        request.error_message = (
                            f"Purge basarisiz: {path}"
                        )
                        return

            request.status = "completed"
            request.completed_at = time.time()

    async def _cloudflare_purge_by_tag(
        self, config, tags, request
    ):
        import aiohttp

        headers = {
            "Authorization": (
                f"Bearer {config.api_token}"
            ),
            "Content-Type": "application/json",
            "Surrogate-Key": " ".join(tags),
        }

        async with aiohttp.ClientSession() as session:
            url = (
                "https://api.cloudflare.com/client/v4"
                f"/zones/{config.zone_id}/purge_cache"
            )
            payload = {"tags": tags}
            async with session.delete(
                url, headers=headers, json=payload
            ) as resp:
                data = await resp.json()
                if data.get("success"):
                    request.status = "completed"
                    request.completed_at = time.time()
                else:
                    request.status = "failed"

    async def _fastly_purge_by_surrogate_key(
        self, config, tags, request
    ):
        import aiohttp

        headers = {
            "Fastly-Key": config.api_token,
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            url = (
                "https://api.fastly.com/service/"
                f"{config.distribution_id}/purge_all"
            )
            async with session.post(
                url, headers=headers
            ) as resp:
                if resp.status == 200:
                    request.status = "completed"
                    request.completed_at = time.time()
                else:
                    request.status = "failed"
```

### 3.5 Edge Onbellek Stratejisi

```
Icerik Turu              TTL (Varsayilan)   Stale-While-Revalidate   Max-Age
---------------------------------------------------------------------------
Master Manifest (.m3u8)  60 saniye           30 saniye                120 saniye
Media Segment (.ts)      30 gun              7 gun                   365 gun
Video Dosyasi (.mp4)     24 saat             1 saat                  7 gun
Thumbnail (.jpg/.webp)   7 gun               1 gun                   30 gun
Preview Video            24 saat             6 saat                  7 gun
API Yaniti (JSON)        0 (no-cache)        0                       0
WebVTT Altyazi           1 saat              15 dakika               6 saat
```

### 3.6 Manifest URL Yonetimi

```
HLS Master Playlist:
  https://cdn.example.com/projects/{id}/hls/master.m3u8
    -> Alt playlist: /projects/{id}/hls/1080p/index.m3u8
    -> Alt playlist: /projects/{id}/hls/720p/index.m3u8
    -> Alt playlist: /projects/{id}/hls/480p/index.m3u8

DASH Manifest:
  https://cdn.example.com/projects/{id}/dash/manifest.mpd
    -> Video adaptation set: Representation@1080p
    -> Video adaptation set: Representation@720p
    -> Audio adaptation set: Representation@192kbps

URL Semasi:
  /{env}/{project_id}/{format}/{resolution}/{seg}.{ext}

  Ornek:
  /prod/abc123/hls/1080p/segment_0001.ts
  /prod/abc123/dash/1080p/chunk_0001.m4s
```

### 3.7 Veri Yapilari

```python
@dataclass
class CDNProvider:
    name: str
    provider_type: str
    distribution_id: str
    api_endpoint: str
    api_token: str
    zone_id: Optional[str] = None
    shield_enabled: bool = False
    shield_region: Optional[str] = None
    purge_rate_limit: int = 100
    regions: list[str] = field(default_factory=list)
    protocols: list[str] = field(
        default_factory=lambda: [
            "https", "http/2", "http/3"
        ]
    )
    features: list[str] = field(default_factory=list)
    cost_per_gb: float = 0.085


@dataclass
class CDNEdgeNode:
    node_id: str
    region: str
    city: str
    country: str
    provider: str
    cache_hit_ratio: float = 0.0
    bandwidth_mbps: float = 0.0
    active_connections: int = 0
    latency_ms: float = 0.0


@dataclass
class CDNConfigFull:
    providers: list[CDNProvider]
    default_provider: str
    failover_provider: Optional[str] = None
    origin_shield_enabled: bool = True
    origin_shield_provider: str = "cloudfront"
    multi_cdn_enabled: bool = False
    health_check_interval_seconds: int = 60
    automatic_failover: bool = True
    ssl_certificate_arn: Optional[str] = None
    custom_domain: Optional[str] = None
```

### 3.8 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Yuksek TTL cache miss | Icerik degistiginde eski dosya sunumu | Short TTL manifest, long TTL segments; stale-while-revalidate |
| Bolgeler arasi purge gecikmesi | Global purge 5-15 dakika | Fastly instant purge (<150ms) veya surrogate-key stratejisi |
| Cold start gecikmesi | Ilk istekte origin'e gidilmesi | Origin Shield, cache warming, prefetch |
| Multi-CDN senkronizasyon | Farkli CDN'lerde farkli icerik | Centralized purge coordinator, real-time consistency monitoring |
| HTTPS sertifika yonetimi | Sertifika suresi dolmasi | AWS Certificate Manager, auto-renewal, multi-domain SAN |

---

## 4. Onizleme Uretici (Preview Generator)

### 4.1 Amaç

Onizleme uretici, duzenleme her asamasinda kullanicina dusuk cozunurluklu video onizlemesi sunar. Gercek zamanli oynatma, timeline'da kaydirma (scrubbing) ve zaman cizelgesi uzerinde kare kare gezinme icin optimize edilmis dusuk cozunurluklu medya uretir.

### 4.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|                  Preview Pipeline                          |
|                                                           |
|  Tam Cozunurluklu Kaynak                                  |
|       |                                                   |
|       v                                                   |
|  +--------------+                                         |
|  | Kaynak Analiz|  -> Codec, cozunurluk, fps, sure       |
|  +------+-------+                                         |
|         |                                                 |
|         v                                                 |
|  +--------------+                                         |
|  | Onizleme     |  -> 720p, 480p, 360p, 144p             |
|  | Kodlama      |  -> H.264 Baseline (hiz oncelikli)     |
|  |              |  -> tek-pass, dusuk gecikme             |
|  +------+-------+                                         |
|         |                                                 |
|         v                                                 |
|  +--------------+                                         |
|  | Kaydirma     |  -> Her 1-5 sn'den bir thumbnail       |
|  | Onizlemesi   |  -> Sprite sheet uretimi                |
|  |              |  -> Seek tablosu                         |
|  +------+-------+                                         |
|         |                                                 |
|         v                                                 |
|  +--------------+                                         |
|  | Onizleme     |  -> CDN'e yukleme                        |
|  | Depolama     |  -> Onbellek dostu URL yapisi           |
|  +--------------+                                         |
+-----------------------------------------------------------+
```

### 4.3 Onizleme Kalite Katmanlari

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PreviewTier(Enum):
    TIER_144P = "144p"
    TIER_240P = "240p"
    TIER_360P = "360p"
    TIER_480P = "480p"
    TIER_720P = "720p"


@dataclass
class PreviewConfig:
    tier: PreviewTier
    resolution: tuple[int, int]
    bitrate_kbps: int
    fps: int
    codec: str
    preset: str
    pixel_format: str
    gop_size: int
    keyframe_only: bool
    buffer_size_kbps: int
    thread_count: int = 0
    scale_filter: str = "fast_bilinear"


DEFAULT_PREVIEW_CONFIGS = {
    PreviewTier.TIER_144P: PreviewConfig(
        tier=PreviewTier.TIER_144P,
        resolution=(256, 144),
        bitrate_kbps=100,
        fps=15,
        codec="h264",
        preset="ultrafast",
        pixel_format="yuv420p",
        gop_size=30,
        keyframe_only=False,
        buffer_size_kbps=200,
    ),
    PreviewTier.TIER_240P: PreviewConfig(
        tier=PreviewTier.TIER_240P,
        resolution=(426, 240),
        bitrate_kbps=250,
        fps=24,
        codec="h264",
        preset="ultrafast",
        pixel_format="yuv420p",
        gop_size=30,
        keyframe_only=False,
        buffer_size_kbps=500,
    ),
    PreviewTier.TIER_360P: PreviewConfig(
        tier=PreviewTier.TIER_360P,
        resolution=(640, 360),
        bitrate_kbps=500,
        fps=30,
        codec="h264",
        preset="ultrafast",
        pixel_format="yuv420p",
        gop_size=30,
        keyframe_only=False,
        buffer_size_kbps=1000,
    ),
    PreviewTier.TIER_480P: PreviewConfig(
        tier=PreviewTier.TIER_480P,
        resolution=(854, 480),
        bitrate_kbps=1000,
        fps=30,
        codec="h264",
        preset="superfast",
        pixel_format="yuv420p",
        gop_size=30,
        keyframe_only=False,
        buffer_size_kbps=2000,
    ),
    PreviewTier.TIER_720P: PreviewConfig(
        tier=PreviewTier.TIER_720P,
        resolution=(1280, 720),
        bitrate_kbps=2000,
        fps=30,
        codec="h264",
        preset="veryfast",
        pixel_format="yuv420p",
        gop_size=30,
        keyframe_only=False,
        buffer_size_kbps=4000,
    ),
}


@dataclass
class ScrubPreviewConfig:
    """Timeline kaydirma onizlemesi icin yapilandirma."""
    frame_interval: float = 2.0
    sprite_sheet_columns: int = 10
    sprite_sheet_rows: int = 10
    thumbnail_width: int = 160
    thumbnail_height: int = 90
    format: str = "jpg"
    quality: int = 75
    webp_enabled: bool = True
    webp_quality: int = 80


@dataclass
class PreviewRenderJob:
    id: str
    source_path: str
    project_id: str
    tier: PreviewTier
    output_path: str
    status: str = "pending"
    progress: float = 0.0
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    output_size_bytes: int = 0
    frame_count: int = 0
    error: Optional[str] = None
```

### 4.4 Onizleme Uretim Hatti

```python
import subprocess
import json
import os
import time
from pathlib import Path


class PreviewGenerator:
    """Onizleme ve kaydirma onizlemesi uretimi."""

    def __init__(
        self,
        config: PreviewConfig,
        storage_backend=None,
    ):
        self.config = config
        self.storage = storage_backend
        self._ffmpeg_path = "ffmpeg"

    def generate_preview(
        self,
        source_path: str,
        output_path: str,
        scrub_config: Optional[ScrubPreviewConfig] = None,
    ) -> dict:
        start_time = time.time()

        probe = self._probe_source(source_path)
        duration = float(
            probe.get("format", {}).get("duration", 0)
        )

        preview_cmd = self._build_preview_command(
            source_path, output_path, probe
        )
        self._run_ffmpeg(preview_cmd)

        scrub_output = None
        if scrub_config:
            scrub_output = self._generate_scrub_preview(
                source_path, output_path,
                probe, scrub_config,
            )

        output_size = os.path.getsize(output_path)
        elapsed = time.time() - start_time

        return {
            "preview_path": output_path,
            "preview_size_bytes": output_size,
            "scrub_output": scrub_output,
            "duration_seconds": duration,
            "encoding_time_seconds": elapsed,
            "encoding_speed": (
                duration / elapsed if elapsed > 0 else 0
            ),
            "tier": self.config.tier.value,
        }

    def _build_preview_command(
        self, source, output, probe
    ) -> list[str]:
        target_w, target_h = self.config.resolution

        cmd = [
            self._ffmpeg_path,
            "-i", source,
            "-c:v", "libx264",
            "-preset", self.config.preset,
            "-profile:v", "baseline",
            "-level", "3.1",
            "-pix_fmt", self.config.pixel_format,
            "-vf",
            f"scale={target_w}:{target_h}"
            f":force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}"
            f":(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1",
            "-b:v", f"{self.config.bitrate_kbps}k",
            "-maxrate",
            f"{int(self.config.bitrate_kbps * 1.5)}k",
            "-bufsize",
            f"{self.config.buffer_size_kbps}k",
            "-r", str(self.config.fps),
            "-g", str(self.config.gop_size),
            "-sc_threshold", "0",
            "-c:a", "aac",
            "-b:a", "64k",
            "-ac", "1",
            "-ar", "22050",
            "-movflags", "+faststart",
            "-y",
            output,
        ]

        if self.config.thread_count > 0:
            idx = cmd.index("-movflags")
            cmd.insert(idx, "-threads")
            cmd.insert(
                idx + 1, str(self.config.thread_count)
            )

        return cmd

    def _generate_scrub_preview(
        self, source, output_base, probe, scrub_config
    ) -> dict:
        duration = float(
            probe.get("format", {}).get("duration", 0)
        )
        interval = scrub_config.frame_interval
        total_frames = int(duration / interval)

        cols = scrub_config.sprite_sheet_columns
        rows = scrub_config.sprite_sheet_rows
        fps_per_sheet = cols * rows
        total_sheets = (
            (total_frames + fps_per_sheet - 1)
            // fps_per_sheet
        )

        thumb_w = scrub_config.thumbnail_width
        thumb_h = scrub_config.thumbnail_height

        sheets = []
        for sheet_idx in range(total_sheets):
            start_f = sheet_idx * fps_per_sheet
            end_f = min(
                start_f + fps_per_sheet, total_frames
            )

            temp_dir = (
                Path(output_base).parent
                / f"scrub_tmp_{sheet_idx}"
            )
            temp_dir.mkdir(parents=True, exist_ok=True)

            for frame_idx in range(start_f, end_f):
                timestamp = frame_idx * interval
                thumb_path = (
                    temp_dir
                    / f"frame_{frame_idx:06d}.jpg"
                )
                cmd = [
                    self._ffmpeg_path,
                    "-ss", str(timestamp),
                    "-i", source,
                    "-vframes", "1",
                    "-vf",
                    f"scale={thumb_w}:{thumb_h}"
                    f":force_original_aspect_ratio=decrease,"
                    f"pad={thumb_w}:{thumb_h}"
                    f":(ow-iw)/2:(oh-ih)/2:black",
                    "-q:v", str(scrub_config.quality),
                    "-y",
                    str(thumb_path),
                ]
                self._run_ffmpeg(cmd)

            sheet_path = (
                f"{output_base}"
                f"_sheet_{sheet_idx:03d}.jpg"
            )
            self._create_sprite_sheet(
                temp_dir, sheet_path, cols, rows,
                thumb_w, thumb_h,
                end_f - start_f,
            )
            sheets.append(sheet_path)

            for f in temp_dir.iterdir():
                f.unlink()
            temp_dir.rmdir()

        seek_table = self._build_seek_table(
            total_frames, interval, total_sheets,
            fps_per_sheet, cols, thumb_w, thumb_h,
        )

        seek_path = f"{output_base}_seek_table.json"
        with open(seek_path, "w") as f:
            json.dump(seek_table, f, indent=2)

        return {
            "sheets": sheets,
            "seek_table_path": seek_path,
            "total_frames": total_frames,
            "total_sheets": total_sheets,
        }

    def _create_sprite_sheet(
        self, temp_dir, output_path, cols, rows,
        thumb_w, thumb_h, frame_count,
    ):
        inputs = []
        for f in sorted(
            temp_dir.glob("frame_*.jpg")
        ):
            inputs.extend(["-i", str(f)])

        n = frame_count
        layout_parts = []
        for i in range(n):
            x = (i % cols) * thumb_w
            y = ((i // cols) % rows) * thumb_h
            layout_parts.append(f"{x}{y}")
        layout = "|".join(layout_parts)

        filter_complex = (
            f"{''.join(f'[{i}:v]' for i in range(n))}"
            f"xstack=inputs={n}:layout={layout}[out]"
        )

        cmd = [self._ffmpeg_path] + inputs + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-frames:v", "1",
            "-q:v", "5",
            "-y",
            output_path,
        ]
        self._run_ffmpeg(cmd)

    def _build_seek_table(
        self, total_frames, frame_interval,
        total_sheets, fps_per_sheet,
        cols, thumb_w, thumb_h,
    ) -> dict:
        entries = []
        for i in range(total_frames):
            timestamp = i * frame_interval
            sheet_idx = i // fps_per_sheet
            local_idx = i % fps_per_sheet
            sheet_col = local_idx % cols
            sheet_row = local_idx // cols

            entries.append({
                "timestamp": round(timestamp, 3),
                "sheet_index": sheet_idx,
                "x": sheet_col * thumb_w,
                "y": sheet_row * thumb_h,
                "width": thumb_w,
                "height": thumb_h,
            })

        return {
            "version": "1.0",
            "frame_interval": frame_interval,
            "total_frames": total_frames,
            "total_sheets": total_sheets,
            "thumbnail_size": {
                "width": thumb_w,
                "height": thumb_h,
            },
            "entries": entries,
        }

    def _probe_source(self, path: str) -> dict:
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def _run_ffmpeg(self, cmd: list[str]):
        result = subprocess.run(
            cmd, capture_output=True,
            text=True, timeout=3600,
        )
        if result.returncode != 0:
            raise PreviewGenerationError(
                f"FFmpeg basarisiz "
                f"(kod {result.returncode}): "
                f"{result.stderr[-500:]}"
            )


class PreviewGenerationError(Exception):
    pass
```

### 4.5 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Yuksek cozunurluklu kaynaktan olcekleme | 4K->144p isleme uzun surer | GPU hizlandirmali olcekleme, boyut zinciri (4K->720p->144p) |
| Es zamanli coklu katman uretimi | Birden fazla tier uretmek CPU'yu tuketir | Oncelikli kuyruk: 360p ilk, sonra 720p; paralel FFmpeg |
| Sprite sheet bellek kullanimi | 100 thumbnail tek image -> yuksek RAM | Streaming tile assembly, JPEG progressive encoding |
| Scrub thumbnail kalitesi | Dusuk kaliteli thumbnail'ler kotu UX | Keyframe-aligned extraction, deinterlace, histogram esitleme |
| CDN'ye yukleme gecikmesi | Onizleme hazir ama CDN'de henuz yok | Prefetch warming, edge compute ile on-the-fly generation |

---

## 5. Kucuk Resim Uretici (Thumbnail Generator)

### 5.1 Amaç

Kucuk resim (thumbnail) uretici, video iceriginden en cekici ve bilgilendirici kareyi secerek platform yukleme ve icerik kesfi icin optimize edilmis gorseller uretir. Akilli kare secimi, yuz algilama, sahne analizi ve metin bindirme ozellikleri sunar.

### 5.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|                Thumbnail Pipeline                          |
|                                                           |
|  Kaynak Video -> Aday Kare Havuzu -> Secim Motoru         |
|                       |                       |           |
|                       v                       v           |
|              +----------------+    +----------------+     |
|              | Her saniyeden  |    | Skorlama:      |     |
|              | 1-3 kare       |    | - Keskinlik    |     |
|              | extract        |    | - Renk         |     |
|              +----------------+    | - Yuz algilama |   |
|                                    | - Dinamik      |   |
|                                    | - Kompozisyon  |   |
|                                    +----------------+   |
|                                           |             |
|                                           v             |
|                              +--------------------+     |
|                              | En Iyi Kare Secimi |     |
|                              +--------+-----------+     |
|                                       |                 |
|                            +----------+----------+      |
|                            v                     v      |
|                   +--------------+     +------------+    |
|                   | Metin        |     | A/B        |    |
|                   | Bindirme     |     | Varyantlar |    |
|                   +--------------+     +------------+    |
|                        |                    |           |
|                        v                    v           |
|                   +----------------------------------+  |
|                   |     Cikti Formatlari             |  |
|                   |  JPG (1280x720)                  |  |
|                   |  WebP (1280x720)                 |  |
|                   |  PNG (saydam bindirme icin)      |  |
|                   +----------------------------------+  |
+-----------------------------------------------------------+
```

### 5.3 Secim Motoru ve Skorlama

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import subprocess
import json


class ThumbnailSelectionMode(Enum):
    BEST_FRAME = "best_frame"
    FACE_BASED = "face_based"
    SCENE_BASED = "scene_based"
    MOST_DYNAMIC = "most_dynamic"
    CENTRAL_COMPOSITION = "central_composition"


class ThumbnailFormat(Enum):
    JPG = "jpg"
    WEBP = "webp"
    PNG = "png"


@dataclass
class FrameCandidate:
    frame_index: int
    timestamp: float
    sharpness_score: float = 0.0
    color_score: float = 0.0
    face_score: float = 0.0
    dynamic_score: float = 0.0
    composition_score: float = 0.0
    brightness_score: float = 0.0
    contrast_score: float = 0.0
    total_score: float = 0.0
    face_count: int = 0
    largest_face_area: float = 0.0


@dataclass
class TextOverlay:
    text: str
    position: str
    font_family: str = "Arial"
    font_size: int = 48
    font_color: str = "#FFFFFF"
    background_color: Optional[str] = (
        "rgba(0,0,0,0.7)"
    )
    padding: int = 20
    border_radius: int = 8
    shadow_enabled: bool = True
    shadow_color: str = "rgba(0,0,0,0.5)"
    shadow_offset: int = 2


@dataclass
class ThumbnailVariant:
    id: str
    mode: ThumbnailSelectionMode
    output_path: str
    width: int
    height: int
    format: ThumbnailFormat
    quality: int
    text_overlay: Optional[TextOverlay] = None
    crop_region: Optional[
        tuple[int, int, int, int]
    ] = None
    score: float = 0.0
    is_primary: bool = False


@dataclass
class ThumbnailConfig:
    output_width: int = 1280
    output_height: int = 720
    format: ThumbnailFormat = ThumbnailFormat.JPG
    quality: int = 90
    selection_mode: ThumbnailSelectionMode = (
        ThumbnailSelectionMode.BEST_FRAME
    )
    candidate_sample_rate: float = 1.0
    max_candidates: int = 300
    text_overlays: list[TextOverlay] = field(
        default_factory=list
    )
    generate_variants: bool = True
    variant_modes: list[ThumbnailSelectionMode] = field(
        default_factory=lambda: [
            ThumbnailSelectionMode.BEST_FRAME,
            ThumbnailSelectionMode.MOST_DYNAMIC,
            ThumbnailSelectionMode.CENTRAL_COMPOSITION,
        ]
    )
    face_detection_enabled: bool = True
    face_weight: float = 0.3
    sharpness_weight: float = 0.25
    color_weight: float = 0.2
    dynamic_weight: float = 0.15
    composition_weight: float = 0.1
    output_directory: str = "thumbnails"


@dataclass
class ThumbnailJob:
    id: str
    source_path: str
    project_id: str
    config: ThumbnailConfig
    status: str = "queued"
    candidates: list[FrameCandidate] = field(
        default_factory=list
    )
    variants: list[ThumbnailVariant] = field(
        default_factory=list
    )
    selected_frame_index: Optional[int] = None
    processing_time_seconds: float = 0.0
    error: Optional[str] = None


class ThumbnailGenerator:
    """Akilli kucuk resim uretici."""

    def __init__(self, config: ThumbnailConfig):
        self.config = config
        self._ffmpeg = "ffmpeg"
        self._ffprobe = "ffprobe"

    def generate_thumbnail(
        self,
        source_path: str,
        output_base: str,
    ) -> dict:
        import time

        start = time.time()

        probe = self._probe(source_path)
        duration = float(
            probe.get("format", {}).get("duration", 0)
        )
        fps = self._parse_fps(probe)

        candidates = self._extract_candidates(
            source_path, duration, fps
        )
        candidates = self._score_candidates(
            source_path, candidates
        )
        candidates.sort(
            key=lambda c: c.total_score, reverse=True
        )

        primary = candidates[0]
        primary_path = (
            f"{output_base}_primary."
            f"{self.config.format.value}"
        )
        self._render_thumbnail(
            source_path, primary.timestamp,
            primary_path,
            self.config.output_width,
            self.config.output_height,
            self.config.format, self.config.quality,
            text_overlay=(
                self.config.text_overlays[0]
                if self.config.text_overlays else None
            ),
        )

        variants = [ThumbnailVariant(
            id=(
                f"primary_"
                f"{self.config.selection_mode.value}"
            ),
            mode=self.config.selection_mode,
            output_path=primary_path,
            width=self.config.output_width,
            height=self.config.output_height,
            format=self.config.format,
            quality=self.config.quality,
            text_overlay=(
                self.config.text_overlays[0]
                if self.config.text_overlays else None
            ),
            score=primary.total_score,
            is_primary=True,
        )]

        if (
            self.config.generate_variants
            and len(candidates) > 1
        ):
            for i, mode in enumerate(
                self.config.variant_modes
            ):
                idx = i + 1
                if idx >= len(candidates):
                    idx = 0
                candidate = candidates[idx]
                variant_path = (
                    f"{output_base}"
                    f"_variant_{mode.value}"
                    f".{self.config.format.value}"
                )
                text_ov = None
                if self.config.text_overlays:
                    ov_idx = min(
                        i,
                        len(self.config.text_overlays) - 1,
                    )
                    text_ov = (
                        self.config.text_overlays[ov_idx]
                    )
                self._render_thumbnail(
                    source_path,
                    candidate.timestamp,
                    variant_path,
                    self.config.output_width,
                    self.config.output_height,
                    self.config.format,
                    self.config.quality,
                    text_overlay=text_ov,
                )
                variants.append(ThumbnailVariant(
                    id=f"variant_{mode.value}",
                    mode=mode,
                    output_path=variant_path,
                    width=self.config.output_width,
                    height=self.config.output_height,
                    format=self.config.format,
                    quality=self.config.quality,
                    text_overlay=text_ov,
                    score=candidate.total_score,
                    is_primary=False,
                ))

        elapsed = time.time() - start

        return {
            "primary_thumbnail": primary_path,
            "variants": [
                {
                    "id": v.id,
                    "mode": v.mode.value,
                    "output_path": v.output_path,
                    "score": v.score,
                    "is_primary": v.is_primary,
                }
                for v in variants
            ],
            "total_candidates_scored": len(candidates),
            "processing_time_seconds": elapsed,
            "best_score": (
                candidates[0].total_score
                if candidates else 0
            ),
        }

    def _extract_candidates(
        self, source, duration, fps
    ) -> list[FrameCandidate]:
        interval = self.config.candidate_sample_rate
        candidates = []
        timestamp = 0.0
        index = 0

        while (
            timestamp < duration
            and index < self.config.max_candidates
        ):
            candidates.append(FrameCandidate(
                frame_index=index,
                timestamp=timestamp,
            ))
            timestamp += interval
            index += 1

        return candidates

    def _score_candidates(
        self, source, candidates
    ) -> list[FrameCandidate]:
        for candidate in candidates:
            candidate.sharpness_score = (
                self._measure_sharpness(
                    source, candidate.timestamp
                )
            )
            candidate.color_score = (
                self._measure_color_diversity(
                    source, candidate.timestamp
                )
            )

            if self.config.face_detection_enabled:
                face_data = self._detect_faces(
                    source, candidate.timestamp
                )
                candidate.face_count = (
                    face_data["count"]
                )
                candidate.largest_face_area = (
                    face_data["largest_area"]
                )
                candidate.face_score = (
                    self._compute_face_score(face_data)
                )

            candidate.dynamic_score = (
                self._measure_dynamics(
                    source, candidate.timestamp
                )
            )
            candidate.composition_score = (
                self._measure_composition(
                    source, candidate.timestamp
                )
            )

            candidate.total_score = (
                candidate.sharpness_score
                * self.config.sharpness_weight
                + candidate.color_score
                * self.config.color_weight
                + candidate.face_score
                * self.config.face_weight
                + candidate.dynamic_score
                * self.config.dynamic_weight
                + candidate.composition_score
                * self.config.composition_weight
            )

        return candidates

    def _measure_sharpness(
        self, source, timestamp
    ) -> float:
        cmd = [
            self._ffmpeg,
            "-ss", str(timestamp),
            "-i", source,
            "-vframes", "1",
            "-vf",
            "format=gray,"
            "convolution="
            "'0 1 0 1 -4 1 0 1 0:"
            "0 1 0 1 -4 1 0 1 0:"
            "0 1 0 1 -4 1 0 1 0:"
            "0 1 0 1 -4 1 0 1 0'",
            "-f", "rawvideo",
            "-pix_fmt", "gray",
            "-",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=10
            )
            pixels = result.stdout
            if len(pixels) == 0:
                return 0.0
            values = list(pixels)
            mean = sum(values) / len(values)
            variance = (
                sum(
                    (v - mean) ** 2 for v in values
                )
                / len(values)
            )
            return min(variance / 1000.0, 1.0)
        except Exception:
            return 0.0

    def _measure_color_diversity(
        self, source, timestamp
    ) -> float:
        try:
            cmd = [
                self._ffmpeg,
                "-ss", str(timestamp),
                "-i", source,
                "-vframes", "1",
                "-vf", "histogram=mode=channel",
                "-f", "image2",
                "-c:v", "mjpeg",
                "-q:v", "1",
                "-",
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=10
            )
            entropy = len(result.stdout) / 100000.0
            return min(entropy, 1.0)
        except Exception:
            return 0.0

    def _detect_faces(
        self, source, timestamp
    ) -> dict:
        try:
            import cv2
            import numpy as np

            cmd = [
                self._ffmpeg,
                "-ss", str(timestamp),
                "-i", source,
                "-vframes", "1",
                "-vf", "scale=640:360",
                "-f", "rawvideo",
                "-pix_fmt", "bgr24",
                "-",
            ]
            result = subprocess.run(
                cmd, capture_output=True, timeout=10
            )

            width, height = 640, 360
            expected = width * height * 3
            frame_data = result.stdout[:expected]

            frame = np.frombuffer(
                frame_data, dtype=np.uint8
            ).reshape((height, width, 3))

            gray = cv2.cvtColor(
                frame, cv2.COLOR_BGR2GRAY
            )

            cascade_path = (
                cv2.data.haarcascades
                + "haarcascade_frontalface_default.xml"
            )
            face_cascade = (
                cv2.CascadeClassifier(cascade_path)
            )
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.1,
                minNeighbors=5,
                minSize=(30, 30),
            )

            largest_area = 0
            for (x, y, w, h) in faces:
                area = w * h
                if area > largest_area:
                    largest_area = area

            total_area = width * height
            return {
                "count": len(faces),
                "largest_area": (
                    largest_area / total_area
                    if total_area > 0 else 0
                ),
            }
        except ImportError:
            return {"count": 0, "largest_area": 0}

    def _compute_face_score(
        self, face_data: dict
    ) -> float:
        count = face_data["count"]
        largest = face_data["largest_area"]

        if count == 0:
            return 0.0

        count_score = (
            1.0 if count == 1
            else 0.7 if count == 2
            else 0.4
        )
        size_score = (
            min(largest * 5, 1.0)
            if largest < 0.3
            else 0.6
        )
        return count_score * 0.5 + size_score * 0.5

    def _measure_dynamics(
        self, source, timestamp
    ) -> float:
        cmd = [
            self._ffmpeg,
            "-ss",
            str(max(0, timestamp - 0.5)),
            "-i", source,
            "-t", "1",
            "-vf",
            "select='gt(scene,0.3)',showinfo",
            "-f", "null",
            "-",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
            )
            scene_changes = (
                result.stderr.count("showinfo")
            )
            return min(scene_changes / 3.0, 1.0)
        except Exception:
            return 0.0

    def _measure_composition(
        self, source, timestamp
    ) -> float:
        return 0.5

    def _render_thumbnail(
        self, source, timestamp, output_path,
        width, height, fmt, quality,
        text_overlay=None,
    ):
        vf_filters = [
            f"scale={width}:{height}"
            f":force_original_aspect_ratio=decrease",
            f"pad={width}:{height}"
            f":(ow-iw)/2:(oh-ih)/2:black",
            "setsar=1",
        ]

        if text_overlay:
            vf_filters.append(
                self._build_text_overlay_filter(
                    text_overlay, width, height
                )
            )

        vf = ",".join(vf_filters)

        fmt_args = []
        if fmt == ThumbnailFormat.JPG:
            q = max(1, (100 - quality) // 10 + 1)
            fmt_args = ["-q:v", str(q)]
        elif fmt == ThumbnailFormat.WEBP:
            fmt_args = ["-quality", str(quality)]

        cmd = [
            self._ffmpeg,
            "-ss", str(timestamp),
            "-i", source,
            "-vframes", "1",
            "-vf", vf,
        ] + fmt_args + ["-y", output_path]

        self._run_ffmpeg(cmd)

    def _build_text_overlay_filter(
        self, overlay, width, height
    ) -> str:
        pos_map = {
            "top-left": (
                f"x={overlay.padding}"
                f":y={overlay.padding}"
            ),
            "top-center": (
                f"x=(w-text_w)/2"
                f":y={overlay.padding}"
            ),
            "top-right": (
                f"x=w-text_w-{overlay.padding}"
                f":y={overlay.padding}"
            ),
            "bottom-center": (
                f"x=(w-text_w)/2"
                f":y=h-text_h-{overlay.padding}"
            ),
        }
        pos = pos_map.get(
            overlay.position,
            pos_map["top-center"],
        )

        shadow = ""
        if overlay.shadow_enabled:
            shadow = (
                f":shadowcolor={overlay.shadow_color}"
                f":shadowx={overlay.shadow_offset}"
                f":shadowy={overlay.shadow_offset}"
            )

        bg = ""
        if overlay.background_color:
            bg = (
                f":box=1"
                f":boxcolor={overlay.background_color}"
                f":boxborderw={overlay.padding}"
            )

        escaped = (
            overlay.text
            .replace("'", "\\'")
            .replace(":", "\\:")
        )

        return (
            f"drawtext=text='{escaped}'"
            f":fontsize={overlay.font_size}"
            f":fontcolor={overlay.font_color}"
            f":{pos}{shadow}{bg}"
        )

    def _probe(self, path: str) -> dict:
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def _parse_fps(self, probe: dict) -> float:
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                rfr = stream.get(
                    "r_frame_rate", "30/1"
                )
                num, den = rfr.split("/")
                return float(num) / float(den)
        return 30.0

    def _run_ffmpeg(self, cmd: list[str]):
        result = subprocess.run(
            cmd, capture_output=True,
            text=True, timeout=60,
        )
        if result.returncode != 0:
            raise ThumbnailError(
                f"FFmpeg basarisiz: "
                f"{result.stderr[-300:]}"
            )


class ThumbnailError(Exception):
    pass
```

### 5.4 A/B Thumbnail Varyantlari

```
A/B testing icin thumbnail varyantlari, farkli secme
stratejileri ve bindirmeler ile uretilir:

Varyant A: En keskin kare (BEST_FRAME) + Baslik
Varyant B: En dinamik kare (MOST_DYNAMIC) + Alt baslik
Varyant C: Merkezi kompozisyon + Slogan

Her bir varyant icin platform-specific boyutlar:
- YouTube: 1280x720 (16:9)
- TikTok: 1080x1920 (9:16)
- Instagram Reels: 1080x1920 (9:16)
- Instagram Feed: 1080x1080 (1:1)
```

### 5.5 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Yuksek cozunurlukte yuz algilama yavas | 4K karelerde yuz algilama 10x yavas | Dusuk cozunurlukte algilama (640x360), ROI tabanli arama |
| Buyuk video dosyalarindan kare cikarma | 10GB+ dosyalarda seek yavas | Seek tablosu, keyframe index, FFmpeg `-ss` before input |
| Metin bindirme font destegi | Sistemler arasi font farklari | Embedded font (TTF/OTF paketleme), fallback font chain |
| Coklu format uretimi | JPG/WebP/PNG ayri ayri render | Tek FFmpeg pass ile multi-output, parallel format encoding |
| Histogram hesaplama maliyeti | Buyuk karelerde renk analizi | Downscale before analysis, sampling-based histogram |

---

## 6. Proxy Medya

### 6.1 Amaç

Proxy medya, yuksek cozunurluklu kaynaklarin hafif versiyonlaridir. Duzenleme sirasinda tam cozunurluklu dosyalar yerine proxy dosyalari kullanilarak sistem performansi ve tepki suresi artirilir. Render ise tam cozunurlukten yapilir.

### 6.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|                 Proxy Media Pipeline                       |
|                                                           |
|  Kaynak (ProRes 422 HQ / RAW / 4K+)                      |
|       |                                                   |
|       +------------------------------------------+        |
|       |                                          |        |
|       v                                          v        |
|  +--------------+                        +----------+     |
|  | Proxy Uretim |                        | Tam      |     |
|  | (Arka Plan)  |                        | Cozunrlk |     |
|  +------+-------+                        | (Arsiv)  |     |
|         |                                +----------+     |
|         v                                                  |
|  +--------------+                                          |
|  | Proxy Dosya  |                                          |
|  | (H.264 /     |                                          |
|  |  ProRes      |                                          |
|  |  Proxy /     |                                          |
|  |  DNxHR LB)   |                                          |
|  +------+-------+                                          |
|         |                                                  |
|         v                                                  |
|  +------------------------------------------------------+  |
|  |              Proxy Switching Manager                  |  |
|  |                                                       |  |
|  |  Duzenleme Modu:   Proxy -> Duzenleme                |  |
|  |  Onizleme Modu:    Proxy -> Oynatma                  |  |
|  |  Render Modu:      Tam Cozunurluk -> Cikti           |  |
|  +------------------------------------------------------+  |
+-----------------------------------------------------------+
```

### 6.3 Proxy Kodlama Seviyeleri

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ProxyCodec(Enum):
    H264_LOW = "h264_low"
    PRORES_PROXY = "prores_proxy"
    PRORES_LT = "prores_lt"
    DNXHR_LB = "dnxhr_lb"
    DNXHR_LQ = "dnxhr_lq"
    HAP = "hap"


class ProxyLevel(Enum):
    QUARTER = "quarter"
    EIGHTH = "eighth"
    SIXTEENTH = "sixteenth"
    CUSTOM = "custom"


@dataclass
class ProxyConfig:
    level: ProxyLevel
    codec: ProxyCodec
    target_resolution: tuple[int, int]
    bitrate_kbps: int
    fps_match_source: bool = True
    gop_size: int = 30
    pixel_format: str = "yuv420p"
    max_bitrate_kbps: Optional[int] = None
    buffer_size_kbps: Optional[int] = None
    faststart: bool = True
    thread_count: int = 0
    hw_acceleration: Optional[str] = None
    output_extension: str = ".mp4"
    storage_path: str = "proxy"


@dataclass
class ProxyLevelConfig:
    level: ProxyLevel
    resolution_scale: float
    bitrate_factor: float
    description: str


PROXY_LEVEL_CONFIGS = {
    ProxyLevel.QUARTER: ProxyLevelConfig(
        level=ProxyLevel.QUARTER,
        resolution_scale=0.25,
        bitrate_factor=0.1,
        description=(
            "Duzenleme icin onerilen seviye. "
            "Hizli oynatma, makul kalite."
        ),
    ),
    ProxyLevel.EIGHTH: ProxyLevelConfig(
        level=ProxyLevel.EIGHTH,
        resolution_scale=0.125,
        bitrate_factor=0.05,
        description=(
            "Dusuk kaynak sistemleri icin. "
            "Minimal bellek kullanimi."
        ),
    ),
    ProxyLevel.SIXTEENTH: ProxyLevelConfig(
        level=ProxyLevel.SIXTEENTH,
        resolution_scale=0.0625,
        bitrate_factor=0.02,
        description=(
            "Sadece ses senkronizasyonu "
            "ve kaba kesim icin."
        ),
    ),
}


PROXY_CODEC_CONFIGS = {
    ProxyCodec.H264_LOW: {
        "codec_name": "libx264",
        "preset": "ultrafast",
        "profile": "baseline",
        "level": "3.1",
        "tune": "fastdecode",
        "extra_flags": {"rc-lookahead": "0"},
    },
    ProxyCodec.PRORES_PROXY: {
        "codec_name": "prores_ks",
        "profile": "proxy",
        "vendor": "apple",
        "extra_flags": {"bits_per_mb": "8192"},
    },
    ProxyCodec.PRORES_LT: {
        "codec_name": "prores_ks",
        "profile": "lt",
        "vendor": "apple",
    },
    ProxyCodec.DNXHR_LB: {
        "codec_name": "dnxhd",
        "profile": "dnxhr_lb",
        "extra_flags": {"bitrate": "36M"},
    },
    ProxyCodec.DNXHR_LQ: {
        "codec_name": "dnxhd",
        "profile": "dnxhr_lq",
        "extra_flags": {"bitrate": "75M"},
    },
    ProxyCodec.HAP: {
        "codec_name": "hap",
        "extra_flags": {"chunks": "1"},
    },
}


@dataclass
class ProxyRenderJob:
    id: str
    source_path: str
    project_id: str
    config: ProxyConfig
    status: str = "queued"
    progress: float = 0.0
    source_duration: float = 0.0
    source_size_bytes: int = 0
    output_size_bytes: int = 0
    encoding_time_seconds: float = 0.0
    output_path: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ProxyMapping:
    """Orijinal ve proxy dosya eslestirmesi."""
    source_path: str
    proxy_path: str
    source_duration: float
    source_fps: float
    proxy_fps: float
    timecode_offset: float = 0.0
    frame_offset: int = 0
    checksum_source: Optional[str] = None
    checksum_proxy: Optional[str] = None
```

### 6.4 Proxy Uretim Hatti

```python
import subprocess
import json
import os
import time
import hashlib
from pathlib import Path


class ProxyPipeline:
    """Proxy medya uretimi icin entegre pipeline."""

    def __init__(self, storage_config=None):
        self.storage = storage_config
        self._ffmpeg = "ffmpeg"
        self._ffprobe = "ffprobe"

    def generate_proxy(
        self,
        source_path: str,
        proxy_config: ProxyConfig,
        output_path: str,
        on_progress: Optional[callable] = None,
    ) -> dict:
        start = time.time()

        probe = self._probe(source_path)
        video_stream = self._get_video_stream(probe)
        source_width = int(
            video_stream.get("width", 1920)
        )
        source_height = int(
            video_stream.get("height", 1080)
        )
        source_duration = float(
            probe.get("format", {}).get("duration", 0)
        )

        target_w, target_h = (
            proxy_config.target_resolution
        )

        if proxy_config.fps_match_source:
            source_fps = self._parse_fps(probe)
        else:
            source_fps = 24

        codec_config = PROXY_CODEC_CONFIGS[
            proxy_config.codec
        ]

        cmd = self._build_proxy_command(
            source_path, output_path, proxy_config,
            codec_config, target_w, target_h,
            source_fps, source_width, source_height,
        )

        if on_progress:
            on_progress({
                "status": "encoding",
                "progress": 0.0,
            })

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        stderr_output = []
        while True:
            line = process.stderr.readline()
            if (
                not line
                and process.poll() is not None
            ):
                break
            if line:
                stderr_output.append(line)
                if "time=" in line:
                    progress = self._parse_progress(
                        line, source_duration
                    )
                    if on_progress and progress > 0:
                        on_progress({
                            "status": "encoding",
                            "progress": progress,
                        })

        process.wait()
        elapsed = time.time() - start

        if process.returncode != 0:
            error_msg = "".join(stderr_output[-20:])
            raise ProxyGenerationError(
                f"Proxy uretimi basarisiz: {error_msg}"
            )

        output_size = os.path.getsize(output_path)
        source_size = os.path.getsize(source_path)

        mapping = ProxyMapping(
            source_path=source_path,
            proxy_path=output_path,
            source_duration=source_duration,
            source_fps=self._parse_fps(probe),
            proxy_fps=source_fps,
            checksum_source=self._file_checksum(
                source_path
            ),
            checksum_proxy=self._file_checksum(
                output_path
            ),
        )

        return {
            "proxy_path": output_path,
            "proxy_size_bytes": output_size,
            "source_size_bytes": source_size,
            "compression_ratio": (
                output_size / source_size
                if source_size > 0 else 0
            ),
            "encoding_time_seconds": elapsed,
            "encoding_speed": (
                source_duration / elapsed
                if elapsed > 0 else 0
            ),
            "resolution": f"{target_w}x{target_h}",
            "level": proxy_config.level.value,
            "codec": proxy_config.codec.value,
            "mapping": {
                "source": mapping.source_path,
                "proxy": mapping.proxy_path,
                "checksum_source": (
                    mapping.checksum_source
                ),
                "checksum_proxy": (
                    mapping.checksum_proxy
                ),
            },
        }

    def _build_proxy_command(
        self, source, output, config, codec_config,
        target_w, target_h, fps,
        source_w, source_h,
    ) -> list[str]:
        cmd = [self._ffmpeg, "-i", source]

        cmd.extend([
            "-c:v", codec_config["codec_name"]
        ])

        if "preset" in codec_config:
            cmd.extend([
                "-preset", codec_config["preset"]
            ])
        if "profile" in codec_config:
            cmd.extend([
                "-profile:v",
                codec_config["profile"],
            ])
        if "level" in codec_config:
            cmd.extend([
                "-level", codec_config["level"]
            ])
        if "tune" in codec_config:
            cmd.extend([
                "-tune", codec_config["tune"]
            ])

        pad_w = (
            target_w
            if target_w % 2 == 0
            else target_w + 1
        )
        pad_h = (
            target_h
            if target_h % 2 == 0
            else target_h + 1
        )
        vf = (
            f"scale={target_w}:{target_h}"
            f":force_original_aspect_ratio=decrease,"
            f"pad={pad_w}:{pad_h}"
            f":(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )
        cmd.extend(["-vf", vf])

        cmd.extend([
            "-b:v", f"{config.bitrate_kbps}k"
        ])

        if config.max_bitrate_kbps:
            cmd.extend([
                "-maxrate",
                f"{config.max_bitrate_kbps}k",
            ])
        if config.buffer_size_kbps:
            cmd.extend([
                "-bufsize",
                f"{config.buffer_size_kbps}k",
            ])

        cmd.extend([
            "-g", str(config.gop_size)
        ])
        cmd.extend(["-sc_threshold", "0"])
        cmd.extend([
            "-pix_fmt", config.pixel_format
        ])
        cmd.extend(["-r", str(fps)])
        cmd.extend([
            "-c:a", "aac",
            "-b:a", "48k",
            "-ac", "1",
        ])

        if config.faststart:
            cmd.extend([
                "-movflags", "+faststart"
            ])

        if config.thread_count > 0:
            cmd.extend([
                "-threads",
                str(config.thread_count),
            ])

        if config.hw_acceleration:
            cmd = self._apply_hw_accel(
                cmd, config.hw_acceleration
            )

        for key, value in codec_config.get(
            "extra_flags", {}
        ).items():
            cmd.extend([f"-{key}", value])

        cmd.extend(["-y", output])
        return cmd

    def _apply_hw_accel(self, cmd, hw_type):
        if hw_type == "cuda":
            cmd[1:1] = [
                "-hwaccel", "cuda",
                "-hwaccel_output_format",
                "cuda",
            ]
            for i, arg in enumerate(cmd):
                if arg == "-c:v":
                    cmd[i + 1] = "h264_nvenc"
                    break
        elif hw_type == "videotoolbox":
            cmd[1:1] = [
                "-hwaccel", "videotoolbox"
            ]
            for i, arg in enumerate(cmd):
                if arg == "-c:v":
                    cmd[i + 1] = (
                        "h264_videotoolbox"
                    )
                    break
        elif hw_type == "vaapi":
            cmd[1:1] = [
                "-hwaccel", "vaapi",
                "-hwaccel_device",
                "/dev/dri/renderD128",
            ]
            for i, arg in enumerate(cmd):
                if arg == "-c:v":
                    cmd[i + 1] = "h264_vaapi"
                    break
        return cmd

    def _parse_progress(self, line, duration):
        import re

        match = re.search(
            r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})",
            line,
        )
        if match and duration > 0:
            h, m, s, cs = match.groups()
            elapsed = (
                int(h) * 3600
                + int(m) * 60
                + int(s)
                + int(cs) / 100
            )
            return min(elapsed / duration, 1.0)
        return 0.0

    def _probe(self, path):
        cmd = [
            self._ffprobe,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True
        )
        return json.loads(result.stdout)

    def _get_video_stream(self, probe):
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                return stream
        return {}

    def _parse_fps(self, probe):
        vs = self._get_video_stream(probe)
        rfr = vs.get("r_frame_rate", "30/1")
        num, den = rfr.split("/")
        return float(num) / float(den)

    def _file_checksum(self, path):
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(
                lambda: f.read(8192), b""
            ):
                sha256.update(chunk)
        return sha256.hexdigest()


class ProxyGenerationError(Exception):
    pass
```

### 6.5 Proxy Anahtarlama (Switching)

```
Proxy anahtarlama, duzenleme sirasindaki akisi yonetir:

1. DUZENLEME MODU:
   Kaynak dosya -> Proxy dosya (dusuk cozunurluk)
   Neden: Hizli oynatma, responsive timeline

2. ONIZLEME MODU:
   Proxy dosya -> Gercek zamanli oynatma
   Neden: Dusuk gecikme, akici kaydirma

3. RENDER MODU:
   Proxy dosya -> Tam cozunurluk dosya (referans)
   Neden: Tam cozunurlukte kodlama

ANAHTARLAMA MEKANIZMASI:
- Edit Decision List (EDL) zaman kodlari korunur
- In/Out noktalari tam cozunurlukte eslenir
- Proxy timestamp = source timestamp + offset
- Codec donusumu gerekmez
```

### 6.6 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Large file proxy generation | 8K RAW dosyalardan proxy uretimi 30+ dk | Chunk-based encoding, GPU NVENC, paralel segment processing |
| Proxy kaynak senkronizasyonu | Proxy ve kaynak arasinda zaman kaymasi | Frame-accurate encoding, EDL tabanli zaman kodu mapping |
| Disk alani yonetimi | Proxy dosyalar depolama alani tuketir | Otomatik temizleme, sikistirilmis proxy formatlari |
| Codec uyumsuzlugu | Bazi NLE'ler ProRes proxy gerektirir | Multi-codec proxy uretimi, NLE-specific default codec |
| Buyuk projelerde queue yonetimi | 100+ klip = uzun kuyruk | Oncelik siralamasi, parallel worker'lar |

---

## 7. Artimli Rendering (Incremental Rendering)

### 7.1 Amaç

Artimli rendering, projede yalnizca degisen bolumlerin yeniden render edilmesini saglar. Tam yeniden render yerine, degisim tespiti ve kismi yeniden isleme ile onemli olcude zaman ve kaynak tasarrufu saglar.

### 7.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|             Incremental Rendering Engine                   |
|                                                           |
|  Proje Degisikligi Algilama                               |
|       |                                                   |
|       v                                                   |
|  +------------------------------+                         |
|  | Degisim Tespiti              |                         |
|  | - Segment bazli diff         |                         |
|  | - Efekt degisikligi          |                         |
|  | - Gecis degisikligi          |                         |
|  | - Ses degisikligi            |                         |
|  +--------------+-----------------+                       |
|                 |                                         |
|                 v                                         |
|  +------------------------------+                         |
|  | Render Plani Olusturma       |                         |
|  | - Degisen segmentler         |                         |
|  | - Bagimlilik analizi         |                         |
|  | - Oncelik siralamasi         |                         |
|  +--------------+-----------------+                       |
|                 |                                         |
|                 v                                         |
|  +------------------------------+                         |
|  | Kisimli Render               |                         |
|  | - Sadece degisen segmentler  |                         |
|  | - Eski segmentleri koru      |                         |
|  | - Yeni segmentleri uret      |                         |
|  +--------------+-----------------+                       |
|                 |                                         |
|                 v                                         |
|  +------------------------------+                         |
|  | Segment Birlestirme          |                         |
|  | - Eski + yeni segmentler     |                         |
|  | - Codec uyumlulugu           |                         |
|  | - Surekli zaman kodu         |                         |
|  +------------------------------+                         |
+-----------------------------------------------------------+
```

### 7.3 Degisim Tespit Mekanizmasi

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChangeType(Enum):
    EFFECT = "effect"
    TRANSITION = "transition"
    TRIM = "trim"
    REORDER = "reorder"
    MEDIA_REPLACE = "media_replace"
    SPEED = "speed"
    COLOR = "color"
    AUDIO = "audio"
    TITLE = "title"
    KEYFRAME = "keyframe"


class ChangeSeverity(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ChangedSegment:
    segment_id: str
    index: int
    start_time: float
    end_time: float
    change_type: ChangeType
    severity: ChangeSeverity
    description: str
    affected_outputs: list[str] = field(
        default_factory=list
    )
    dependencies: list[str] = field(
        default_factory=list
    )
    is_dirty: bool = True
    cached_output_path: Optional[str] = None
    original_checksum: Optional[str] = None
    modified_checksum: Optional[str] = None


@dataclass
class RenderSegment:
    """Render edilmis segment bilgisi."""
    id: str
    index: int
    start_time: float
    end_time: float
    output_path: str
    checksum: str
    file_size_bytes: int
    codec: str
    resolution: tuple[int, int]
    fps: float
    render_time_seconds: float = 0.0
    is_stale: bool = False


@dataclass
class IncrementalRenderPlan:
    project_id: str
    total_segments: int
    changed_segments: list[ChangedSegment]
    unchanged_segments: list[RenderSegment]
    render_order: list[str]
    estimated_time_saved: float = 0.0
    estimated_time_needed: float = 0.0
    full_render_time: float = 0.0
    cache_hit_ratio: float = 0.0
    output_format: str = "mp4"
    output_codec: str = "h264"
    output_bitrate_kbps: int = 6000

    @property
    def segments_to_render(
        self,
    ) -> list[ChangedSegment]:
        return [
            s for s in self.changed_segments
            if s.is_dirty
        ]

    @property
    def time_saved_percent(self) -> float:
        if self.full_render_time == 0:
            return 0.0
        return (
            self.estimated_time_saved
            / self.full_render_time
        ) * 100

    @property
    def segments_to_keep(
        self,
    ) -> list[RenderSegment]:
        return [
            s for s in self.unchanged_segments
            if not s.is_stale
        ]


@dataclass
class StitchResult:
    """Segment birlestirme sonucu."""
    output_path: str
    total_duration: float
    segment_count: int
    total_file_size: int
    stitch_time_seconds: float = 0.0
    output_checksum: Optional[str] = None
    error: Optional[str] = None
```

### 7.4 Render Plan Olusturucu

```python
import hashlib
import json
from pathlib import Path


class IncrementalRenderPlanner:
    """Degisim tespiti ve render plani."""

    def __init__(
        self, cache_dir: str = ".render_cache"
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(
            parents=True, exist_ok=True
        )

    def create_plan(
        self,
        project_id: str,
        segments: list[dict],
        timeline_changes: list[dict],
        previous_render: Optional[dict] = None,
    ) -> IncrementalRenderPlan:
        changed_segments = []
        unchanged_segments = []

        for i, segment in enumerate(segments):
            segment_id = segment.get(
                "id", f"seg_{i}"
            )
            is_changed = False
            change_type = None
            severity = ChangeSeverity.LOW

            for change in timeline_changes:
                if (
                    change.get("segment_id")
                    == segment_id
                ):
                    is_changed = True
                    change_type = ChangeType(
                        change.get("type", "effect")
                    )
                    severity = ChangeSeverity(
                        change.get(
                            "severity", "medium"
                        )
                    )
                    break

            current_checksum = (
                self._compute_segment_checksum(
                    segment
                )
            )
            cache_key = (
                f"{project_id}_{segment_id}"
            )
            cached_checksum = (
                self._get_cached_checksum(cache_key)
            )

            if (
                current_checksum != cached_checksum
            ):
                is_changed = True
                if severity == ChangeSeverity.LOW:
                    severity = ChangeSeverity.MEDIUM

            if is_changed:
                dependencies = (
                    self._find_dependencies(
                        segment_id,
                        segments,
                        timeline_changes,
                    )
                )

                if dependencies:
                    severity = ChangeSeverity.HIGH

                changed_segments.append(
                    ChangedSegment(
                        segment_id=segment_id,
                        index=i,
                        start_time=segment.get(
                            "start_time", 0
                        ),
                        end_time=segment.get(
                            "end_time", 0
                        ),
                        change_type=(
                            change_type
                            or ChangeType.EFFECT
                        ),
                        severity=severity,
                        description=(
                            self._generate_desc(
                                segment_id,
                                change_type,
                                severity,
                            )
                        ),
                        dependencies=dependencies,
                        modified_checksum=(
                            current_checksum
                        ),
                    )
                )
            else:
                cached = (
                    self._get_cached_render(
                        cache_key
                    )
                )
                if cached:
                    unchanged_segments.append(cached)
                else:
                    changed_segments.append(
                        ChangedSegment(
                            segment_id=segment_id,
                            index=i,
                            start_time=segment.get(
                                "start_time", 0
                            ),
                            end_time=segment.get(
                                "end_time", 0
                            ),
                            change_type=(
                                ChangeType.EFFECT
                            ),
                            severity=(
                                ChangeSeverity.MEDIUM
                            ),
                            description=(
                                "Onbellek yok, "
                                "yeniden render"
                            ),
                        )
                    )

            self._update_cache(
                cache_key, current_checksum
            )

        render_order = (
            self._determine_render_order(
                segments,
                changed_segments,
                timeline_changes,
            )
        )

        full_time = sum(
            s.get("end_time", 0)
            - s.get("start_time", 0)
            for s in segments
        )
        changed_time = sum(
            s.end_time - s.start_time
            for s in changed_segments
        )
        time_saved = full_time - changed_time

        return IncrementalRenderPlan(
            project_id=project_id,
            total_segments=len(segments),
            changed_segments=changed_segments,
            unchanged_segments=unchanged_segments,
            render_order=render_order,
            estimated_time_saved=time_saved * 2,
            estimated_time_needed=changed_time * 2,
            full_render_time=full_time * 2,
        )

    def _find_dependencies(
        self, segment_id, all_segments, changes
    ):
        dependencies = []

        for i, seg in enumerate(all_segments):
            if (
                seg.get("id") == segment_id
                and i > 0
            ):
                prev_id = all_segments[
                    i - 1
                ].get("id")
                prev_changes = [
                    c for c in changes
                    if c.get("segment_id") == prev_id
                ]
                if prev_changes:
                    dependencies.append(prev_id)
                break

        return dependencies

    def _determine_render_order(
        self, segments, changed, changes
    ):
        severity_order = {
            ChangeSeverity.CRITICAL: 0,
            ChangeSeverity.HIGH: 1,
            ChangeSeverity.MEDIUM: 2,
            ChangeSeverity.LOW: 3,
        }

        sorted_changed = sorted(
            changed,
            key=lambda s: (
                severity_order.get(s.severity, 3),
                s.index,
            ),
        )

        return [
            s.segment_id for s in sorted_changed
        ]

    def _compute_segment_checksum(self, segment):
        content = json.dumps(
            segment,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(
            content.encode()
        ).hexdigest()[:16]

    def _get_cached_checksum(self, cache_key):
        path = self.cache_dir / (
            f"{cache_key}.checksum"
        )
        if path.exists():
            return path.read_text().strip()
        return None

    def _update_cache(self, cache_key, checksum):
        path = self.cache_dir / (
            f"{cache_key}.checksum"
        )
        path.write_text(checksum)

    def _get_cached_render(self, cache_key):
        path = self.cache_dir / (
            f"{cache_key}.meta"
        )
        if path.exists():
            data = json.loads(path.read_text())
            return RenderSegment(**data)
        return None

    def _generate_desc(
        self, segment_id, change_type, severity
    ):
        if change_type:
            return (
                f"{change_type.value} degisikligi"
                f" - {severity.value} siddet"
            )
        return (
            f"Icerik degisikligi"
            f" - {severity.value} siddet"
        )
```

### 7.5 Segment Birlestirme

```
Segment Stitching Akisi:

1. Mevcut segmentlerin listelenmesi
   +-- seg_0001.ts (eski - onbelleginden)
   +-- seg_0002.ts (yeni - yeniden render)
   +-- seg_0003.ts (eski - onbelleginden)
   +-- seg_0004.ts (yeni - yeniden render)
   +-- seg_0005.ts (eski - onbelleginden)

2. Concat listesi olusturma
   file 'seg_0001.ts'
   file 'seg_0002.ts'
   file 'seg_0003.ts'
   file 'seg_0004.ts'
   file 'seg_0005.ts'

3. Codec uyumlulugu kontrolu
   - Tum segmentler ayni codec -> dogrudan birlestirme
   - Farkli codec'ler -> yeniden encode

4. Surekli zaman kodu saglama
   - Her segment icin kesin baslangic/bitis zamani
   - Frame-accurate kesim noktalari
   - GOP sinirlarina saygi

5. Bitstream filtering
   - MP4 atom yapisini duzelt
   - moov atomunu basa tasi
   - Metadata birlestir
```

### 7.6 Onbellek Bilincli Rendering

```
Onbellek Stratejisi:

DOGRULAMA:
- Her render segmenti icin SHA-256 checksum
- Kaynak segment checksum'u ile eslesme kontrolu
- Timeline metadata checksum'u
- Render parametreleri checksum'u

DEPOLAMA:
- Segment bazli dosya sistemi onbellegi
- Boyut: Her segment icin maks 2 kat
- Temizleme: LRU stratejisi
- Proje bazli izolasyon

TEKRAR KULLANIM:
- Eslesen checksum -> onbelleginden yukle
- Farkli checksum -> yeniden render
- Kisimi eslesme -> segment ici yeniden render
```

### 7.7 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| Checksum hesaplama maliyeti | Buyuk segmentlerde diff yavas | Fingerprint-based incremental hash |
| Segment sinirlarinda artefaktlar | Birlestirme noktalarinda gorsel hatalar | Overlap-based stitching, crossfade |
| Codec donusumu birlestirme sirasinda | Farkli codec segmentleri yeniden encode gerektirir | Uniform proxy format, intermediate codec (DNxHR) |
| Buyuk projelerde onbellek boyutu | 1000+ segment x 2 format = terabaytlar | Tiered cache (SSD hot -> HDD warm -> Cloud cold) |
| Paralel segment render cakismasi | Es zamanli write -> dosya bozulma | File locking, temp file -> atomic rename |

---

## 8. Arka Plan Rendering (Background Rendering)

### 8.1 Amaç

Arka plan rendering, kullanicinin duzenlemeye devam ederken arka planda rendering islemlerini yonetir. Bos zaman rendering'i, kademeli kalite artirma ve akillica zamanlama ile sistem kaynaklarini verimli kullanir.

### 8.2 Mimari Genel Gorunum

```
+-----------------------------------------------------------+
|            Background Render Manager                       |
|                                                           |
|  Kullanici Duzenlemesi       Arka Plan Rendering           |
|  +--------------+           +----------------------+      |
|  | Aktif         |  Change   | Render Kuyrug        |      |
|  | Duzenleme     | -------> | +----+ +----+ +----+ |      |
|  +--------------+  Event    | |Job1| |Job2| |Job3| |      |
|                             | +----+ +----+ +----+ |      |
|                             +----------------------+      |
|                                       |                   |
|                    +------------------+                   |
|                    v                  v                   |
|  +----------------------+  +----------------------------+|
|  | Bos Zaman            |  | Kademeli Kalite            ||
|  | Tespiti              |  |                            ||
|  |                      |  | Dusuk -> Orta -> Yuksek    ||
|  | CPU kullanimi        |  | 360p  -> 720p -> 1080p    ||
|  | < %30 -> render      |  | Rough -> Medium -> Final   ||
|  | > %70 -> dur         |  |                            ||
|  +----------------------+  +----------------------------+|
|                                                           |
|  +------------------------------------------------------+|
|  |            Zamanlama Motoru                           ||
|  |  - Tercih edilen saat: 02:00-06:00                   ||
|  |  - Agresif render: her bos an                        ||
|  |  - energy_mode: guc tasarrufu                        ||
|  |  - thermal throttling korumasi                       ||
|  +------------------------------------------------------+|
+-----------------------------------------------------------+
```

### 8.3 Veri Yapilari

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime, timedelta


class RenderPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3
    PREEMPTED = -1


class RenderPhase(Enum):
    ROUGH = "rough"
    DRAFT = "draft"
    STANDARD = "standard"
    FINAL = "final"


class SchedulerMode(Enum):
    AGGRESSIVE = "aggressive"
    BALANCED = "balanced"
    CONSERVATIVE = "conservative"
    SCHEDULED = "scheduled"


class SystemLoad(Enum):
    IDLE = "idle"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class BackgroundRenderConfig:
    enabled: bool = True
    scheduler_mode: SchedulerMode = (
        SchedulerMode.BALANCED
    )
    preferred_hours_start: int = 2
    preferred_hours_end: int = 6
    max_cpu_usage_percent: int = 70
    idle_threshold_percent: int = 30
    render_during_idle: bool = True
    thermal_throttle_threshold_celsius: int = 80
    battery_min_percent: int = 30
    quality_phases: list[RenderPhase] = field(
        default_factory=lambda: [
            RenderPhase.ROUGH,
            RenderPhase.DRAFT,
            RenderPhase.STANDARD,
            RenderPhase.FINAL,
        ]
    )
    max_concurrent_renders: int = 2
    render_timeout_seconds: int = 3600
    auto_retry_on_failure: bool = True
    max_retries: int = 3
    save_state_interval_seconds: int = 30
    progress_callback_url: Optional[str] = None
    notification_enabled: bool = True


@dataclass
class BackgroundRenderJob:
    id: str
    project_id: str
    phase: RenderPhase
    priority: RenderPriority
    status: str = "queued"
    progress: float = 0.0
    current_phase_index: int = 0
    total_phases: int = 4
    queued_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    estimated_remaining_seconds: float = 0.0
    render_params: dict = field(
        default_factory=dict
    )
    error_count: int = 0
    last_error: Optional[str] = None
    is_paused: bool = False
    pause_reason: Optional[str] = None

    @property
    def elapsed_time(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.completed_at or datetime.utcnow()
        return (
            end - self.started_at
        ).total_seconds()

    @property
    def eta(self) -> float:
        if self.progress <= 0:
            return 0.0
        elapsed = self.elapsed_time
        return (
            elapsed
            * (1 - self.progress)
            / self.progress
        )


@dataclass
class SystemMetrics:
    """Sistem durumu metrikleri."""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    disk_io_read_mbps: float = 0.0
    disk_io_write_mbps: float = 0.0
    gpu_percent: float = 0.0
    gpu_memory_percent: float = 0.0
    temperature_celsius: float = 0.0
    battery_percent: Optional[float] = None
    is_charging: Optional[bool] = None
    network_up_mbps: float = 0.0
    network_down_mbps: float = 0.0
    active_render_count: int = 0

    @property
    def system_load(self) -> SystemLoad:
        if self.cpu_percent < 20:
            return SystemLoad.IDLE
        elif self.cpu_percent < 40:
            return SystemLoad.LOW
        elif self.cpu_percent < 60:
            return SystemLoad.MEDIUM
        elif self.cpu_percent < 80:
            return SystemLoad.HIGH
        return SystemLoad.CRITICAL

    @property
    def should_render(self) -> bool:
        if self.cpu_percent > 80:
            return False
        if (
            self.temperature_celsius
            and self.temperature_celsius > 75
        ):
            return False
        if (
            self.battery_percent is not None
            and self.battery_percent < 20
            and not self.is_charging
        ):
            return False
        return True


@dataclass
class RenderSchedule:
    """Render zamanlama bilgisi."""
    job_id: str
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    preferred_start_hour: int = 2
    preferred_end_hour: int = 6
    is_urgent: bool = False
    defer_if_system_busy: bool = True
    max_deferral_hours: int = 24


class BackgroundRenderManager:
    """Arka plan rendering yoneticisi."""

    def __init__(self, config: BackgroundRenderConfig):
        self.config = config
        self._jobs: list[BackgroundRenderJob] = []
        self._metrics = SystemMetrics()
        self._is_paused = False
        self._pause_reason = ""

    def submit_job(
        self,
        project_id: str,
        render_params: dict,
        priority: RenderPriority = (
            RenderPriority.NORMAL
        ),
    ) -> BackgroundRenderJob:
        job = BackgroundRenderJob(
            id=self._generate_job_id(),
            project_id=project_id,
            phase=self.config.quality_phases[0],
            priority=priority,
            queued_at=datetime.utcnow(),
            render_params=render_params,
            total_phases=len(
                self.config.quality_phases
            ),
        )
        self._jobs.append(job)
        self._schedule_next()
        return job

    def update_metrics(
        self, metrics: SystemMetrics
    ):
        self._metrics = metrics
        self._check_thermal_throttle()
        self._check_render_continuation()

    def pause_all(self, reason: str):
        self._is_paused = True
        self._pause_reason = reason
        for job in self._jobs:
            if job.status == "rendering":
                job.is_paused = True
                job.pause_reason = reason

    def resume_all(self):
        self._is_paused = False
        self._pause_reason = ""
        for job in self._jobs:
            if job.is_paused:
                job.is_paused = False
                job.pause_reason = None
        self._schedule_next()

    def get_queue_status(self) -> dict:
        return {
            "total_jobs": len(self._jobs),
            "queued": sum(
                1 for j in self._jobs
                if j.status == "queued"
            ),
            "rendering": sum(
                1 for j in self._jobs
                if j.status == "rendering"
            ),
            "completed": sum(
                1 for j in self._jobs
                if j.status == "completed"
            ),
            "failed": sum(
                1 for j in self._jobs
                if j.status == "failed"
            ),
            "is_paused": self._is_paused,
            "pause_reason": self._pause_reason,
            "system_load": (
                self._metrics.system_load.value
            ),
        }

    def _schedule_next(self):
        if self._is_paused:
            return

        if not self._metrics.should_render:
            return

        active = sum(
            1 for j in self._jobs
            if j.status == "rendering"
        )
        if (
            active
            >= self.config.max_concurrent_renders
        ):
            return

        pending = sorted(
            [
                j for j in self._jobs
                if j.status == "queued"
            ],
            key=lambda j: j.priority.value,
            reverse=True,
        )

        if not pending:
            return

        self._start_render(pending[0])

    def _start_render(
        self, job: BackgroundRenderJob
    ):
        job.status = "rendering"
        job.started_at = datetime.utcnow()
        # Gercek render burada tetiklenir

    def _check_thermal_throttle(self):
        if (
            self._metrics.temperature_celsius
            > self.config
            .thermal_throttle_threshold_celsius
        ):
            self.pause_all(
                "Isi siniri asildi: "
                f"{self._metrics.temperature_celsius}C"
            )

    def _check_render_continuation(self):
        if (
            self._is_paused
            and self._metrics.should_render
        ):
            self.resume_all()

    def _generate_job_id(self) -> str:
        import uuid
        return str(uuid.uuid4())[:12]
```

### 8.4 Kademeli Kalite Artirma

```
Kademeli kalite artirma, ayni icerigin farkli kalite
seviyelerinde render edilerek kullanici deneyimini
iyilestirir:

FAZE 1 - ROUGH (Kaba):
  - Cozunurluk: 360p
  - Codec: H.264 ultrafast
  - Amacli: Hizli onizleme, ritim kontrolu
  - Sure: ~0.5x gercek zaman

FAZE 2 - DRAFT (Taslak):
  - Cozunurluk: 720p
  - Codec: H.264 veryfast
  - Amacli: Renk duzeltme, gecis onizleme
  - Sure: ~1x gercek zaman

FAZE 3 - STANDARD:
  - Cozunurluk: 1080p
  - Codec: H.264 medium
  - Amacli: Detay kontrolu, metin dogrulama
  - Sure: ~2x gercek zaman

FAZE 4 - FINAL:
  - Cozunurluk: Kaynak cozunurluk (4K'ya kadar)
  - Codec: H.264 slow veya H.265 main
  - Amacli: Cikti kalitesi, platform yukleme
  - Sure: ~4x gercek zaman

Oncelik Mekanizmasi:
- Yeni degisiklik yapildiginda mevcut faze sifirlanir
- Dusuk fazedeyken degisiklik hizli gecer
- Yuksek fazedeyken degisiklik daha yavas gecer
- Kullanici istedigi fazedan baslayabilir
```

### 8.5 Zamanlama Motoru

```python
from datetime import datetime, time as dt_time


class RenderScheduler:
    """Akillica render zamanlama motoru."""

    def __init__(self, config: BackgroundRenderConfig):
        self.config = config

    def is_preferred_window(self) -> bool:
        now = datetime.now().time()
        start = dt_time(
            self.config.preferred_hours_start, 0
        )
        end = dt_time(
            self.config.preferred_hours_end, 0
        )

        if start <= end:
            return start <= now <= end
        else:
            return now >= start or now <= end

    def calculate_optimal_start(
        self,
        estimated_duration_seconds: float,
    ) -> datetime:
        now = datetime.now()

        if self.is_preferred_window():
            return now

        if self.config.scheduler_mode == (
            SchedulerMode.AGGRESSIVE
        ):
            return now

        if self.config.scheduler_mode == (
            SchedulerMode.SCHEDULED
        ):
            return self._next_preferred_window(now)

        return now

    def _next_preferred_window(
        self, now: datetime
    ) -> datetime:
        today_start = now.replace(
            hour=self.config.preferred_hours_start,
            minute=0,
            second=0,
            microsecond=0,
        )
        if today_start > now:
            return today_start

        return today_start + timedelta(days=1)

    def should_defer(
        self, metrics: SystemMetrics
    ) -> bool:
        if not self.is_preferred_window():
            if metrics.system_load in (
                SystemLoad.HIGH,
                SystemLoad.CRITICAL,
            ):
                return True
        return False

    def get_next_render_window(
        self,
    ) -> dict:
        now = datetime.now()
        next_start = self._next_preferred_window(now)
        return {
            "next_start": next_start.isoformat(),
            "is_currently_preferred": (
                self.is_preferred_window()
            ),
            "hours_until_next": (
                (next_start - now).total_seconds()
                / 3600
            ),
        }
```

### 8.6 Darboğazlar ve Cozumleri

| Darboğaz | Etki | Cozum |
|---|---|---|
| CPU/GPU kaynak cakismasi | Duzenleme ve render ayni anda yavaslatir | Process priority management, nice/renice, GPU context switching |
| Sicaklik yonetimi | Uzun sureli render'da isinma | Thermal monitoring, otomatik throttle, fan hizi optimizasyonu |
| Bellek sizintisi | Arka plan render bellek tuketimi | Memory-mapped files, streaming render, bellek kota siniri |
| Ilerleme kaybasi | Render durduruldugunda sifirdan baslar | State serialization, incremental checkpoint, warm restart |
| Kuyruk yonetimi cakismasi | Oncelikli isler bekler | Priority queue with preemption, deadline-based scheduling |