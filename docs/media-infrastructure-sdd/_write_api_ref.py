#!/usr/bin/env python3
"""Script to generate the master API reference document."""

import os

OUTPUT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "11-api-contracts-master.md"
)

content = r"""# MASTER API REFERANS — Medya Altyapisi Sozlesme Belgesi

**Surum:** 3.0.0  
**Durum:** Uretimde Kullanima Hazir  
**Son Guncelleme:** 2026-07-16  
**Sorumlu:** Principal Media Infrastructure Engineer  

---

## Icindekiler

1. [Sistem Mimarisi Entegrasyon Haritasi](#1-sistem-mimarisi-entegrasyon-haritasi)
2. [Cekirdek Motor API (Modul 1)](#2-cekirdek-motor-api-modul-1)
3. [Islem Hatti API (Modul 2)](#3-islem-hatti-api-modul-2)
4. [Zeka API (Modul 3)](#4-zeka-api-modul-3)
5. [Tipografi ve Grafik API (Modul 4)](#5-tipografi-ve-grafik-api-modul-4)
6. [Ses API (Modul 5)](#6-ses-api-modul-5)
7. [Altyapi API (Modul 6)](#7-altyapi-api-modul-6)
8. [Eklenti API (Modul 7)](#8-eklenti-api-modul-7)
9. [Teslimat API (Modul 8)](#9-teslimat-api-modul-8)
10. [REST API Uclari (FastAPI)](#10-rest-api-uclari-fastapi)
11. [Veri Akis Diyagramlari](#11-veri-akis-diyagramlari)

---

# 1. Sistem Mimarisi Entegrasyon Haritasi

## 1.1 Tam Sistem Diyagrami

```
+-------------------------------------------------------------------------------+
|                           DIS CLI KATMANI                                      |
|                                                                               |
|  +-----------+  +--------------+  +------------+  +----------+  +----------+  |
|  | Web App   |  | Mobile Client|  | CLI Tool   |  | CI/CD    |  | 3. Party |  |
|  | (React)   |  | (Flutter)    |  | (Python)   |  | Pipeline |  | Integr.  |  |
|  +-----+-----+  +------+-------+  +-----+------+  +----+-----+  +----+-----+  |
|        |               |               |               |              |        |
+--------+---------------+---------------+---------------+--------------+--------+
         |               |               |               |              |
         v               v               v               v              v
+-------------------------------------------------------------------------------+
|                        API GATEWAY & AUTH LAYER                                |
|                                                                               |
|  +-------------------------------------------------------------------------+  |
|  |                    FastAPI Uygulama Sunucusu                              |  |
|  |  +-------------+ +-----------+ +------------+ +-----------+ +----------+ |  |
|  |  | JWT Auth    | | Rate      | | Request    | | WebSocket | | CORS     | |  |
|  |  | Middleware   | | Limiter   | | Validator  | | Manager   | | Handler  | |  |
|  |  +-------------+ +-----------+ +------------+ +-----------+ +----------+ |  |
|  |  +-------------+ +-----------+ +------------+ +-----------+              |  |
|  |  | Error       | | Logging   | | Metrics    | | Health    |              |  |
|  |  | Handler     | | Middleware| | Collector  | | Check     |              |  |
|  |  +-------------+ +-----------+ +------------+ +-----------+              |  |
|  +-------------------------------------------------------------------------+  |
+-------------------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------------------+
|                          MODUL 8: TESLIMAT API                                 |
|  +---------------+  +---------------+  +---------------+                       |
|  | Export API    |  | Storage API   |  | CDN API       |                       |
|  +-------+-------+  +-------+-------+  +-------+-------+                       |
+----------+-----------------+-----------------+---------------------------------+
           |                 |                 |
           v                 v                 v
+-------------------------------------------------------------------------------+
|                          MODUL 6: ALTYAPI API                                  |
|  +---------------+  +---------------+  +---------------+  +----------------+  |
|  | Render Queue  |  | Worker Pool   |  | Job Scheduler |  | Asset Manager  |  |
|  +-------+-------+  +-------+-------+  +-------+-------+  +-------+--------+  |
|          |                 |                 |                 |               |
|  +-------+-------+  +-------+-------+  +-------+-------+  +-------+--------+  |
|  | Cache Manager |  | Metrics       |  | Health        |  | Config         |  |
|  +---------------+  | Monitor       |  | Monitor       |  | Manager        |  |
|                     +---------------+  +---------------+  +----------------+  |
+-------------------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------------------+
|                     MODUL 7: EKLENTI API (Plugin SDK)                          |
|  +---------------+  +---------------+  +---------------+  +---------------+   |
|  | Plugin SDK    |  | Template SDK  |  | Theme API     |  | Preset API    |   |
|  +---------------+  +---------------+  +---------------+  +---------------+   |
+-------------------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------------------+
|   +-----------------------------------------------------------------------+   |
|   |                MODUL 1: CEKIRDEK MOTOR API                            |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   |  | Timeline    |  | Layer       |  | Effect    |  | Compositor     | |   |
|   |  | Operations  |  | Management  |  | Graph     |  |                | |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   +-----------------------------------------------------------------------+   |
|   +-----------------------------------------------------------------------+   |
|   |                MODUL 2: ISLEM HATTI API                               |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   |  | GPU         |  | FFmpeg      |  | Hardware  |  | Dynamic        | |   |
|   |  | Pipeline    |  | Filter Bld  |  | Encoding  |  | Crop           | |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   +-----------------------------------------------------------------------+   |
|   +-----------------------------------------------------------------------+   |
|   |                MODUL 3: ZEKA API                                      |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   |  | Face        |  | Scene       |  | Content   |  | Edit           | |   |
|   |  | Tracking    |  | Detection   |  | Analysis  |  | Decision       | |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   +-----------------------------------------------------------------------+   |
|   +-----------------------------------------------------------------------+   |
|   |          MODUL 4: TIPOGRAFI VE GRAFIK API                            |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   |  | Subtitle    |  | Karaoke     |  | Animation |  | Sticker        | |   |
|   |  | Engine      |  | System      |  | Engine    |  | Engine         | |   |
|   |  +-------------+  +-------------+  +-----------+  +----------------+ |   |
|   +-----------------------------------------------------------------------+   |
|   +-----------------------------------------------------------------------+   |
|   |                MODUL 5: SES API                                       |   |
|   |  +-------------+  +-------------+  +-----------+                       |   |
|   |  | Mixer       |  | Loudness    |  | Ducking   |                       |   |
|   |  +-------------+  +-------------+  +-----------+                       |   |
|   +-----------------------------------------------------------------------+   |
+-------------------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------------------+
|                        VERI DEPOLAMA KATMANI                                  |
|  +---------------+  +---------------+  +---------------+  +---------------+   |
|  | PostgreSQL    |  | Redis         |  | MinIO/S3      |  | Local FS      |   |
|  | (Metadata)    |  | (Cache/Queue) |  | (Assets)      |  | (Temp Files)  |   |
|  +---------------+  +---------------+  +---------------+  +---------------+   |
+-------------------------------------------------------------------------------+
```

## 1.2 Veri Akis Hatti

```
Giris Kaynagi          Analiz        Karar Verici        Uretici         Cikis
=============     ============   ===============   ============   ============
                  |           |   |              |   |           |   |          |
 Video Dosya ---> | Sahne     |-->| Kirtasiye    |-->| GPU       |-->| Hedef    |
                  | Tespiti   |   | Motoru       |   | Islem     |   | Format   |
                  |           |   |              |   |           |   |          |
 Audio Dosya ---> | Ses       |-->| Otomatik     |-->| FFmpeg    |-->| CDN      |
                  | Analizi   |   | Duzenleme    |   | Filtre    |   | Yukleme  |
                  |           |   |              |   |           |   |          |
 Webcam Akis ---> | Yuz       |-->| Alt Yazi     |-->| Hardware  |-->| Akis     |
                  | Takibi    |   | Senkron      |   | Kodlama   |   | Cikisi   |
                  |           |   |              |   |           |   |          |
 Screen Rec ---> | Icerik    |-->| Efekt Secimi |-->| Dinamik   |-->| Indirme  |
                  | Analizi   |   |              |   | Kirpma    |   |          |
                  ============   ===============   ============   ============
                       |                |                  |               |
                       v                v                  v               v
                  +----------------------------------------------------------+
                  |                    DEPOLAMA KATMANI                      |
                  |  Redis (Gecici)  |  PostgreSQL (Kalici)  |  S3 (Varliklar)|
                  +----------------------------------------------------------+
```

## 1.3 Modul Bagimlilik Grafigi

```
                        +---------------------+
                        |   Modul 1: Cekirdek |
                        |   Motor API         |
                        +----------+----------+
                                   |
                     +-------------+-------------+
                     |             |             |
                     v             v             v
           +----------+--+  +-----+-------+  +--+-----------+
           |  Modul 2:   |  |  Modul 3:   |  |  Modul 4:   |
           |  Islem      |  |  Zeka       |  |  Tipografi  |
           |  Hatti      |  |  API        |  |  ve Grafik  |
           +------+------+  +------+------+  +------+------+
                  |                |                |
                  |         +------+------+         |
                  |         |  Modul 5:   |         |
                  |         |  Ses API    |         |
                  |         +------+------+         |
                  |                |                |
                  +----------------+----------------+
                                   |
                                   v
                        +---------------------+
                        |  Modul 6: Altyapi   |
                        |  API                |
                        +----------+----------+
                                   |
                     +-------------+-------------+
                     |             |             |
                     v             v             v
           +----------+--+  +-----+-------+  +--+----------+
           |  Modul 7:   |  |  Modul 8:   |  |  REST API  |
           |  Eklenti    |  |  Teslimat   |  |  Uclari    |
           |  API        |  |  API        |  |            |
           +-------------+  +-------------+  +------------+
```

## 1.4 Baslatma Sirasi

| Sira | Modul                        | Baslatma Kriteri                          |
|------|------------------------------|-------------------------------------------|
| 1    | Config Manager               | Konfigurasyon dosyasi yuklendi             |
| 2    | Cache Manager                | Redis baglantisi kuruldu                   |
| 3    | PostgreSQL Adapter           | Veritabani baglantisi kuruldu              |
| 4    | S3/MinIO Adapter             | Nesne depolama baglantisi kuruldu          |
| 5    | Worker Pool                  | Is parcaciklari baslatildi                 |
| 6    | Render Queue                 | Kuyruk dinleyicisi baslatildi              |
| 7    | Job Scheduler                | Zamanlayici baslatildi                     |
| 8    | Metrics Collector            | Metrik toplama baslatildi                  |
| 9    | Plugin Manager               | Eklentiler yuklendi ve dogrulandi          |
| 10   | Timeline Engine              | Zaman cizelgesi motoru hazir               |
| 11   | Compositor                   | Kompozitor hazir                           |
| 12   | GPU Pipeline                 | GPU erisimi dogrulandi                     |
| 13   | FFmpeg Pipeline              | FFmpeg surumu dogrulandi                   |
| 14   | Intelligence Engine          | Zeka motoru modelleri yuklendi             |
| 15   | Typography Engine            | Tipografi motoru hazir                     |
| 16   | Audio Engine                 | Ses motoru hazir                           |
| 17   | API Gateway                  | HTTP ucleri baslatildi                     |
| 18   | WebSocket Manager            | Gercek zamanli iletisim hazir              |
| 19   | Health Monitor               | Saglik izleme baslatildi                   |
| 20   | Export Manager               | Disa aktarma motoru hazir                  |

## 1.5 Hata Yayilma Stratejisi

```
+--------------------------------------------------------------------------+
|                     HATA YAYILMA HIYERARSISI                             |
|                                                                          |
|  Seviye 0: Kritik Hata (Sistem cokme)                                   |
|  +- Tum isler durdurulur                                                 |
|  +- Alarm gonderilir (PagerDuty/Slack)                                   |
|  +- Otomatik yeniden baslatma denenir                                    |
|                                                                          |
|  Seviye 1: Is Hatti Hatasi (Tek bir is basarisiz)                        |
|  +- Is kuyrugundan kaldirilir                                            |
|  +- Yeniden deneme hakki tuketilir (varsayilan: 3)                       |
|  +- Bagli isler iptal edilir (cascading cancel)                          |
|  +- Istemciye WebSocket uzerinden bildirim                               |
|                                                                          |
|  Seviye 2: Islem Hatti Hatasi (GPU/FFmpeg hata)                          |
|  +- Alternatif isleyiciye gecis (CPU fallback)                           |
|  +- Dusuk cozunurlukte yeniden deneme                                    |
|  +- Hata raporu olusturulur                                              |
|  +- Modul 6'ya durum bildirilir                                          |
|                                                                          |
|  Seviye 3: Zeka Hatasi (Model/analiz hata)                               |
|  +- Varsayilan degerlerle devam                                          |
|  +- Manuel girdi iste                                                    |
|  +- Kalite dustu olarak isaretlenir                                      |
|                                                                          |
|  Seviye 4: Uyari (Non-fatal)                                             |
|  +- Log kaydi olusturulur                                                |
|  +- Metrik guncellenir                                                   |
|  +- Islem devam eder                                                     |
|                                                                          |
|  HATA YAKALAMA ZINCIRI:                                                  |
|                                                                          |
|  [Istek] -> [API Gateway] -> [Modul 8] -> [Modul 6] -> [Modul 1]       |
|      |           |              |           |           |                |
|      v           v              v           v           v                |
|  HTTP Error  401/403        502/503      500/500      422/400            |
|  Response    Auth Error     Pipeline     Internal     Validation         |
|                             Failure      Failure      Error              |
|                                                                          |
|  Merkezi Hata Yonetici: ErrorHandler                                     |
|  +- Tum hatalar ErrorHandler.from_exception() ile sarilir                |
|  +- Hata sinifi otomatik tespit edilir                                   |
|  +- Uygun HTTP durum kodu atanir                                        |
|  +- Istemciye anlamsal mesaj donulur                                     |
|  +- Detayli log olusturulur (traceback + context)                        |
|  +- Metrikleri guncellenir (hata_sayisi, hata_turu)                      |
+--------------------------------------------------------------------------+
```

---

# 2. Cekirdek Motor API (Modul 1 Referansi)

## 2.1 Zaman Cizelgesi Islemleri API

### 2.1.1 Timecode Sinifi

```python
class Timecode(BaseModel):
    """SMPTE zaman kodu temsili."""
    hours: int = Field(ge=0, le=23)
    minutes: int = Field(ge=0, le=59)
    seconds: int = Field(ge=0, le=59)
    frames: int = Field(ge=0, le=99)
    fps: float = Field(gt=0, default=30.0)

    def to_seconds(self) -> float: ...
    def to_frames(self) -> int: ...
    def to_timedelta(self) -> timedelta: ...

    @classmethod
    def from_seconds(cls, seconds: float, fps: float = 30.0) -> Timecode: ...
    @classmethod
    def from_frames(cls, frames: int, fps: float = 30.0) -> Timecode: ...
    @classmethod
    def from_string(cls, tc_string: str, fps: float = 30.0) -> Timecode: ...

    def __add__(self, other: Timecode) -> Timecode: ...
    def __sub__(self, other: Timecode) -> Timecode: ...
    def __lt__(self, other: Timecode) -> bool: ...
    def __le__(self, other: Timecode) -> bool: ...
    def __eq__(self, other: Timecode) -> bool: ...
```

### 2.1.2 TimeRange Sinifi

```python
class TimeRange(BaseModel):
    """Zaman araligi temsili (baslangic + sure)."""
    start: Timecode
    duration: Timecode

    @property
    def end(self) -> Timecode: ...
    def contains(self, time: Timecode) -> bool: ...
    def overlaps(self, other: TimeRange) -> bool: ...
    def intersection(self, other: TimeRange) -> Optional[TimeRange]: ...
    def union(self, other: TimeRange) -> TimeRange: ...
    def split_at(self, point: Timecode) -> tuple[TimeRange, TimeRange]: ...
```

### 2.1.3 PlaybackSpeed ve TimeRemap

```python
class PlaybackSpeed(BaseModel):
    """Oynatma hizi ayarlari."""
    rate: float = Field(gt=0, default=1.0, description="Oynatma hizi carpani")
    reverse: bool = Field(default=False, description="Ters oynatma")
    frame_interpolation: Literal["none", "blend", "optical_flow", "frame_doubling"] = "none"

    def apply(self, time: Timecode) -> Timecode: ...
    def inverse(self) -> PlaybackSpeed: ...


class TimeRemapMode(str, Enum):
    CONSTANT_SPEED = "constant_speed"
    VARIABLE_SPEED = "variable_speed"
    TIME_WARP = "time_warp"
    FREEZE_FRAME = "freeze_frame"


class TimeRemapKeyframe(BaseModel):
    time: Timecode
    speed: float = Field(gt=0)
    ease_in: str = "linear"
    ease_out: str = "linear"


class TimeRemap(BaseModel):
    """Klibin zaman yeniden haritalama ayarlari."""
    mode: TimeRemapMode = TimeRemapMode.CONSTANT_SPEED
    speed: PlaybackSpeed = Field(default_factory=PlaybackSpeed)
    keyframes: list[TimeRemapKeyframe] = Field(default_factory=list)
    reverse: bool = False

    def evaluate(self, time: Timecode) -> Timecode: ...
    def add_keyframe(self, time: Timecode, speed: float, ease: str = "linear") -> None: ...
    def remove_keyframe(self, time: Timecode) -> None: ...
```

### 2.1.4 Transform ve Destek Tipleri

```python
class Transform(BaseModel):
    """2D donusum parametreleri."""
    position_x: float = Field(default=0.0, description="Yatay konum (piksel)")
    position_y: float = Field(default=0.0, description="Dikey konum (piksel)")
    scale_x: float = Field(default=1.0, gt=0, description="Yatay olcekleme")
    scale_y: float = Field(default=1.0, gt=0, description="Dikey olcekleme")
    rotation: float = Field(default=0.0, description="Donme acisi (derece)")
    anchor_x: float = Field(default=0.0, description="Ancor noktasi X")
    anchor_y: float = Field(default=0.0, description="Ancor noktasi Y")
    skew_x: float = Field(default=0.0, description="Egiklik X")
    skew_y: float = Field(default=0.0, description="Egiklik Y")

    def to_matrix(self) -> list[list[float]]: ...
    def interpolate(self, target: Transform, progress: float) -> Transform: ...


class BlendMode(str, Enum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    DARKEN = "darken"
    LIGHTEN = "lighten"
    COLOR_DODGE = "color_dodge"
    COLOR_BURN = "color_burn"
    HARD_LIGHT = "hard_light"
    SOFT_LIGHT = "soft_light"
    DIFFERENCE = "difference"
    EXCLUSION = "exclusion"
    HUE = "hue"
    SATURATION = "saturation"
    COLOR = "color"
    LUMINOSITY = "luminosity"
    ADD = "add"
    SUBTRACT = "subtract"


class OpacityKeyframe(BaseModel):
    time: Timecode
    value: float = Field(ge=0.0, le=1.0)
    ease: str = "linear"


class Opacity(BaseModel):
    """Opaklik degeri ve animasyonu."""
    value: float = Field(ge=0.0, le=1.0, default=1.0)
    keyframes: list[OpacityKeyframe] = Field(default_factory=list)

    def evaluate(self, time: Timecode) -> float: ...
```

### 2.1.5 Timeline Sinifi

```python
class Timeline(BaseModel):
    """Ana zaman cizelgesi nesnesi."""
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=256)
    description: str = Field(default="", max_length=4096)
    fps: float = Field(gt=0, default=30.0)
    width: int = Field(gt=0, default=1920)
    height: int = Field(gt=0, default=1080)
    duration: Timecode
    created_at: str
    updated_at: str
    layers: list[Layer] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    # --- Olusturma ---
    @classmethod
    def create(cls, name: str, duration: Timecode, fps: float = 30.0,
               resolution: tuple[int, int] = (1920, 1080)) -> Timeline: ...
    @classmethod
    def from_template(cls, template_id: UUID, overrides: dict = {}) -> Timeline: ...
    @classmethod
    def from_edl(cls, edl_content: str) -> Timeline: ...
    @classmethod
    def from_xml(cls, xml_content: str) -> Timeline: ...
    @classmethod
    def from_json(cls, json_content: str) -> Timeline: ...

    # --- Temel Islemler ---
    def get_duration_frames(self) -> int: ...
    def get_duration_seconds(self) -> float: ...
    def get_time_at_frame(self, frame: int) -> Timecode: ...
    def get_frame_at_time(self, time: Timecode) -> int: ...
    def validate(self) -> list[str]: ...
    def deep_copy(self) -> Timeline: ...
    def normalize(self) -> Timeline: ...

    # --- Export ---
    def to_dict(self) -> dict: ...
    def to_json(self, indent: int = 2) -> str: ...
    def to_edl(self) -> str: ...
    def to_xml(self) -> str: ...
    def to_premiere_xml(self) -> str: ...
    def to_davinci_powergrade(self) -> dict: ...

    # --- Undo/Redo ---
    def create_snapshot(self) -> TimelineSnapshot: ...
    def restore_snapshot(self, snapshot: TimelineSnapshot) -> None: ...

    # --- Arama ---
    def find_layer(self, layer_id: UUID) -> Optional[Layer]: ...
    def find_clip(self, clip_id: UUID) -> Optional[Clip]: ...
    def find_effect(self, effect_id: UUID) -> Optional[EffectInstance]: ...
    def search_clips(self, query: str) -> list[Clip]: ...
    def get_clips_at_time(self, time: Timecode) -> list[Clip]: ...


class TimelineSnapshot(BaseModel):
    """Zaman cizelgesi anlik goruntusu (undo/icin)."""
    id: UUID = Field(default_factory=uuid4)
    timeline_id: UUID
    timestamp: str
    data: dict
    description: str = ""
```

### 2.1.6 TimelineOperations Sinifi

```python
class TimelineOperations:
    """Zaman cizelgesi uzerindeki temel islemler."""

    def __init__(self, timeline: Timeline): ...

    def split_clip(self, clip_id: UUID, at_time: Timecode, *,
                   ripple: bool = False) -> tuple[Clip, Clip]: ...
    def trim_clip(self, clip_id: UUID, *, in_point: Optional[Timecode] = None,
                  out_point: Optional[Timecode] = None,
                  ripple: bool = False) -> Clip: ...
    def move_clip(self, clip_id: UUID, target_layer_index: int,
                  target_time: Timecode, *, snap: bool = True,
                  collision_mode: Literal["push", "overwrite", "insert", "reject"] = "reject") -> Clip: ...
    def ripple_edit(self, clip_id: UUID, delta: Timecode) -> None: ...
    def roll_edit(self, clip_id_left: UUID, clip_id_right: UUID, delta: Timecode) -> None: ...
    def slip_edit(self, clip_id: UUID, delta: Timecode) -> Clip: ...
    def slide_edit(self, clip_id: UUID, delta: Timecode) -> Clip: ...
    def extract(self, time_range: TimeRange, layer_index: Optional[int] = None) -> list[Clip]: ...
    def lift(self, time_range: TimeRange, layer_index: Optional[int] = None) -> None: ...
    def insert_gap(self, at_time: Timecode, duration: Timecode, *,
                   all_layers: bool = True) -> None: ...
    def remove_gap(self, at_time: Timecode, *, all_layers: bool = True) -> None: ...
    def snap_to_grid(self, time: Timecode, grid_interval: Timecode) -> Timecode: ...
    def find_snap_points(self, time: Timecode, tolerance: Timecode) -> list[Timecode]: ...
    def match_frame(self, clip_id: UUID, direction: Literal["forward", "backward"]) -> Optional[Timecode]: ...
    def add_marker(self, time: Timecode, name: str, color: str = "#FF0000", notes: str = "") -> Marker: ...
    def remove_marker(self, marker_id: UUID) -> None: ...
    def get_markers(self, time_range: Optional[TimeRange] = None) -> list[Marker]: ...
    def render_preview(self, time_range: TimeRange, *, resolution: tuple[int, int] = (640, 360),
                       fps: float = 15.0) -> bytes: ...


class Marker(BaseModel):
    """Zaman cizelgesi isareti."""
    id: UUID = Field(default_factory=uuid4)
    time: Timecode
    name: str
    color: str = "#FF0000"
    notes: str = ""
    duration: Optional[Timecode] = None
    chapter_title: Optional[str] = None
```

## 2.2 Katman Yonetimi API

### 2.2.1 Layer Tipleri ve Temeller

```python
class LayerType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    GRAPHICS = "graphics"
    EFFECT = "effect"
    ADJUSTMENT = "adjustment"
    NULL = "null"


class LayerVisibility(BaseModel):
    visible: bool = True
    solo: bool = False
    locked: bool = False
    collapsed: bool = False
    opacity: Opacity = Field(default_factory=Opacity)


class LayerBlend(BaseModel):
    mode: BlendMode = BlendMode.NORMAL
    opacity: Opacity = Field(default_factory=Opacity)
    track_matte: Optional[UUID] = None
    track_matte_mode: Literal["alpha", "luma", "alpha_inverted", "luma_inverted"] = "alpha"
```

### 2.2.2 Layer Sinifi

```python
class Layer(BaseModel):
    """Zaman cizelgesi katmani."""
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=256)
    layer_type: LayerType
    index: int = Field(ge=0, description="Katman sirasi (0 = en ust)")
    visibility: LayerVisibility = Field(default_factory=LayerVisibility)
    blend: LayerBlend = Field(default_factory=LayerBlend)
    transform: Transform = Field(default_factory=Transform)
    clips: list[Clip] = Field(default_factory=list)
    effects: list[EffectInstance] = Field(default_factory=list)
    parent_id: Optional[UUID] = None
    children: list[UUID] = Field(default_factory=list)
    muted: bool = False
    solo: bool = False
    locked: bool = False
    color_label: Optional[str] = None
    custom_data: dict = Field(default_factory=dict)

    # --- Olusturma ---
    @classmethod
    def create_video_layer(cls, name: str, index: int) -> Layer: ...
    @classmethod
    def create_audio_layer(cls, name: str, index: int) -> Layer: ...
    @classmethod
    def create_subtitle_layer(cls, name: str, index: int) -> Layer: ...
    @classmethod
    def create_adjustment_layer(cls, name: str, index: int) -> Layer: ...
    @classmethod
    def create_null_layer(cls, name: str, index: int) -> Layer: ...

    # --- Clip Islemleri ---
    def add_clip(self, clip: Clip, position: Timecode) -> Clip: ...
    def remove_clip(self, clip_id: UUID) -> Optional[Clip]: ...
    def get_clip(self, clip_id: UUID) -> Optional[Clip]: ...
    def get_clips_in_range(self, time_range: TimeRange) -> list[Clip]: ...
    def get_clip_at_time(self, time: Timecode) -> Optional[Clip]: ...
    def move_clip(self, clip_id: UUID, new_position: Timecode) -> Clip: ...
    def order_clips(self, clip_ids: list[UUID]) -> None: ...

    # --- Efekt Islemleri ---
    def add_effect(self, effect: EffectInstance) -> EffectInstance: ...
    def remove_effect(self, effect_id: UUID) -> Optional[EffectInstance]: ...
    def move_effect(self, effect_id: UUID, new_index: int) -> EffectInstance: ...
    def get_effects(self) -> list[EffectInstance]: ...
    def toggle_effect(self, effect_id: UUID, enabled: bool) -> None: ...

    # --- Gorunurluk ---
    def toggle_visibility(self) -> bool: ...
    def toggle_solo(self) -> bool: ...
    def toggle_lock(self) -> bool: ...
    def set_opacity(self, value: float) -> None: ...
    def set_blend_mode(self, mode: BlendMode) -> None: ...

    # --- Hiyerarsi ---
    def set_parent(self, parent_id: Optional[UUID]) -> None: ...
    def add_child(self, child_id: UUID) -> None: ...
    def remove_child(self, child_id: UUID) -> None: ...
    def get_root_transform(self) -> Transform: ...

    # --- Dogrulama ---
    def validate(self) -> list[str]: ...
    def get_overlapping_clips(self) -> list[tuple[Clip, Clip]]: ...
    def get_total_duration(self) -> Timecode: ...
```

### 2.2.3 LayerOperations Sinifi

```python
class LayerOperations:
    """Katmanlar uzerindeki toplu islemler."""

    def __init__(self, timeline: Timeline): ...

    def add_layer(self, layer_type: LayerType, name: str,
                  index: Optional[int] = None) -> Layer: ...
    def remove_layer(self, layer_id: UUID) -> Optional[Layer]: ...
    def move_layer(self, layer_id: UUID, new_index: int) -> Layer: ...
    def duplicate_layer(self, layer_id: UUID, *, name: Optional[str] = None,
                        offset: Timecode = Timecode(hours=0, minutes=0, seconds=0, frames=0)) -> Layer: ...
    def merge_layers(self, layer_ids: list[UUID], *, name: str = "Merged",
                     render: bool = False) -> Layer: ...
    def flatten(self, *, time_range: Optional[TimeRange] = None,
                include_effects: bool = True) -> Layer: ...
    def get_layer(self, layer_id: UUID) -> Optional[Layer]: ...
    def get_layers_by_type(self, layer_type: LayerType) -> list[Layer]: ...
    def get_all_layers(self) -> list[Layer]: ...
    def reorder_layers(self, layer_ids: list[UUID]) -> None: ...
    def set_layer_color(self, layer_id: UUID, color: str) -> None: ...
```

## 2.3 Efekt Graf API

### 2.3.1 Efekt Tipleri

```python
class EffectType(str, Enum):
    COLOR_CORRECTION = "color_correction"
    BLUR = "blur"
    SHARPEN = "sharpen"
    DISTORT = "distort"
    STYLIZE = "stylize"
    GENERATE = "generate"
    PERSPECTIVE = "perspective"
    TIME = "time"
    OBSERVE = "observe"
    CHANNEL = "channel"
    NOISE = "noise"
    KEYING = "keying"
    WARP = "warp"
    STABILIZE = "stabilize"
    CUSTOM = "custom"
    LUT = "lut"
    GRAIN = "grain"
    VIGNETTE = "vignette"
    CHROMATIC_ABERRATION = "chromatic_aberration"
    GLITCH = "glitch"
```

### 2.3.2 Efekt Parametreleri ve Instancelar

```python
class EffectParameter(BaseModel):
    """Efekt parametresi tanimi."""
    name: str
    display_name: str
    parameter_type: Literal["int", "float", "bool", "color", "enum", "string", "curve", "position"]
    default_value: Any
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None
    enum_values: Optional[list[str]] = None
    animatable: bool = True
    group: str = "default"
    description: str = ""


class EffectPreset(BaseModel):
    """Efekt on ayari."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    effect_type: EffectType
    parameters: dict[str, Any]
    thumbnail: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    is_builtin: bool = False


