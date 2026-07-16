# MASTER API REFERANS - Medya Altyapisi Sozlesme Belgesi

**Surum:** 3.0.0  
**Durum:** Uretimde Kullanima Hazir  
**Son Guncelleme:** 2026-07-16  
**Sorumlu:** Principal Media Infrastructure Engineer  

---

## Icindekiler

1. [Sistem Mimarisi Entegrasyon Haritasi](#1)
2. [Cekirdek Motor API (Modul 1)](#2)
3. [Islem Hatti API (Modul 2)](#3)
4. [Zeka API (Modul 3)](#4)
5. [Tipografi ve Grafik API (Modul 4)](#5)
6. [Ses API (Modul 5)](#6)
7. [Altyapi API (Modul 6)](#7)
8. [Eklenti API (Modul 7)](#8)
9. [Teslimat API (Modul 8)](#9)
10. [REST API Uclari (FastAPI)](#10)
11. [Veri Akis Diyagramlari](#11)

---

# 1. Sistem Mimarisi Entegrasyon Haritasi

## 1.1 Tam Sistem Diyagrami

```
+-------------------------------------------------------------------------------+
|                           DIS CLI KATMANI                                      |
|  +-----------+  +--------------+  +------------+  +----------+  +----------+  |
|  | Web App   |  | Mobile Client|  | CLI Tool   |  | CI/CD    |  | 3. Party |  |
|  | (React)   |  | (Flutter)    |  | (Python)   |  | Pipeline |  | Integr.  |  |
|  +-----+-----+  +------+-------+  +-----+------+  +----+-----+  +----+-----+  |
+--------+---------------+---------------+---------------+--------------+--------+
         |               |               |               |              |
         v               v               v               v              v
+-------------------------------------------------------------------------------+
|                        API GATEWAY & AUTH LAYER                                |
|  FastAPI Sunucusu: JWT Auth, Rate Limiter, Request Validator, WebSocket,     |
|  CORS, Error Handler, Logging, Metrics Collector, Health Check               |
+-------------------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------------------+
| MODUL 8: TESLIMAT  | MODUL 6: ALTYAPI  | MODUL 7: EKLENTI (Plugin SDK)       |
| Export | Storage    | Render Queue      | Plugin SDK | Template SDK           |
|        | CDN        | Worker Pool       | Theme API  | Preset API             |
|        |            | Job Scheduler     |            |                        |
|        |            | Cache Manager     |            |                        |
|        |            | Asset Manager     |            |                        |
+--------+------------+-------------------+------------+------------------------+
         |
         v
+-------------------------------------------------------------------------------+
| MODUL 1: CEKIRDEK MOTOR  | MODUL 2: ISLEM HATTI | MODUL 3: ZEKA API          |
| Timeline | Layer | Effect | GPU | FFmpeg | HW Enc | Face | Scene | Content   |
| Graph    | Mgmt  | Graph  | Pipe| Filter | Dynamic| Track| Detect| Analysis  |
| Compositor        |        |     | Builder| Crop   |      |       | EditDec   |
+-------------------+--------+-----+--------+--------+------+------+-----------+
         |
         v
+-------------------------------------------------------------------------------+
| MODUL 4: TIPOGRAFI/GRAFIK  | MODUL 5: SES API                                |
| Subtitle | Karaoke | Anim   | Mixer | Loudness | Ducking                    |
| Sticker | AnimationEngine    |                                              |
+-------------------------------------------------------------------------------+
         |
         v
+-------------------------------------------------------------------------------+
| VERI DEPOLAMA: PostgreSQL (Metadata) | Redis (Cache/Queue) | MinIO/S3 (Assets)|
+-------------------------------------------------------------------------------+
```

## 1.2 Veri Akis Hatti

```
Giris Kaynagi    ->  Analiz     ->  Karar Verici  ->  Uretici    ->  Cikis
--------------      ----------      -------------      ----------      ------
Video Dosya      -> Sahne Tespiti-> Kirtasiye Motoru-> GPU Islem   -> Hedef Format
Audio Dosya      -> Ses Analizi  -> Otomatik Duzenle-> FFmpeg Filtre-> CDN Yukleme
Webcam Akis      -> Yuz Takibi   -> Alt Yazi Senkron-> HW Kodlama  -> Akis Cikisi
Screen Recording -> Icerik Analizi-> Efekt Secimi   -> Dinamik Kirpma-> Indirme
```

## 1.3 Modul Bagimlilik Grafigi

```
           Modul 1 (Cekirdek Motor)
              /      |      \
             /       |       \
    Modul 2 (Islem) Modul 3 (Zeka) Modul 4 (Tipografi)
             \       |       /
              \      |      /
              Modul 5 (Ses)
                   |
           Modul 6 (Altyapi)
              /      |      \
    Modul 7 (Eklenti)  Modul 8 (Teslimat)  Modul 10 (REST API)
```

## 1.4 Baslatma Sirasi

| Sira | Modul | Baslatma Kriteri |
|------|-------|------------------|
| 1 | Config Manager | Konfigurasyon yuklendi |
| 2 | Cache Manager | Redis baglandi |
| 3 | PostgreSQL Adapter | DB baglandi |
| 4 | S3/MinIO Adapter | Nesne depolama baglandi |
| 5 | Worker Pool | Is parcaciklari baslatildi |
| 6 | Render Queue | Kuyruk dinleyicisi baslatildi |
| 7 | Job Scheduler | Zamanlayici baslatildi |
| 8 | Metrics Collector | Metrik toplama baslatildi |
| 9 | Plugin Manager | Eklentiler yuklendi |
| 10 | Timeline Engine | Zaman cizelgesi hazir |
| 11 | Compositor | Kompozitor hazir |
| 12 | GPU Pipeline | GPU erisimi dogrulandi |
| 13 | FFmpeg Pipeline | FFmpeg surumu dogrulandi |
| 14 | Intelligence Engine | Zeka modelleri yuklendi |
| 15 | Typography Engine | Tipografi hazir |
| 16 | Audio Engine | Ses motoru hazir |
| 17 | API Gateway | HTTP ucleri baslatildi |
| 18 | WebSocket Manager | WS iletisim hazir |
| 19 | Health Monitor | Saglik izleme baslatildi |
| 20 | Export Manager | Disa aktarma hazir |

## 1.5 Hata Yayilma Stratejisi

```
Seviye 0: Kritik Hata (Sistem Cokme)
  -> Tum isler durdurulur, alarm gonderilir, otomatik yeniden baslatma

Seviye 1: Is Hatti Hatasi (Tek bir is basarisiz)
  -> Is kuyrugundan kaldirilir, yeniden deneme (max 3), cascading cancel

Seviye 2: Islem Hatti Hatasi (GPU/FFmpeg hata)
  -> CPU fallback, dusuk cozunurlukle yeniden deneme, hata raporu

Seviye 3: Zeka Hatasi (Model/analiz hata)
  -> Varsayilan degerlerle devam, kalite dustu olarak isaretlenir

Seviye 4: Uyari (Non-fatal)
  -> Log kaydi, metrik guncelleme, islem devam eder

HATA YAKALAMA ZINCIRI:
  [Istek] -> [API Gateway] -> [Modul 8] -> [Modul 6] -> [Modul 1]
      |          |              |            |            |
  HTTP Error  401/403       502/503       500/500      422/400
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
    rate: float = Field(gt=0, default=1.0)
    reverse: bool = Field(default=False)
    frame_interpolation: Literal["none","blend","optical_flow","frame_doubling"] = "none"

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

### 2.1.4 Transform, BlendMode ve Destek Tipleri

```python
class Transform(BaseModel):
    """2D donusum parametreleri."""
    position_x: float = Field(default=0.0)
    position_y: float = Field(default=0.0)
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)
    rotation: float = Field(default=0.0)
    anchor_x: float = Field(default=0.0)
    anchor_y: float = Field(default=0.0)
    skew_x: float = Field(default=0.0)
    skew_y: float = Field(default=0.0)

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

    def get_duration_frames(self) -> int: ...
    def get_duration_seconds(self) -> float: ...
    def get_time_at_frame(self, frame: int) -> Timecode: ...
    def get_frame_at_time(self, time: Timecode) -> int: ...
    def validate(self) -> list[str]: ...
    def deep_copy(self) -> Timeline: ...
    def normalize(self) -> Timeline: ...

    def to_dict(self) -> dict: ...
    def to_json(self, indent: int = 2) -> str: ...
    def to_edl(self) -> str: ...
    def to_xml(self) -> str: ...
    def to_premiere_xml(self) -> str: ...
    def to_davinci_powergrade(self) -> dict: ...

    def create_snapshot(self) -> TimelineSnapshot: ...
    def restore_snapshot(self, snapshot: TimelineSnapshot) -> None: ...

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
                  collision_mode: Literal["push","overwrite","insert","reject"] = "reject") -> Clip: ...
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
    def match_frame(self, clip_id: UUID, direction: Literal["forward","backward"]) -> Optional[Timecode]: ...
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

### 2.2.1 Layer Tipleri

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
    track_matte_mode: Literal["alpha","luma","alpha_inverted","luma_inverted"] = "alpha"
```

### 2.2.2 Layer Sinifi

```python
class Layer(BaseModel):
    """Zaman cizelgesi katmani."""
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=256)
    layer_type: LayerType
    index: int = Field(ge=0)
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

    def add_clip(self, clip: Clip, position: Timecode) -> Clip: ...
    def remove_clip(self, clip_id: UUID) -> Optional[Clip]: ...
    def get_clip(self, clip_id: UUID) -> Optional[Clip]: ...
    def get_clips_in_range(self, time_range: TimeRange) -> list[Clip]: ...
    def get_clip_at_time(self, time: Timecode) -> Optional[Clip]: ...
    def move_clip(self, clip_id: UUID, new_position: Timecode) -> Clip: ...
    def order_clips(self, clip_ids: list[UUID]) -> None: ...

    def add_effect(self, effect: EffectInstance) -> EffectInstance: ...
    def remove_effect(self, effect_id: UUID) -> Optional[EffectInstance]: ...
    def move_effect(self, effect_id: UUID, new_index: int) -> EffectInstance: ...
    def get_effects(self) -> list[EffectInstance]: ...
    def toggle_effect(self, effect_id: UUID, enabled: bool) -> None: ...

    def toggle_visibility(self) -> bool: ...
    def toggle_solo(self) -> bool: ...
    def toggle_lock(self) -> bool: ...
    def set_opacity(self, value: float) -> None: ...
    def set_blend_mode(self, mode: BlendMode) -> None: ...

    def set_parent(self, parent_id: Optional[UUID]) -> None: ...
    def add_child(self, child_id: UUID) -> None: ...
    def remove_child(self, child_id: UUID) -> None: ...
    def get_root_transform(self) -> Transform: ...

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
    parameter_type: Literal["int","float","bool","color","enum","string","curve","position"]
    default_value: Any
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    step: Optional[Union[int, float]] = None
    enum_values: Optional[list[str]] = None
    animatable: bool = True
    group: str = "default"
    description: str = ""

class EffectKeyframe(BaseModel):
    """Efekt anahtar karesi."""
    time: Timecode
    value: Any
    ease_in: str = "linear"
    ease_out: str = "linear"
    bezier_handles: Optional[tuple[tuple[float,float], tuple[float,float]]] = None

class EffectInstance(BaseModel):
    """Efekt ornegi."""
    id: UUID = Field(default_factory=uuid4)
    effect_type: EffectType
    name: str
    enabled: bool = True
    parameters: dict[str, Any] = Field(default_factory=dict)
    keyframes: dict[str, list[EffectKeyframe]] = Field(default_factory=dict)
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
class EffectNode(BaseModel):
    """Efekt graf dugumu."""
    id: UUID = Field(default_factory=uuid4)
    effect_type: EffectType
    name: str
    position: tuple[int, int] = (0, 0)
    parameters: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    label: Optional[str] = None
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
    """Renk duzeltme efekti - 16 animatable parametre."""
    # Parametreler: brightness, contrast, saturation, hue_shift,
    #   temperature, tint, exposure, gamma, lift, gain,
    #   saturation_vibrance, shadow_color, highlight_color,
    #   lut_file, lut_intensity, curves
    @staticmethod
    def get_parameters() -> list[EffectParameter]: ...

class BlurEffect:
    """Bulaniklik efekti - 7 parametre."""
    # Parametreler: blur_type(gaussian|box|motion|radial|lens|tilt_shift),
    #   radius, angle, quality, center_x, center_y, feather
    @staticmethod
    def get_parameters() -> list[EffectParameter]: ...

class StabilizeEffect:
    """Video sabitleme efekti - 6 parametre."""
    # Parametreler: method(smooth|tripod|follow|lockshot), smoothness,
    #   crop_ratio, analysis_area, shakiness, accuracy
    @staticmethod
    def get_parameters() -> list[EffectParameter]: ...
```
## 2.4 Kompozitor API

### 2.4.1 Kompozitor Destek Tipleri

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
    output_format: Literal["rgba8","rgba16","rgba32","bgra8","rgb8","yuv420p","yuv422p"] = "rgba8"
    quality: int = Field(ge=1, le=100, default=100)
    denoise: bool = False
    deinterlace: bool = False
    hardware_accelerated: bool = True
    tile_size: Optional[int] = None
    region_of_interest: Optional[RenderRegion] = None
    start_frame: int = 0
    frame_count: Optional[int] = None
    parallel_workers: int = 4

class RenderNode(BaseModel):
    """Render agaci dugumu."""
    node_id: UUID
    node_type: Literal["layer","effect","composite","input"]
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

    def compose_frame(self, time: Timecode) -> CompositorFrame: ...
    def compose_region(self, time: Timecode, region: RenderRegion) -> CompositorFrame: ...
    def compose_sequence(self, time_range: TimeRange, *,
                         progress_callback: Optional[callable] = None) -> list[CompositorFrame]: ...

    def clear_cache(self) -> None: ...
    def get_cache_size(self) -> int: ...
    def set_cache_limit(self, max_bytes: int) -> None: ...
    def get_memory_usage(self) -> dict[str, int]: ...

    def preview_frame(self, time: Timecode, quality: int = 50) -> bytes: ...
    def preview_sequence(self, time_range: TimeRange, quality: int = 50) -> list[bytes]: ...

    def get_render_stats(self) -> RenderStats: ...
    def get_layer_stats(self, layer_id: UUID) -> dict: ...
    def get_layer_render_order(self) -> list[UUID]: ...
    def get_visible_layers(self, time: Timecode) -> list[Layer]: ...
    def get_render_tree(self, time: Timecode) -> RenderNode: ...
```

---

# 3. Islem Hatti API (Modul 2 Referansi)

## 3.1 GPU Islem Hatti API

### 3.1.1 GPU Destek Tipleri

```python
class GPUDevice(BaseModel):
    """GPU aygiti bilgisi."""
    device_id: int
    name: str
    vendor: Literal["nvidia","amd","intel","apple","unknown"]
    driver_version: str
    vram_total_mb: int
    vram_used_mb: int
    compute_capability: Optional[str] = None
    cuda_cores: Optional[int] = None
    compute_units: Optional[int] = None
    supported_codecs: list[str] = Field(default_factory=list)

class GPUBuffer(BaseModel):
    """GPU tampon bellek referansi."""
    buffer_id: UUID
    device_id: int
    size_bytes: int
    format: Literal["rgba8","rgba16","rgba32","bgra8","nv12","yuv420p"]
    width: int
    height: int
    stride: int
    is_pinned: bool = False
    ref_count: int = 0

class GPUKernel(BaseModel):
    """GPU cekirdek tanimi."""
    kernel_id: UUID
    name: str
    source_file: str
    entry_point: str
    compile_options: dict[str, str] = Field(default_factory=dict)
    block_size: tuple[int, int, int] = (256, 1, 1)
    grid_size: Optional[tuple[int, int, int]] = None
```

### 3.1.2 GPUPipeline Sinifi

```python
class GPUPipeline:
    """GPU islem hatti yoneticisi."""

    def __init__(self, device_ids: Optional[list[int]] = None, *,
                 memory_limit_mb: int = 4096, enable_profiling: bool = False): ...

    def get_devices(self) -> list[GPUDevice]: ...
    def get_active_device(self) -> GPUDevice: ...
    def select_device(self, device_id: int) -> None: ...
    def get_device_utilization(self, device_id: int) -> dict[str, float]: ...

    def allocate_buffer(self, width: int, height: int, format: str, *,
                        device_id: Optional[int] = None, pinned: bool = False) -> GPUBuffer: ...
    def free_buffer(self, buffer_id: UUID) -> None: ...
    def upload_buffer(self, buffer_id: UUID, data: bytes) -> None: ...
    def download_buffer(self, buffer_id: UUID) -> bytes: ...
    def copy_buffer(self, source_id: UUID, dest_id: UUID) -> None: ...
    def get_memory_usage(self) -> dict[str, int]: ...

    def compile_kernel(self, kernel: GPUKernel) -> None: ...
    def launch_kernel(self, kernel_id: UUID, args: list[Any], *,
                      grid_size: Optional[tuple[int,int,int]] = None,
                      block_size: Optional[tuple[int,int,int]] = None,
                      shared_memory: int = 0, stream: int = 0) -> None: ...
    def synchronize(self, stream: int = 0) -> None: ...

    def create_stream(self) -> int: ...
    def destroy_stream(self, stream_id: int) -> None: ...
    def get_stream_status(self, stream_id: int) -> Literal["idle","busy","error"]: ...

    def get_profile_results(self) -> dict[str, Any]: ...
    def reset_counters(self) -> None: ...
    def get_bottleneck_analysis(self) -> dict[str, Any]: ...
```

### 3.1.3 GPU Islem Operasyonlari

```python
class GPUColorOperations:
    """GPU renk isleme operasyonlari."""
    def __init__(self, pipeline: GPUPipeline): ...
    def apply_lut(self, input_buffer: UUID, output_buffer: UUID,
                  lut_data: bytes, *, intensity: float = 1.0,
                  format: Literal["cube","3dl","csp"] = "cube") -> GPUOperation: ...
    def adjust_color(self, input_buffer: UUID, output_buffer: UUID, *,
                     brightness: float = 0.0, contrast: float = 1.0,
                     saturation: float = 1.0, hue: float = 0.0,
                     temperature: float = 0.0, tint: float = 0.0) -> GPUOperation: ...
    def color_space_convert(self, input_buffer: UUID, output_buffer: UUID,
                            from_space: Literal["srgb","linear","rec709","rec2020","aces"],
                            to_space: Literal["srgb","linear","rec709","rec2020","aces"]) -> GPUOperation: ...
    def apply_curves(self, input_buffer: UUID, output_buffer: UUID,
                     curves: dict[str, list[tuple[float,float]]]) -> GPUOperation: ...
    def levels_adjust(self, input_buffer: UUID, output_buffer: UUID, *,
                      input_black: float = 0.0, input_white: float = 1.0,
                      output_black: float = 0.0, output_white: float = 1.0,
                      gamma: float = 1.0) -> GPUOperation: ...

class GPUFilterOperations:
    """GPU filtre isleme operasyonlari."""
    def __init__(self, pipeline: GPUPipeline): ...
    def gaussian_blur(self, in_buf: UUID, out_buf: UUID, *,
                      radius_x: float, radius_y: float, quality: int = 3) -> GPUOperation: ...
    def directional_blur(self, in_buf: UUID, out_buf: UUID, *,
                         radius: float, angle: float) -> GPUOperation: ...
    def sharpen(self, in_buf: UUID, out_buf: UUID, *,
                amount: float = 1.0, radius: float = 1.0, threshold: float = 0.0) -> GPUOperation: ...
    def edge_detect(self, in_buf: UUID, out_buf: UUID, *,
                    method: Literal["sobel","canny","prewitt"] = "sobel",
                    threshold: float = 0.5) -> GPUOperation: ...
    def emboss(self, in_buf: UUID, out_buf: UUID, *,
               angle: float = 45.0, depth: float = 1.0) -> GPUOperation: ...
    def median_filter(self, in_buf: UUID, out_buf: UUID, *,
                      kernel_size: int = 3) -> GPUOperation: ...

class GPUTransformOperations:
    """GPU donusum operasyonlari."""
    def __init__(self, pipeline: GPUPipeline): ...
    def resize(self, in_buf: UUID, out_buf: UUID, *,
               method: Literal["bilinear","bicubic","lanczos","nearest"] = "lanczos") -> GPUOperation: ...
    def rotate(self, in_buf: UUID, out_buf: UUID, *,
               angle: float, fill_color: tuple[int,int,int,int] = (0,0,0,0)) -> GPUOperation: ...
    def flip(self, in_buf: UUID, out_buf: UUID, *,
             horizontal: bool = False, vertical: bool = False) -> GPUOperation: ...
    def crop(self, in_buf: UUID, out_buf: UUID, region: RenderRegion) -> GPUOperation: ...
    def perspective_transform(self, in_buf: UUID, out_buf: UUID,
                              corners: tuple) -> GPUOperation: ...
    def lens_distortion(self, in_buf: UUID, out_buf: UUID, *,
                        k1: float = 0.0, k2: float = 0.0,
                        p1: float = 0.0, p2: float = 0.0) -> GPUOperation: ...
```
## 3.2 FFmpeg Filtre Builder API

### 3.2.1 Filtre Modelleri

```python
class FFmpegFilterParam(BaseModel):
    """FFmpeg filtre parametresi."""
    key: str
    value: Union[str, int, float, bool]
    is_expression: bool = False

class FFmpegFilter(BaseModel):
    """Tek bir FFmpeg filtresi."""
    name: str
    params: list[FFmpegFilterParam] = Field(default_factory=list)
    link_label: Optional[str] = None
    def to_string(self) -> str: ...

class FFmpegFilterChain(BaseModel):
    """FFmpeg filtre zinciri."""
    filters: list[FFmpegFilter]
    input_labels: list[str] = Field(default_factory=list)
    output_labels: list[str] = Field(default_factory=list)
    def to_string(self) -> str: ...

class FFmpegFilterGraph(BaseModel):
    """FFmpeg filtre graf (coklu zincir)."""
    chains: list[FFmpegFilterChain] = Field(default_factory=list)
    def add_chain(self, chain: FFmpegFilterChain) -> None: ...
    def to_string(self) -> str: ...
```

### 3.2.2 FFmpegFilterBuilder Sinifi

```python
class FFmpegFilterBuilder:
    """FFmpeg filtre olusturucu."""
    def __init__(self): ...

    # Temel Filtreler
    def scale(self, width, height, *, interpolation='lanczos',
              force_original_aspect_ratio=None, force_divisible_by=None) -> FFmpegFilter: ...
    def crop(self, width, height, x, y, *, keep_aspect=False) -> FFmpegFilter: ...
    def pad(self, width, height, x, y, *, color='black') -> FFmpegFilter: ...
    def format(self, pixel_format: str) -> FFmpegFilter: ...
    def fps(self, fps, *, round='near') -> FFmpegFilter: ...

    # Renk Filtreleri
    def color_balance(self, *, rs=0.0, gs=0.0, bs=0.0, ms=0.0, hs=0.0, ss=0.0) -> FFmpegFilter: ...
    def curves(self, channels=None, preset=None) -> FFmpegFilter: ...
    def eq(self, *, brightness=0.0, contrast=1.0, saturation=1.0, gamma=1.0) -> FFmpegFilter: ...
    def hue(self, *, h=None, s=None) -> FFmpegFilter: ...
    def color_temperature(self, temperature: float) -> FFmpegFilter: ...
    def lut3d(self, file_path: str, *, interp=None) -> FFmpegFilter: ...
    def colorlevels(self, *, rimin=0.0, gimin=0.0, bimin=0.0, rimax=1.0, gimax=1.0, bimax=1.0) -> FFmpegFilter: ...

    # Bulaniklik Filtreleri
    def boxblur(self, luma_radius, luma_power, *, chroma_radius=None) -> FFmpegFilter: ...
    def gaussianblur(self, sigma, *, sigma_v=None) -> FFmpegFilter: ...
    def lensblur(self, radius, *, sides=6, rotation=0.0) -> FFmpegFilter: ...
    def motionblur(self, *, angle=0.0, luma_radius=5.0) -> FFmpegFilter: ...
    def smartblur(self, *, luma_radius=1.0, luma_strength=1.0, luma_threshold=0) -> FFmpegFilter: ...

    # Keskinlestirme
    def unsharp(self, *, luma_msize_x=5, luma_msize_y=5, luma_amount=1.0) -> FFmpegFilter: ...

    # Zaman
    def setpts(self, expression: str) -> FFmpegFilter: ...
    def asetpts(self, expression: str) -> FFmpegFilter: ...

    # Cizim ve Overlay
    def drawtext(self, text, *, fontfile='', fontsize=24, fontcolor='white',
                  x=0, y=0, borderw=0, box=False, enable=None) -> FFmpegFilter: ...
    def overlay(self, x=0, y=0, *, eof_action='repeat', shortest=False) -> FFmpegFilter: ...

    # Chroma Keying
    def chromakey(self, color, similarity, blend=0.0) -> FFmpegFilter: ...
    def colorkey(self, color, similarity, blend=0.0) -> FFmpegFilter: ...

    # Ses Filtreleri
    def volume(self, volume, *, eval='frame') -> FFmpegFilter: ...
    def aformat(self, sample_fmts=None, sample_rates=None, channel_layouts=None) -> FFmpegFilter: ...
    def amix(self, inputs=2, *, duration='longest') -> FFmpegFilter: ...
    def afade(self, *, type='in', start_sample=0, nb_samples=44100) -> FFmpegFilter: ...
    def loudnorm(self, *, I=-24.0, TP=-2.0, LRA=7.0) -> FFmpegFilter: ...
    def acompressor(self, *, threshold=0.125, ratio=2.0, attack=20.0, release=250.0) -> FFmpegFilter: ...
    def equalizer(self, frequency, *, width_type='q', gain=0.0) -> FFmpegFilter: ...

    # Zincir Olusturma
    def create_chain(self, *filters: FFmpegFilter) -> FFmpegFilterChain: ...
    def create_graph(self, *chains: FFmpegFilterChain) -> FFmpegFilterGraph: ...

    # Yaygin Sablonlar
    def build_vfr_to_cfr_chain(self, fps: float) -> FFmpegFilterChain: ...
    def build_scale_to_1080p_chain(self) -> FFmpegFilterChain: ...
    def build_4k_downscale_chain(self) -> FFmpegFilterChain: ...
    def build_hardware_upload_chain(self, hwaccel='cuda') -> FFmpegFilterChain: ...
    def build_srt_subtitle_chain(self, srt_path: str) -> FFmpegFilterChain: ...
    def build_karaoke_chain(self) -> FFmpegFilterChain: ...
    def build_dual_audio_chain(self) -> FFmpegFilterChain: ...
```

## 3.3 Hardware Kodlama API

### 3.3.1 Kodlama Destek Tipleri

```python
class EncodingPreset(str, Enum):
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"

class HWCodec(str, Enum):
    NVENC_H264 = "h264_nvenc"
    NVENC_H265 = "hevc_nvenc"
    NVENC_AV1 = "av1_nvenc"
    AMF_H264 = "h264_amf"
    AMF_H265 = "hevc_amf"
    QSV_H264 = "h264_qsv"
    QSV_H265 = "hevc_qsv"
    VAAPI_H264 = "h264_vaapi"
    VAAPI_H265 = "hevc_vaapi"
    VIDEOTOOLBOX_H264 = "h264_videotoolbox"
    VIDEOTOOLBOX_H265 = "hevc_videotoolbox"
    V4L2M2M_H264 = "h264_v4l2m2m"

class EncoderProfile(BaseModel):
    profile: Literal["baseline","main","high","high10","high422","high444"]
    level: Optional[str] = None
    tier: Optional[Literal["main","high"]] = None

class RateControl(BaseModel):
    """Hiz kontrol parametreleri."""
    mode: Literal["cbr","vbr","cqp","cq","qp"] = "vbr"
    bitrate_kbps: Optional[int] = None
    max_bitrate_kbps: Optional[int] = None
    buffer_size_kbps: Optional[int] = None
    crf: Optional[int] = Field(None, ge=0, le=51)
    qp: Optional[int] = Field(None, ge=0, le=51)
    target_quality: Optional[float] = Field(None, ge=0, le=51)

class EncodingConfig(BaseModel):
    """Kodlama yapilandirmasi."""
    codec: HWCodec
    preset: EncodingPreset = EncodingPreset.MEDIUM
    profile: EncoderProfile = Field(default_factory=lambda: EncoderProfile(profile='main'))
    rate_control: RateControl = Field(default_factory=RateControl)
    pixel_format: Literal["yuv420p","yuv422p","yuv444p","p010"] = "yuv420p"
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    keyframe_interval: int = 60
    b_frames: int = 3
    refs: int = 3
    lookahead: int = 32
    temporal_aq: bool = True
    spatial_aq: bool = True
    weighted_pred: bool = True
    multi_pass: bool = False
    tune: Optional[str] = None
    custom_options: dict[str, str] = Field(default_factory=dict)

class QualityMetrics(BaseModel):
    """Kodlama kalite metrikleri."""
    psnr: Optional[float] = None
    ssim: Optional[float] = None
    vmaf: Optional[float] = None
    ms_ssim: Optional[float] = None

class EncodingResult(BaseModel):
    """Kodlama sonucu."""
    success: bool
    output_path: str
    file_size_bytes: int
    duration_seconds: float
    average_bitrate_kbps: float
    peak_bitrate_kbps: float
    encoding_time_seconds: float
    fps_achieved: float
    frames_encoded: int
    keyframes_generated: int
    encoder_used: str
    quality_metrics: Optional[QualityMetrics] = None
    error_message: Optional[str] = None
```

### 3.3.2 HardwareEncoder Sinifi

```python
class HardwareEncoder:
    """Donanim hizli kodlayici."""

    def __init__(self, *, device_id: int = 0,
                 max_concurrent: int = 2, fallback_to_cpu: bool = True): ...

    def encode(self, input_path: str, output_path: str, config: EncodingConfig, *,
               progress_callback=None, cancel_event=None) -> EncodingResult: ...
    def encode_sequence(self, frame_paths: list[str], output_path: str,
                        config: EncodingConfig) -> EncodingResult: ...
    def encode_from_buffer(self, frames: list[bytes], output_path: str,
                           config: EncodingConfig, *, width=1920, height=1080,
                           pixel_format='rgba') -> EncodingResult: ...

    def get_available_encoders(self) -> list[HWCodec]: ...
    def get_encoder_capabilities(self, codec: HWCodec) -> dict[str, Any]: ...
    def is_hardware_available(self, codec: HWCodec) -> bool: ...
    def get_recommended_config(self, target_bitrate_kbps: int,
                               resolution: tuple[int, int], fps: float) -> EncodingConfig: ...

    def benchmark_encoder(self, codec: HWCodec, duration_seconds: float = 10.0) -> dict: ...
    def compare_encoders(self, codecs: list[HWCodec], input_path: str) -> list[dict]: ...
    def estimate_file_size(self, config: EncodingConfig, duration_seconds: float) -> int: ...
    def get_supported_pixel_formats(self, codec: HWCodec) -> list[str]: ...
    def get_supported_resolutions(self, codec: HWCodec) -> list[tuple[int, int]]: ...
```

## 3.4 Dinamik Kirpma API

### 3.4.1 Dinamik Kirpma Tipleri

```python
class CropStrategy(str, Enum):
    FACE_CENTER = "face_center"
    ACTION_FOLLOW = "action_follow"
    RULE_OF_THIRDS = "rule_of_thirds"
    SMART_CROP = "smart_crop"
    STATIC = "static"
    PANORAMIC = "panoramic"
    PILLARBOX_FILL = "pillarbox_fill"
    LETTERBOX_FILL = "letterbox_fill"
    CONTENT_AWARE = "content_aware"
    MOTION_BASED = "motion_based"

class CropRegion(BaseModel):
    """Kirpma bolgesi."""
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    source_width: int = 1920
    source_height: int = 1080
    def to_ffmpeg_crop(self) -> str: ...
    def to_absolute(self) -> tuple[int, int, int, int]: ...
    def center_point(self) -> tuple[int, int]: ...
    def aspect_ratio(self) -> float: ...

class CropKeyframe(BaseModel):
    """Kirpma anahtar karesi."""
    time: Timecode
    region: CropRegion
    ease_in: str = "ease_in_out"
    ease_out: str = "ease_in_out"

class CropAnalysis(BaseModel):
    """Kirpma analiz sonucu."""
    source_width: int
    source_height: int
    target_width: int
    target_height: int
    target_aspect: float
    source_aspect: float
    recommended_regions: list[CropRegion]
    strategy_used: CropStrategy
    confidence: float
    analysis_time_ms: float
```

### 3.4.2 DynamicCrop Sinifi

```python
class DynamicCrop:
    """Dinamik kirpma motoru."""

    def __init__(self, source_width: int, source_height: int,
                 target_width: int, target_height: int, *,
                 max_shift_per_frame: int = 10, smoothness: float = 0.3): ...

    def analyze_frame(self, frame_data: bytes, time: Timecode, *,
                       strategy: CropStrategy = CropStrategy.SMART_CROP) -> CropRegion: ...
    def crop_frame(self, frame_data: bytes, region: CropRegion) -> bytes: ...

    def analyze_video(self, video_path: str, *,
                       strategy: CropStrategy = CropStrategy.SMART_CROP,
                       sample_interval: float = 1.0,
                       progress_callback=None) -> list[CropKeyframe]: ...

    def apply_crop_keyframes(self, video_path: str, output_path: str,
                             keyframes: list[CropKeyframe], *,
                             interpolation: Literal["linear","smooth","step"] = "smooth") -> str: ...

    def analyze_for_aspect_ratios(self, video_path: str,
                                  target_aspects: list[tuple[int, int]], *,
                                  strategy: CropStrategy = CropStrategy.SMART_CROP)
                                  -> dict[str, list[CropKeyframe]]: ...

    def preview_crop(self, frame_data: bytes, region: CropRegion, *,
                      border: bool = True, border_color: tuple = (255, 0, 0)) -> bytes: ...
    def generate_crop_map(self, video_path: str, keyframes: list[CropKeyframe], *,
                          output_path: Optional[str] = None) -> str: ...
```

---
# 4. Zeka API (Modul 3 Referansi)

## 4.1 Yuz Takibi API

### 4.1.1 Yuz Tespit Modelleri

```python
class BoundingBox(BaseModel):
    """Sinir kutusu."""
    x: float
    y: float
    width: float
    height: float
    def center(self) -> tuple[float, float]: ...
    def area(self) -> float: ...
    def intersects(self, other: BoundingBox) -> bool: ...
    def iou(self, other: BoundingBox) -> float: ...
    def scale(self, factor: float) -> BoundingBox: ...

class FaceLandmarks(BaseModel):
    """Yuz noktalari (68 veya 478 nokta)."""
    points: list[tuple[float, float]]
    model_type: Literal["68_point","478_point","3d"]
    @property
    def left_eye(self) -> tuple[float, float]: ...
    @property
    def right_eye(self) -> tuple[float, float]: ...
    @property
    def nose_tip(self) -> tuple[float, float]: ...
    @property
    def mouth_center(self) -> tuple[float, float]: ...
    def get_eye_distance(self) -> float: ...
    def get_face_center(self) -> tuple[float, float]: ...

class FacePose(BaseModel):
    """Yuz pozu (3D donusum)."""
    pitch: float
    yaw: float
    roll: float
    translation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: float = 1.0
    def is_frontal(self, threshold: float = 15.0) -> bool: ...
    def get_rotation_matrix(self) -> list[list[float]]: ...

class FaceAttributes(BaseModel):
    """Yuz ozellikleri."""
    age: Optional[int] = None
    gender: Optional[Literal["male","female","unknown"]] = None
    emotion: Optional[Literal["happy","sad","angry","surprise","fear","disgust","neutral"]] = None
    emotion_confidence: float = 0.0
    glasses: bool = False
    sunglasses: bool = False
    beard: bool = False
    mustache: bool = False
    mouth_open: bool = False
    eyes_open: bool = True
    mask: bool = False
    skin_tone: Optional[str] = None
    expression_intensity: float = 0.0

class FaceDetection(BaseModel):
    """Yuz tespiti sonucu."""
    face_id: UUID
    confidence: float = Field(ge=0.0, le=1.0)
    bbox: BoundingBox
    landmarks: FaceLandmarks
    pose: FacePose
    attributes: FaceAttributes
    embedding: Optional[list[float]] = None
    frame_number: int = 0
    timestamp: Timecode

class FaceTrack(BaseModel):
    """Yuz izleme yolu (video boyunca)."""
    track_id: UUID
    detections: list[FaceDetection] = Field(default_factory=list)
    first_seen: Timecode
    last_seen: Timecode
    total_frames: int = 0
    average_confidence: float = 0.0
    identity_confidence: float = 0.0
    identity_label: Optional[str] = None
    def get_detection_at(self, time: Timecode) -> Optional[FaceDetection]: ...
    def get_smoothed_path(self, window: int = 5) -> list[FaceDetection]: ...
    def get_velocity(self) -> list[tuple[float, float]]: ...
    def get_bounding_box_timeline(self) -> list[tuple[Timecode, BoundingBox]]: ...
```

### 4.1.2 TrackingConfig ve FaceTracker

```python
class TrackingConfig(BaseModel):
    """Yuz takip yapilandirmasi."""
    model: Literal["retinaface","mtcnn","mediapipe","yoloface","insightface"] = "insightface"
    detection_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    tracking_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    max_faces: int = Field(ge=1, default=10)
    min_face_size: int = Field(ge=20, default=30)
    detect_landmarks: bool = True
    landmark_model: Literal["68_point","478_point"] = "478_point"
    detect_pose: bool = True
    detect_attributes: bool = True
    compute_embedding: bool = False
    embedding_model: Literal["arcface","facenet","openface"] = "arcface"
    gpu_enabled: bool = True
    batch_size: int = 8
    device_id: int = 0
    use_tracking: bool = True
    tracker_type: Literal["sort","deepsort","bytetrack","botsort"] = "bytetrack"

class FaceTracker:
    """Yuz takip motoru."""
    def __init__(self, config: Optional[TrackingConfig] = None): ...
    def detect_faces(self, frame: bytes, *, timestamp: Optional[Timecode] = None) -> list[FaceDetection]: ...
    def track_faces(self, frame: bytes, *, timestamp: Optional[Timecode] = None,
                    previous_tracks: Optional[list[FaceTrack]] = None) -> list[FaceDetection]: ...
    def track_video(self, video_path: str, *, time_range: Optional[TimeRange] = None,
                    sample_fps: Optional[float] = None,
                    progress_callback=None) -> list[FaceTrack]: ...
    def detect_faces_in_video(self, video_path: str, *,
                              time_range: Optional[TimeRange] = None,
                              sample_interval: float = 1.0) -> dict[Timecode, list[FaceDetection]]: ...
    def match_faces(self, detections: list[FaceDetection],
                    tracks: list[FaceTrack]) -> dict[UUID, list[FaceDetection]]: ...
    def cluster_faces(self, tracks: list[FaceTrack], *,
                      similarity_threshold: float = 0.6) -> dict[str, list[UUID]]: ...
    def identify_face(self, detection: FaceDetection,
                      reference_embeddings: dict[str, list[float]]) -> tuple[str, float]: ...
    def get_face_statistics(self, tracks: list[FaceTrack]) -> dict[str, Any]: ...
    def get_most_prominent_face(self, tracks: list[FaceTrack]) -> Optional[FaceTrack]: ...
    def get_face_screen_time(self, tracks: list[FaceTrack]) -> dict[str, float]: ...
    def load_model(self, model_name: str) -> None: ...
    def get_available_models(self) -> list[str]: ...
    def warmup(self, sample_count: int = 5) -> None: ...
```

## 4.2 Sahne Tespiti API

### 4.2.1 Sahne Tespit Modelleri

```python
class SceneType(str, Enum):
    CUT = "cut"
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE = "wipe"
    ZOOM = "zoom"
    PUSH = "push"
    FLASH = "flash"
    JUMP_CUT = "jump_cut"
    UNKNOWN = "unknown"

class SceneBoundary(BaseModel):
    """Sahne siniri tespiti."""
    boundary_id: UUID = Field(default_factory=uuid4)
    frame_number: int
    timestamp: Timecode
    scene_type: SceneType
    confidence: float = Field(ge=0.0, le=1.0)
    transition_start_frame: Optional[int] = None
    transition_end_frame: Optional[int] = None
    transition_duration_frames: Optional[int] = None
    score: float = 0.0

class SceneSegment(BaseModel):
    """Sahne parcasi."""
    segment_id: UUID = Field(default_factory=uuid4)
    start_frame: int
    end_frame: int
    start_time: Timecode
    end_time: Timecode
    duration_frames: int
    duration_seconds: float
    scene_type: str
    motion_score: float = 0.0
    content_score: float = 0.0
    color_variance: float = 0.0
    audio_energy: float = 0.0
    face_count: int = 0
    text_detected: bool = False
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    dominant_colors: list[str] = Field(default_factory=list)

class DetectionConfig(BaseModel):
    """Sahne tespit yapilandirmasi."""
    method: Literal["threshold","adaptive","content","combined"] = "combined"
    threshold: float = Field(ge=0.0, le=1.0, default=0.3)
    adaptive_threshold: float = Field(ge=0.0, le=1.0, default=0.25)
    min_scene_duration_ms: int = Field(ge=0, default=500)
    max_scene_duration_ms: int = Field(ge=1000, default=600000)
    detect_transitions: bool = True
    transition_threshold: float = Field(ge=0.0, le=1.0, default=0.15)
    compute_motion: bool = True
    compute_color_histogram: bool = True
    compute_audio_energy: bool = True
    detect_faces: bool = False
    detect_text: bool = False
    use_gpu: bool = True
    batch_size: int = 16
    device_id: int = 0

class SceneDetector:
    """Sahne tespit motoru."""
    def __init__(self, config: Optional[DetectionConfig] = None): ...
    def analyze_frame(self, frame: bytes, previous_frame: Optional[bytes] = None) -> dict[str, float]: ...
    def detect_scenes(self, video_path: str, *,
                      time_range: Optional[TimeRange] = None,
                      progress_callback=None) -> list[SceneBoundary]: ...
    def get_scene_segments(self, video_path: str, *, min_duration_ms: int = 500) -> list[SceneSegment]: ...
    def detect_cuts_only(self, video_path: str, *, threshold: float = 0.3) -> list[Timecode]: ...
    def analyze_scene_content(self, video_path: str, segment: SceneSegment) -> SceneSegment: ...
    def get_best_moments(self, video_path: str, *, count: int = 5,
                          criteria: Literal["motion","emotion","variety","face"] = "emotion")
                          -> list[SceneSegment]: ...
    def filter_by_duration(self, boundaries: list[SceneBoundary], *,
                           min_duration_ms: int = 0, max_duration_ms: int = 999999) -> list[SceneBoundary]: ...
    def filter_by_confidence(self, boundaries: list[SceneBoundary], *,
                             min_confidence: float = 0.0) -> list[SceneBoundary]: ...
    def merge_nearby(self, boundaries: list[SceneBoundary], *, min_gap_ms: int = 500) -> list[SceneBoundary]: ...
    def merge_short_scenes(self, segments: list[SceneSegment], *,
                           min_duration_ms: int = 500) -> list[SceneSegment]: ...
```

## 4.3 Icerik Analizi API

### 4.3.1 Icerik Analiz Modelleri

```python
class ContentCategory(str, Enum):
    TALKING_HEAD = "talking_head"
    ACTION = "action"
    SCENIC = "scenic"
    MUSIC = "music"
    GAMING = "gaming"
    EDUCATION = "education"
    DOCUMENTARY = "documentary"
    INTERVIEW = "interview"
    MONTAGE = "montage"
    BROLL = "broll"
    SCREEN_RECORDING = "screen_recording"
    LIVESTREAM = "livestream"

class ColorPaletteEntry(BaseModel):
    hex_color: str
    percentage: float = Field(ge=0.0, le=100.0)
    name: Optional[str] = None

class TextRegion(BaseModel):
    """Tespit edilen yazi bolgesi."""
    text: str
    bbox: BoundingBox
    confidence: float
    timestamp: Timecode
    duration: Timecode
    language: Optional[str] = None
    font_size: Optional[int] = None
    is_subtitle: bool = False
    is_watermark: bool = False
    is_chyron: bool = False

class AudioEvent(BaseModel):
    """Ses olayi tespiti."""
    event_type: Literal["music","speech","silence","noise","applause","laughter","cheering","sfx","transition"]
    start_time: Timecode
    end_time: Timecode
    confidence: float
    intensity: float = Field(ge=0.0, le=1.0)
    description: str = ""
    bpm: Optional[float] = None
    key: Optional[str] = None

class ContentSegment(BaseModel):
    """Icerik parcasi."""
    segment_id: UUID = Field(default_factory=uuid4)
    start_time: Timecode
    end_time: Timecode
    category: ContentCategory
    description: str
    confidence: float
    tags: list[str] = Field(default_factory=list)
    suggested_edit_points: list[Timecode] = Field(default_factory=list)
    suggested_effects: list[str] = Field(default_factory=list)
    suggested_music: list[str] = Field(default_factory=list)

class Highlight(BaseModel):
    """One cikan an."""
    timestamp: Timecode
    duration: Timecode
    score: float = Field(ge=0.0, le=1.0)
    reason: str
    tags: list[str] = Field(default_factory=list)
    thumbnail_path: Optional[str] = None

class ContentAnalysis(BaseModel):
    """Tam icerik analiz sonucu."""
    video_path: str
    total_duration: Timecode
    total_frames: int
    resolution: tuple[int, int]
    fps: float
    category: ContentCategory
    category_confidence: float
    tags: list[str] = Field(default_factory=list)
    description: str = ""
    dominant_colors: list[str] = Field(default_factory=list)
    color_palette: list[ColorPaletteEntry] = Field(default_factory=list)
    motion_level: Literal["none","low","medium","high","extreme"] = "medium"
    audio_level: Literal["silent","low","normal","loud","very_loud"] = "normal"
    visual_complexity: float = Field(ge=0.0, le=1.0, default=0.5)
    aesthetic_score: float = Field(ge=0.0, le=1.0, default=0.5)
    technical_quality: float = Field(ge=0.0, le=1.0, default=0.5)
    scenes: list[SceneSegment] = Field(default_factory=list)
    faces: list[FaceTrack] = Field(default_factory=list)
    text_regions: list[TextRegion] = Field(default_factory=list)
    audio_events: list[AudioEvent] = Field(default_factory=list)
    segments: list[ContentSegment] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

class AnalysisConfig(BaseModel):
    """Analiz yapilandirmasi."""
    detect_faces: bool = True
    detect_text: bool = True
    detect_scenes: bool = True
    detect_audio_events: bool = True
    analyze_colors: bool = True
    analyze_motion: bool = True
    analyze_audio: bool = True
    compute_aesthetic: bool = True
    compute_quality: bool = True
    auto_tag: bool = True
    auto_describe: bool = True
    find_highlights: bool = True
    highlight_count: int = 5
    sample_fps: float = 1.0
    face_config: Optional[TrackingConfig] = None
    scene_config: Optional[DetectionConfig] = None
    use_gpu: bool = True

class ContentAnalyzer:
    """Tam icerik analiz motoru."""
    def __init__(self, config: Optional[AnalysisConfig] = None): ...
    def analyze(self, video_path: str, *, progress_callback=None) -> ContentAnalysis: ...
    def quick_analyze(self, video_path: str) -> dict[str, Any]: ...
    def classify_content(self, video_path: str) -> tuple[ContentCategory, float]: ...
    def get_segments(self, video_path: str) -> list[ContentSegment]: ...
    def generate_tags(self, video_path: str, *, max_tags: int = 20) -> list[str]: ...
    def generate_description(self, video_path: str, *,
                              style: Literal["concise","detailed","social_media"] = "concise") -> str: ...
    def find_highlights(self, video_path: str, *, count: int = 5,
                         criteria: Literal["motion","emotion","audio","variety","all"] = "all")
                         -> list[Highlight]: ...
    def assess_quality(self, video_path: str) -> dict[str, float]: ...
    def get_tech_report(self, video_path: str) -> dict[str, Any]: ...
```

## 4.4 Duzenleme Karari API

### 4.4.1 Duzenleme Karari Modelleri

```python
class EditStyle(str, Enum):
    TIKTOK_VIRAL = "tiktok_viral"
    YOUTUBE_VLOG = "youtube_vlog"
    CINEMATIC = "cinematic"
    COMMERCIAL = "commercial"
    MUSIC_VIDEO = "music_video"
    DOCUMENTARY = "documentary"
    EDUCATIONAL = "educational"
    SHORT_FORM = "short_form"
    PODCAST = "podcast"
    TUTORIAL = "tutorial"

class EditPoint(BaseModel):
    """Duzenleme noktasi."""
    point_id: UUID = Field(default_factory=uuid4)
    time: Timecode
    type: Literal["cut","fade_in","fade_out","transition","effect_start","effect_end",
                   "subtitle_start","subtitle_end","zoom_start","zoom_end"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    priority: int = Field(ge=1, le=10, default=5)
    transition_type: Optional[Literal["cut","cross_dissolve","dip_black","wipe_left","zoom_in"]] = None
    transition_duration: Optional[Timecode] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class SubtitleTiming(BaseModel):
    """Alt yazi zamanlama onerisi."""
    start_time: Timecode
    end_time: Timecode
    text: str
    position: Literal["top","center","bottom"] = "bottom"
    style: str = "default"
    animation: Optional[Literal["fade","typewriter","pop","slide_up"]] = None
    confidence: float = 1.0

class MusicSuggestion(BaseModel):
    """Muzik onerisi."""
    name: str
    genre: str
    mood: str
    bpm: Optional[float] = None
    start_time: Timecode
    end_time: Timecode
    fade_in: Optional[Timecode] = None
    fade_out: Optional[Timecode] = None
    volume: float = 0.3

class EffectSuggestion(BaseModel):
    """Efekt onerisi."""
    effect_type: EffectType
    start_time: Timecode
    end_time: Timecode
    parameters: dict[str, Any] = Field(default_factory=dict)
    reason: str
    confidence: float

class ColorSuggestion(BaseModel):
    """Renk duzeltme onerisi."""
    preset: Optional[str] = None
    lut: Optional[str] = None
    adjustments: dict[str, float] = Field(default_factory=dict)
    apply_to_range: Optional[TimeRange] = None

class EditDecision(BaseModel):
    """Duzenleme karari."""
    decision_id: UUID = Field(default_factory=uuid4)
    source_video: str
    style: EditStyle
    output_duration: Timecode
    output_resolution: tuple[int, int]
    edit_points: list[EditPoint] = Field(default_factory=list)
    subtitle_timings: list[SubtitleTiming] = Field(default_factory=list)
    music_suggestions: list[MusicSuggestion] = Field(default_factory=list)
    effect_suggestions: list[EffectSuggestion] = Field(default_factory=list)
    color_suggestion: Optional[ColorSuggestion] = None
    overall_pacing: Literal["fast","medium","slow"] = "medium"
    energy_curve: list[tuple[Timecode, float]] = Field(default_factory=list)
    estimated_engagement: float = Field(ge=0.0, le=1.0, default=0.5)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    timeline_preview: Optional[Timeline] = None

class EditDecisionConfig:
    """Duzenleme karari yapilandirmasi."""
    style: EditStyle = EditStyle.SHORT_FORM
    target_duration: Optional[Timecode] = None
    output_resolution: tuple[int, int] = (1080, 1920)
    output_fps: float = 30.0
    auto_subtitle: bool = True
    auto_music: bool = True
    auto_effects: bool = True
    auto_color: bool = True
    max_cuts_per_minute: int = 15
    min_shot_duration_ms: int = 500
    max_shot_duration_ms: int = 30000
    prefer_face_shots: bool = True
    prefer_action_shots: bool = False
    avoid_jump_cuts: bool = True
    energy_level: Literal["low","medium","high","adaptive"] = "medium"

class EditDecisionEngine:
    """Otomatik duzenleme karari motoru."""
    def __init__(self, config: Optional[EditDecisionConfig] = None): ...
    def generate_edit_decision(self, video_path: str, *,
                               analysis: Optional[ContentAnalysis] = None) -> EditDecision: ...
    def generate_edit_decision_from_analysis(self, analysis: ContentAnalysis) -> EditDecision: ...
    def find_edit_points(self, video_path: str, *,
                          style: EditStyle = EditStyle.SHORT_FORM) -> list[EditPoint]: ...
    def find_best_clips(self, video_path: str, *, count: int = 10,
                        min_duration: Timecode = Timecode(hours=0,minutes=0,seconds=1,frames=0),
                        max_duration: Timecode = Timecode(hours=0,minutes=0,seconds=10,frames=0))
                        -> list[tuple[TimeRange, float]]: ...
    def optimize_pacing(self, edit_decision: EditDecision, *,
                        energy_curve: Optional[list[tuple[Timecode, float]]] = None) -> EditDecision: ...
    def align_to_music(self, edit_decision: EditDecision, music_path: str, *,
                       beat_detection: bool = True) -> EditDecision: ...
    def simulate_edit(self, edit_decision: EditDecision) -> Timeline: ...
    def preview_edit(self, edit_decision: EditDecision, *,
                     preview_fps: float = 15.0) -> list[bytes]: ...
    def get_edit_summary(self, decision: EditDecision) -> dict[str, Any]: ...
    def export_decision(self, decision: EditDecision,
                        format: Literal["edl","fcp7","json"]) -> str: ...
```

---
# 5. Tipografi ve Grafik API (Modul 4 Referansi)

## 5.1 Alt Yazi Motoru API

```python
class SubtitleFormat(str, Enum):
    SRT = "srt"
    ASS = "ass"
    SSA = "ssa"
    VTT = "vtt"
    TTML = "ttml"
    JSON = "json"
    EBU_STL = "ebu_stl"

class SubtitleStyle(BaseModel):
    """Alt yazi stili."""
    font_family: str = "Arial"
    font_size: int = 48
    font_weight: Literal["normal","bold","light"] = "normal"
    font_style: Literal["normal","italic"] = "normal"
    color: str = "#FFFFFF"
    background_color: Optional[str] = None
    outline_color: str = "#000000"
    outline_width: int = 2
    shadow_color: str = "#000000"
    shadow_offset_x: int = 1
    shadow_offset_y: int = 1
    shadow_blur: float = 0.0
    position: Literal["top","center","bottom"] = "bottom"
    margin_left: int = 20
    margin_right: int = 20
    margin_top: int = 20
    margin_bottom: int = 60
    alignment: Literal["left","center","right"] = "center"
    line_spacing: float = 1.2
    letter_spacing: float = 0.0
    word_spacing: float = 0.0
    border_style: Literal["outline","background"] = "outline"
    wrap_style: Literal["smart","end_of_line","none"] = "smart"
    kerning: bool = True
    opacity: float = 1.0

class WordTiming(BaseModel):
    """Kelime zamanlamasi."""
    word: str
    start_time: Timecode
    end_time: Timecode
    confidence: float = 1.0
    phonemes: list[Phoneme] = Field(default_factory=list)

class Phoneme(BaseModel):
    phoneme: str
    start_time: Timecode
    end_time: Timecode

class SubtitleAnimation(BaseModel):
    """Alt yazi animasyonu."""
    animation_type: Literal["fade_in","fade_out","typewriter","pop_in",
                             "slide_up","slide_down","scale_up","bounce",
                             "wave","glitch","highlight_word","karaoke_fill"]
    duration: Timecode = Timecode(hours=0, minutes=0, seconds=0, frames=15)
    delay: Timecode = Timecode(hours=0, minutes=0, seconds=0, frames=0)
    easing: Literal["linear","ease_in","ease_out","ease_in_out","bounce","elastic"] = "ease_in_out"
    parameters: dict[str, Any] = Field(default_factory=dict)

class SubtitleEntry(BaseModel):
    """Tek bir alt yazi satiri."""
    index: int = 0
    start_time: Timecode
    end_time: Timecode
    text: str
    style: Optional[SubtitleStyle] = None
    animation: Optional[SubtitleAnimation] = None
    position_override: Optional[tuple[int, int]] = None
    words: list[WordTiming] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    @property
    def duration(self) -> Timecode: ...
    @property
    def character_count(self) -> int: ...
    @property
    def words_per_second(self) -> float: ...

class SubtitleTrack(BaseModel):
    """Alt yazi klibi."""
    track_id: UUID = Field(default_factory=uuid4)
    name: str = "Default"
    language: str = "tr"
    entries: list[SubtitleEntry] = Field(default_factory=list)
    global_style: SubtitleStyle = Field(default_factory=SubtitleStyle)
    visible: bool = True
    locked: bool = False
    def add_entry(self, entry: SubtitleEntry) -> None: ...
    def remove_entry(self, index: int) -> None: ...
    def sort_entries(self) -> None: ...
    def get_entry_at(self, time: Timecode) -> Optional[SubtitleEntry]: ...
    def get_entries_in_range(self, time_range: TimeRange) -> list[SubtitleEntry]: ...
    def reflow(self, max_chars_per_line: int = 42) -> None: ...
    def adjust_timing(self, delta: Timecode) -> None: ...
    def validate(self) -> list[str]: ...
    def get_total_characters(self) -> int: ...
    def estimate_reading_speed(self) -> float: ...
    def split_long_entries(self, max_duration_ms: int = 7000) -> None: ...

class SubtitleEngine:
    """Alt yazi motoru."""
    def __init__(self, *, default_style: Optional[SubtitleStyle] = None,
                  language: str = "tr", max_line_length: int = 42): ...
    def parse(self, content: str, format: SubtitleFormat) -> SubtitleTrack: ...
    def parse_file(self, file_path: str) -> SubtitleTrack: ...
    def export(self, track: SubtitleTrack, format: SubtitleFormat) -> str: ...
    def export_file(self, track: SubtitleTrack, file_path: str, format: SubtitleFormat) -> None: ...
    def auto_time(self, track: SubtitleTrack, video_path: str, *,
                   method: Literal["whisper","vosk","speech_recognition"] = "whisper") -> SubtitleTrack: ...
    def adjust_timing(self, track: SubtitleTrack, delta: Timecode) -> SubtitleTrack: ...
    def sync_to_audio(self, track: SubtitleTrack, audio_path: str, *,
                       tolerance_ms: int = 100) -> SubtitleTrack: ...
    def generate_word_timings(self, track: SubtitleTrack, audio_path: str) -> SubtitleTrack: ...
    def apply_style(self, track: SubtitleTrack, style: SubtitleStyle, *,
                     entry_indices: Optional[list[int]] = None) -> SubtitleTrack: ...
    def apply_animation(self, track: SubtitleTrack, animation: SubtitleAnimation, *,
                         entry_indices: Optional[list[int]] = None) -> SubtitleTrack: ...
    def apply_template(self, track: SubtitleTrack, template_name: str) -> SubtitleTrack: ...
    def reflow_text(self, track: SubtitleTrack, *,
                     max_chars_per_line: int = 42, max_lines: int = 2) -> SubtitleTrack: ...
    def optimize_reading_speed(self, track: SubtitleTrack, *,
                                min_duration_ms: int = 800,
                                max_chars_per_second: float = 20.0) -> SubtitleTrack: ...
    def remove_duplicates(self, track: SubtitleTrack, *,
                           time_threshold_ms: int = 100) -> SubtitleTrack: ...
    def burn_in(self, video_path: str, track: SubtitleTrack, output_path: str, *,
                style: Optional[SubtitleStyle] = None, hard_sub: bool = True) -> str: ...
    def generate_preview_frames(self, track: SubtitleTrack, video_path: str, *,
                                 sample_count: int = 10) -> list[bytes]: ...
```

## 5.2 Karaoke Sistemi API

```python
class KaraokeDisplayMode(str, Enum):
    FILL_LEFT_TO_RIGHT = "fill_left_to_right"
    WORD_BY_WORD = "word_by_word"
    SYLLABLE_BY_SYLLABLE = "syllable_by_syllable"
    HIGHLIGHT_ACTIVE = "highlight_active"
    GLOW_EFFECT = "glow_effect"
    BOUNCE = "bounce"
    COLOR_WAVE = "color_wave"

class KaraokeStyle(BaseModel):
    """Karaoke stili."""
    base_color: str = "#FFFFFF"
    active_color: str = "#FFD700"
    past_color: str = "#808080"
    glow_color: Optional[str] = "#FFD700"
    glow_radius: float = 5.0
    font_family: str = "Arial Black"
    font_size: int = 56
    font_weight: Literal["normal","bold"] = "bold"
    stroke_color: str = "#000000"
    stroke_width: int = 3
    shadow_enabled: bool = True
    shadow_color: str = "#000000"
    shadow_offset: tuple[int, int] = (2, 2)
    bounce_height: int = 10
    animation_speed: float = 1.0
    position: Literal["top","center","bottom"] = "bottom"
    margin_bottom: int = 80

class KaraokeEntry(BaseModel):
    """Tek bir karaoke satiri."""
    index: int
    text: str
    words: list[WordTiming]
    start_time: Timecode
    end_time: Timecode
    style: Optional[KaraokeStyle] = None
    display_mode: KaraokeDisplayMode = KaraokeDisplayMode.WORD_BY_WORD
    def get_active_word_at(self, time: Timecode) -> Optional[WordTiming]: ...
    def get_progress_at(self, time: Timecode) -> float: ...

class KaraokeTrack(BaseModel):
    """Karaoke parcasi."""
    track_id: UUID = Field(default_factory=uuid4)
    title: str = ""
    artist: str = ""
    entries: list[KaraokeEntry] = Field(default_factory=list)
    style: KaraokeStyle = Field(default_factory=KaraokeStyle)
    bpm: Optional[float] = None
    key: Optional[str] = None
    language: str = "tr"
    def add_entry(self, entry: KaraokeEntry) -> None: ...
    def get_entry_at(self, time: Timecode) -> Optional[KaraokeEntry]: ...
    def sync_to_lyrics(self, lyrics: str, audio_path: str) -> None: ...

class KaraokeSystem:
    """Karaoke yonetim sistemi."""
    def __init__(self, default_style: Optional[KaraokeStyle] = None): ...
    def create_from_lyrics(self, lyrics: str, audio_path: str, *,
                           style: Optional[KaraokeStyle] = None) -> KaraokeTrack: ...
    def create_from_srt(self, srt_path: str, audio_path: str) -> KaraokeTrack: ...
    def create_from_timing_data(self, lyrics: str, timing_data: list[WordTiming], *,
                                 style: Optional[KaraokeStyle] = None) -> KaraokeTrack: ...
    def detect_words(self, audio_path: str, lyrics: str) -> list[WordTiming]: ...
    def detect_phonemes(self, audio_path: str, text: str) -> list[Phoneme]: ...
    def align_to_beats(self, track: KaraokeTrack, audio_path: str, *,
                       detect_bpm: bool = True) -> KaraokeTrack: ...
    def set_display_mode(self, track: KaraokeTrack, mode: KaraokeDisplayMode) -> KaraokeTrack: ...
    def set_style(self, track: KaraokeTrack, style: KaraokeStyle) -> KaraokeTrack: ...
    def apply_preset(self, track: KaraokeTrack, preset_name: str) -> KaraokeTrack: ...
    def render_frames(self, track: KaraokeTrack, time_range: TimeRange, *,
                       width: int = 1920, height: int = 1080, fps: float = 30.0) -> list[bytes]: ...
    def burn_in(self, video_path: str, track: KaraokeTrack, output_path: str) -> str: ...
    def validate_timing(self, track: KaraokeTrack) -> list[str]: ...
    def get_difficulty_score(self, track: KaraokeTrack) -> float: ...
    def suggest_tempo_adjustments(self, track: KaraokeTrack) -> list[dict]: ...
```

## 5.3 Animasyon Motoru API

```python
class EasingFunction(str, Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    EASE_IN_CUBIC = "ease_in_cubic"
    EASE_OUT_CUBIC = "ease_out_cubic"
    EASE_IN_OUT_CUBIC = "ease_in_out_cubic"
    EASE_IN_BACK = "ease_in_back"
    EASE_OUT_BACK = "ease_out_back"
    EASE_IN_OUT_BACK = "ease_in_out_back"
    EASE_IN_ELASTIC = "ease_in_elastic"
    EASE_OUT_ELASTIC = "ease_out_elastic"
    EASE_IN_OUT_ELASTIC = "ease_in_out_elastic"
    EASE_IN_BOUNCE = "ease_in_bounce"
    EASE_OUT_BOUNCE = "ease_out_bounce"
    EASE_IN_OUT_BOUNCE = "ease_in_out_bounce"
    SPRING = "spring"
    ANTICIPATE = "anticipate"

class AnimationKeyframe(BaseModel):
    """Animasyon anahtar karesi."""
    time: Timecode
    value: Any
    easing: EasingFunction = EasingFunction.EASE_IN_OUT
    bezier_p1: Optional[tuple[float, float]] = None
    bezier_p2: Optional[tuple[float, float]] = None
    overshoot: float = 0.0

class AnimationTrack(BaseModel):
    """Animasyon izi (bir ozelligin zaman serisi)."""
    track_id: UUID = Field(default_factory=uuid4)
    property_name: str
    keyframes: list[AnimationKeyframe] = Field(default_factory=list)
    interpolation: Literal["linear","bezier","step"] = "bezier"
    pre_extrapolate: Literal["none","constant","loop","ping_pong"] = "none"
    post_extrapolate: Literal["none","constant","loop","ping_pong"] = "none"
    def evaluate(self, time: Timecode) -> Any: ...
    def add_keyframe(self, keyframe: AnimationKeyframe) -> None: ...
    def remove_keyframe(self, time: Timecode) -> None: ...
    def get_duration(self) -> Timecode: ...
    def offset_time(self, delta: Timecode) -> None: ...
    def scale_time(self, factor: float) -> None: ...

class AnimationPreset(BaseModel):
    """Animasyon on ayari."""
    id: UUID = Field(default_factory=uuid4)
    name: str
    tracks: list[AnimationTrack] = Field(default_factory=list)
    category: str = "general"
    tags: list[str] = Field(default_factory=list)
    thumbnail: Optional[str] = None
    description: str = ""

class AnimationPresetCategory(str, Enum):
    ENTRANCE = "entrance"
    EXIT = "exit"
    EMPHASIS = "emphasis"
    TRANSITION = "transition"
    KARAOKE = "karaoke"
    EFFECT = "effect"

class AnimationEngine:
    """Animasyon motoru."""
    def __init__(self): ...
    def create_track(self, property_name: str, keyframes: list[AnimationKeyframe], *,
                      interpolation: str = "bezier") -> AnimationTrack: ...
    def create_spring_animation(self, property_name: str, from_value: Any, to_value: Any, *,
                                 stiffness: float = 100.0, damping: float = 10.0,
                                 mass: float = 1.0) -> AnimationTrack: ...
    def create_bounce_animation(self, property_name: str, from_value: Any, to_value: Any, *,
                                 bounces: int = 3, amplitude: float = 0.3) -> AnimationTrack: ...
    def create_typewriter_animation(self, text: str, *,
                                     characters_per_second: float = 20.0,
                                     cursor: bool = True) -> AnimationTrack: ...
    def create_wave_animation(self, property_name: str, values: list[Any], *,
                               frequency: float = 1.0, amplitude: float = 1.0) -> AnimationTrack: ...
    def sequence(self, *tracks: AnimationTrack) -> AnimationTrack: ...
    def parallel(self, *tracks: AnimationTrack) -> list[AnimationTrack]: ...
    def loop(self, track: AnimationTrack, *, count: int = -1,
             duration: Optional[Timecode] = None) -> AnimationTrack: ...
    def ping_pong(self, track: AnimationTrack) -> AnimationTrack: ...
    def offset(self, track: AnimationTrack, delta: Timecode) -> AnimationTrack: ...
    def get_presets(self, category: Optional[AnimationPresetCategory] = None) -> list[AnimationPreset]: ...
    def apply_preset(self, preset_id: UUID, target_property: str) -> AnimationTrack: ...
    def create_preset(self, name: str, tracks: list[AnimationTrack], *,
                       category: AnimationPresetCategory = AnimationPresetCategory.EMPHASIS) -> AnimationPreset: ...
    def evaluate_track(self, track: AnimationTrack, time: Timecode) -> Any: ...
    def evaluate_tracks(self, tracks: list[AnimationTrack], time: Timecode) -> dict[str, Any]: ...
    def render_to_keyframes(self, tracks: list[AnimationTrack], fps: float) -> list[dict[str, Any]]: ...
    @staticmethod
    def get_easing_value(easing: EasingFunction, progress: float, *,
                          overshoot: float = 0.0) -> float: ...
```

## 5.4 Sticker Motoru API

```python
class StickerType(str, Enum):
    STATIC_IMAGE = "static_image"
    ANIMATED_GIF = "animated_gif"
    ANIMATED_WEBP = "animated_webp"
    LOTTIE = "lottie"
    SVG = "svg"
    VIDEO_STICKER = "video_sticker"
    EMOJI = "emoji"
    CUSTOM_GRAPHIC = "custom_graphic"

class StickerPosition(BaseModel):
    x: float
    y: float
    coordinate_mode: Literal["relative","absolute"] = "relative"
    anchor: Literal["top_left","top_center","top_right","center_left","center",
                     "center_right","bottom_left","bottom_center","bottom_right"] = "center"
    follow_face: bool = False
    face_index: int = 0
    follow_object: bool = False
    object_tracking_id: Optional[UUID] = None

class StickerTransform(BaseModel):
    scale_x: float = Field(default=1.0, gt=0)
    scale_y: float = Field(default=1.0, gt=0)
    rotation: float = Field(default=0.0)
    skew_x: float = 0.0
    skew_y: float = 0.0
    flip_horizontal: bool = False
    flip_vertical: bool = False
    opacity: float = Field(default=1.0, ge=0.0, le=1.0)

class StickerInstance(BaseModel):
    """Sticker ornegi."""
    instance_id: UUID = Field(default_factory=uuid4)
    sticker_id: Optional[UUID] = None
    sticker_type: StickerType
    source_path: str
    position: StickerPosition = Field(default_factory=StickerPosition)
    transform: StickerTransform = Field(default_factory=StickerTransform)
    start_time: Timecode
    end_time: Timecode
    animation: Optional[AnimationPreset] = None
    animation_tracks: list[AnimationTrack] = Field(default_factory=list)
    visible: bool = True
    locked: bool = False
    blend_mode: BlendMode = BlendMode.NORMAL
    layer_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

class StickerEngine:
    """Sticker yonetim motoru."""
    def __init__(self, assets_dir: str = "./assets/stickers"): ...
    def add_sticker(self, timeline: Timeline, sticker, *,
                     start_time: Timecode, end_time: Timecode,
                     position=None, transform=None) -> StickerInstance: ...
    def remove_sticker(self, instance_id: UUID) -> None: ...
    def update_sticker(self, instance_id: UUID, *, position=None,
                       transform=None, start_time=None, end_time=None) -> StickerInstance: ...
    def duplicate_sticker(self, instance_id: UUID, *, offset=None) -> StickerInstance: ...
    def attach_to_face(self, timeline: Timeline, sticker, face_tracks: list[FaceTrack], *,
                        face_index: int = 0, offset=None, scale: float = 1.0, rotation: float = 0.0) -> StickerInstance: ...
    def attach_to_all_faces(self, timeline: Timeline, sticker, face_tracks, *,
                             max_faces: int = 10) -> list[StickerInstance]: ...
    def load_collection(self, collection_path: str) -> dict: ...
    def search_stickers(self, query: str) -> list: ...
    def import_sticker(self, source_path: str, *, sticker_type=StickerType.STATIC_IMAGE,
                       name=None, tags=None) -> dict: ...
    def render_sticker_frame(self, sticker, frame_number: int, *,
                              width: int = 200, height: int = 200) -> bytes: ...
    def compose_stickers(self, video_frame: bytes, stickers: list[StickerInstance],
                         time: Timecode) -> bytes: ...
```

---
# 6. Ses API (Modul 5 Referansi)

## 6.1 Mikser API

```python
class AudioTrack(BaseModel):
    """Ses izi."""
    track_id: UUID = Field(default_factory=uuid4)
    name: str
    source_path: str
    duration: Timecode
    sample_rate: int = 44100
    channels: int = 2
    bit_depth: int = 16
    volume: float = Field(ge=0.0, le=2.0, default=1.0)
    pan: float = Field(ge=-1.0, le=1.0, default=0.0)
    mute: bool = False
    solo: bool = False
    locked: bool = False
    start_offset: Timecode = Timecode(hours=0, minutes=0, seconds=0, frames=0)
    trim_in: Timecode = Timecode(hours=0, minutes=0, seconds=0, frames=0)
    trim_out: Optional[Timecode] = None
    eq_bands: list[EQBand] = Field(default_factory=list)
    compressor: Optional[CompressorSettings] = None
    effects: list[str] = Field(default_factory=list)

class EQBand(BaseModel):
    frequency: float
    gain_db: float = Field(ge=-24.0, le=24.0)
    q_factor: float = Field(gt=0, default=1.0)
    band_type: Literal["low_shelf","peak","high_shelf","low_pass","high_pass"] = "peak"

class CompressorSettings(BaseModel):
    threshold_db: float = Field(ge=-60.0, le=0.0, default=-20.0)
    ratio: float = Field(gt=1.0, le=20.0, default=4.0)
    attack_ms: float = Field(ge=0.1, le=200.0, default=10.0)
    release_ms: float = Field(ge=10.0, le=2000.0, default=100.0)
    makeup_gain_db: float = Field(ge=0.0, le=24.0, default=0.0)
    knee_db: float = Field(ge=0.0, le=36.0, default=6.0)

class MixerConfig(BaseModel):
    """Mixer yapilandirmasi."""
    master_volume: float = Field(ge=0.0, le=2.0, default=1.0)
    master_pan: float = Field(ge=-1.0, le=1.0, default=0.0)
    sample_rate: int = 44100
    bit_depth: int = 16
    channels: int = 2
    output_format: Literal["wav","mp3","aac","flac","ogg"] = "wav"
    normalize: bool = False
    target_lufs: float = -14.0

class AudioMixer:
    """Ses mikser motoru."""
    def __init__(self, config: Optional[MixerConfig] = None): ...
    def add_track(self, source_path: str, name: str, *,
                   start_offset: Timecode = Timecode(hours=0, minutes=0, seconds=0, frames=0)) -> AudioTrack: ...
    def remove_track(self, track_id: UUID) -> Optional[AudioTrack]: ...
    def get_track(self, track_id: UUID) -> Optional[AudioTrack]: ...
    def get_all_tracks(self) -> list[AudioTrack]: ...
    def set_volume(self, track_id: UUID, volume: float) -> None: ...
    def set_pan(self, track_id: UUID, pan: float) -> None: ...
    def set_mute(self, track_id: UUID, mute: bool) -> None: ...
    def set_solo(self, track_id: UUID, solo: bool) -> None: ...
    def apply_eq(self, track_id: UUID, bands: list[EQBand]) -> None: ...
    def apply_compressor(self, track_id: UUID, settings: CompressorSettings) -> None: ...
    def mix(self, time_range: TimeRange, *, output_path: Optional[str] = None) -> bytes: ...
    def mix_to_file(self, output_path: str, time_range: Optional[TimeRange] = None) -> str: ...
    def get_meter_levels(self, time: Timecode) -> dict[UUID, tuple[float, float]]: ...
    def get_peak_levels(self, time_range: TimeRange) -> dict[UUID, tuple[float, float]]: ...
    def analyze_track(self, track_id: UUID) -> dict[str, Any]: ...
    def get_duration(self) -> Timecode: ...
```

## 6.2 Loudness API

```python
class LoudnessStandard(str, Enum):
    EBU_R128 = "ebu_r128"
    ITU_R_BS1770 = "itu_r_bs1770"
    ATSC_A85 = "atsc_a85"
    ARIB_TR_B32 = "arib_tr_b32"
    OPUS = "opus"
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"
    PODCAST = "podcast"
    CUSTOM = "custom"

class LoudnessMeasurement(BaseModel):
    """Loluk olcum sonucu."""
    integrated_lufs: float
    loudness_range_lu: float
    short_term_lufs: float
    momentary_lufs: float
    true_peak_dbtp: float
    sample_peak_dbfs: float
    measurement_duration_seconds: float
    below_threshold_percentage: float
    above_threshold_percentage: float

class LoudnessConfig(BaseModel):
    """Loluk yapilandirmasi."""
    standard: LoudnessStandard = LoudnessStandard.EBU_R128
    target_lufs: float = -14.0
    target_true_peak_dbtp: float = -1.0
    target_lra: float = 7.0
    max_lra: float = 20.0
    min_lra: float = 1.0
    gate_threshold: float = -70.0
    relative_gate_threshold: float = -10.0
    momentary_window_ms: int = 400
    short_term_window_ms: int = 3000

class LoudnessManager:
    """Loluk yonetim motoru."""
    def __init__(self, config: Optional[LoudnessConfig] = None): ...
    def measure(self, audio_path: str, *, time_range: Optional[TimeRange] = None) -> LoudnessMeasurement: ...
    def measure_stream(self, audio_data: bytes, *,
                        sample_rate: int = 44100, channels: int = 2) -> LoudnessMeasurement: ...
    def normalize(self, audio_path: str, output_path: str, *,
                   target_lufs: Optional[float] = None,
                   target_true_peak: Optional[float] = None) -> str: ...
    def normalize_stream(self, audio_data: bytes, *,
                          target_lufs: Optional[float] = None) -> bytes: ...
    def analyze_loudness_timeline(self, audio_path: str, *,
                                   window_ms: int = 3000) -> list[tuple[Timecode, LoudnessMeasurement]]: ...
    def check_compliance(self, audio_path: str, standard: Optional[LoudnessStandard] = None)
                         -> tuple[bool, list[str]]: ...
    def get_recommended_settings(self, content_type: str) -> LoudnessConfig: ...
    def apply_limiting(self, audio_path: str, output_path: str, *,
                        true_peak_limit: float = -1.0) -> str: ...
```

## 6.3 Ducking API

```python
class DuckingMode(str, Enum):
    SIDECHAIN = "sidechain"
    DIALOG_FOLLOW = "dialog_follow"
    BEAT_SYNC = "beat_sync"
    MANUAL = "manual"

class DuckingConfig(BaseModel):
    """Ducking yapilandirmasi."""
    mode: DuckingMode = DuckingMode.SIDECHAIN
    trigger_track_id: UUID
    target_track_ids: list[UUID]
    duck_amount_db: float = Field(ge=-30.0, le=0.0, default=-12.0)
    attack_ms: float = Field(ge=1.0, le=500.0, default=50.0)
    release_ms: float = Field(ge=10.0, le=5000.0, default=200.0)
    hold_ms: float = Field(ge=0.0, le=5000.0, default=100.0)
    lookahead_ms: float = Field(ge=0.0, le=100.0, default=10.0)
    threshold_db: float = Field(ge=-60.0, le=0.0, default=-30.0)
    range_db: float = Field(ge=-30.0, le=0.0, default=-12.0)
    time_constant_ms: float = Field(ge=1.0, le=1000.0, default=100.0)
    fade_curve: Literal["linear", "logarithmic", "s_curve"] = "logarithmic"

class DuckingEvent(BaseModel):
    """Ducking olayi."""
    start_time: Timecode
    end_time: Timecode
    trigger_amplitude: float
    duck_amount_applied: float
    target_track_id: UUID

class AudioDucker:
    """Ses ducking motoru."""
    def __init__(self, mixer: AudioMixer): ...
    def apply_ducking(self, config: DuckingConfig) -> list[DuckingEvent]: ...
    def remove_ducking(self, target_track_id: UUID) -> None: ...
    def analyze_ducking(self, config: DuckingConfig) -> list[DuckingEvent]: ...
    def preview_ducking(self, config: DuckingConfig, *, time_range: Optional[TimeRange] = None)
                        -> dict[UUID, bytes]: ...
    def auto_duck_speech(self, music_track_id: UUID, speech_track_id: UUID, *,
                          duck_amount_db: float = -12.0) -> list[DuckingEvent]: ...
    def auto_duck_narration(self, music_track_id: UUID, narration_track_id: UUID) -> list[DuckingEvent]: ...
    def get_ducking_curve(self, config: DuckingConfig) -> list[tuple[Timecode, float]]: ...
```

---
# 7. Altyapi API (Modul 6 Referansi)

## 7.1 Render Kuyrugu API

```python
class JobPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    BACKGROUND = "background"

class JobStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"

class RenderJob(BaseModel):
    """Render is gorevi."""
    job_id: UUID = Field(default_factory=uuid4)
    name: str
    timeline_id: UUID
    output_path: str
    status: JobStatus = JobStatus.PENDING
    priority: JobPriority = JobPriority.NORMAL
    progress: float = Field(ge=0.0, le=100.0, default=0.0)
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    estimated_completion: Optional[str] = None
    worker_id: Optional[UUID] = None
    retry_count: int = 0
    max_retries: int = 3
    error_message: Optional[str] = None
    render_config: Optional[RenderOptions] = None
    metadata: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    dependencies: list[UUID] = Field(default_factory=list)
    callback_url: Optional[str] = None
    webhook_events: list[str] = Field(default_factory=list)

class RenderQueue:
    """Render kuyruğu yoneticisi."""
    def __init__(self, redis_url: str = "redis://localhost:6379"): ...
    def enqueue(self, job: RenderJob) -> UUID: ...
    def dequeue(self) -> Optional[RenderJob]: ...
    def get_job(self, job_id: UUID) -> Optional[RenderJob]: ...
    def cancel_job(self, job_id: UUID) -> bool: ...
    def pause_job(self, job_id: UUID) -> bool: ...
    def resume_job(self, job_id: UUID) -> bool: ...
    def retry_job(self, job_id: UUID) -> bool: ...
    def update_progress(self, job_id: UUID, progress: float) -> None: ...
    def get_queue_size(self) -> int: ...
    def get_jobs_by_status(self, status: JobStatus) -> list[RenderJob]: ...
    def get_all_jobs(self, *, limit: int = 100, offset: int = 0) -> list[RenderJob]: ...
    def clear_completed(self) -> int: ...
    def get_statistics(self) -> dict[str, Any]: ...
    def prioritize(self, job_id: UUID, priority: JobPriority) -> None: ...
```

## 7.2 Worker Havuzu API

```python
class WorkerInfo(BaseModel):
    """Is parcacigi bilgisi."""
    worker_id: UUID = Field(default_factory=uuid4)
    hostname: str
    pid: int
    status: Literal["idle", "busy", "stopped", "error"] = "idle"
    current_job_id: Optional[UUID] = None
    capabilities: list[str] = Field(default_factory=list)
    gpu_devices: list[int] = Field(default_factory=list)
    max_concurrent: int = 1
    cpu_cores: int = 0
    memory_mb: int = 0
    started_at: str
    last_heartbeat: str
    jobs_completed: int = 0
    jobs_failed: int = 0

class WorkerPool:
    """Is parcacigi havuzu yoneticisi."""
    def __init__(self, *, min_workers: int = 1, max_workers: int = 8,
                 heartbeat_interval: int = 30): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_workers(self) -> list[WorkerInfo]: ...
    def get_idle_workers(self) -> list[WorkerInfo]: ...
    def get_worker(self, worker_id: UUID) -> Optional[WorkerInfo]: ...
    def scale_up(self, count: int) -> list[WorkerInfo]: ...
    def scale_down(self, count: int) -> int: ...
    def assign_job(self, worker_id: UUID, job_id: UUID) -> bool: ...
    def release_worker(self, worker_id: UUID) -> None: ...
    def get_pool_stats(self) -> dict[str, Any]: ...
    def health_check(self) -> dict[UUID, bool]: ...
    def restart_worker(self, worker_id: UUID) -> bool: ...
```

## 7.3 Is Zamanlayici API

```python
class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    CRON = "cron"
    DAILY = "daily"
    WEEKLY = "weekly"

class ScheduledJob(BaseModel):
    """Zamanlanmis is gorevi."""
    schedule_id: UUID = Field(default_factory=uuid4)
    name: str
    schedule_type: ScheduleType
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    next_run_time: Optional[str] = None
    last_run_time: Optional[str] = None
    job_template: RenderJob
    enabled: bool = True
    max_runs: Optional[int] = None
    total_runs: int = 0
    failed_runs: int = 0

class JobScheduler:
    """Is zamanlayici yoneticisi."""
    def __init__(self, render_queue: RenderQueue): ...
    def schedule(self, job: ScheduledJob) -> UUID: ...
    def unschedule(self, schedule_id: UUID) -> bool: ...
    def get_schedule(self, schedule_id: UUID) -> Optional[ScheduledJob]: ...
    def get_all_schedules(self) -> list[ScheduledJob]: ...
    def enable(self, schedule_id: UUID) -> None: ...
    def disable(self, schedule_id: UUID) -> None: ...
    def trigger_now(self, schedule_id: UUID) -> Optional[UUID]: ...
    def get_run_history(self, schedule_id: UUID) -> list[dict[str, Any]]: ...
```

## 7.4 Varlik Yoneticisi API

```python
class AssetType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    SUBTITLE = "subtitle"
    LUT = "lut"
    FONT = "font"
    TEMPLATE = "template"
    EFFECT = "effect"
    PROJECT = "project"
    OTHER = "other"

class Asset(BaseModel):
    """Varlik nesnesi."""
    asset_id: UUID = Field(default_factory=uuid4)
    name: str
    asset_type: AssetType
    file_path: str
    file_size: int = 0
    mime_type: str = ""
    duration: Optional[Timecode] = None
    resolution: Optional[tuple[int, int]] = None
    created_at: str
    updated_at: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    thumbnail_path: Optional[str] = None
    proxy_path: Optional[str] = None
    original_filename: str = ""
    checksum: str = ""
    storage_backend: str = "local"

class AssetManager:
    """Varlik yonetim motoru."""
    def __init__(self, storage_backend: str = "local",
                 storage_path: str = "./assets"): ...
    def upload(self, file_path: str, *, name: Optional[str] = None,
               asset_type: AssetType = AssetType.OTHER,
               tags: Optional[list[str]] = None) -> Asset: ...
    def download(self, asset_id: UUID, output_path: str) -> str: ...
    def get_asset(self, asset_id: UUID) -> Optional[Asset]: ...
    def search(self, query: str, *, asset_type: Optional[AssetType] = None,
               tags: Optional[list[str]] = None) -> list[Asset]: ...
    def delete(self, asset_id: UUID) -> bool: ...
    def update_metadata(self, asset_id: UUID, metadata: dict[str, Any]) -> None: ...
    def generate_thumbnail(self, asset_id: UUID) -> Optional[str]: ...
    def generate_proxy(self, asset_id: UUID, *, resolution: tuple[int, int] = (640, 360)) -> Optional[str]: ...
    def get_storage_usage(self) -> dict[str, Any]: ...
    def list_assets(self, *, asset_type: Optional[AssetType] = None,
                     limit: int = 100, offset: int = 0) -> list[Asset]: ...
```

## 7.5 Onbellek Yoneticisi API

```python
class CacheStrategy(str, Enum):
    LRU = "lru"
    LFU = "lfu"
    TTL = "ttl"
    MANUAL = "manual"

class CacheEntry(BaseModel):
    """Onbellek girisi."""
    key: str
    value: Any
    size_bytes: int
    created_at: str
    last_accessed: str
    access_count: int = 0
    ttl_seconds: Optional[int] = None
    tags: list[str] = Field(default_factory=list)

class CacheManager:
    """Onbellek yonetim motoru."""
    def __init__(self, *, max_size_mb: int = 2048,
                 strategy: CacheStrategy = CacheStrategy.LRU,
                 default_ttl: Optional[int] = None): ...
    def get(self, key: str) -> Optional[Any]: ...
    def set(self, key: str, value: Any, *, ttl: Optional[int] = None,
             tags: Optional[list[str]] = None) -> None: ...
    def delete(self, key: str) -> bool: ...
    def exists(self, key: str) -> bool: ...
    def clear(self) -> int: ...
    def clear_by_tag(self, tag: str) -> int: ...
    def get_or_set(self, key: str, factory, *, ttl: Optional[int] = None) -> Any: ...
    def get_usage(self) -> dict[str, Any]: ...
    def get_stats(self) -> dict[str, Any]: ...
    def invalidate_pattern(self, pattern: str) -> int: ...
    def warm_up(self, entries: dict[str, Any]) -> None: ...
```

---

# 8. Eklenti API (Modul 7 Referansi)

## 8.1 Plugin SDK API

```python
class PluginManifest(BaseModel):
    """Eklenti manifest dosyasi."""
    plugin_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "MIT"
    min_platform_version: str = "1.0.0"
    max_platform_version: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)
    entry_point: str
    icon: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)

class PluginBase(ABC):
    """Plugin temel sinifi (tum eklentiler bunu miras alir)."""

    @abstractmethod
    def initialize(self, context: PluginContext) -> None: ...

    @abstractmethod
    def shutdown(self) -> None: ...

    def get_manifest(self) -> PluginManifest: ...
    def get_version(self) -> str: ...
    def on_event(self, event_type: str, data: dict) -> Optional[dict]: ...

class PluginContext(BaseModel):
    """Eklenti baglami."""
    plugin_id: str
    platform_version: str
    config: dict[str, Any] = Field(default_factory=dict)
    data_dir: str
    logger: Any = None
    event_bus: Any = None
    api_client: Any = None

class PluginManager:
    """Eklenti yonetici."""
    def __init__(self, plugins_dir: str = "./plugins"): ...
    def load_plugin(self, plugin_id: str) -> PluginBase: ...
    def unload_plugin(self, plugin_id: str) -> None: ...
    def get_plugin(self, plugin_id: str) -> Optional[PluginBase]: ...
    def list_plugins(self) -> list[PluginManifest]: ...
    def install_plugin(self, plugin_path: str) -> PluginManifest: ...
    def uninstall_plugin(self, plugin_id: str) -> None: ...
    def enable_plugin(self, plugin_id: str) -> None: ...
    def disable_plugin(self, plugin_id: str) -> None: ...
    def reload_plugin(self, plugin_id: str) -> None: ...
    def validate_plugin(self, plugin_id: str) -> list[str]: ...
    def emit_event(self, event_type: str, data: dict) -> dict: ...
```

## 8.2 Sablon SDK API

```python
class TemplateVariable(BaseModel):
    """Sablon degiskeni."""
    name: str
    var_type: Literal["string","int","float","bool","color","image","audio","video","font"]
    display_name: str
    default_value: Any = None
    required: bool = False
    description: str = ""
    options: Optional[list[Any]] = None
    min_value: Optional[Union[int, float]] = None
    max_value: Optional[Union[int, float]] = None
    placeholder: Optional[str] = None

class Template(BaseModel):
    """Video sablonu."""
    template_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    category: str = "general"
    thumbnail: Optional[str] = None
    preview_video: Optional[str] = None
    duration: Timecode
    resolution: tuple[int, int] = (1920, 1080)
    fps: float = 30.0
    variables: list[TemplateVariable] = Field(default_factory=list)
    timeline_data: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0"
    author: str = ""
    is_public: bool = False
    usage_count: int = 0
    rating: float = 0.0

class TemplateEngine:
    """Sablon motoru."""
    def __init__(self, templates_dir: str = "./templates"): ...
    def load_template(self, template_id: UUID) -> Optional[Template]: ...
    def list_templates(self, *, category: Optional[str] = None) -> list[Template]: ...
    def create_from_timeline(self, timeline: Timeline, name: str, *,
                              variables: Optional[list[TemplateVariable]] = None) -> Template: ...
    def render_template(self, template_id: UUID, variables: dict[str, Any]) -> Timeline: ...
    def preview_template(self, template_id: UUID, variables: dict[str, Any]) -> bytes: ...
    def export_template(self, template_id: UUID, output_path: str) -> str: ...
    def import_template(self, file_path: str) -> Template: ...
    def save_template(self, template: Template) -> None: ...
    def delete_template(self, template_id: UUID) -> None: ...
    def search_templates(self, query: str) -> list[Template]: ...
```

## 8.3 Tema API

```python
class ThemeElement(BaseModel):
    """Tema elemani."""
    element_type: Literal["text","logo","lower_third","intro","outro","transition","overlay"]
    name: str
    default_font: Optional[str] = None
    default_font_size: Optional[int] = None
    default_color: str = "#FFFFFF"
    default_bg_color: Optional[str] = None
    default_animation: Optional[str] = None
    position: Optional[tuple[float, float]] = None
    scale: float = 1.0
    opacity: float = 1.0

class Theme(BaseModel):
    """Gorunum temasi."""
    theme_id: UUID = Field(default_factory=uuid4)
    name: str
    description: str = ""
    primary_color: str = "#FF0000"
    secondary_color: str = "#0000FF"
    accent_color: str = "#FFFF00"
    bg_color: str = "#000000"
    text_color: str = "#FFFFFF"
    font_family: str = "Arial"
    logo_path: Optional[str] = None
    watermark_path: Optional[str] = None
    watermark_opacity: float = 0.3
    elements: list[ThemeElement] = Field(default_factory=list)
    transition_style: str = "cut"
    music_genre: Optional[str] = None
    tags: list[str] = Field(default_factory=list)

class ThemeManager:
    """Tema yonetici."""
    def __init__(self, themes_dir: str = "./themes"): ...
    def load_theme(self, theme_id: UUID) -> Optional[Theme]: ...
    def list_themes(self) -> list[Theme]: ...
    def create_theme(self, theme: Theme) -> UUID: ...
    def update_theme(self, theme: Theme) -> None: ...
    def delete_theme(self, theme_id: UUID) -> None: ...
    def apply_theme(self, timeline: Timeline, theme_id: UUID) -> Timeline: ...
    def generate_brand_kit(self, theme_id: UUID, output_dir: str) -> dict[str, str]: ...
```

## 8.4 On Ayar API

```python
class PresetCategory(str, Enum):
    COLOR = "color"
    EFFECT = "effect"
    TRANSITION = "transition"
    TEXT = "text"
    AUDIO = "audio"
    RENDER = "render"
    EXPORT = "export"
    COMPLETE = "complete"

class Preset(BaseModel):
    """On ayar nesnesi."""
    preset_id: UUID = Field(default_factory=uuid4)
    name: str
    category: PresetCategory
    description: str = ""
    settings: dict[str, Any]
    thumbnail: Optional[str] = None
    is_builtin: bool = False
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0"
    author: str = ""
    rating: float = 0.0
    usage_count: int = 0

class PresetManager:
    """On ayar yonetici."""
    def __init__(self, presets_dir: str = "./presets"): ...
    def get_preset(self, preset_id: UUID) -> Optional[Preset]: ...
    def list_presets(self, *, category: Optional[PresetCategory] = None) -> list[Preset]: ...
    def save_preset(self, preset: Preset) -> None: ...
    def delete_preset(self, preset_id: UUID) -> None: ...
    def apply_preset(self, preset_id: UUID, target: Any) -> Any: ...
    def import_preset(self, file_path: str) -> Preset: ...
    def export_preset(self, preset_id: UUID, output_path: str) -> str: ...
    def search_presets(self, query: str) -> list[Preset]: ...
    def get_recommended(self, context: str) -> list[Preset]: ...
```

---

# 9. Teslimat API (Modul 8 Referansi)

## 9.1 Disa Aktarma API

```python
class ExportFormat(str, Enum):
    MP4_H264 = "mp4_h264"
    MP4_H265 = "mp4_h265"
    MOV_PRORES = "mov_prores"
    MOV_H264 = "mov_h264"
    WEBM_VP9 = "webm_vp9"
    WEBM_AV1 = "webm_av1"
    MKV_H264 = "mkv_h264"
    AVI = "avi"
    GIF = "gif"
    APNG = "apng"
    IMAGE_SEQUENCE = "image_sequence"
    AUDIO_ONLY = "audio_only"
    CUSTOM = "custom"

class ExportPreset(BaseModel):
    """Disa aktarma on ayari."""
    name: str
    format: ExportFormat
    codec: str = "h264"
    container: str = "mp4"
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    bitrate_kbps: Optional[int] = None
    max_bitrate_kbps: Optional[int] = None
    crf: Optional[int] = None
    preset: str = "medium"
    pixel_format: str = "yuv420p"
    audio_codec: str = "aac"
    audio_bitrate_kbps: int = 192
    audio_sample_rate: int = 48000
    audio_channels: int = 2
    faststart: bool = True
    hw_acceleration: bool = False
    custom_ffmpeg_args: list[str] = Field(default_factory=list)

class ExportRequest(BaseModel):
    """Disa aktarma istegi."""
    request_id: UUID = Field(default_factory=uuid4)
    timeline_id: UUID
    output_path: str
    export_preset: ExportPreset
    time_range: Optional[TimeRange] = None
    include_audio: bool = True
    include_subtitles: bool = True
    subtitle_mode: Literal["none","soft","hard"] = "soft"
    watermark: Optional[str] = None
    watermark_opacity: float = 0.3
    metadata: dict[str, Any] = Field(default_factory=dict)
    callback_url: Optional[str] = None

class ExportResult(BaseModel):
    """Disa aktarma sonucu."""
    success: bool
    output_path: str
    file_size_bytes: int
    duration_seconds: float
    format_used: ExportFormat
    export_time_seconds: float
    thumbnail_path: Optional[str] = None
    error_message: Optional[str] = None

class ExportManager:
    """Disa aktarma yonetici."""
    def __init__(self, render_queue: RenderQueue,
                 asset_manager: Optional[AssetManager] = None): ...
    def export(self, request: ExportRequest) -> UUID: ...
    def export_direct(self, timeline: Timeline, output_path: str,
                       preset: ExportPreset) -> ExportResult: ...
    def get_export_status(self, request_id: UUID) -> Optional[dict]: ...
    def cancel_export(self, request_id: UUID) -> bool: ...
    def get_export_presets(self) -> list[ExportPreset]: ...
    def create_preset(self, preset: ExportPreset) -> None: ...
    def get_social_media_presets(self) -> dict[str, ExportPreset]: ...
    def estimate_file_size(self, timeline: Timeline, preset: ExportPreset) -> int: ...
    def generate_thumbnail(self, timeline: Timeline, time: Timecode) -> Optional[str]: ...
    def generate_preview(self, timeline: Timeline, *, duration_seconds: int = 15) -> Optional[str]: ...
```

## 9.2 Depolama API

```python
class StorageBackend(str, Enum):
    LOCAL = "local"
    S3 = "s3"
    GCS = "gcs"
    AZURE = "azure"
    MINIO = "minio"

class StorageConfig(BaseModel):
    """Depolama yapilandirmasi."""
    backend: StorageBackend = StorageBackend.LOCAL
    bucket_name: Optional[str] = None
    region: Optional[str] = None
    endpoint_url: Optional[str] = None
    access_key: Optional[str] = None
    secret_key: Optional[str] = None
    local_path: str = "./storage"
    max_file_size_mb: int = 5120
    allowed_extensions: list[str] = Field(default_factory=list)
    cdn_url: Optional[str] = None

class StorageManager:
    """Depolama yonetici."""
    def __init__(self, config: StorageConfig): ...
    def store(self, file_path: str, *, key: Optional[str] = None,
              content_type: Optional[str] = None) -> str: ...
    def retrieve(self, key: str, output_path: str) -> str: ...
    def delete(self, key: str) -> bool: ...
    def exists(self, key: str) -> bool: ...
    def get_url(self, key: str, *, expiry: int = 3600) -> str: ...
    def list_files(self, prefix: str = "", *, limit: int = 100) -> list[str]: ...
    def get_file_info(self, key: str) -> Optional[dict[str, Any]]: ...
    def get_total_usage(self) -> dict[str, Any]: ...
    def cleanup_expired(self) -> int: ...
```

## 9.3 CDN API

```python
class CDNDistribution(BaseModel):
    """CDN dagitim konfigurasyonu."""
    distribution_id: str
    domain: str
    origin_bucket: str
    paths: list[str] = Field(default_factory=list)
    cache_ttl: int = 86400
    ssl_enabled: bool = True
    compression_enabled: bool = True
    geo_restriction: Optional[list[str]] = None
    price_class: str = "PriceClass_All"

class CDNManager:
    """CDN yonetici."""
    def __init__(self, storage_manager: StorageManager): ...
    def create_distribution(self, config: CDNDistribution) -> CDNDistribution: ...
    def invalidate(self, paths: list[str]) -> str: ...
    def get_distribution(self, distribution_id: str) -> Optional[CDNDistribution]: ...
    def list_distributions(self) -> list[CDNDistribution]: ...
    def delete_distribution(self, distribution_id: str) -> bool: ...
    def get_analytics(self, distribution_id: str, *,
                       start_date: str, end_date: str) -> dict[str, Any]: ...
    def purge_cache(self, distribution_id: str, paths: list[str]) -> bool: ...
```

---
# 10. REST API Uclari (FastAPI)

## 10.1 Kimlik Dogrulama ve Yetkilendirme

```python
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600
    refresh_token: Optional[str] = None

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: str
    password: str = Field(min_length=8)
    full_name: Optional[str] = None

class UserResponse(BaseModel):
    id: UUID
    username: str
    email: str
    full_name: Optional[str] = None
    is_active: bool = True
    created_at: str
    role: str = "user"
    api_key: Optional[str] = None

class ErrorResponse(BaseModel):
    detail: str
    error_code: str
    request_id: Optional[str] = None
    timestamp: str
```

## 10.2 Uclere Goreli Endpointler

### 10.2.1 Zaman Cizelgesi Ucleri (`/api/v1/timelines`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/timelines` | Yeni zaman cizelgesi olustur | `TimelineCreate` | `Timeline` |
| GET | `/timelines` | Zaman cizelgelerini listele | query: page,limit,search | `list[Timeline]` |
| GET | `/timelines/{id}` | Zaman cizelgesini getir | - | `Timeline` |
| PUT | `/timelines/{id}` | Zaman cizelgesini guncelle | `TimelineUpdate` | `Timeline` |
| DELETE | `/timelines/{id}` | Zaman cizelgesini sil | - | `204` |
| POST | `/timelines/{id}/copy` | Zaman cizelgesini kopyala | `TimelineCopy` | `Timeline` |
| GET | `/timelines/{id}/snapshot` | Anlik goruntu al | - | `TimelineSnapshot` |
| POST | `/timelines/{id}/restore` | Anlik goruntuyu geri yukle | `TimelineSnapshot` | `Timeline` |
| GET | `/timelines/{id}/validate` | Zaman cizelgesini dogrula | - | `ValidationResult` |

### 10.2.2 Katman Ucleri (`/api/v1/timelines/{timeline_id}/layers`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/layers` | Yeni katman ekle | `LayerCreate` | `Layer` |
| GET | `/layers` | Katmanlari listele | - | `list[Layer]` |
| GET | `/layers/{id}` | Katmani getir | - | `Layer` |
| PUT | `/layers/{id}` | Katmani guncelle | `LayerUpdate` | `Layer` |
| DELETE | `/layers/{id}` | Katmani sil | - | `204` |
| POST | `/layers/{id}/duplicate` | Katmani kopyala | - | `Layer` |
| PUT | `/layers/reorder` | Katmanlari yeniden sirala | `LayerReorder` | `200` |

### 10.2.3 Clip Ucleri (`/api/v1/timelines/{timeline_id}/clips`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/clips` | Yeni clip ekle | `ClipCreate` | `Clip` |
| GET | `/clips/{id}` | Clipi getir | - | `Clip` |
| PUT | `/clips/{id}` | Clipi guncelle | `ClipUpdate` | `Clip` |
| DELETE | `/clips/{id}` | Clipi sil | - | `204` |
| POST | `/clips/{id}/split` | Clipi bol | `SplitRequest` | `tuple[Clip, Clip]` |
| POST | `/clips/{id}/trim` | Clipi kirp | `TrimRequest` | `Clip` |
| POST | `/clips/{id}/move` | Clipi tasi | `MoveRequest` | `Clip` |

### 10.2.4 Efekt Ucleri (`/api/v1/timelines/{timeline_id}/effects`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/effects` | Efekt ekle | `EffectInstanceCreate` | `EffectInstance` |
| GET | `/effects/{id}` | Efekti getir | - | `EffectInstance` |
| PUT | `/effects/{id}` | Efekti guncelle | `EffectInstanceUpdate` | `EffectInstance` |
| DELETE | `/effects/{id}` | Efekti sil | - | `204` |
| POST | `/effects/{id}/toggle` | Efekti ac/kapa | `ToggleRequest` | `EffectInstance` |
| GET | `/effects/types` | Mevcut efekt turleri | - | `list[EffectType]` |
| GET | `/effects/presets` | Efekt on ayarlari | query: type | `list[EffectPreset]` |

### 10.2.5 Render Ucleri (`/api/v1/render`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/render/preview` | Onizleme render et | `PreviewRequest` | `PreviewResult` |
| POST | `/render/frame` | Tek kare render et | `FrameRequest` | `FrameResult` |
| GET | `/render/stats` | Render istatistikleri | - | `RenderStats` |

### 10.2.6 Disa Aktarma Ucleri (`/api/v1/export`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/export` | Videoyu disa aktar | `ExportRequest` | `ExportJobResponse` |
| GET | `/export/{job_id}` | Disa aktarma durumu | - | `ExportStatus` |
| DELETE | `/export/{job_id}` | Disa aktarmayi iptal | - | `204` |
| GET | `/export/presets` | Mevcut on ayarlar | - | `list[ExportPreset]` |
| POST | `/export/presets` | On ayar olustur | `ExportPreset` | `ExportPreset` |
| GET | `/export/{job_id}/download` | Indir | - | `FileResponse` |

### 10.2.7 Zeka Ucleri (`/api/v1/intelligence`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/intelligence/analyze` | Tam analiz | `AnalysisRequest` | `ContentAnalysis` |
| POST | `/intelligence/quick-analyze` | Hizli analiz | `QuickAnalysisRequest` | `dict` |
| POST | `/intelligence/detect-faces` | Yuz tespiti | `FaceDetectionRequest` | `list[FaceDetection]` |
| POST | `/intelligence/detect-scenes` | Sahne tespiti | `SceneDetectionRequest` | `list[SceneBoundary]` |
| POST | `/intelligence/generate-edit` | Duzenleme karari | `EditDecisionRequest` | `EditDecision` |
| POST | `/intelligence/auto-crop` | Otomatik kirpma | `AutoCropRequest` | `list[CropKeyframe]` |

### 10.2.8 Subtitle Ucleri (`/api/v1/subtitles`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/subtitles/parse` | Alt yazi parse et | `SubtitleParseRequest` | `SubtitleTrack` |
| POST | `/subtitles/auto-time` | Otomatik zamanlama | `AutoTimeRequest` | `SubtitleTrack` |
| POST | `/subtitles/burn-in` | Alt yazi yazdir | `BurnInRequest` | `JobResponse` |
| POST | `/subtitles/validate` | Alt yazi dogrula | `SubtitleTrack` | `ValidationResult` |

### 10.2.9 Ses Ucleri (`/api/v1/audio`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/audio/analyze` | Ses analizi | `AudioAnalysisRequest` | `AudioAnalysis` |
| POST | `/audio/normalize` | Loudness normalizasyonu | `NormalizeRequest` | `JobResponse` |
| POST | `/audio/mix` | Ses karistirma | `MixRequest` | `JobResponse` |
| POST | `/audio/ducking` | Ducking uygula | `DuckingRequest` | `list[DuckingEvent]` |

### 10.2.10 Varlik Ucleri (`/api/v1/assets`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| POST | `/assets/upload` | Varlik yukle | `multipart/form-data` | `Asset` |
| GET | `/assets` | Varliklari listele | query: type,tags,page | `list[Asset]` |
| GET | `/assets/{id}` | Varligi getir | - | `Asset` |
| PUT | `/assets/{id}` | Varligi guncelle | `AssetUpdate` | `Asset` |
| DELETE | `/assets/{id}` | Varligi sil | - | `204` |
| GET | `/assets/{id}/download` | Varligi indir | - | `FileResponse` |
| GET | `/assets/usage` | Depolama kullanimi | - | `StorageUsage` |

### 10.2.11 Is Ucleri (`/api/v1/jobs`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| GET | `/jobs` | Isleri listele | query: status,page | `list[RenderJob]` |
| GET | `/jobs/{id}` | Isle getir | - | `RenderJob` |
| DELETE | `/jobs/{id}` | Isle iptal et | - | `204` |
| POST | `/jobs/{id}/retry` | Isle yeniden dene | - | `RenderJob` |
| PUT | `/jobs/{id}/priority` | Oncelik degistir | `PriorityUpdate` | `RenderJob` |
| GET | `/jobs/stats` | Is istatistikleri | - | `JobStats` |

### 10.2.12 Sistem Ucleri (`/api/v1/system`)

| Method | Endpoint | Aciklama | Request Body | Response |
|--------|----------|----------|-------------|----------|
| GET | `/system/health` | Sistem sagligi | - | `HealthStatus` |
| GET | `/system/metrics` | Sistem metrikleri | - | `SystemMetrics` |
| GET | `/system/gpu` | GPU durumu | - | `list[GPUDevice]` |
| GET | `/system/workers` | Worker durumu | - | `list[WorkerInfo]` |
| GET | `/system/cache` | Onbellek durumu | - | `CacheStats` |
| GET | `/system/config` | Yapilandirma | - | `SystemConfig` |
| POST | `/system/validate` | Sistem dogrulama | - | `ValidationResult` |

## 10.3 WebSocket Ucleri

```python
# WebSocket: ws://host/ws/render/{job_id}
# render durumu gercek zamanli guncelleme
# Messages: {"type": "progress", "data": {"job_id": "...", "progress": 45.2}}
#           {"type": "completed", "data": {"job_id": "...", "result": {...}}}
#           {"type": "error", "data": {"job_id": "...", "error": "..."}}

# WebSocket: ws://host/ws/timeline/{timeline_id}
# Zaman cizelgesi gercek zamanli guncelleme
# Messages: {"type": "layer_changed", "data": {...}}
#           {"type": "clip_added", "data": {...}}
#           {"type": "effect_toggled", "data": {...}}

# WebSocket: ws://host/ws/export/{job_id}
# Disa aktarma gercek zamanli guncelleme
# Messages: {"type": "encoding_progress", "data": {"progress": 67.8}}
#           {"type": "encoding_complete", "data": {"output_path": "..."}}

# WebSocket: ws://host/ws/intelligence/{analysis_id}
# Analiz gercek zamanli guncelleme
# Messages: {"type": "face_detected", "data": {...}}
#           {"type": "scene_boundary", "data": {...}}
```

## 10.4 Hiz Sinirlama

```python
# Varsayilan hiz sinirlari (istemci basina)
RATE_LIMITS = {
    "default": "60/minute",
    "read": "120/minute",
    "write": "30/minute",
    "upload": "10/minute",
    "render": "5/minute",
    "export": "3/minute",
    "intelligence": "10/minute",
    "websocket": "5 concurrent",
}
```

---

# 11. Veri Akis Diyagramlari

## 11.1 Stream-to-Clip Pipeline

```
  +-----------+    +----------+    +----------+    +----------+    +---------+
  | Kaynak    |--->| Decode   |--->| Analiz   |--->| Duzenle  |--->| Kodla   |
  | (dosya/  |    | (FFmpeg/ |    | (Yuz/    |    | (Klip/  |    | (GPU/   |
  |  akis)   |    |  GPU)    |    |  Sahne/  |    |  Katman/ |    |  FFmpeg)|
  +-----------+    +----------+    |  Icerik) |    |  Efekt)  |    +----+----+
                                  +----------+    +----------+         |
                                                                      v
                                                                 +---------+
                                                                 | Cikis   |
                                                                 | (dosya/ |
                                                                 |  CDN)   |
                                                                 +---------+
```

## 11.2 Render Pipeline

```
  +-------------+    +-----------+    +----------+    +-----------+    +--------+
  | Timeline    |--->| Compositor|--->| Effect   |--->| GPU       |--->| Encoder|
  | (katmanlar, |    | (katman   |    | Graf     |    | Pipeline  |    | (H264/ |
  |  klipler)   |    |  agaci)   |    | isleme)  |    | (islem)   |    |  H265) |
  +-------------+    +-----------+    +----------+    +-----------+    +----+---+
                                                                            |
                                                                            v
                                                                        +--------+
                                                                        | Cikis  |
                                                                        | Dosya  |
                                                                        +--------+
```

## 11.3 Is Zamanlama Akisi

```
  +----------+    +----------+    +----------+    +----------+    +----------+
  | Istemci  |--->| API      |--->| Job      |--->| Worker   |--->| Render   |
  | (REST/  |    | Gateway  |    | Scheduler|    | Pool     |    | Queue    |
  |  WS)    |    |          |    |          |    |          |    |          |
  +----------+    +----------+    +----+-----+    +----+-----+    +----+-----+
                                     |               |               |
                                     |    +----------+               |
                                     |    |                          |
                                     v    v                          v
                                  +----------+                  +----------+
                                  | Zamanlanmis|               | Worker   |
                                  | Isler      |               | Calistir |
                                  +------------+               +----+-----+
                                                                  |
                                                                  v
                                                            +----------+
                                                            | Sonuc    |
                                                            | (dosya)  |
                                                            +----------+
```

## 11.4 Varlik Yasam Dongusu

```
  +----------+    +----------+    +----------+    +----------+    +----------+
  | Yukleme  |--->| Islem    |--->| Depolama |--->| Kullanim |--->| Temizleme|
  | (upload) |    | (proxy,  |    | (S3/FS)  |    | (render/ |    | (cache   |
  |          |    |  thumb)  |    |          |    |  export) |    |  expire) |
  +----------+    +----------+    +----+-----+    +----+-----+    +----+-----+
                                      |               |               |
                                      |    +----------+               |
                                      |    |                          |
                                      v    v                          v
                                  +----------+                  +----------+
                                  | Metadata |                  | Geri     |
                                  | (DB)     |                  | Donusum  |
                                  +----------+                  | (reuse)  |
                                                               +----------+
```

## 11.5 Tam Sistem Entegrasyon Akisi

```
  +========================================================================+
  |                     TAM SISTEM INTEGRASYON AKISI                        |
  +========================================================================+
  |                                                                        |
  |  1. GIRIS KATMANI                                                     |
  |     +-----------+  +-----------+  +-----------+  +-----------+        |
  |     | Web UI    |  | Mobile    |  | CLI       |  | API       |        |
  |     +-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+        |
  |           |              |              |              |              |
  +-----------+--------------+--------------+--------------+--------------+
                              |
  +---------------------------v------------------------------------------+
  |  2. API GATEWAY (FastAPI)                                            |
  |     Auth -> Rate Limit -> Validation -> Route -> Error Handler        |
  +---------------------------+------------------------------------------+
                              |
  +---------------------------v------------------------------------------+
  |  3. IS YONETIMI (Modul 6)                                            |
  |     RenderQueue -> JobScheduler -> WorkerPool -> CacheManager         |
  +---------------------------+------------------------------------------+
                              |
  +---------------------------v------------------------------------------+
  |  4. MOTOR katmanlari (Moduller 1-5)                                  |
  |     Timeline -> Compositor -> Effects -> GPU Pipeline -> Encoder      |
  |     FaceTracker -> SceneDetector -> ContentAnalyzer -> EditDecision   |
  |     SubtitleEngine -> KaraokeSystem -> AnimationEngine -> Sticker     |
  |     AudioMixer -> LoudnessManager -> AudioDucker                     |
  +---------------------------+------------------------------------------+
                              |
  +---------------------------v------------------------------------------+
  |  5. TESLIMAT (Modul 8)                                               |
  |     ExportManager -> StorageManager -> CDNManager                     |
  +---------------------------+------------------------------------------+
                              |
  +---------------------------v------------------------------------------+
  |  6. DEPOLAMA KATMANI                                                 |
  |     PostgreSQL | Redis | MinIO/S3 | Local FS                         |
  +========================================================================+
```

---

## Son Notlar

- **Surum:** Bu API sozlesmesi 3.0.0 surumu icin gecerlidir.
- **Uyumluluk:** Geriye donuk uyumluluk 2.x surumleri icin garanti edilmez.
- **Destek:** Teknik destek icin repository issues veya Slack kanali kullanilabilir.
- **Lisans:** MIT Lisansi altinda yayinlanmaktadir.

---
*Belge Sonu - Master API Referans v3.0.0*
