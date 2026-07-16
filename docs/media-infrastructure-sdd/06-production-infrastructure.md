# 06 - Uretim Altyapisi: Render Kuyrugu, Dagitik Render, Worker Pool, Is Zamanlayicisi, Asset Yoneticisi, Onbellek Yoneticisi

**Durum:** Taslak v1.0
**Son Guncelleme:** 2026-07-16
**Yazar:** Principal Media Infrastructure Engineer
**Kapsam:** Production-grade medya altyapisi - kuyruk yonetimi, dagitik render, worker yasam dongusu, is zamanlamasi, asset yasam dongusu, cok katmanli onbellek

---

## Icindekiler

1. [Render Kuyrugu](#1-render-kuyrugu)
2. [Dagitik Render](#2-dagitik-render)
3. [Worker Pool](#3-worker-pool)
4. [Is Zamanlayicisi](#4-is-zamanlayicisi)
5. [Asset Yoneticisi](#5-asset-yoneticisi)
6. [Onbellek Yoneticisi](#6-onbellek-yoneticisi)

---

## 1. Render Kuyrugu

### 1.1 Amac

Render kuyrugu, video render islerinin yasam dongusunu yoneten merkezi bilesendir. Islerin olusturulmasi, onceliklendirilmesi, bagimliliklarinin cozulmesi, segmentlere bolunmesi, ilerleme takibi ve kaliciligi bu katmanda gerceklesir. Kuyruk, sunucu yeniden baslatmalarinda is durumunu korur ve dagitik render altyapisina besleme yapar.

### 1.2 Render Is Yasam Dongusu

Her render isi asagidaki durum makinesinden gecer:

```
+-------------+
|   CREATED   |  Is olusturuldu, henuz kuyruga alinmadi
+------+------+
       |
       v
+-------------+
|   QUEUED    |  Kuyruga eklendi, scheduler tarafindan degerlendirilmeyi bekliyor
+------+------+
       |
       v
+---------------+
|   ANALYZING   |  Kaynak analiz ediliyor (sure, codec, cozunurluk, segmentasyon)
+-------+-------+
        |
        v
+--------------+
|  RENDERING   |  Render islemi devam ediyor (segmentlere bolunmus olabilir)
+------+-------+
       |
       v
+--------------+
|  ENCODING   |  Post-process: final encoding, QC, thumbnail uretimi
+------+-------+
       |
       v
+----------+     +----------+
| COMPLETE |     |  FAILED  |  Terminal durumlar
+----------+     +----------+
```

**Durum gecis kurallari:**

| Gecis | Kosul | Aksiyon |
|-------|-------|---------|
| CREATED -> QUEUED | Validasyon gecti, kaynak mevcut | Scheduler degerlendirme kuyruguna ekle |
| QUEUED -> ANALYZING | Scheduler slot tahsis etti | FFprobe ile medya analizi baslat |
| ANALYZING -> RENDERING | Segmentasyon tamamlandi | Render worker'a dispatch et |
| RENDERING -> ENCODING | Tum segmentler tamamlandi | Final encoding, QC pipeline |
| ENCODING -> COMPLETE | QC gecti, thumbnail uretildi | Is sonu callback, bildirim |
| RENDERING -> FAILED | Worker hatasi, kaynak yok | Retry karari (max_retries kontrolu) |
| ENCODING -> FAILED | QC basarisiz, encoding hatasi | Detayli hata logu |
| ANALYZING -> FAILED | Kaynak bozuk, okunamiyor | Kalici hata, otomatik retry yok |
| QUEUED -> CANCELLED | Kullanici iptali | Kaynaklari serbest birak |
| RENDERING -> CANCELLING | Graceful shutdown istegi | Mevcut segmenti bitir, kalanini iptal et |

### 1.3 Is Onceligi (Priority)

Dort oncelik seviyesi tanimlanir; scheduler kaynak tahsisini bu oncelige gore yapar:

| Priority | Kullanim | P99 Bekleme Hedefi | Preempt Edilebilir |
|----------|----------|---------------------|---------------------|
| `urgent` | Canli yayin klibi, acil duzeltme | < 5 s | Hayir |
| `normal` | Kullanici talebiyle olusturulan render | < 30 s | Evet (urgent geldiginde) |
| `low` | On izleme, draft render | < 5 dk | Evet |
| `background` | Batch is, gece renderi, yeniden encoding | < 60 dk | Evet (her zaman) |

### 1.4 Is Bagimliliklari

Bazi render isleri birbirine bagimlidir. Ornegin, montaj renderi tum alt kliplerin once tamamlanmasini gerektirir. Bagimlilik sistemi DAG (Directed Acyclic Graph) olarak modellenir:

```python
class DependencyType(str, Enum):
    FINISH_TO_START = 'finish_to_start'  # A bitmeden B baslamaz
    START_TO_START = 'start_to_start'    # A baslayinca B baslayabilir
    FINISH_TO_FINISH = 'finish_to_finish' # A bitince B bitebilir

class JobDependency(BaseModel):
    depends_on_job_id: str
    dependency_type: DependencyType = DependencyType.FINISH_TO_START
    required_segments: Optional[List[str]] = None
```

Bagimlilik cozumleme algoritmasi:
1. Tum isler icin dependency graph olustur
2. Cycle detection (DFS ile)
3. Topolojik siralama
4. Her seviyedeki bagimsiz isleri paralel calistirilabilir olarak isaretle
5. FINISH_TO_START tipinde upstream is COMPLETE olmadan downstream is RENDERING'e gecemez

### 1.5 Is Iptali ve Tekrar Deneme (Cancellation & Retry)

Iptal uc seviyede desteklenir:

1. **Graceful cancellation (CANCELLING):** Worker'a sinyal gonder, mevcut segmenti bitir, kalanini atla
2. **Force cancellation (CANCELLED):** Worker surecini SIGKILL ile sonlandir, tum kaynaklari geri al
3. **Rollback cancellation:** S3'e yuklenmis kismi artifact'lari temizle

**Retry politikasi:**

| Hata Turu | Otomatik Retry | Max Retry | Backoff |
|-----------|---------------|-----------|---------|
| Worker crash (heartbeat timeout) | Evet | 3 | Exponential (10s -> 30s -> 90s) |
| S3 upload hatasi | Evet | 5 | Exponential (5s -> 15s -> 45s -> 135s -> 405s) |
| FFmpeg exit code != 0 | Evet (gecici ise) | 2 | Fixed 30s |
| Kaynak bozuk/gecersiz | Hayir | 0 | - |
| Kota asimi | Hayir | 0 | - |

### 1.6 Render Is Bolme (Segment-Based Parallel Rendering)

Uzun videolar (ornegin > 60 saniye) segmentlere bolunerek paralel render edilir:

```
INPUT: 120s video, 12 segment (her biri 10s)
       +---+---+---+---+---+---+---+---+---+---+---+---+
       | S1| S2| S3| S4| S5| S6| S7| S8| S9|S10|S11|S12|
       +---+---+---+---+---+---+---+---+---+---+---+---+
         |   |   |   |   |   |   |   |   |   |   |   |
         +---+---+---+---+---+---+---+---+---+---+---+
                           v
              4 Worker (her biri 3 segment)
              +------+ +------+ +------+ +------+
              |  W1  | |  W2  | |  W3  | |  W4  |
              |S1-3  | |S4-6  | |S7-9  | |S10-12|
              +--+---+ +--+---+ +--+---+ +--+---+
                 |        |        |        |
                 v        v        v        v
              +-------------------------------------+
              |          Concatenation               |
              |      (ffmpeg concat demuxer)          |
              +-------------------------------------+
```

Segmentasyon stratejisi:
- Varsayilan segment suresi: 10 saniye, yapilandirilabilir
- Minimum segment: 5 saniye (FFmpeg sync sorunlarini onlemek icin)
- Keyframe hizalama: Segment sinirlari en yakin keyframe'e hizalanir
- Gecis bolgeleri: Her segmente %5 overlap eklenir (glitch onleme)

**Concatenation yontemleri:**
- Ayni codec/parametre: concat demuxer (lossless, cok hizli)
- Farkli codec: Yeniden kodlayarak birlestirme
- Gecis efekti varsa: xfade filter ile birlestirme

### 1.7 Ilerleme Takibi (Progress Tracking)

Her is ve segment icin ilerleme takibi:

| Metrik | Kaynak | Guncelleme Sikligi |
|--------|--------|---------------------|
| Overall progress % | Segment bazli agirlikli ortalama | Her segment tamamlandiginda |
| Current segment | Worker heartbeat | Her 5 saniye |
| FFmpeg frame | stderr parsing | Her frame (veya 100ms) |
| Tahmini kalan sure | Progress hizi + kalan is | Her 10 saniye |
| Islenen byte | Cikti dosya boyutu | Her 30 saniye |

### 1.8 Is Kaliciligi (Sunucu Yeniden Baslatmaya Dayaniklilik)

Render islari PostgreSQL'de kalici olarak saklanir. Her state gecisi ayri bir transaction ile commit edilir:

```sql
CREATE TABLE render_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'created',
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    source_path TEXT NOT NULL,
    output_path TEXT,
    spec_json JSONB NOT NULL,
    segments_json JSONB,
    progress_pct REAL DEFAULT 0,
    attempt_number INT DEFAULT 0,
    max_attempts INT DEFAULT 3,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INT NOT NULL DEFAULT 1,
    UNIQUE (id)
);
CREATE INDEX idx_render_jobs_status ON render_jobs(status);
CREATE INDEX idx_render_jobs_priority ON render_jobs(priority, created_at);
```

### 1.9 Veri Yapilari

```python
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4

class RenderJobStatus(str, Enum):
    CREATED = 'created'
    QUEUED = 'queued'
    ANALYZING = 'analyzing'
    RENDERING = 'rendering'
    ENCODING = 'encoding'
    COMPLETE = 'complete'
    FAILED = 'failed'
    CANCELLING = 'cancelling'
    CANCELLED = 'cancelled'

class RenderJobPriority(str, Enum):
    URGENT = 'urgent'
    NORMAL = 'normal'
    LOW = 'low'
    BACKGROUND = 'background'

class RenderSegment(BaseModel):
    segment_id: str = Field(default_factory=lambda: str(uuid4()))
    index: int
    start_time: float
    duration: float
    overlap_start: float = 0
    overlap_end: float = 0.05
    status: RenderJobStatus = RenderJobStatus.CREATED
    worker_id: Optional[str] = None
    progress_pct: float = 0
    error_message: Optional[str] = None
    output_path: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class RenderJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    status: RenderJobStatus = RenderJobStatus.CREATED
    priority: RenderJobPriority = RenderJobPriority.NORMAL
    source_path: str
    spec_json: Dict[str, Any]
    segments: List[RenderSegment] = []
    dependencies: List[JobDependency] = []
    progress_pct: float = 0
    attempt_number: int = 0
    max_attempts: int = 3
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1
```

### 1.10 Render Queue Manager - Python Uygulamasi

```python
'''
Render Queue Manager - Core queue management logic.
'''
import asyncio, json, logging
from datetime import datetime
from typing import Optional, List, Callable

logger = logging.getLogger(__name__)

class RenderQueueManager:
    '''Render job yasam dongusunu yoneten ana sinif.'''

    def __init__(self, db_session_factory, outbox_relay=None):
        self._db = db_session_factory
        self._outbox = outbox_relay
        self._active_jobs = {}
        self._event_handlers = {}

    async def create_job(self, tenant_id, source_path, spec_json,
                          priority=RenderJobPriority.NORMAL,
                          dependencies=None):
        segments = await self._compute_segments(source_path, spec_json)
        job = RenderJob(
            tenant_id=tenant_id, source_path=source_path,
            spec_json=spec_json, priority=priority, segments=segments,
            dependencies=dependencies or [],
        )
        if job.dependencies:
            job.status = RenderJobStatus.CREATED
        else:
            job.status = RenderJobStatus.QUEUED
        async with self._db() as session:
            await self._persist_job(session, job)
            if self._outbox:
                await self._outbox('render_job.created', job.dict())
        self._active_jobs[job.job_id] = job
        return job

    async def _compute_segments(self, source_path, spec_json):
        duration = await self._get_media_duration(source_path)
        seg_dur = spec_json.get('segment_duration', 10.0)
        min_dur = spec_json.get('min_segment_duration', 5.0)
        if duration <= seg_dur * 1.1:
            return [RenderSegment(index=0, start_time=0.0, duration=duration)]
        segments, current, idx = [], 0.0, 0
        while current < duration:
            sd = min(seg_dur, duration - current)
            if sd < min_dur and segments:
                segments[-1].duration += sd; break
            segments.append(RenderSegment(
                index=idx, start_time=current, duration=sd,
                overlap_start=0.05 if idx > 0 else 0,
                overlap_end=0.05 if current + sd < duration else 0,
            ))
            current += sd; idx += 1
        return segments

    async def transition_job(self, job_id, new_status, error=None):
        job = self._active_jobs.get(job_id)
        if not job:
            job = await self._load_job(job_id)
            if not job: return None
        if not job.can_transition_to(new_status): return None
        old_status = job.status
        job.status = new_status; job.updated_at = datetime.utcnow()
        if new_status == RenderJobStatus.FAILED: job.error_message = error
        elif new_status == RenderJobStatus.RENDERING: job.started_at = datetime.utcnow()
        elif new_status == RenderJobStatus.COMPLETE: job.completed_at = datetime.utcnow()
        async with self._db() as session:
            ok = await self._update_job_status(session, job, old_status)
            if not ok: return None
            if self._outbox:
                await self._outbox('render_job.status_changed', {
                    'job_id': job_id, 'old_status': old_status.value,
                    'new_status': new_status.value,
                })
        self._active_jobs[job_id] = job
        return job

    async def cancel_job(self, job_id, force=False):
        job = self._active_jobs.get(job_id)
        if not job: return False
        if force:
            return bool(await self.transition_job(job_id, RenderJobStatus.CANCELLED, 'Force cancelled'))
        if job.status in (RenderJobStatus.QUEUED, RenderJobStatus.ANALYZING):
            return bool(await self.transition_job(job_id, RenderJobStatus.CANCELLED, 'Cancelled by user'))
        elif job.status == RenderJobStatus.RENDERING:
            return bool(await self.transition_job(job_id, RenderJobStatus.CANCELLING))
        return False

    async def retry_job(self, job_id):
        job = await self._load_job(job_id)
        if not job or job.attempt_number >= job.max_attempts: return None
        job.attempt_number += 1; job.error_message = None
        for seg in job.segments:
            seg.status = RenderJobStatus.CREATED; seg.worker_id = None
            seg.progress_pct = 0; seg.error_message = None
        return await self.transition_job(job_id, RenderJobStatus.QUEUED)

    async def _get_media_duration(self, path):
        proc = await asyncio.create_subprocess_exec(
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_format', path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return float(json.loads(stdout.decode()).get('format', {}).get('duration', 0))
```

### 1.11 API Sozlesmeleri (Render Queue)

| Endpoint | Method | Aciklama |
|----------|--------|----------|
| /api/v1/render-jobs | POST | Yeni render job olustur |
| /api/v1/render-jobs/{id} | GET | Job durumu ve detay |
| /api/v1/render-jobs/{id}/progress | GET | Ilerleme bilgisi |
| /api/v1/render-jobs/{id}/cancel | POST | Job iptal |
| /api/v1/render-jobs/{id}/retry | POST | Job yeniden dene |
| /api/v1/render-jobs | GET | Job listesi (filtreleme) |

### 1.12 Dar Bogazlar ve Cozumler

| Dar Bogaz | Cozum |
|-----------|-------|
| PostgreSQL write contention (yuksek job throughput) | Batch insert, connection pooling (PgBouncer), partition by tenant |
| Uzun kuyruk beklemesi (priority inversion) | Priority queue + preemption support |
| Segment concatenation sirasinda dar bogaz | Concat worker poolunu ayri queueya al, GPU yerine CPU fast-preset kullan |
| Outbox relay gecikmesi | CDC (Debezium) + Kafka yerine direkt pg_notify + in-memory relay |
| State machine locking contention | Optimistic locking (version kolonu), FOR UPDATE SKIP LOCKED |

---

## 2. Dagitik Render (Distributed Rendering)

### 2.1 Amac

Dagitik render katmani, render islerini birden fazla worker node'a dagitarak paralel isleme saglar. Master-worker mimarisi ile calisir; master frame/segment dagitimi, worker registration, health check ve fault tolerance'dan sorumludur. Hedef: tek bir makinenin yapamayacagi buyuklukteki isleri yatay olcekle islemek.

### 2.2 Master-Worker Mimarisi

```
                    +------------------------------------+
                    |              MASTER                 |
                    |  +------------------------------+  |
                    |  |    Job Scheduler              |  |
                    |  |    - Priority queue           |  |
                    |  |    - Resource-aware placement |  |
                    |  +--------------+---------------+  |
                    |  +--------------+---------------+  |
                    |  |    Frame Distributor          |  |
                    |  |    - Round-robin dagitim      |  |
                    |  |    - Load-balanced dagitim    |  |
                    |  |    - Region-based dagitim     |  |
                    |  +--------------+---------------+  |
                    |  +--------------+---------------+  |
                    |  |    Worker Registry             |  |
                    |  |    - Registration              |  |
                    |  |    - Health check              |  |
                    |  |    - Capability management     |  |
                    |  +--------------+---------------+  |
                    |  +--------------+---------------+  |
                    |  |    Result Aggregator           |  |
                    |  |    - Segment birlestirme      |  |
                    |  |    - Checksum dogrulama       |  |
                    |  +------------------------------+  |
                    +------------------------------------+
                                 |
                +----------------+------------------+
                v                v                  v
        +------------+ +------------+ +------------+
        | Worker 1   | | Worker 2   | | Worker N   |
        | GPU A100   | | GPU A100   | | CPU Only   |
        | 80GB VRAM  | | 80GB VRAM  | | 16 cores   |
        +------------+ +------------+ +------------+
                |                |                  |
                +----------------+------------------+
                                 v
                    +------------------------------+
                    |       Result Storage          |
                    |         (S3 CAS)              |
                    +------------------------------+
```

### 2.3 Frame Dagitim Stratejisi

Uc dagitim stratejisi desteklenir:

**1. Round-Robin (varsayilan)**
Segmentler workerlara sirayla dagitilir. Basit ve ongorulebilir.
Worker 1: S1, S4, S7, S10 | Worker 2: S2, S5, S8, S11 | Worker 3: S3, S6, S9, S12
Kullanim: Homojen worker poollari, esit segment sureleri.

**2. Load-Balanced**
Workerin anlik yukune ve gecmis performansina gore dagitim yapilir.
En dusuk load_scorea sahip workera bir sonraki segment verilir.
Kullanim: Heterojen worker poollari, degisken segment sureleri.

**3. Region-Based**
Segmentin icerigine gore worker secimi. Karmasik efekt iceren segment GPU workera gider.
Kullanim: Heterojen worker poollari, asimetrik segment karmasikligi.

### 2.4 Worker Kaydi ve Saglik Kontrolu (Registration & Health Check)

Registration flow: Worker START -> Self-test (codec, GPU, disk write) -> Capability raporu -> Master'a POST /api/v1/workers/register -> Heartbeat baslat (her 10 saniye) -> Task poll baslat

| Kontrol | Periyot | Timeout | Aksiyon |
|---------|---------|---------|---------|
| Heartbeat | 10 s | 30 s | Worker'i UNHEALTHY isaretle |
| GPU health | 60 s | 120 s | GPU dustuyse capabilityden cikar |
| Disk space | 30 s | - | Disk < %10 -> yeni job kabul etme |

Worker durumlari: REGISTERED -> READY -> BUSY -> READY -> DRAINING -> DRAINED -> DEREGISTERED

### 2.5 Worker Capabilities (Yetenekler)

Workerlar yeteneklerini bir sema ile bildirir:

| Capability | Aciklama | Ornek |
|------------|----------|-------|
| gpu.model | GPU modeli | NVIDIA A100-SXM4-80GB |
| gpu.vram_gb | GPU bellegi | 80 |
| gpu.encoder | Donanim encoderlari | h264_nvenc, hevc_nvenc, av1_nvenc |
| cpu.cores | CPU cekirdek sayisi | 32 |
| memory.gb | RAM | 256 |
| disk.available_gb | Kullanilabilir scratch | 1500 |
| os.type | Isletim sistemi | linux, windows |
| ffmpeg.version | FFmpeg versiyonu | 6.1.1 |
| ffmpeg.codecs | Desteklenen codecler | libx264, libx265, aac |
| ffmpeg.filters | Desteklenen filterlar | drawtext, ass, xfade |

### 2.6 Hata Toleransi (Worker Failure -> Redistribute)

| Scenario | Tespit | Kurtarma |
|----------|--------|----------|
| Worker crash | Heartbeat timeout (30s) | Segmentleri QUEUED durumuna dondur, baska workera ata |
| GPU reset | GPU health check basarisiz | Capabilityden GPuyu cikar, CPU failover |
| Disk full | Disk monitor < threshold | Worker'i DRAINING, tamamlanan segmentleri kurtar |
| Network partition | Heartbeat + task queue unreachable | Master isaretler, Temporal timeout ile retry |

Redistribut mekanizmasi:
1. Worker UNHEALTHY veya DRAINING olarak isaretlenir
2. O workera ait tum aktif segmentler QUEUED durumuna dondurulur
3. Segmentlerin attempt_numberi artirilir
4. Max attempt gecilmemis segmentler FAILED olur
5. Scheduler kalan segmentleri baska workerlara dagitir

### 2.7 Sonuc Toplama (Result Aggregation)

1. Her segment kendi outputunu S3'e yukler
2. Master, tum segmentler COMPLETE oldugunda concat jobini baslatir
3. Concat jobi ayri bir workerda calisir
4. Sonuc checksum dogrulamasi yapilir
5. Final output path joba yazilir

Concat stratejisi:
- Homojen segmentler: ffmpeg concat demuxer (lossless, < 1 saniye)
- Heterojen segmentler: Yeniden encode ederek birlestirme
- Transition varsa: xfade filter ile birlestirme

### 2.8 Veri Yapilari

```python
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4

class WorkerStatus(str, Enum):
    REGISTERED = 'registered'
    READY = 'ready'
    BUSY = 'busy'
    UNHEALTHY = 'unhealthy'
    DRAINING = 'draining'
    DRAINED = 'drained'
    DEREGISTERED = 'deregistered'

class WorkerCapabilities(BaseModel):
    gpu_model: Optional[str] = None
    gpu_vram_gb: Optional[float] = None
    gpu_encoders: List[str] = []
    gpu_decoders: List[str] = []
    cpu_cores: int
    cpu_threads: int
    memory_gb: float
    disk_total_gb: float
    disk_available_gb: float
    os_type: str = 'linux'
    ffmpeg_version: str
    ffmpeg_codecs: List[str] = []
    ffmpeg_filters: List[str] = []

    def has_encoder(self, encoder): return encoder in self.gpu_encoders or encoder in self.ffmpeg_codecs

class RenderWorker(BaseModel):
    worker_id: str
    hostname: str
    status: WorkerStatus = WorkerStatus.REGISTERED
    capabilities: WorkerCapabilities
    current_load: int = 0
    max_concurrency: int
    registered_at: datetime = Field(default_factory=datetime.utcnow)
    last_heartbeat: datetime = Field(default_factory=datetime.utcnow)
    total_jobs_completed: int = 0
    total_jobs_failed: int = 0
    average_fps: float = 0.0
    tags: Dict[str, str] = {}

    def load_pct(self):
        if self.max_concurrency == 0: return 100.0
        return (self.current_load / self.max_concurrency) * 100

class FrameAssignment(BaseModel):
    assignment_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    segment_id: str
    worker_id: str
    assigned_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = 'assigned'
    attempt_number: int = 0
    result_path: Optional[str] = None
    error_message: Optional[str] = None
```

### 2.9 API Sozlesmeleri (Distributed Rendering)

| Endpoint | Method | Aciklama |
|----------|--------|----------|
| /api/v1/workers/register | POST | Worker kaydi |
| /api/v1/workers/{id}/heartbeat | POST | Worker heartbeat |
| /api/v1/workers | GET | Tum worker listesi |
| /api/v1/workers/{id} | GET | Worker detay |
| /api/v1/workers/{id}/drain | POST | Worker drain et |
| /api/v1/assignments/{job_id} | GET | Job atamalarini getir |

### 2.10 Dar Bogazlar ve Cozumler

| Dar Bogaz | Cozum |
|-----------|-------|
| Master tek nokta hatasi | Master replikasi + leader election (etcd / PostgreSQL advisory lock) |
| Worker registration race condition | Worker ID bazli upsert, distributed lock |
| Segment dagitiminda gecikme | Pre-fetch: worker bosaldiginda bir sonraki segmenti onceden hazirla |
| Concat dar bogazi | Concat isleri icin ayri bir yuksek oncelikli queue |
| Network bandwidth (segment transfer) | Workera S3 signed URL ver, master uzerinden aktarma |
| Clock skew (heartbeat degerlendirme) | Master zamanini referans al, NTP dogrulamasi |

---

## 3. Worker Pool

### 3.1 Amac

Worker pool, render workerlarinin yasam dongusunu, olceklenmesini, kaynak izlemesini ve gorev dagilimini yonettir. GPU ve CPU workerlarini ayristirir, her worker tipi icin affinity kurallari belirler. Horizontal auto-scaling ile worker sayisini talebe gore dinamik olarak ayarlar.

### 3.2 Worker Yasam Dongusu Yonetimi

Worker durum makinesi: INIT -> WARM_UP -> READY -> BUSY -> COOL_DOWN -> SHUTDOWN

| Event | Tetikleyici | Aksiyon |
|-------|-------------|---------|
| INIT | Worker start | GPU probe, FFmpeg version check, disk mount check |
| WARM_UP | Probe basarili | Test encode (1s 1080p), cache warming, capability register |
| READY | Self-test gecti | Master'a register ol, heartbeat baslat |
| BUSY | Task assignment | FFmpeg process baslat, heartbeat'e progress ekle |
| COOL_DOWN | Task complete | Temp file cleanup, GPU memory cache clear, process group kill |
| SHUTDOWN | SIGTERM / scale-in | Drain active tasks, cleanup workspace, deregister |

### 3.3 Worker Olceklendirme (Horizontal Auto-Scaling)

Auto-scaling metrikleri:

| Metrik | Kaynak | Scale Up Threshold | Scale Down Threshold |
|--------|--------|-------------------|---------------------|
| Queue depth (pending jobs) | Redis / PostgreSQL | > 50 | < 10 |
| Average wait time | Job scheduler | > 30 s | < 5 s |
| Worker load p95 | Worker heartbeat | > %80 | < %30 |
| GPU utilization | nvidia-smi | > %85 | < %40 |
| CPU utilization | /proc/stat | > %75 | < %30 |

Scale-down guard: Worker'da aktif job varsa scale-down engellenir. Drain timeout: 300 saniye. Minimum replica: 2. Scale-down cooldown: 300 saniye.

### 3.4 Worker Kaynak Izleme (Resource Monitoring)

Her worker asagidaki metrikleri toplar ve master'a raporlar:

- CPU: cpu_percent, cpu_temperature, load_average
- GPU: gpu_utilization_pct, gpu_memory_used_mb, gpu_temperature, gpu_power_watts
- Memory: memory_used_mb, memory_total_mb, memory_percent
- Disk: disk_used_gb, disk_total_gb, disk_percent, disk_iops
- Network: network_rx_mbps, network_tx_mbps
- Render: active_segments, completed_segments_total, current_fps

### 3.5 Worker Isinma ve Soguma (Warm-Up & Cool-Down)

**Isinma proseduru (~15-30 saniye):**
1. GPU memory allocation test (100MB CUDA malloc/free)
2. Test encode: 1 saniyelik 1080p video -> libx264 + h264_nvenc
3. Test decode: mevcut bir test videosunu decode et
4. Disk write benchmark: 1GB random write, latency test
5. Network latency test: master'a ping, S3 upload test (1MB)
6. Cache warming: sik kullanilan fontlari, lut dosyalarini, filter graph templatelerini load et
7. Capability register: tum test sonuclarini master'a bildir

**Soguma proseduru (~5 saniye):**
1. FFmpeg process groupunu sonlandir (SIGTERM -> 5s -> SIGKILL)
2. Workspace gecici dosyalarini temizle
3. GPU memory cache temizligi (cudaDeviceReset)
4. Python/CUDA context release
5. Disk cache drop (varsa)
6. Segment sonuc raporu master'a gonder

### 3.6 GPU vs CPU Worker Ayrimi

| Ozellik | GPU Worker | CPU Worker |
|---------|-----------|------------|
| Kullanim | NVENC encode, CUDA filter, AI inference | libx264, libx265, software filter |
| Concurrency | 1-2 (GPU memorye bagli) | CPU core sayisina bagli |
| Isletim sistemi | Linux (NVIDIA driver) | Linux / Windows |
| Filter capability | scale_cuda, yadif_cuda, nvcomp | scale, yadif, tpad (software) |
| Guc tuketimi | 300-400W (A100) | 150-250W (high-end CPU) |
| Maliyet | $1-2/saat (bulut) | $0.5-1/saat (bulut) |

GPU worker allocation rules:
- 4K+ cozunurluk -> GPU (NVENC)
- AV1 codec -> GPU (AV1 NVENC)
- Motion blur, glow gibi agir filterlar -> GPU (CUDA filter)
- TensorRT model inference -> GPU

CPU worker allocation rules:
- 1080p alti cozunurluk -> CPU
- libx265 encode -> CPU (GPU genelde dusuk kalite)
- Complex filter graph (10+ filter) -> CPU
- Concatenation / remux -> CPU

### 3.7 Worker Affinity

Belirli is turleri belirli workerlara yonlendirilebilir:

| Affinity Kurali | Is Turu | Hedef Worker Pool |
|----------------|----------|-------------------|
| gpu_required | 4K render, AV1, AI efektleri | GPU pool |
| cpu_preferred | Basit kirpma, concat, thumbnail | CPU pool |
| batch_affinity | Gece batch isleri | Batch-optimized pool |
| tenant_affinity | Belirli tenantin isleri | Tenant-dedicated pool |
| region_affinity | GDPR/bolge kisitlamasi | Region-specific pool |
| codec_affinity | Apple ProRes, DNxHD | Windows pool |

### 3.8 Veri Yapilari

```python
class WorkerPool(BaseModel):
    pool_id: str
    pool_type: str   # gpu, cpu, windows, batch
    min_workers: int = 2
    max_workers: int = 20
    current_workers: int = 0
    workers: Dict[str, RenderWorker] = {}
    average_load_pct: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def get_available_workers(self):
        return [w for w in self.workers.values()
                if w.status in (WorkerStatus.READY, WorkerStatus.BUSY)
                and w.load_pct() < 100]

class WorkerHealth(BaseModel):
    worker_id: str
    status: WorkerStatus
    last_heartbeat: datetime
    is_gpu_healthy: bool = True
    is_disk_healthy: bool = True
    is_network_healthy: bool = True
    is_ffmpeg_healthy: bool = True
    health_score: float = 1.0

    def compute_health_score(self):
        score = 1.0
        if not self.is_gpu_healthy: score *= 0.5
        if not self.is_disk_healthy: score *= 0.3
        if not self.is_ffmpeg_healthy: score *= 0.0
        self.health_score = round(score, 2)
        return self.health_score

class WorkerMetric(BaseModel):
    worker_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    cpu_percent: float
    gpu_utilization_pct: Optional[float] = None
    gpu_memory_used_mb: Optional[float] = None
    memory_percent: float
    disk_percent: float
    active_segments: int
    current_fps: Optional[float] = None
```

### 3.9 API Sozlesmeleri (Worker Pool)

| Endpoint | Method | Aciklama |
|----------|--------|----------|
| /api/v1/pools | GET | Pool listesi |
| /api/v1/pools/{id} | GET | Pool detay |
| /api/v1/pools/{id}/scale | POST | Manuel scale |
| /api/v1/pools/{id}/workers | GET | Pool'daki workerlar |
| /api/v1/pools/{id}/metrics | GET | Pool metrikleri |

### 3.10 Dar Bogazlar ve Cozumler

| Dar Bogaz | Cozum |
|-----------|-------|
| GPU memory oversubscription | VRAM estimation + admission control, is basi VRAM limiti |
| Worker startup latency (warm-up) | Pre-warmed worker buffer pool (2-3 her zaman hazir) |
| Scale-up latency (yeni worker boot) | VM image snapshot, container image layer caching |
| GPU worker idle cost | Spot/preemptible instance kullanimi, scale-to-zero (batch pool) |
| Resource fragmentation | Bin-packing algorithm, worker bazli capability-based scheduling |

---

## 4. Is Zamanlayicisi (Job Scheduler)

### 4.1 Amac

Is zamanlayicisi, render islerini workerlara en verimli sekilde atamak icin priority queue, fair scheduling, deadline-aware scheduling ve resource-aware scheduling algoritmalarini uygular. Kaynaklarin asiri yuklenmesini engeller, tenantlar arasi adil dagitim saglar ve deadlinei yaklasan islere oncelik verir.

### 4.2 Priority Queue Scheduling

Cok seviyeli priority queue:
URGENT (P0, preemptive) -> NORMAL (P1, weighted RR) -> LOW (P2, background) -> BACKGROUND (P3, batch only)

Scheduling algoritmasi (multi-level feedback queue):
Her tick'te:
  1. URGENT queue bos degilse -> URGENT'ten al
  2. URGENT bossa NORMAL queue'dan al (weighted round-robin)
  3. NORMAL bossa LOW queue'dan al
  4. LOW bossa BACKGROUND queue'dan al

Preemption:
  - URGENT job geldiginde BACKGROUND veya LOW job preempt edilebilir
  - NORMAL job ancak kullanici onayi ile preempt edilir
  - Preempt edilen job QUEUED durumuna doner, attempt sayisi artmaz

### 4.3 Adil Zamanlama (Weighted Round-Robin Per User/Project)

Her tenant/proje icin agirlikli kuyruk:
Tenant A (weight: 3) -> 3 job | Tenant B (weight: 1) -> 1 job | Tenant C (weight: 2) -> 2 job
Her cycle: [A, B, A, C, A, C] (toplam 6 job)

Weight assignment: Varsayilan weight: 1 | Premium tenant: 2-5 | Kurumsal tenant: 5-10

### 4.4 Deadline-Aware Scheduling

Deadlinei yaklasan islere oncelik veren scheduling:
Urgency Score = (scheduler_current_time - job_created_at) / (job_deadline - job_created_at)
Score > 0.8 -> critical (priority gecici yukseltme)
Score > 0.5 -> warning (normal scheduling)
Score < 0.5 -> relaxed (arka plan)

### 4.5 Kaynak Bilincli Zamanlama (Resource-Aware Scheduling)

Kaynak bazli scheduling, workerlarin asiri yuklenmesini engeller:
- GPU Memory: Workerin kullanilabilir VRAM'i jobin VRAM ihtiyacindan buyuk olmali
- CPU Cores: Workerda kullanilabilir core sayisi jobin ihtiyacindan buyuk olmali
- Scratch Disk: Workerda kullanilabilir disk jobin tahmini scratch ihtiyacindan buyuk olmali

Kaynak tahmini formulleri:

```python
def estimate_vram(resolution, codec, fps, concurrent_segments=1):
    base = {'480p': 0.5, '720p': 1.0, '1080p': 2.0, '1440p': 4.0, '2160p': 8.0}
    codec_factor = {'h264': 1.0, 'hevc': 1.5, 'av1': 2.0}.get(codec, 1.0)
    return base.get(resolution, 2.0) * codec_factor * (fps / 30.0) * concurrent_segments
```

### 4.6 Oncelik Kestirme (Preemption Support)

Preemptor -> Preemptee -> Kosul:
URGENT -> BACKGROUND veya LOW -> Her zaman
URGENT -> NORMAL -> Tenant ayni degilse
NORMAL -> BACKGROUND -> Deadline < 30 dk
Tenant-A (weight 5) -> Tenant-B (weight 1) -> Tenant-A kotasini astiysa

Preemption flow:
1. Preemptor job siraya girer, kaynak yok
2. Scheduler preempt edilecek isleri secer
3. Preemptee joba CANCELLING sinyali gonderilir
4. Preemptee worker checkpoint kaydeder (varsa)
5. Preemptee QUEUED durumuna doner
6. Preemptor kaynagi alir ve baslar

### 4.7 Zamanlama Goruntuleme (Schedule Visualization)

Scheduler durumu, kuyruk derinlikleri, worker kullanim oranlari, deadline pressure ve aktif preemptionlar bir dashboard uzerinden izlenebilir.

API endpoint: GET /api/v1/scheduler/visualization -> HTML/Mermaid timeline

### 4.8 Veri Yapilari

```python
from enum import Enum
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import uuid4

class SchedulerPolicy(str, Enum):
    FIFO = 'fifo'
    PRIORITY = 'priority'
    WEIGHTED_ROUND_ROBIN = 'weighted_round_robin'
    DEADLINE_AWARE = 'deadline_aware'
    RESOURCE_AWARE = 'resource_aware'
    HYBRID = 'hybrid'

class ResourceQuota(BaseModel):
    tenant_id: str
    max_concurrent_jobs: int = 5
    max_gpu_jobs: int = 3
    max_vram_gb: float = 16.0
    max_scratch_gb: float = 100.0
    priority_weight: int = 1
    daily_job_limit: int = 100
    daily_jobs_used: int = 0

class ScheduleSlot(BaseModel):
    slot_id: str = Field(default_factory=lambda: str(uuid4()))
    worker_id: str
    pool_id: str
    job_id: Optional[str] = None
    reserved_vram_gb: float = 0
    reserved_scratch_gb: float = 0
    status: str = 'free'
    reserved_at: Optional[datetime] = None

    def is_free(self): return self.status == 'free'

class SchedulerState(BaseModel):
    policy: SchedulerPolicy = SchedulerPolicy.HYBRID
    queues: Dict[str, List] = {}
    slots: Dict[str, List[ScheduleSlot]] = {}
    active_assignments: Dict[str, ScheduleSlot] = {}
    tenant_quotas: Dict[str, ResourceQuota] = {}
    tenant_weights: Dict[str, int] = {}
    total_jobs_scheduled: int = 0
    total_preemptions: int = 0
```

### 4.9 Job Scheduler - Python Uygulamasi

```python
'''
Job Scheduler - Core scheduling engine.
Hybrid policy: priority + weighted RR + deadline + resource-aware.
'''
import asyncio, logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

class JobScheduler:
    def __init__(self, queue_manager, worker_pool, db):
        self._queue = queue_manager
        self._pool = worker_pool
        self._db = db
        self._state = SchedulerState()
        self._running = False
        self._interval = 2.0

    async def start(self):
        self._running = True
        logger.info('Job scheduler started (interval=%.1fs)', self._interval)
        while self._running:
            await self._schedule_cycle()
            await asyncio.sleep(self._interval)

    async def stop(self):
        self._running = False

    async def _schedule_cycle(self):
        try:
            await self._refresh_queues()
            await self._update_tenant_weights()
            deadline_pressure = self._compute_deadline_pressure()
            slots = self._collect_available_slots()
            if not slots: return
            assignments = self._select_jobs_for_slots(slots, deadline_pressure)
            for job, slot in assignments:
                await self._assign_job_to_slot(job, slot)
        except Exception as e:
            logger.error('Schedule cycle error: %s', e)

    async def _refresh_queues(self):
        for priority in ['urgent', 'normal', 'low', 'background']:
            jobs = await self._queue.get_next_ready_jobs(limit=100, priority=priority)
            self._state.queues[priority] = jobs

    def _compute_deadline_pressure(self):
        pressure = {}
        now = datetime.utcnow().timestamp()
        for priority in self._state.queues.values():
            for job in priority:
                deadline = job.spec_json.get('deadline')
                if deadline:
                    created = job.created_at.timestamp()
                    dead = datetime.fromisoformat(deadline).timestamp()
                    if dead > created:
                        pressure[job.job_id] = min(1.0, max(0.0, (now - created) / (dead - created)))
        return pressure

    def _collect_available_slots(self):
        slots = []
        for pool in self._pool.values():
            for worker in pool.get_available_workers():
                for _ in range(worker.max_concurrency - worker.current_load):
                    slots.append(ScheduleSlot(worker_id=worker.worker_id, pool_id=pool.pool_id))
        return slots

    def _select_jobs_for_slots(self, slots, deadline_pressure):
        order = {'urgent': 0, 'normal': 1, 'low': 2, 'background': 3}
        scored = []
        for pname, jobs in self._state.queues.items():
            base = order.get(pname, 99)
            for job in jobs:
                dscore = deadline_pressure.get(job.job_id, 0.0)
                weight = self._state.tenant_weights.get(job.tenant_id, 1)
                score = base * 1000 - dscore * 500 - weight * 10
                scored.append((score, job))
        scored.sort(key=lambda x: x[0])
        assignments, si = [], 0
        for _, job in scored:
            if si >= len(slots): break
            assignments.append((job, slots[si])); si += 1
        return assignments

    async def _assign_job_to_slot(self, job, slot):
        slot.job_id = job.job_id; slot.status = 'occupied'
        self._state.active_assignments[job.job_id] = slot
        await self._queue.transition_job(job.job_id, RenderJobStatus.RENDERING)
        self._state.total_jobs_scheduled += 1
        logger.info('Job %s -> worker %s', job.job_id, slot.worker_id)
```

### 4.10 API Sozlesmeleri (Job Scheduler)

| Endpoint | Method | Aciklama |
|----------|--------|----------|
| /api/v1/scheduler/status | GET | Scheduler durumu |
| /api/v1/scheduler/policy | PUT | Policy degistir |
| /api/v1/scheduler/queues | GET | Kuyruk derinlikleri |
| /api/v1/tenants/{id}/quota | GET | Tenant kotasi |
| /api/v1/tenants/{id}/quota | PUT | Tenant kota guncelleme |

### 4.11 Dar Bogazlar ve Cozumler

| Dar Bogaz | Cozum |
|-----------|-------|
| Schedule cycle latency (cok job) | Partition schedule: her pool ayri schedule thread |
| Priority inversion | Preemption + GPU memory checkpoint/restore |
| Fairness ihlali (tenant starvasyonu) | Weighted RR + minimum resource guarantee (min 1 slot/tenant) |
| Resource estimation hatasi (VRAM tasmasi) | Actual usage monitoring + dynamic estimation adjustment |
| Deadline drift | Deadline buffer: internal deadline = user deadline - %%10 |

---

## 5. Asset Yoneticisi (Asset Manager)

### 5.1 Amac

Asset yoneticisi, video, ses, goruntu ve metadata gibi tum medya varliklarinin yasam dongusunu yonetti. Icerik adresli depolama (CAS) ile deduplikasyon saglar, varliklarin format/codec/cozunurluk gibi metadata'larini tutar, versiyonlama yapar ve proxy (thumbnail, low-res preview) uretim pipeline'ini yonetti.

### 5.2 Asset Yasam Dongusu

IMPORTING -> PROCESSING -> ACTIVE -> ARCHIVE veya DELETE

| Durum | Aciklama | Retention |
|-------|----------|-----------|
| IMPORTING | Dosya yukleniyor, gecici storageda | Upload timeout: 1 saat |
| PROCESSING | Checksum dogrulama, metadata cikarma, proxy uretimi | - |
| ACTIVE | Kullanima hazir, hot storageda | Tenant politikasina bagli (varsayilan: 30 gun) |
| ARCHIVED | Cold storageda (S3 Glacier / GCS Archive) | Tenant politikasina bagli (varsayilan: 1 yil) |
| DELETED | Soft delete, metadata tutulur | 7 gun (sonra hard delete) |

### 5.3 Asset Metadata

Her asset icin kapsamli metadata saklanir:
- Dosya: filename, size_bytes, mime_type, sha256, md5
- Video: duration, width, height, dar, fps, bitrate, codec, profile, pixel_format, color_space
- Audio: has_audio, audio_codec, audio_bitrate, audio_sample_rate, audio_channels
- Streams: video_streams, audio_streams, subtitle_streams
- Container: container (mp4, mov, mkv), is_faststart
- Generated: scene_count, black_detected, has_silence, is_interlaced, is_corrupt

### 5.4 Asset Versiyonlama

Her asset version takip eder. Her versiyon: version_id, asset_id, version_number, sha256, size_bytes, storage_key, storage_backend, metadata, change_reason, created_by, created_at, is_latest icerir.

Version retention policy: Varsayilan: son 5 version saklanir. Tenant ayari: 1-100 version. Eski versionlarin storage'i archive'e tasinir.

### 5.5 Asset Deduplikasyonu (Content Hash)

Deduplication, ayni icerigin tekrar storage'a yazilmasini engeller:

Upload flow:
1. Istemci SHA-256 hash gonderir (Content-Digest header)
2. Asset Manager hashi kontrol eder:
   a. Varsa -> mevcut assete referans dondur (instant)
   b. Yoksa -> yeni upload baslat
3. Upload tamamlaninca hash dogrulanir
4. Hash cakismasi varsa -> yeni version olarak kaydedilir

Storage path format (CAS): s3://bucket/assets/{sha256[:2]}/{sha256[2:4]}/{sha256}.mp4

### 5.6 Proxy Uretim Pipelinei

Her asset icin otomatik proxy (thumbnail, low-res preview) uretilir:

Full Resolution (4K) -> Scene Detection -> Keyframes -> Thumbnails (320x180, JPG)
Full Resolution (4K) -> Transcode -> Proxy 1080p (libx264, CRF 28)
Full Resolution (4K) -> Transcode -> Proxy 720p (libx264, CRF 30)
Full Resolution (4K) -> Waveform -> Audio visualization (PNG)
Full Resolution (4K) -> Analyze -> Scene list (JSON)

### 5.7 Depolama Backend Soyutlamasi

Asset manager, depolama backend'ini soyutlar. Desteklenen backend'ler: S3 (AWS, MinIO), GCS (Google Cloud Storage), Azure Blob Storage, Local (yerel disk).

Her backend asagidaki arayuzu uygular:
- upload(local_path, remote_key, content_type) -> str
- download(remote_key, local_path) -> str
- delete(remote_key) -> bool
- exists(remote_key) -> bool
- get_signed_url(remote_key, expires_in) -> str
- get_metadata(remote_key) -> dict

### 5.8 Veri Yapilari

```python
class Asset(BaseModel):
    asset_id: str = Field(default_factory=lambda: str(uuid4()))
    tenant_id: str
    sha256: str
    original_filename: str
    mime_type: str
    size_bytes: int
    status: str = 'importing'
    metadata: Optional[AssetMetadata] = None
    versions: List[AssetVersion] = []
    proxy_keys: Dict[str, str] = {}
    tags: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class AssetMetadata(BaseModel):
    filename: str
    size_bytes: int
    mime_type: str
    sha256: str
    duration_seconds: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    bitrate_kbps: Optional[int] = None
    codec: Optional[str] = None
    pixel_format: Optional[str] = None
    has_audio: bool = False
    audio_codec: Optional[str] = None
    container: Optional[str] = None

class AssetVersion(BaseModel):
    version_id: str = Field(default_factory=lambda: str(uuid4()))
    asset_id: str
    version_number: int
    sha256: str
    size_bytes: int
    storage_key: str
    storage_backend: str
    metadata: AssetMetadata
    change_reason: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_latest: bool = True

class StorageBackend(ABC):
    @abstractmethod
    async def upload(self, local_path, remote_key, content_type='application/octet-stream'): ...
    @abstractmethod
    async def download(self, remote_key, local_path): ...
    @abstractmethod
    async def delete(self, remote_key): ...
    @abstractmethod
    async def exists(self, remote_key): ...
    @abstractmethod
    async def get_signed_url(self, remote_key, expires_in=3600): ...
```

### 5.9 API Sozlesmeleri (Asset Manager)

| Endpoint | Method | Aciklama |
|----------|--------|----------|
| /api/v1/assets | POST | Asset import (multipart upload) |
| /api/v1/assets/{id} | GET | Asset metadata |
| /api/v1/assets/{id}/versions | GET | Version gecmisi |
| /api/v1/assets/{id}/download | GET | Asset download (signed URL) |
| /api/v1/assets/{id} | DELETE | Soft delete |
| /api/v1/assets/dedup-check | POST | Hash ile dedup kontrol |
| /api/v1/assets/query | GET | Asset sorgulama (metadata filter) |

### 5.10 Dar Bogazlar ve Cozumler

| Dar Bogaz | Cozum |
|-----------|-------|
| Large file upload timeout (50GB+) | Multipart upload + presigned URL + resumable upload |
| Metadata extraction latency (4K video) | Async ffprobe + caching, stream metadataya oncelik ver |
| Proxy generation storage cost | Generation on-demand (first request), cache with TTL |
| Cross-region S3 transfer cost | Edge cache + origin shield, region-pinned bucket |
| Concurrent dedup check race | Atomic check-and-set, Redis lock with TTL |

---

## 6. Onbellek Yoneticisi (Cache Manager)

### 6.1 Amac

Onbellek yoneticisi, multi-tier caching sistemi ile render islemlerini hizlandirir. Sik kullanilan medya dosyalarini, proxyleri, analiz sonuclarini ve render ara ciktilarini memory -> SSD -> HDD -> Cloud hiyerarsisinde onbellege alir. Cache eviction, invalidation, warming ve monitoring bu katmanda yonettir.

### 6.2 Cok Katmanli Cache Hiyerarsisi

```
+------------------------------------------------------------------+
|                    L1: MEMORY (RAM)                              |
| Kapasite: 10-50 GB                                               |
| Gecikme: < 1ms                                                    |
| Icerik: Metadata, scene list, thumbnail, font cache              |
| Cikarma: LRU                                                      |
+----------------------------------+-------------------------------+
                                   |
                                   v
+------------------------------------------------------------------+
|                    L2: SSD (NVMe)                                |
| Kapasite: 500 GB - 2 TB                                          |
| Gecikme: 10-100us                                                 |
| Icerik: Proxy files, render intermediates, segment outputs       |
| Cikarma: LFU + TTL                                                |
+----------------------------------+-------------------------------+
                                   |
                                   v
+------------------------------------------------------------------+
|                    L3: HDD                                        |
| Kapasite: 10-50 TB                                                |
| Gecikme: 5-20ms                                                   |
| Icerik: Full-res assets, older versions, batch outputs           |
| Cikarma: Size-based + TTL                                         |
+----------------------------------+-------------------------------+
                                   |
                                   v
+------------------------------------------------------------------+
|                    L4: CLOUD (S3/GCS/Azure)                      |
| Kapasite: Limitsiz                                                 |
| Gecikme: 50-500ms                                                  |
| Icerik: Cold data, archived assets, disaster recovery            |
+------------------------------------------------------------------+
```

Cache yonlendirme algoritmasi:
1. Istenen key once L1'de aranir (memory, ~1ms)
2. L1 miss -> L2'de aranir (SSD, ~100us)
3. L2 miss -> L3'te aranir (HDD, ~10ms)
4. L3 miss -> L4'ten getirilir ve L3'e yazilir (Cloud, ~200ms)
5. L3'ten L2'ye, L2'den L1'e promosyon (en sik kullanilanlar)

### 6.3 Cache Cikarma Politikalari (Eviction Policies)

| Policy | Aciklama | Kullanim |
|--------|----------|----------|
| LRU (Least Recently Used) | En uzun suredir kullanilmayani cikar | Memory cache (L1) |
| LFU (Least Frequently Used) | En az kullanilani cikar | SSD cache (L2) |
| TTL (Time To Live) | Suresi dolani cikar | Metadata, scene analysis |
| Size-based | En buyuk dosyalari cikar | HDD cache (L3) |

Hybrid eviction (varsayilan): LRU + LFU + TTL + size-based weighted scoring.
Dusuk skor = once cikarilir.

### 6.4 Cache Gecersiz Kilma (Invalidation)

| Strateji | Tetikleyici | Mekanizma |
|----------|-------------|-----------|
| File change detection | Inotify / Watchdog | Dosya degistiginde ilgili entryleri temizle |
| Manual invalidation | API call | Belirli bir key veya pattern temizleme |
| TTL expiration | Zaman asimi | Arka plan cleanup taski |
| Cache busting | Version increment | Asset yeni versionu -> eski cache entry gecersiz |
| Pub/Sub invalidation | Workerlar arasi | Redis pub/sub ile tum workerlara invalidation mesaji |

Cache invalidation flow:
Asset updated on S3 -> Asset Manager publishes cache.invalidate event (Redis pub/sub) -> All workers receive event -> Each worker checks its own cache layers -> Matching entries are evicted -> Next request re-fetches from origin (cache miss)

### 6.5 Cache Isitma (Warming)

Cache warming, render baslamadan once gerekli dosyalari onbellege yukler:
- Source video -> L2 (SSD), TTL: 1 saat
- Font files (subtitle icin) -> L1 (Memory), TTL: 24 saat
- LUT files (color grading icin) -> L2 (SSD), TTL: 24 saat
- Template files (lower third, end screen icin) -> L2 (SSD), TTL: 24 saat

Predictive warming: Gecmis is pattern'lerine gore bir sonraki islerin ihtiyac duyacagi assetleri tahmin eder ve onceden cache'e yukler.

### 6.6 Cache Istatistikleri ve Izleme

Her cache katmani icin:
- total_entries, total_size_bytes, max_size_bytes, usage_pct
- hits, misses, hit_ratio
- avg_latency_ms, p50/p95/p99_latency_ms
- evictions_total, evictions_last_hour
- warm_ops_total, warm_bytes_total
- invalidations_total

Prometheus metrikleri:
cache_hit_ratio{layer='l1'} 0.95
cache_size_bytes{layer='l2'} 1099511627776
cache_evictions_total{layer='l2'} 1245
cache_latency_ms{layer='l1',quantile='0.95'} 0.8

### 6.7 Workerlar Arasi Paylasimli Cache

Workerlar arasi cache paylasimi:
- L1: her worker'da local (private)
- L2: shared Redis cluster (tum workerlar erisebilir)
- L3: shared NFS/S3 (tum workerlar erisebilir)
- L4: origin storage

DistributedCache implementasyonu: get() tüm katmanlari sirayla dener, hit durumunda degeri ust katmanlara promover eder.

### 6.8 Veri Yapilari

```python
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field
from datetime import datetime
import time

class CacheLayer(str, Enum):
    L1_MEMORY = 'l1'
    L2_SSD = 'l2'
    L3_HDD = 'l3'
    L4_CLOUD = 'l4'

class CachePolicy(BaseModel):
    layer: CacheLayer
    max_size_bytes: int
    eviction_policy: str = 'lru'
    default_ttl_seconds: Optional[int] = 3600
    max_entry_size_bytes: int = 500 * 1024 * 1024
    prefetch_enabled: bool = False

class CacheEntry(BaseModel):
    key: str
    value_ref: str
    size_bytes: int
    content_type: str = 'application/octet-stream'
    created_at: float = Field(default_factory=time.time)
    last_accessed: float = Field(default_factory=time.time)
    access_count: int = 1
    expires_at: Optional[float] = None
    layer: CacheLayer = CacheLayer.L1_MEMORY

    def is_expired(self):
        if self.expires_at is None: return False
        return time.time() > self.expires_at

    def touch(self):
        self.last_accessed = time.time()
        self.access_count += 1

class CacheStats(BaseModel):
    layer: str
    total_entries: int = 0
    total_size_bytes: int = 0
    max_size_bytes: int = 0
    usage_pct: float = 0.0
    hits: int = 0
    misses: int = 0
    hit_ratio: float = 0.0
    avg_latency_ms: float = 0.0
    evictions_total: int = 0
    warm_ops_total: int = 0
    invalidations_total: int = 0

    def update_ratio(self):
        total = self.hits + self.misses
        self.hit_ratio = self.hits / total if total > 0 else 0.0
```

### 6.9 Cache Manager - Python Uygulamasi

```python
'''
Cache Manager - Multi-tier cache management.
'''
import asyncio, hashlib, heapq, logging, os, time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger(__name__)

class MemoryCacheLayer:
    '''L1: In-process memory cache. LRU eviction, bounded size.'''

    def __init__(self, max_size_bytes=10*1024**3, default_ttl=300):
        self._max_size = max_size_bytes
        self._current_size = 0
        self._default_ttl = default_ttl
        self._cache = OrderedDict()
        self._lock = asyncio.Lock()
        self._stats = CacheStats(layer='l1', max_size_bytes=max_size_bytes)

    async def get(self, key):
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.is_expired():
                self._stats.misses += 1
                if entry: await self._remove(key)
                return None
            entry.touch()
            self._cache.move_to_end(key)
            self._stats.hits += 1
            return entry.value_ref

    async def put(self, key, value, ttl=None, content_type='application/octet-stream'):
        async with self._lock:
            entry_size = len(value)
            if entry_size > 500*1024*1024: return False
            while self._current_size + entry_size > self._max_size:
                if not self._evict_one(): return False
            expires = (time.time() + (ttl or self._default_ttl)) if (ttl or self._default_ttl) else None
            entry = CacheEntry(key=key, value_ref=value, size_bytes=entry_size, expires_at=expires)
            if key in self._cache:
                old = self._cache.pop(key); self._current_size -= old.size_bytes
            self._cache[key] = entry; self._current_size += entry_size
            return True

    def _evict_one(self):
        if not self._cache: return False
        _, entry = self._cache.popitem(last=False)
        self._current_size -= entry.size_bytes
        self._stats.evictions_total += 1
        return True

    async def _remove(self, key):
        entry = self._cache.pop(key, None)
        if entry: self._current_size -= entry.size_bytes

    def get_stats(self):
        self._stats.total_entries = len(self._cache)
        self._stats.total_size_bytes = self._current_size
        self._stats.usage_pct = (self._current_size / self._max_size * 100) if self._max_size > 0 else 0
        self._stats.update_ratio()
        return self._stats

class SSDCacheLayer:
    '''L2: SSD/NVMe disk cache. LFU eviction, file-based storage.'''

    def __init__(self, cache_path, max_size_bytes=500*1024**3, default_ttl=3600):
        self._path = Path(cache_path); self._path.mkdir(parents=True, exist_ok=True)
        self._max_size = max_size_bytes; self._current_size = 0
        self._default_ttl = default_ttl
        self._entries = {}; self._lfu_heap = []
        self._stats = CacheStats(layer='l2', max_size_bytes=max_size_bytes)

    async def get(self, key):
        entry = self._entries.get(key)
        if entry is None or entry.is_expired():
            self._stats.misses += 1
            if entry: await self._remove(key)
            return None
        fp = self._path / entry.value_ref
        if not fp.exists():
            await self._remove(key); self._stats.misses += 1; return None
        entry.touch()
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, fp.read_bytes)
        self._stats.hits += 1
        return data

    async def put(self, key, value, ttl=None, content_type='application/octet-stream'):
        entry_size = len(value)
        if entry_size > self._max_size * 0.1: return False
        while self._current_size + entry_size > self._max_size:
            if not await self._evict_one(): return False
        fn = hashlib.sha256(key.encode()).hexdigest()
        fp = self._path / fn
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, fp.write_bytes, value)
        expires = (time.time() + (ttl or self._default_ttl)) if (ttl or self._default_ttl) else None
        entry = CacheEntry(key=key, value_ref=fn, size_bytes=entry_size, expires_at=expires, layer=CacheLayer.L2_SSD)
        self._entries[key] = entry; self._current_size += entry_size
        heapq.heappush(self._lfu_heap, (entry.access_count, key))
        return True

    async def _evict_one(self):
        if not self._lfu_heap: return False
        _, key = heapq.heappop(self._lfu_heap)
        entry = self._entries.pop(key, None)
        if entry:
            self._current_size -= entry.size_bytes
            fp = self._path / entry.value_ref
            if fp.exists(): fp.unlink()
            self._stats.evictions_total += 1
        return True

class DistributedCache:
    '''Workerlar arasi paylasimli cache.'''

    def __init__(self, redis_client, local_cache):
        self._local = local_cache
        self._shared_fs = SSDCacheLayer('/mnt/shared-cache')
        self._stats = CacheStats(layer='distributed')

    async def get(self, key):
        val = await self._local.get(key)
        if val: return val
        val = await self._shared_fs.get(key)
        if val:
            await self._local.put(key, val, ttl=300)
        return val

    async def put(self, key, value, layer='l2', ttl=None):
        if layer == 'l1': return await self._local.put(key, value, ttl=ttl)
        return await self._shared_fs.put(key, value, ttl=ttl)

    async def invalidate(self, key_pattern):
        await self._local.delete_pattern(key_pattern)
```

### 6.10 API Sozlesmeleri (Cache Manager)

| Endpoint | Method | Aciklama |
|----------|--------|----------|
| /api/v1/cache/stats | GET | Cache istatistikleri |
| /api/v1/cache/invalidate | POST | Cache gecersiz kilma |
| /api/v1/cache/warm | POST | Cache isitma (pre-warm) |
| /api/v1/cache/entries | GET | Cache entry listesi |
| /api/v1/cache/clear | POST | Tüm cache temizleme |

### 6.11 Dar Bogazlar ve Cozumler

| Dar Bogaz | Cozum |
|-----------|-------|
| Cache miss storm (yeni deploy sonrasi) | Cache warming + gradual rollout |
| L1 memory pressure (cok buyuk entry) | Max entry size limiti, large objects L2'ye yonlendir |
| Cache invalidation storm (toplu asset guncellemesi) | Rate limiting, batch invalidation, async cleanup |
| Cache stampede (aynı anda cok fazla miss) | Request coalescing (ayni key icin tek fetch) |
| L2 disk IOPS limiti | SSD'ler arasi sharding, IOPS provisioned SSD kullanimi |
| Cross-worker cache consistency | Eventual consistency modeli, TTL ile nihai tutarlilik |

---

## Referanslar

- [Video Engine SDD 00: System Architecture](.../video-engine-sdd/00-system-architecture.md)
- [Video Engine SDD 05: Execution, Storage, Delivery](.../video-engine-sdd/05-execution-storage-delivery.md)
- [Temporal.io Workflow Documentation](https://docs.temporal.io)
- [FFmpeg Filter Graph Documentation](https://ffmpeg.org/ffmpeg-filters.html)
- [AWS S3 Multipart Upload](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)

---

*Bu belge, Principal Media Infrastructure Engineer tarafindan hazirlanmistir. Production-grade media altyapisi icin kapsamli bir referans niteligi tasir.*

--- END OF DOCUMENT ---