class EffectKeyframe(BaseModel):
    """Efekt anahtar karesi."""
    time: Timecode
    value: Any
    ease_in: str = "linear"
    ease_out: str = "linear"
    bezier_handles: Optional[tuple[tuple[float, float], tuple[float, float]]] = None


class EffectInstance(BaseModel):
    """Efekt ornegi (zaman cizelgesindeki kullanim)."""
    id: UUID = Field(default_factory=uuid4)
    effect_type: EffectType
    name: str
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    keyframes: dict[str, list[EffectKeyframe]] = Field(default_factory=dict)
    input_connections: list[InputConnection] = Field(default_factory=list)
    output_connections: list[OutputConnection] = Field(default_factory=list)
    render_order: int = 0
    bypass_when_beyond: Optional[TimeRange] = None

    def set_parameter(self, name: str, value: Any, time: Optional[Timecode] = None) -> None: ...
    def get_parameter(self, name: str, time: Optional[Timecode] = None) -> Any: ...
    def add_keyframe(self, param_name: str, keyframe: EffectKeyframe) -> None: ...
    def remove_keyframe(self, param_name: str, time: Timecode) -> None: ...
    def get_keyframes(self, param_name: str) -> list[EffectKeyframe]: ...
    def toggle(self, enabled: bool) -> None: ...
    def get_schema(self) -> list[EffectParameter]: ...
    def validate_parameters(self) -> list[str]: ...
```

### 2.3.3 Efekt Graf Yapisi

```python
class InputConnection(BaseModel):
    source_node_id: UUID
    source_output: str = "output"
    target_input: str = "input"


class OutputConnection(BaseModel):
    target_node_id: UUID
    target_input: str = "input"
    source_output: str = "output"


class EffectNode(BaseModel):
    """Efekt graf dugumu."""
    id: UUID = Field(default_factory=uuid4)
    effect_type: EffectType
    name: str
    position: tuple[int, int] = (0, 0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    label: Optional[str] = None
    color: Optional[str] = None
    bypassed: bool = False


class GraphConnection(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    source_node_id: UUID
    source_output_name: str = "output"
    target_node_id: UUID
    target_input_name: str = "input"
    label: Optional[str] = None


class EffectGraph(BaseModel):
    """Efekt graf (node tabanli isleme)."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    nodes: list[EffectNode] = Field(default_factory=list)
    connections: list[GraphConnection] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    def add_node(self, node: EffectNode) -> EffectNode: ...
    def remove_node(self, node_id: UUID) -> Optional[EffectNode]: ...
    def add_connection(self, connection: GraphConnection) -> None: ...
    def remove_connection(self, source_id: UUID, target_id: UUID) -> None: ...
    def get_node(self, node_id: UUID) -> Optional[EffectNode]: ...
    def topological_sort(self) -> list[EffectNode]: ...
    def validate(self) -> list[str]: ...
    def get_render_order(self) -> list[EffectNode]: ...
    def detect_cycles(self) -> list[list[UUID]]: ...
    def get_input_nodes(self) -> list[EffectNode]: ...
    def get_output_nodes(self) -> list[EffectNode]: ...
    def clone(self) -> EffectGraph: ...
```

### 2.3.4 Onceden Tanimli Efektler

```python
class ColorCorrectionEffect:
    """Renk duzeltme efekti parametreleri."""

    @staticmethod
    def get_parameters() -> list[EffectParameter]:
        return [
            EffectParameter(name="brightness", display_name="Parlaklik",
                          parameter_type="float", default_value=0.0,
                          min_value=-1.0, max_value=1.0, step=0.01),
            EffectParameter(name="contrast", display_name="Kontrast",
                          parameter_type="float", default_value=1.0,
                          min_value=0.0, max_value=3.0, step=0.01),
            EffectParameter(name="saturation", display_name="Doygunluk",
                          parameter_type="float", default_value=1.0,
                          min_value=0.0, max_value=3.0, step=0.01),
            EffectParameter(name="hue_shift", display_name="Renk Kaymasi",
                          parameter_type="float", default_value=0.0,
                          min_value=-180.0, max_value=180.0, step=1.0),
            EffectParameter(name="temperature", display_name="Sicaklik",
                          parameter_type="float", default_value=0.0,
                          min_value=-1.0, max_value=1.0, step=0.01),
            EffectParameter(name="tint", display_name="Ton",
                          parameter_type="float", default_value=0.0,
                          min_value=-1.0, max_value=1.0, step=0.01),
            EffectParameter(name="exposure", display_name="Pozlama",
                          parameter_type="float", default_value=0.0,
                          min_value=-5.0, max_value=5.0, step=0.1),
            EffectParameter(name="gamma", display_name="Gama",
                          parameter_type="float", default_value=1.0,
                          min_value=0.1, max_value=5.0, step=0.01),
            EffectParameter(name="lift", display_name="Kaldirma",
                          parameter_type="float", default_value=0.0,
                          min_value=-1.0, max_value=1.0, step=0.01),
            EffectParameter(name="gain", display_name="Kazanc",
                          parameter_type="float", default_value=1.0,
                          min_value=0.0, max_value=5.0, step=0.01),
            EffectParameter(name="saturation_vibrance", display_name="Canlilik",
                          parameter_type="float", default_value=0.0,
                          min_value=-1.0, max_value=1.0, step=0.01),
            EffectParameter(name="shadow_color", display_name="Golge Rengi",
                          parameter_type="color", default_value="#000000"),
            EffectParameter(name="highlight_color", display_name="Parlak Rengi",
                          parameter_type="color", default_value="#FFFFFF"),
            EffectParameter(name="lut_file", display_name="LUT Dosyasi",
                          parameter_type="string", default_value=""),
            EffectParameter(name="lut_intensity", display_name="LUT Yogunlugu",
                          parameter_type="float", default_value=1.0,
                          min_value=0.0, max_value=1.0, step=0.01),
            EffectParameter(name="curves", display_name="Egriler",
                          parameter_type="curve", default_value={}),
        ]


class BlurEffect:
    """Bulaniklik efekti parametreleri."""

    @staticmethod
    def get_parameters() -> list[EffectParameter]:
        return [
            EffectParameter(name="blur_type", display_name="Bulaniklik Turu",
                          parameter_type="enum", default_value="gaussian",
                          enum_values=["gaussian", "box", "motion", "radial", "lens", "tilt_shift"]),
            EffectParameter(name="radius", display_name="Yaricapi",
                          parameter_type="float", default_value=5.0,
                          min_value=0.0, max_value=200.0, step=0.1),
            EffectParameter(name="angle", display_name="Acisi",
                          parameter_type="float", default_value=0.0,
                          min_value=0.0, max_value=360.0, step=1.0),
            EffectParameter(name="quality", display_name="Kalite",
                          parameter_type="int", default_value=3,
                          min_value=1, max_value=10),
            EffectParameter(name="center_x", display_name="Merkez X",
                          parameter_type="float", default_value=0.5,
                          min_value=0.0, max_value=1.0, step=0.01),
            EffectParameter(name="center_y", display_name="Merkez Y",
                          parameter_type="float", default_value=0.5,
                          min_value=0.0, max_value=1.0, step=0.01),
            EffectParameter(name="feather", display_name="Tuylenme",
                          parameter_type="float", default_value=0.0,
                          min_value=0.0, max_value=1.0, step=0.01),
        ]


class StabilizeEffect:
    """Video sabitleme efekti parametreleri."""

    @staticmethod
    def get_parameters() -> list[EffectParameter]:
        return [
            EffectParameter(name="method", display_name="Yontem",
                          parameter_type="enum", default_value="smooth",
                          enum_values=["smooth", "tripod", "follow", "lockshot"]),
            EffectParameter(name="smoothness", display_name="Yumusaklik",
                          parameter_type="float", default_value=50.0,
                          min_value=0.0, max_value=100.0, step=1.0),
            EffectParameter(name="crop_ratio", display_name="Kirpma Orani",
                          parameter_type="float", default_value=0.05,
                          min_value=0.0, max_value=0.3, step=0.01),
            EffectParameter(name="analysis_area", display_name="Analiz Alani",
                          parameter_type="enum", default_value="full_frame",
                          enum_values=["full_frame", "center_third", "center_sixth"]),
            EffectParameter(name="shakiness", display_name="Sarsinti Seviyesi",
                          parameter_type="int", default_value=5,
                          min_value=1, max_value=10),
            EffectParameter(name="accuracy", display_name="Hassasiyet",
                          parameter_type="enum", default_value="good",
                          enum_values=["fast", "good", "best"]),
        ]
```

## 2.4 Kompozitor API

### 2.4.1 Kompozitor Tipleri

```python
class RenderRegion(BaseModel):
    """Render bolgesi tanimi."""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    def intersects(self, other: RenderRegion) -> bool: ...
    def union(self, other: RenderRegion) -> RenderRegion: ...
    def intersection(self, other: RenderRegion) -> Optional[RenderRegion]: ...
    def scale(self, factor: float) -> RenderRegion: ...


class CompositorFrame(BaseModel):
    """Tek bir kare kompozisyon sonucu."""
    frame_number: int
    timecode: Timecode
    width: int
    height: int
    pixel_data: Optional[bytes] = None
    alpha_data: Optional[bytes] = None
    metadata: dict = Field(default_factory=dict)
    render_time_ms: float = 0.0
    cache_hit: bool = False


class RenderOptions(BaseModel):
    """Render secenekleri."""
    time_range: TimeRange
    output_width: int = 1920
    output_height: int = 1080
    output_fps: float = 30.0
    output_format: Literal["rgba8", "rgba16", "rgba32", "bgra8", "rgb8", "yuv420p", "yuv422p"] = "rgba8"
    quality: int = Field(ge=1, le=100, default=100)
    denoise: bool = False
    deinterlace: bool = False
    hardware_accelerated: bool = True
    tile_size: Optional[int] = None
    region_of_interest: Optional[RenderRegion] = None
    start_frame: int = 0
    frame_count: Optional[int] = None
    callback: Optional[str] = None
    parallel_workers: int = 4


class RenderNode(BaseModel):
    """Render agaci dugumu."""
    node_id: UUID
    node_type: Literal["layer", "effect", "composite", "input"]
    children: list[RenderNode] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    bounding_box: Optional[RenderRegion] = None
    blend_mode: BlendMode = BlendMode.NORMAL
    opacity: float = 1.0


class RenderStats(BaseModel):
    """Render istatistikleri."""
    total_frames_rendered: int = 0
    average_frame_time_ms: float = 0.0
    max_frame_time_ms: float = 0.0
    min_frame_time_ms: float = 0.0
    cache_hit_rate: float = 0.0
    memory_peak_mb: float = 0.0
    gpu_utilization: float = 0.0
    cpu_utilization: float = 0.0
    layers_processed: int = 0
    effects_applied: int = 0
    total_pixels_rendered: int = 0
```

### 2.4.2 Compositor Sinifi

```python
class Compositor:
    """Ana kompozitor sinifi."""

    def __init__(self, timeline: Timeline, options: Optional[RenderOptions] = None): ...

    # --- Kompozisyon ---
    def compose_frame(self, time: Timecode) -> CompositorFrame: ...
    def compose_region(self, time: Timecode, region: RenderRegion) -> CompositorFrame: ...
    def compose_sequence(self, time_range: TimeRange, *,
                         progress_callback: Optional[callable] = None) -> list[CompositorFrame]: ...

    # --- Bellek Yonetimi ---
    def clear_cache(self) -> None: ...
    def get_cache_size(self) -> int: ...
    def set_cache_limit(self, max_bytes: int) -> None: ...
    def get_memory_usage(self) -> dict[str, int]: ...

    # --- Onizleme ---
    def preview_frame(self, time: Timecode, quality: int = 50) -> bytes: ...
    def preview_sequence(self, time_range: TimeRange, quality: int = 50) -> list[bytes]: ...

    # --- Istatistik ---
    def get_render_stats(self) -> RenderStats: ...
    def get_layer_stats(self, layer_id: UUID) -> dict: ...

    # --- Katman Haritalama ---
    def get_layer_render_order(self) -> list[UUID]: ...
    def get_visible_layers(self, time: Timecode) -> list[Layer]: ...
    def get_render_tree(self, time: Timecode) -> RenderNode: ...
```
"""

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(content)

print(f"Part 1 written ({len(content)} chars)")
