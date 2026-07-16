# 07 - Eklenti Sistemi (Extension System)

> **Plugin SDK · Template SDK · Theme Engine · Preset System**
> 
> Kullanici tarafindan gelistirilebilir, guvenli ve modular eklenti mimarisi.

## Icerik

| Bölüm | Konu |
|-------|------|
| **1** | **Plugin SDK** |
| 1.1 | Mimari Uzgunluk |
| 1.2 | Plugin Turleri |
| 1.3 | Plugin Hayat Donusu |
| 1.4 | Guvenli Sandbox Ortami |
| 1.5 | Plugin API Sozlesmesi |
| 1.6 | Plugin Veri Yapisi ve Kayit Defteri |
| 1.7 | Plugin Yukleyici (Loader) |
| 1.8 | Hot-Plug Destege |
| 1.9 | Plugin Guvenlik Modeli |
| 1.10 | Plugin Depo Yapisi |
| 1.11 | Plugin Test Cercevesi |
| 1.12 | Plugin Performans Izleme |
| 1.13 | Plugin Ornekleri |
| **2** | **Template SDK** |
| 2.1 | Sablon Mimarisi |
| 2.2 | Yer Tutucu (Placeholder) Turleri |
| 2.3 | Sablon Kalitim Modeli |
| 2.4 | Sablon Derleme ve Optimize |
| 2.5 | Sablon Render Hattı |
| 2.6 | Sablon Dogrulama |
| 2.7 | Sablon Versiyonlama |
| 2.8 | Sablon Kullanim Ornegi |
| **3** | **Theme Engine** |
| 3.1 | Tema Mimarisi |
| 3.2 | Renk Paletleri |
| 3.3 | Tipografi |
| 3.4 | Animasyonlar |
| 3.5 | Platforma Ozgu Temalar |
| 3.6 | Tema Degiskenleri |
| 3.7 | Tema Derleme |
| 3.8 | Varsayilan Temalar |
| **4** | **Preset System** |
| 4.1 | Preset Mimarisi |
| 4.2 | Efekt Presetleri |
| 4.3 | Render Presetleri |
| 4.4 | Preset Yonetim Motoru |
| 4.5 | Preset Paylasimi |
| 4.6 | Preset Bundle'lari |
| **5** | **Butunesme ve Etkilesim** |
| 5.1 | Sistemler Arasi Etkilesim |
| 5.2 | Entegrasyon Akis Diyagrami |

---

## 1. Plugin SDK

### 1.1 Mimari Uzgunluk

Plugin SDK, Tuncay-klip'in dis eklentilerle guvenli sekilde genisletilmesini saglayan
ana platformdur. Tum pluginler sandbox ortaminda calisir, merkezi bir yonetim
araciligiyla yuklenir/boşaltılır ve yasam dongusu boyunca denetlenir.

```
┌─────────────────────────────────────────────────────────┐
│                     PLUGIN MIMARISI                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Plugin 1 │    │   Plugin 2   │    │   Plugin N   │  │
│  │ (Effect) │    │ (Transition) │    │ (Generator)  │  │
│  └────┬─────┘    └──────┬───────┘    └──────┬───────┘  │
│       │                 │                   │           │
│  ┌────▼─────────────────▼───────────────────▼───────┐  │
│  │              PLUGIN LOADER / REGISTRY             │  │
│  │   - Keşif (Discovery)  ·  Doğrulama (Validation) │  │
│  │   - Yaşam Döngüsü      ·  Hot-Plug               │  │
│  └────────────────────────┬─────────────────────────┘  │
│                           │                            │
│  ┌────────────────────────▼─────────────────────────┐  │
│  │              GÜVENLİ SANDBOX ORTAMI               │  │
│  │  - Bellek izolasyonu  ·  API erişim kontrolü     │  │
│  │  - Kaynak kotası     ·  Zaman aşılaması         │  │
│  └────────────────────────┬─────────────────────────┘  │
│                           │                            │
│  ┌────────────────────────▼─────────────────────────┐  │
│  │              ANA UYGULAMA ÇEKIRDEĞİ               │  │
│  │  - Timeline  ·  Renderer  ·  Exporter            │  │
│  └─────────────────────────────────────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Plugin Turleri

Plugin SDK bes temel plugin turunu destekler:

| Plugin Turu | Aciklama | Ornek Kullanim |
|-------------|----------|----------------|
| **Effect** | Kare uzerinde gorsel efekt uygular | Blur, renk duzeltme, grain |
| **Transition** | Iki kara arasinda gecis olusturur | Crossfade, wipe, morph |
| **Generator** | Yeni kare uretir | Titreşim, particle, metin animasyonu |
| **Analyser** | Kare analiz eder (veri uretir) | Sahne algilama, renk histogrami |
| **Exporter** | Export isini genisletir | Ozel codec, streaming protokolu |

### 1.3 Plugin Hayat Donusu

Her plugin asagidaki yasam dongusunden gecer:

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│  KEŞİF   │───▶│  YÜKLEME │───▶│  AKTİF   │───▶│ KALDIRMA│
│(Discover)│    │  (Load)  │    │  (Active)│    │(Unload) │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
     │               │               │               │
     ▼               ▼               ▼               ▼
  manifest        on_load()     process_frame()   on_unload()
  okuma           context       set_parameter()   kaynak
  dogrulama       alir          get_parameters()  temizligi
```

**Yasam Donusu Adimlari:**

1. **Kesif (Discovery):** Plugin dizini taranir, manifest dosyasi okunur
2. **Dogrulama (Validation):** Manifest ve bağımlılıklar kontrol edilir
3. **Yukleme (Load):** Plugin sinifi instantiate edilir, `on_load()` cagrilir
4. **Aktif (Active):** Plugin isteklere yanit verir, parametreleri yonetilir
5. **Kaldirma (Unload):** `on_unload()` cagrilir, kaynaklar serbest birakilir

### 1.4 Guvenli Sandbox Ortami

Pluginler sandbox ortaminda calisir. Bu ortam sunlari saglar:

| Ozellik | Aciklama | Sinir |
|---------|----------|-------|
| Bellek Kotası | Plugin'in kullanabilecegi azami bellek | 256 MB |
| Zaman Asimi | Tek bir islem icin azami sure | 5000 ms |
| API Erisim | İzin verilen moduller | Sadece PluginAPI |
| Dosya Erisim | Plugin'in okuyacagi/yazacagi dizinler | Sadece kendi dizini |
| Ag Erisim | Network erisimi | Varsayilan kapali |
| Thread Sayisi | Eşzamanlı iş parçacığı | max 4 |

```python
class SandboxConfig:
    """Sandbox konfigurasyonu."""
    max_memory_mb: int = 256
    max_execution_ms: int = 5000
    allowed_modules: List[str] = field(default_factory=lambda: [
        'math', 'json', 'copy', 'functools', 'itertools',
        'dataclasses', 'typing', 'enum', 'datetime', 'uuid'
    ])
    filesystem_access: FilesystemAccess = FilesystemAccess.RESTRICTED
    network_access: bool = False
    max_threads: int = 4

class SandboxViolation(Exception):
    """Sandbox ihlali tespit edildiginde firlatilir."""
    pass
```

### 1.5 Plugin API Sozlesmesi

Tum pluginler asagidaki temel API'yi uymalidir:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class PluginAPI(Protocol):
    """Plugin'lerin erisebildigi genel API sozlesmesi."""

    def get_version(self) -> str: ...
    def get_platform_info(self) -> PlatformInfo: ...
    def log(self, level: LogLevel, message: str) -> None: ...
    def register_event(self, event_type: str, handler: Callable) -> None: ...
    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None: ...
    def get_config(self, key: str, default: Any = None) -> Any: ...
    def set_config(self, key: str, value: Any) -> None: ...
```

**Kullanilabilir Event Turleri:**

| Event Turu | Aciklama | Veri |
|------------|----------|------|
| `timeline.changed` | Timeline degistirildi | {action, clip_id} |
| `render.started` | Render baslatildi | {job_id, preset} |
| `render.progress` | Render ilerlemesi | {job_id, percent} |
| `render.completed` | Render tamamlandi | {job_id, output_path} |
| `export.started` | Export baslatildi | {job_id, format} |
| `export.completed` | Export tamamlandi | {job_id, output_path} |
| `plugin.loaded` | Plugin yuklendi | {plugin_id} |
| `plugin.unloaded` | Plugin kaldirildi | {plugin_id} |


### 1.6 Plugin Veri Yapisi ve Kayit Defteri

```python
import importlib.util
import os, sys, json, hashlib, threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol


class PluginInterface(Protocol):
    """Tum pluginlerin uymasi gereken arayuz."""
    manifest: PluginManifest
    def on_load(self, context: 'PluginContext') -> None: ...
    def on_unload(self) -> None: ...
    def get_parameters(self) -> List[PluginParameter]: ...
    def set_parameter(self, name: str, value: Any) -> None: ...


class EffectPluginInterface(PluginInterface, Protocol):
    def process_frame(self, frame, params: Dict[str, Any]): ...

class TransitionPluginInterface(PluginInterface, Protocol):
    def process_transition(self, frame_a, frame_b, progress: float, params: Dict[str, Any]): ...

class GeneratorPluginInterface(PluginInterface, Protocol):
    def generate_frame(self, timestamp: float, params: Dict[str, Any]): ...

class AnalyserPluginInterface(PluginInterface, Protocol):
    def analyse(self, frame) -> Dict[str, Any]: ...

class ExporterPluginInterface(PluginInterface, Protocol):
    def export(self, timeline, output_path: str, params: Dict[str, Any]) -> str: ...


@dataclass
class PluginContext:
    """Plugin'e sunulan baglam nesnesi. Sadece guvenli alt kume."""
    logger: logging.Logger
    config: Dict[str, Any]
    temp_dir: str
    cache_dir: str
    platform_version: str


@dataclass
class Plugin:
    """Yuklenmis ve calistirmaya hazir plugin instance'i."""
    manifest: PluginManifest
    instance: PluginInterface
    state: PluginState
    module: Any
    directory: str
    checksum: str
    load_time: float = 0.0
    last_exec_time: float = 0.0
    total_exec_count: int = 0
    error_count: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def is_available(self) -> bool:
        return self.state in (PluginState.INITIALIZED, PluginState.EXECUTING)

    def get_average_exec_time(self) -> float:
        if self.total_exec_count == 0: return 0.0
        return self.last_exec_time / self.total_exec_count


@dataclass
class PluginRegistry:
    """Tum kesfedilmis ve yuklenmis pluginlerin merkezi kaydi."""
    plugins: Dict[str, Plugin] = field(default_factory=dict)
    _discovery_paths: List[str] = field(default_factory=list)

    def register_path(self, path: str) -> None:
        if path not in self._discovery_paths:
            self._discovery_paths.append(path)

    def discover_all(self) -> List[PluginManifest]:
        manifests = []
        for base_path in self._discovery_paths:
            base = Path(base_path)
            if not base.exists(): continue
            for child in base.iterdir():
                if not child.is_dir(): continue
                for name in ('plugin.json', 'plugin.yaml', 'plugin.yml'):
                    candidate = child / name
                    if candidate.exists():
                        raw = candidate.read_text(encoding='utf-8')
                        data = json.loads(raw) if candidate.suffix == '.json' else yaml.safe_load(raw)
                        m = PluginManifest.from_dict(data)
                        m._source_dir = str(child)
                        manifests.append(m)
                        break
        return manifests

    def load_plugin(self, manifest: PluginManifest) -> Plugin:
        source_dir = getattr(manifest, '_source_dir', '')
        entry = os.path.join(source_dir, manifest.entry_point)
        with open(entry, 'rb') as f:
            checksum = hashlib.sha256(f.read()).hexdigest()
        module_name = f'tuncay_plugin_{manifest.id.replace(chr(46), chr(95))}'
        spec = importlib.util.spec_from_file_location(module_name, entry)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, 'process_frame'):
                instance = attr()
                plugin = Plugin(manifest=manifest, instance=instance,
                    state=PluginState.LOADED, module=module,
                    directory=source_dir, checksum=checksum)
                self.plugins[manifest.id] = plugin
                return plugin
        raise TypeError(f'Plugin sinifi bulunamadi: {entry}')

    def init_plugin(self, plugin_id: str, context: PluginContext) -> None:
        plugin = self.plugins[plugin_id]
        plugin.instance.on_load(context)
        plugin.state = PluginState.INITIALIZED

    def unload_plugin(self, plugin_id: str) -> None:
        plugin = self.plugins.get(plugin_id)
        if plugin is None: return
        plugin.state = PluginState.UNLOADING
        try: plugin.instance.on_unload()
        finally:
            plugin.state = PluginState.UNLOADED
            sys.modules.pop(plugin.module.__name__, None)
            del self.plugins[plugin_id]

    def reload_plugin(self, plugin_id: str, context: PluginContext) -> Plugin:
        manifest = self.plugins[plugin_id].manifest
        self.unload_plugin(plugin_id)
        plugin = self.load_plugin(manifest)
        self.init_plugin(plugin_id, context)
        return plugin

    def get_by_type(self, plugin_type: PluginType) -> List[Plugin]:
        return [p for p in self.plugins.values()
                if p.manifest.plugin_type == plugin_type and p.is_available]
```

### 1.7 Plugin Manifest Formati (JSON)

```json
{
  "id": "com.tuncay.chromatic-aberration",
  "name": "Chromatic Aberration",
  "version": "2.1.0",
  "type": "effect",
  "author": "Tuncay Studio",
  "description": "RGB kanallarini ayristirarak kromatik sapma efekti uygular.",
  "min_platform_version": "1.0.0",
  "max_platform_version": null,
  "entry_point": "plugin.py",
  "parameters": [
    {
      "name": "intensity", "display_name": "Yogunluk",
      "type": "float", "default": 0.5, "min": 0.0, "max": 5.0, "step": 0.1,
      "description": "Efekt yogunlugu", "group": "core", "ui_hint": "slider"
    },
    {
      "name": "center_x", "display_name": "Merkez X",
      "type": "float", "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01,
      "description": "Sapmanin odak noktasi yatay", "group": "position"
    },
    {
      "name": "blend_mode", "display_name": "Karistirma Modu",
      "type": "enum", "default": "screen",
      "enum_values": ["screen", "add", "overlay", "normal"],
      "description": "Kanallarin karistirilma yontemi"
    },
    {
      "name": "enable_anamorphic", "display_name": "Anamorfik Mod",
      "type": "bool", "default": false,
      "description": "Sadece yatay eksende sapma uygula"
    }
  ],
  "tags": ["cinematic", "lens", "glitch", "color"],
  "dependencies": [],
  "license": "MIT",
  "icon": "icon.png",
  "platform": "all",
  "gpu_required": false,
  "max_instances": 4
}
```

### 1.8 Plugin Kod Ornegi - Chromatic Aberration (Effect)

```python
from plugin_api import PluginParameter, PluginContext
from typing import Any, Dict, List


class ChromaticAberrationPlugin:
    """RGB kanallarini merkezden disari kaydirarak kromatik sapma efekti."""

    def __init__(self):
        self._context = None
        self._params = {"intensity": 0.5, "center_x": 0.5, "center_y": 0.5,
                        "blend_mode": "screen", "enable_anamorphic": False}

    def on_load(self, context: PluginContext) -> None:
        self._context = context
        context.logger.info("Chromatic Aberration plugin yuklendi")

    def on_unload(self) -> None:
        self._context.logger.info("Chromatic Aberration plugin kaldirildi")
        self._context = None

    def get_parameters(self) -> List[PluginParameter]:
        return [
            PluginParameter(name="intensity", display_name="Yogunluk",
                param_type="float", default=0.5, min_value=0.0, max_value=5.0,
                step=0.1, description="Efekt yogunlugu", group="core"),
            PluginParameter(name="center_x", display_name="Merkez X",
                param_type="float", default=0.5, min_value=0.0, max_value=1.0,
                step=0.01, description="Odak noktasi yatay", group="position"),
            PluginParameter(name="blend_mode", display_name="Karistirma",
                param_type="enum", default="screen",
                enum_values=["screen", "add", "overlay", "normal"]),
            PluginParameter(name="enable_anamorphic", display_name="Anamorfik",
                param_type="bool", default=False, group="advanced"),
        ]

    def set_parameter(self, name: str, value: Any) -> None:
        for param in self.get_parameters():
            if param.name == name and param.validate(value):
                self._params[name] = value
                return
        raise KeyError(f'Bilinmeyen parametre: {name}')

    def process_frame(self, frame, params: Dict[str, Any]):
        intensity = params.get("intensity", self._params["intensity"])
        cx = params.get("center_x", self._params["center_x"])
        blend = params.get("blend_mode", self._params["blend_mode"])
        if intensity == 0.0: return frame
        # Gercek uygulamada NumPy/OpenCV ile RGB ayristirma yapilir:
        # r, g, b = frame.split_channels()
        # r = shift_channel(r, offset_x=+intensity)
        # b = shift_channel(b, offset_x=-intensity)
        # result = merge_channels(r, g, b, blend_mode=blend)
        return frame
```

### 1.9 Plugin Kod Ornegi - Sahne Degisim Analizi (Analyser)

```python
from plugin_api import PluginParameter, PluginContext
from typing import Any, Dict, List
import numpy as np


class SceneDetectorPlugin:
    """Kareler arasindaki histogram farkini analiz ederek sahne degisimleri algilar."""

    def __init__(self):
        self._context = None
        self._params = {"threshold": 30.0, "method": "histogram", "block_size": 16}
        self._prev_histogram = None

    def on_load(self, context: PluginContext) -> None:
        self._context = context

    def on_unload(self) -> None:
        self._prev_histogram = None
        self._context = None

    def get_parameters(self) -> List[PluginParameter]:
        return [
            PluginParameter(name="threshold", display_name="Esik Degeri",
                param_type="float", default=30.0, min_value=1.0, max_value=255.0),
            PluginParameter(name="method", display_name="Yontem",
                param_type="enum", default="histogram",
                enum_values=["histogram", "edge", "pixel_diff"]),
            PluginParameter(name="block_size", display_name="Blok Boyutu",
                param_type="int", default=16, min_value=4, max_value=128),
        ]

    def analyse(self, frame) -> Dict[str, Any]:
        threshold = self._params["threshold"]
        current_hist = np.random.rand(8, 8, 8)  # Placeholder
        result = {"scene_change_detected": False, "difference_score": 0.0}
        if self._prev_histogram is not None:
            diff = float(np.sum(np.abs(current_hist - self._prev_histogram)))
            result["difference_score"] = diff
            result["scene_change_detected"] = diff > threshold
        self._prev_histogram = current_hist
        return result
```

### 1.10 Plugin Kod Ornegi - Test Deseni Uretici (Generator)

```python
from plugin_api import PluginParameter, PluginContext
from typing import Any, Dict, List


class TestPatternGenerator:
    """Video test deseni uretir (renk cubuklari, grid, sinus dalgasi)."""

    def __init__(self):
        self._context = None
        self._params = {"pattern": "color_bars", "width": 1920, "height": 1080}

    def on_load(self, context): self._context = context
    def on_unload(self): self._context = None

    def get_parameters(self) -> List[PluginParameter]:
        return [
            PluginParameter(name="pattern", display_name="Desen",
                param_type="enum", default="color_bars",
                enum_values=["color_bars", "grid", "sinewave", "gradient", "noise"]),
            PluginParameter(name="width", display_name="Genislik",
                param_type="int", default=1920, min_value=64, max_value=7680),
            PluginParameter(name="height", display_name="Yukseklik",
                param_type="int", default=1080, min_value=64, max_value=4320),
        ]

    def generate_frame(self, timestamp: float, params: Dict[str, Any]):
        pattern = params.get("pattern", self._params["pattern"])
        w = params.get('width', self._params['width'])
        h = params.get('height', self._params['height'])
        # Gercek uygulamada NumPy ile piksel uretimi yapilir
        return None  # VideoFrame doner
```

### 1.11 Hot-Plug Destegi

Hot-plug, uygulama calisirken plugin eklenip kaldirilmasini ifade eder:

```python
class HotPlugManager:
    """Calisma zamaninda plugin ekleme/kaldirma yoneticisi."""

    def __init__(self, registry: PluginRegistry, context: PluginContext):
        self._registry = registry
        self._context = context
        self._callbacks = {'on_plugin_added': [], 'on_plugin_removed': [],
                           'on_plugin_updated': [], 'on_plugin_error': []}

    def add_plugin_from_directory(self, directory: str) -> Plugin:
        """Dizinden yeni plugin yukler."""
        for name in ('plugin.json', 'plugin.yaml'):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                with open(candidate) as f: data = json.load(f)
                manifest = PluginManifest.from_dict(data)
                manifest._source_dir = directory
                for dep_id in manifest.dependencies:
                    if dep_id not in self._registry.plugins:
                        raise DependencyError(f'Eksik bagimlilik: {dep_id}')
                plugin = self._registry.load_plugin(manifest)
                self._registry.init_plugin(manifest.id, self._context)
                return plugin
        raise FileNotFoundError(f'Manifest bulunamadi: {directory}')

    def remove_plugin(self, plugin_id: str) -> None:
        for other in self._registry.plugins.values():
            if plugin_id in other.manifest.dependencies:
                raise DependencyError(f'{other.manifest.id} bu plugin e bagimli')
        self._registry.unload_plugin(plugin_id)

    def check_for_updates(self) -> List[str]:
        """Dizinlerdeki degisiklikleri tarar."""
        updated = []
        for manifest in self._registry.discover_all():
            sd = getattr(manifest, '_source_dir', '')
            entry = os.path.join(sd, manifest.entry_point)
            if not os.path.isfile(entry): continue
            with open(entry, 'rb') as f:
                cs = hashlib.sha256(f.read()).hexdigest()
            existing = self._registry.plugins.get(manifest.id)
            if existing and existing.checksum != cs:
                updated.append(manifest.id)
        return updated
```

### 1.12 Plugin Surlumleme ve Uyumluluk

Surum numaralari **Semantic Versioning** (semver) izler: `MAJOR.MINOR.PATCH`

| Surum Degisimi | Anlami | Uyumluluk |
|----------------|--------|-----------|
| `1.0.0` -> `1.0.1` | Hata duzeltmesi | Geriye uyumlu |
| `1.0.0` -> `1.1.0` | Yenizellik | Geriye uyumlu |
| `1.0.0` -> `2.0.0` | Kirici degisiklik | Kirima - API degisimi |

```python
def check_compatibility(manifest, platform_version, loaded_plugins):
    """Plugin uyumlulugunu kontrol eder."""
    errors = []
    if not manifest.is_compatible(platform_version):
        errors.append(f'Platform uyumsuz: {manifest.id}')
    for dep_id in manifest.dependencies:
        if dep_id not in loaded_plugins:
            errors.append(f'Eksik bagimlilik: {dep_id}')
    return len(errors) == 0, errors
```

---

## 2. Template SDK

### 2.1 Amaç

Template SDK, video projelerinin **yeniden kullanilabilir sablonlar** araciligiyla hizlica olusturulmasini saglar. Yer tutucu (placeholder) sistemi ile veri girilir, sablon motoru bu verileri kare, ses ve metin katmanlarina donusturur.

### 2.2 Mimari Genel Bakis

```
+--------------------------------------------------------------+
|                   Template Engine                             |
|  +------------+    +----------------+    +--------------+     |
|  |  Template   |-->|  Placeholder   |-->|  Renderer    |     |
|  |  Registry   |    |  Resolver      |    |  Pipeline    |     |
|  +------------+    +----------------+    +--------------+     |
|        v                  v                     v              |
|  +------------+    +----------------+    +--------------+     |
|  |  Param      |    |  Validation    |    |  Timeline    |     |
|  |  Schema     |    |  Engine        |    |  Generator   |     |
|  +------------+    +----------------+    +--------------+     |
+--------------------------------------------------------------+
```

### 2.3 Sablon Turleri

| Tur | Tanim | Kullanim Alani |
|-----|-------|----------------|
| **Single Clip** | Tek bir klibin uzerinde islem | Hizli duzenleme, filtre |
| **Montage** | Coklu klibi sirali/senalizli birlestirme | Muzik klibi, etkinlik ozeti |
| **Highlight Reel** | Otomatik en iyi anlari secen derleme | Spor, konser, dugun |
| **Podcast** | Ses odakli, konusma baloncuklari ile | Podcast parcasi |
| **Interview** | Iki kisilik konusma duzeni | Rorontaj, panel |

### 2.4 Yer Tutucu Sistemi

```json
{
  "name": "Instagram Reels - Muzik Klibi",
  "type": "montage",
  "placeholders": {
    "{{video_clips}}": {"type": "video[]", "min_count": 3, "max_count": 10},
    "{{title}}": {"type": "text", "max_length": 80},
    "{{subtitle}}": {"type": "text", "max_length": 120, "optional": true},
    "{{music}}": {"type": "audio"},
    "{{brand_color}}": {"type": "color", "default": "#FF0050"},
    "{{logo}}": {"type": "image", "optional": true},
    "{{duration}}": {"type": "duration", "min": "5s", "max": "60s"}
  }
}
```

**Yer Tutucu Turleri:**

| Tip | Zorunlu | Dogrulama | Aciklama |
|-----|---------|-----------|----------|
| `text` | Evet | `max_length`, `pattern` (regex) | Metin girisi |
| `video` / `video[]` | Evet | `min_duration`, `max_count` | Video dosyasi |
| `audio` | Evet | `min_duration`, `format` | Ses dosyasi |
| `image` | Hayir | `min_width`, `min_height` | Goruntu dosyasi |
| `color` | Hayir | Hex formati, `default` | Renk |
| `duration` | Evet | `min`, `max` (sn) | Sure |
| `number` | Hayir | `min`, `max`, `step` | Sayisal deger |
| `enum` | Evet | `allowed_values` | Secenek |
| `boolean` | Hayir | `default` | Evet/Hayir |

### 2.5 Veri Modelleri

```python
import re, copy, json
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Tuple


class PlaceholderType(Enum):
    TEXT = auto(); VIDEO = auto(); VIDEO_ARRAY = auto()
    AUDIO = auto(); IMAGE = auto(); COLOR = auto()
    DURATION = auto(); NUMBER = auto(); ENUM = auto()
    BOOLEAN = auto(); FONT = auto(); JSON = auto()


@dataclass
class TemplatePlaceholder:
    """Tek bir yer tutucunun tanimi."""
    key: str
    placeholder_type: PlaceholderType
    display_name: str = ""
    description: str = ""
    required: bool = True
    default: Any = None
    group: str = "general"
    min_value: Optional[float] = None; max_value: Optional[float] = None
    max_length: Optional[int] = None; min_length: Optional[int] = None
    pattern: Optional[str] = None
    allowed_values: Optional[List[str]] = None
    min_duration: Optional[float] = None; max_duration: Optional[float] = None
    min_width: Optional[int] = None; min_height: Optional[int] = None
    ui_component: str = "auto"

    def validate(self, value: Any) -> Tuple[bool, str]:
        if value is None:
            if self.required: return False, f"{self.key} zorunludur"
            return True, ''
        type_checks = {PlaceholderType.TEXT: str, PlaceholderType.VIDEO: str,
            PlaceholderType.NUMBER: (int, float), PlaceholderType.BOOLEAN: bool,
            PlaceholderType.ENUM: str, PlaceholderType.COLOR: str}
        expected = type_checks.get(self.placeholder_type)
        if expected and not isinstance(value, expected):
            return False, f"{self.key}: {expected} bekleniyor"
        if self.placeholder_type == PlaceholderType.TEXT and self.max_length:
            if len(value) > self.max_length:
                return False, f"{self.key}: max {self.max_length} karakter"
        if self.placeholder_type == PlaceholderType.COLOR:
            if not re.match(r"^#[0-9A-Fa-f]{3,6}$", value):
                return False, f"{self.key}: gecerli hex renk bekleniyor"
        return True, ''


class TemplateType(Enum):
    SINGLE_CLIP = auto(); MONTAGE = auto()
    HIGHLIGHT_REEL = auto(); PODCAST = auto(); INTERVIEW = auto()


@dataclass
class TimelineTrackTemplate:
    """Zaman cizelgesi sablonu icindeki bir iz tanimi."""
    name: str; track_type: str
    source_placeholder: Optional[str] = None
    start: str = "0s"; end: Optional[str] = None
    effects: List[str] = field(default_factory=list)
    transition_in: Optional[str] = None; transition_out: Optional[str] = None
    opacity: float = 1.0; volume: float = 1.0


@dataclass
class Template:
    """Bir video sablonunun tam tanimi."""
    id: str; name: str; template_type: TemplateType
    version: str = "1.0.0"; author: str = ""; description: str = ""
    category: str = ""; tags: List[str] = field(default_factory=list)
    aspect_ratio: str = '9:16'; resolution: Tuple[int, int] = (1080, 1920)
    placeholders: List[TemplatePlaceholder] = field(default_factory=list)
    timeline_tracks: List[TimelineTrackTemplate] = field(default_factory=list)
    parent_template_id: Optional[str] = None
    overrides: Dict[str, Any] = field(default_factory=dict)

    def validate_params(self, params: Dict[str, Any]) -> List[str]:
        errors = []
        for p in self.placeholders:
            valid, msg = p.validate(params.get(p.key))
            if not valid: errors.append(msg)
        return errors

    def fill_placeholders(self, params: Dict[str, Any]) -> Dict[str, Any]:
        filled = {}
        for p in self.placeholders:
            value = params.get(p.key, p.default)
            if value is None and p.required:
                raise ValueError(f'Zorunlu eksik: {p.key}')
            filled[p.key] = value
        return filled

    def resolve_timeline(self, filled_params: Dict[str, Any]):
        tracks = []
        for tt in self.timeline_tracks:
            track = {'name': tt.name, 'type': tt.track_type,
                     'start': tt.start, 'end': tt.end,
                     'opacity': tt.opacity, 'volume': tt.volume}
            if tt.source_placeholder:
                track['source'] = filled_params.get(tt.source_placeholder)
            tracks.append(track)
        return tracks
```

### 2.6 Sablon Mirasi ve Bilesimi

```python
class TemplateInheritanceResolver:
    """Sablon miras zincirini cozer."""

    def __init__(self, registry: Dict[str, Template]):
        self._registry = registry
        self._cache: Dict[str, Template] = {}

    def resolve(self, template_id: str) -> Template:
        if template_id in self._cache: return self._cache[template_id]
        template = self._registry.get(template_id)
        if template is None: raise KeyError(f'Sablon bulunamadi: {template_id}')
        if template.parent_template_id is None:
            self._cache[template_id] = copy.deepcopy(template)
            return self._cache[template_id]
        parent = self.resolve(template.parent_template_id)
        resolved = copy.deepcopy(parent)
        resolved.id = template.id; resolved.name = template.name
        if template.overrides:
            for key, value in template.overrides.items():
                if key == 'placeholders':
                    for pk, pv in value.items():
                        existing = resolved.get_placeholder(pk)
                        if existing:
                            for attr, val in pv.items():
                                setattr(existing, attr, val)
                        else:
                            resolved.placeholders.append(
                                TemplatePlaceholder.from_dict(pk, pv))
                elif key == 'timeline_tracks':
                    resolved.timeline_tracks = [
                        TimelineTrackTemplate(**t) for t in value]
        self._cache[template_id] = resolved
        return resolved
```

### 2.7 Sablon Islem Hatti (Rendering Pipeline)

```python
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class RenderStage:
    name: str; process: Callable; order: int; enabled: bool = True


@dataclass
class TemplateRenderResult:
    success: bool
    timeline: Optional[List[Dict[str, Any]]] = None
    filled_params: Optional[Dict[str, Any]] = None
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    render_time_ms: float = 0.0


class TemplateRenderer:
    """Sablon islem hatti: dogrulama -> doldurma -> zaman cizelgesi."""

    def __init__(self, resolver):
        self._resolver = resolver
        self._stages = []
        self._hooks = {'pre_render': [], 'post_render': [], 'on_error': []}
        self.register_stage('validate', self._validate, 10)
        self.register_stage('fill', self._fill, 20)
        self.register_stage('timeline', self._timeline, 30)
        self.register_stage('optimize', self._optimize, 50)

    def register_stage(self, name, process, order=100):
        self._stages.append(RenderStage(name, process, order))
        self._stages.sort(key=lambda s: s.order)

    def render(self, template_id, params) -> TemplateRenderResult:
        start = time.monotonic()
        result = TemplateRenderResult(success=False)
        ctx = {'template_id': template_id, 'params': params.copy(),
               'resolved_template': None, 'filled_params': {},
               'timeline': [], 'warnings': [], 'errors': []}
        try:
            ctx['resolved_template'] = self._resolver.resolve(template_id)
            for stage in self._stages:
                if not stage.enabled: continue
                ctx = stage.process(ctx)
                if ctx.get('abort'): return result
            result.success = True
            result.timeline = ctx['timeline']
            result.filled_params = ctx['filled_params']
            result.warnings = ctx['warnings']
        except Exception as e:
            result.errors.append(str(e))
        finally:
            result.render_time_ms = (time.monotonic() - start) * 1000
        return result

    def _validate(self, ctx):
        errors = ctx['resolved_template'].validate_params(ctx['params'])
        if errors: ctx['errors'] = errors; ctx['abort'] = True
        return ctx

    def _fill(self, ctx):
        ctx['filled_params'] = ctx['resolved_template'].fill_placeholders(ctx['params'])
        return ctx

    def _timeline(self, ctx):
        ctx['timeline'] = ctx['resolved_template'].resolve_timeline(ctx['filled_params'])
        return ctx

    def _optimize(self, ctx):
        ctx['timeline'] = [t for t in ctx['timeline'] if t.get('source')]
        return ctx
```

### 2.8 Sablon Kullanim Ornegi

```python
registry = {}
reels = Template(id='ig-reels', name='Instagram Reels',
    template_type=TemplateType.MONTAGE, aspect_ratio='9:16',
    resolution=(1080, 1920),
    placeholders=[
        TemplatePlaceholder(key='{{video_clips}}',
            placeholder_type=PlaceholderType.VIDEO_ARRAY, required=True),
        TemplatePlaceholder(key='{{title}}',
            placeholder_type=PlaceholderType.TEXT, required=True, max_length=80),
        TemplatePlaceholder(key='{{music}}',
            placeholder_type=PlaceholderType.AUDIO, required=True),
        TemplatePlaceholder(key='{{brand_color}}',
            placeholder_type=PlaceholderType.COLOR, default='#FF0050'),
    ],
    timeline_tracks=[
        TimelineTrackTemplate(name='video', track_type='video',
                              source_placeholder='{{video_clips}}'),
        TimelineTrackTemplate(name='audio', track_type='audio',
                              source_placeholder='{{music}}'),
        TimelineTrackTemplate(name='title', track_type='text',
                              source_placeholder='{{title}}', start='0s', end='3s'),
    ])
registry['ig-reels'] = reels

resolver = TemplateInheritanceResolver(registry)
renderer = TemplateRenderer(resolver)

params = {
    '{{video_clips}}': ['/v/c1.mp4', '/v/c2.mp4', '/v/c3.mp4'],
    '{{title}}': 'Tuncay Klip Yeni Sezon',
    '{{music}}': '/a/track.mp3',
    '{{brand_color}}': '#00AAFF',
}
result = renderer.render('ig-reels', params)
print(f'Render basarili: {result.success}, sure: {result.render_time_ms:.1f}ms')
```

---

## 3. Theme Engine

### 3.1 Amaç

Theme Engine, video projelerinin **gorsel kimligini** tutarli bir sekilde yonetir: renk paletleri, tipografi, animasyon stilleri ve platform ozellestirmeleri.

### 3.2 Mimari Genel Bakis

```
+--------------------------------------------------------------+
|                      Theme Engine                             |
|  +------------------+  +----------------+  +--------------+  |
|  |  Theme Registry   |  |  Color Engine   |  |  Typography  |  |
|  +------------------+  +----------------+  +--------------+  |
|         v                    v                    v            |
|  +------------------+  +----------------+  +--------------+  |
|  |  Animation Style  |  |  Platform      |  |  Theme       |  |
|  |  Manager          |  |  Resolver      |  |  Serializer  |  |
|  +------------------+  +----------------+  +--------------+  |
+--------------------------------------------------------------+
```

### 3.3 Renk Paleti Yonetimi

```python
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class ColorPalette:
    """Bir tema icin renk paleti tanimi."""
    name: str; primary: str; secondary: str; accent: str
    background: str; surface: str
    on_primary: str; on_secondary: str; on_accent: str
    on_background: str; on_surface: str
    success: str = "#4CAF50"; warning: str = "#FFC107"
    error: str = "#F44336"; info: str = "#2196F3"
    gradients: Dict[str, List[str]] = field(default_factory=dict)

    @staticmethod
    def hex_to_rgb(h: str) -> Tuple[int, int, int]:
        h = h.lstrip("#")
        if len(h) == 3: h = h[0]*2+h[1]*2+h[2]*2
        return (int(h[0:2],16), int(h[1:3],16), int(h[2:4],16))

    @staticmethod
    def relative_luminance(hex_color: str) -> float:
        """WCAG 2.1 gorece parlaklik."""
        r, g, b = ColorPalette.hex_to_rgb(hex_color)
        vals = []
        for c in (r, g, b):
            s = c / 255.0
            vals.append(s/12.92 if s <= 0.03928 else ((s+0.055)/1.055)**2.4)
        return 0.2126*vals[0] + 0.7152*vals[1] + 0.0722*vals[2]

    def contrast_ratio(self, c1: str, c2: str) -> float:
        l1, l2 = self.relative_luminance(c1), self.relative_luminance(c2)
        return (max(l1,l2)+0.05) / (min(l1,l2)+0.05)

    def wcag_compliance(self, fg: str, bg: str) -> Dict[str, bool]:
        r = self.contrast_ratio(fg, bg)
        return {'aa_normal': r>=4.5, 'aa_large': r>=3.0,
                'aaa_normal': r>=7.0, 'aaa_large': r>=4.5, 'ratio': r}

    def generate_shades(self, base: str, steps=9) -> List[str]:
        r, g, b = self.hex_to_rgb(base)
        shades = []
        for i in range(steps):
            f = 1.0 - (i/(steps-1))*0.85
            shades.append(self.rgb_to_hex(
                max(0,min(255,int(r*f+(1-f)*255))),
                max(0,min(255,int(g*f+(1-f)*255))),
                max(0,min(255,int(b*f+(1-f)*255)))))
        return shades

    @staticmethod
    def rgb_to_hex(r, g, b) -> str:
        return f'#{r:02x}{g:02x}{b:02x}'
```

### 3.4 Tipografi Temasi

```python
@dataclass
class TextStyle:
    """Tek bir metin stili tanimi."""
    name: str; font_family: str; font_weight: int; font_size: float
    line_height: float; letter_spacing: float
    text_transform: str = "none"; text_decoration: str = "none"
    color_ref: str = "on_background"; max_width: Optional[float] = None
    text_align: str = "left"


@dataclass
class TypographyTheme:
    """Bir tema icin tum tipografi stilleri."""
    name: str; base_font_family: str
    styles: Dict[str, TextStyle] = field(default_factory=dict)
    scale_factor: float = 1.0

    def get_style(self, style_name: str) -> TextStyle:
        s = self.styles[style_name]
        return TextStyle(name=s.name, font_family=s.font_family,
            font_weight=s.font_weight, font_size=s.font_size*self.scale_factor,
            line_height=s.line_height,
            letter_spacing=s.letter_spacing*self.scale_factor,
            text_transform=s.text_transform, color_ref=s.color_ref,
            text_align=s.text_align)

    def register_default_styles(self):
        sf = self.base_font_family
        self.styles = {
            'heading_1': TextStyle('h1', sf, 700, 48, 1.2, -0.5),
            'heading_2': TextStyle('h2', sf, 600, 36, 1.25, -0.25),
            'heading_3': TextStyle('h3', sf, 600, 28, 1.3, 0),
            'subtitle': TextStyle('sub', sf, 500, 20, 1.4, 0.15),
            'body': TextStyle('body', sf, 400, 16, 1.5, 0.5),
            'body_small': TextStyle('sm', sf, 400, 14, 1.4, 0.25),
            'caption': TextStyle('cap', sf, 400, 12, 1.33, 0.4),
            'overline': TextStyle('ovl', sf, 500, 10, 1.6, 1.5),
        }
```

### 3.5 Animasyon Stil Presetleri

```python
@dataclass
class AnimationPreset:
    """Tek bir animasyonun parametreleri."""
    name: str; duration_ms: float; delay_ms: float = 0.0
    easing_in: str = "ease_out_cubic"; easing_out: str = "ease_in_cubic"
    translate_x: Optional[float] = None; translate_y: Optional[float] = None
    scale_x: Optional[float] = None; scale_y: Optional[float] = None
    rotation: Optional[float] = None
    opacity_start: float = 0.0; opacity_end: float = 1.0
    blur_start: Optional[float] = None; blur_end: Optional[float] = None
    repeat: int = 1; yoyo: bool = False; stagger_ms: float = 0.0


@dataclass
class AnimationStylePreset:
    """Bir tema icin animasyon stilleri koleksiyonu."""
    name: str
    presets: Dict[str, AnimationPreset] = field(default_factory=dict)
    easings: Dict[str, Tuple] = field(default_factory=dict)

    def register_defaults(self):
        self.easings = {
            'linear': (0,0,1,1),
            'ease_in_cubic': (0.55,0.055,0.675,0.19),
            'ease_out_cubic': (0.215,0.61,0.355,1),
            'ease_in_out_cubic': (0.645,0.045,0.355,1),
            'ease_out_back': (0.175,0.885,0.32,1.275),
            'ease_out_elastic': (0.25,1.0,0.25,1.25),
            'ease_out_bounce': (0.34,1.56,0.64,1),
        }
        self.presets = {
            'fade_in': AnimationPreset('fade_in', 300, opacity_end=1.0),
            'fade_out': AnimationPreset('fade_out', 300, opacity_start=1.0, opacity_end=0.0),
            'slide_in_left': AnimationPreset('slide_in_left', 400, translate_x=-100.0),
            'slide_in_right': AnimationPreset('slide_in_right', 400, translate_x=100.0),
            'slide_in_up': AnimationPreset('slide_in_up', 400, translate_y=50.0),
            'scale_in': AnimationPreset('scale_in', 350, scale_x=0.5, scale_y=0.5),
            'pop_in': AnimationPreset('pop_in', 500, easing_in='ease_out_elastic',
                                      scale_x=0.0, scale_y=0.0),
            'blur_in': AnimationPreset('blur_in', 400, blur_start=20.0, blur_end=0.0),
            'typewriter': AnimationPreset('typewriter', 1000, easing_in='linear', stagger_ms=50),
        }
```

### 3.6 Platform Temalari ve Tema Motoru

```python
@dataclass
class PlatformTheme:
    """Belirli bir platform icin tema ozellestirmeleri."""
    platform: str; aspect_ratio: str; resolution: Tuple[int, int]
    max_duration_seconds: float; max_file_size_mb: float
    supported_codecs: List[str]; safe_zone: Dict[str, float]
    typography_scale: float
    color_adjustments: Dict[str, str] = field(default_factory=dict)
    recommended_fps: List[int] = field(default_factory=lambda: [30, 60])


@dataclass
class Theme:
    """Tum tema bilesenlerini birlestiren ust duzey tema nesnesi."""
    id: str; name: str; version: str = '1.0.0'
    author: str = ''; description: str = ''; is_dark: bool = False
    colors: Optional[ColorPalette] = None
    typography: Optional[TypographyTheme] = None
    animations: Optional[AnimationStylePreset] = None
    platform_overrides: Dict[str, PlatformTheme] = field(default_factory=dict)
    parent_theme_id: Optional[str] = None

    def resolve_for_platform(self, platform: str) -> 'Theme':
        resolved = copy.deepcopy(self)
        pt = self.platform_overrides.get(platform)
        if pt and resolved.typography:
            resolved.typography.scale_factor *= pt.typography_scale
            for attr, val in pt.color_adjustments.items():
                if resolved.colors and hasattr(resolved.colors, attr):
                    setattr(resolved.colors, attr, val)
        return resolved


class ThemeEngine:
    """Tema motoru: kaydetme, yukleme, cozme."""

    def __init__(self):
        self._themes: Dict[str, Theme] = {}
        self._active_id: Optional[str] = None

    def register_theme(self, theme: Theme): self._themes[theme.id] = theme
    def set_active(self, theme_id: str): self._active_id = theme_id

    def get_active(self) -> Optional[Theme]:
        if not self._active_id: return None
        return self._resolve(self._active_id)

    def _resolve(self, theme_id: str) -> Theme:
        theme = self._themes[theme_id]
        if not theme.parent_theme_id: return copy.deepcopy(theme)
        parent = self._resolve(theme.parent_theme_id)
        resolved = copy.deepcopy(parent)
        resolved.id, resolved.name = theme.id, theme.name
        if theme.colors and resolved.colors:
            for attr in ('primary','secondary','accent','background','surface'):
                v = getattr(theme.colors, attr, None)
                if v: setattr(resolved.colors, attr, v)
        if theme.typography and theme.typography.styles:
            resolved.typography.styles.update(theme.typography.styles)
        resolved.platform_overrides.update(theme.platform_overrides)
        return resolved

    def resolve_for_platform(self, platform: str) -> Theme:
        return self.get_active().resolve_for_platform(platform)
```

### 3.7 Varsayilan Platform Temalari

```python
def create_default_platform_themes() -> Dict[str, PlatformTheme]:
    return {
        'instagram_reels': PlatformTheme('instagram_reels', '9:16', (1080,1920),
            90, 250, ['h264','h265'], {'top':0.12,'bottom':0.18,'left':0.05,'right':0.05}, 1.1),
        'tiktok': PlatformTheme('tiktok', '9:16', (1080,1920),
            180, 287, ['h264','h265'], {'top':0.15,'bottom':0.20,'left':0.05,'right':0.05}, 1.15),
        'youtube_shorts': PlatformTheme('youtube_shorts', '9:16', (1080,1920),
            60, 500, ['h264','h265','vp9','av1'], {'top':0.10,'bottom':0.15,'left':0.04,'right':0.04}, 1.0),
        'instagram_feed': PlatformTheme('instagram_feed', '1:1', (1080,1080),
            60, 250, ['h264'], {'top':0.08,'bottom':0.08,'left':0.05,'right':0.05}, 1.0),
        'youtube_landscape': PlatformTheme('youtube_landscape', '16:9', (1920,1080),
            43200, 12288, ['h264','h265','vp9','av1'], {'top':0.08,'bottom':0.08}, 1.0),
    }
```

### 3.8 Tema Kullanim Ornegi

```python
engine = ThemeEngine()
dark = Theme(id='dark-cinema', name='Karanlik Sinema', is_dark=True,
    colors=ColorPalette('dark', '#E8A838', '#8B6914', '#FF6B35',
        '#0D0D0D', '#1A1A1A', '#000', '#FFF', '#FFF', '#F0F0F0', '#D0D0D0'),
    typography=TypographyTheme('typo', 'Inter'),
    animations=AnimationStylePreset('anim'),
    platform_overrides=create_default_platform_themes())
dark.typography.register_default_styles()
dark.animations.register_defaults()
engine.register_theme(dark)
engine.set_active('dark-cinema')

reels_theme = engine.resolve_for_platform('instagram_reels')
print(f'Baslik boyutu: {reels_theme.typography.get_style("heading_1").font_size}px')
c = reels_theme.colors.wcag_compliance(reels_theme.colors.on_background,
                                        reels_theme.colors.background)
print(f'Kontrast: {c["ratio"]:.1f}:1, AA: {c["aa_normal"]}')
```

---

## 4. Preset System

### 4.1 Amaç

Preset System, sik kullanilan parametre setlerinin **kaydedilmesi, yuklenmesi ve paylasilmasini** saglar.

### 4.2 Mimari Genel Bakis

```
+--------------------------------------------------------------+
|                      Preset System                            |
|  +------------------+  +------------------+  +------------+  |
|  |  Preset Registry   |  |  Preset Engine    |  |  Import/   |  |
|  |  (merkezi kayit    |  |  (olustur, uygula |  |  Export    |  |
|  |   defteri)        |  |   dogrula, birles) |  |  Manager  |  |
|  +------------------+  +------------------+  +------------+  |
|         v                    v                    v            |
|  +------------------+  +------------------+  +------------+  |
|  |  Effect Presets   |  |  Render Presets   |  |  Export    |  |
|  |  (efekt param     |  |  (kalite, hiz,   |  |  Presets   |  |
|  |   setleri)        |  |   codec ayarlari) |  |  (platform)|  |
|  +------------------+  +------------------+  +------------+  |
+--------------------------------------------------------------+
```

### 4.3 Veri Modelleri

```python
import time, uuid, json, copy, os
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional


class PresetType(Enum):
    EFFECT = auto(); RENDER = auto(); EXPORT = auto()
    THEME = auto(); CUSTOM = auto()


@dataclass
class PresetParameter:
    """Preset icindeki tek bir parametre degeri."""
    key: str; value: Any; param_type: str
    display_name: str = ""; description: str = ""; locked: bool = False


@dataclass
class Preset:
    """Bir parametre setinin tam tanimi."""
    id: str; name: str; preset_type: PresetType
    version: str = "1.0.0"; author: str = ""; description: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    target_plugin_id: Optional[str] = None
    target_format: Optional[str] = None
    target_platform: Optional[str] = None
    parameters: List[PresetParameter] = field(default_factory=list)
    category: str = "default"; tags: List[str] = field(default_factory=list)
    is_builtin: bool = False; is_favorite: bool = False; use_count: int = 0

    def get_param(self, key: str) -> Optional[PresetParameter]:
        for p in self.parameters:
            if p.key == key: return p
        return None

    def set_param(self, key: str, value: Any, locked=False):
        existing = self.get_param(key)
        if existing: existing.value = value; existing.locked = locked
        else: self.parameters.append(PresetParameter(key, value, type(value).__name__, locked=locked))
        self.updated_at = time.time()

    def apply_to_dict(self, target: Dict) -> Dict:
        result = target.copy()
        for p in self.parameters:
            if not p.locked: result[p.key] = p.value
        self.use_count += 1
        return result

    def merge_with(self, other: 'Preset') -> 'Preset':
        merged = {p.key: copy.deepcopy(p) for p in other.parameters}
        for p in self.parameters: merged[p.key] = copy.deepcopy(p)
        return Preset(id=str(uuid.uuid4()),
            name=f'{other.name} + {self.name}',
            preset_type=self.preset_type, parameters=list(merged.values()),
            category=self.category, tags=list(set(self.tags+other.tags)))
```

### 4.4 Preset Yonetim Motoru

```python
class PresetEngine:
    """Preset olusturma, yukleme, kaydetme, arama, disa/ice aktarma."""

    def __init__(self, storage_path='~/.tuncay/presets'):
        self._path = os.path.expanduser(storage_path)
        self._presets: Dict[str, Preset] = {}
        self._bundles: Dict[str, PresetBundle] = {}

    def create_preset(self, name, preset_type, parameters, category='default',
                      tags=None, author='', target_platform=None) -> Preset:
        p = Preset(id=str(uuid.uuid4()), name=name, preset_type=preset_type,
            author=author, parameters=parameters, category=category,
            tags=tags or [], target_platform=target_platform)
        self._presets[p.id] = p
        return p

    def save_preset(self, preset: Preset) -> str:
        d = os.path.join(self._path, preset.preset_type.name.lower())
        os.makedirs(d, exist_ok=True)
        fp = os.path.join(d, f'{preset.id}.json')
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(preset.to_dict(), f, indent=2, ensure_ascii=False)
        return fp

    def load_preset(self, preset_id: str) -> Optional[Preset]:
        if preset_id in self._presets: return self._presets[preset_id]
        for td in ('effect','render','export','theme','custom'):
            fp = os.path.join(self._path, td, f'{preset_id}.json')
            if os.path.isfile(fp):
                with open(fp) as f: p = Preset.from_dict(json.load(f))
                self._presets[p.id] = p
                return p
        return None

    def search(self, query='', preset_type=None, category=None,
               tags=None, target_platform=None, sort_by='name') -> List[Preset]:
        results = list(self._presets.values())
        if query: q = query.lower(); results = [p for p in results if q in p.name.lower()]
        if preset_type: results = [p for p in results if p.preset_type == preset_type]
        if category: results = [p for p in results if p.category == category]
        if tags: results = [p for p in results if any(t in p.tags for t in tags)]
        if target_platform: results = [p for p in results if p.target_platform == target_platform]
        results.sort(key=lambda p: p.name.lower())
        return results

    def export_preset(self, preset_id: str) -> str:
        return json.dumps(self._presets[preset_id].to_dict(), indent=2)

    def import_preset(self, json_str: str) -> Preset:
        p = Preset.from_dict(json.loads(json_str))
        p.id = str(uuid.uuid4()); p.created_at = time.time()
        self._presets[p.id] = p; self.save_preset(p)
        return p

    def create_bundle(self, name, preset_ids, description='', tags=None) -> PresetBundle:
        b = PresetBundle(id=str(uuid.uuid4()), name=name, description=description,
            preset_ids=preset_ids, tags=tags or [])
        self._bundles[b.id] = b
        return b

    def export_bundle(self, bundle_id: str) -> str:
        b = self._bundles[bundle_id]
        presets = [self._presets[pid].to_dict() for pid in b.preset_ids if pid in self._presets]
        return json.dumps({'bundle': b.to_dict(), 'presets': presets}, indent=2)
```

### 4.5 Varsayilan Render Presetleri

```python
def create_default_render_presets() -> List[Preset]:
    return [
        Preset('render-hq', 'Yuksek Kalite', PresetType.RENDER,
            category='render', tags=['quality','cinematic'], is_builtin=True,
            parameters=[
                PresetParameter('quality','ultra','str'),
                PresetParameter('bitrate',50000000,'int','Bit Hizi'),
                PresetParameter('codec','h265','str'),
                PresetParameter('crf',15,'int','CRF'),
                PresetParameter('gpu_acceleration',True,'bool'),
                PresetParameter('two_pass',True,'bool')]),
        Preset('render-balanced', 'Dengeli', PresetType.RENDER,
            category='render', tags=['balanced','default'], is_builtin=True,
            parameters=[
                PresetParameter('quality','high','str'),
                PresetParameter('bitrate',25000000,'int'),
                PresetParameter('codec','h264','str'),
                PresetParameter('crf',20,'int'),
                PresetParameter('gpu_acceleration',True,'bool')]),
        Preset('render-fast', 'Hizli', PresetType.RENDER,
            category='render', tags=['fast','preview'], is_builtin=True,
            parameters=[
                PresetParameter('quality','medium','str'),
                PresetParameter('bitrate',10000000,'int'),
                PresetParameter('crf',28,'int'),
                PresetParameter('gpu_acceleration',True,'bool')]),
        Preset('render-mobile', 'Mobil', PresetType.RENDER,
            category='render', tags=['mobile'], is_builtin=True,
            parameters=[
                PresetParameter('quality','good','str'),
                PresetParameter('bitrate',5000000,'int'),
                PresetParameter('max_file_size_mb',50,'int')]),
    ]


def create_default_export_presets() -> List[Preset]:
    return [
        Preset('exp-ig-reels', 'Instagram Reels', PresetType.EXPORT,
            target_platform='instagram_reels', category='export',
            tags=['instagram','reels'], is_builtin=True,
            parameters=[
                PresetParameter('resolution','1080x1920','str'),
                PresetParameter('aspect_ratio','9:16','str'),
                PresetParameter('max_duration',90,'int'),
                PresetParameter('codec','h264','str'),
                PresetParameter('bitrate',15000000,'int'),
                PresetParameter('max_file_size_mb',250,'int')]),
        Preset('exp-tiktok', 'TikTok', PresetType.EXPORT,
            target_platform='tiktok', category='export',
            tags=['tiktok','social'], is_builtin=True,
            parameters=[
                PresetParameter('resolution','1080x1920','str'),
                PresetParameter('aspect_ratio','9:16','str'),
                PresetParameter('max_duration',180,'int'),
                PresetParameter('bitrate',12000000,'int'),
                PresetParameter('max_file_size_mb',287,'int')]),
        Preset('exp-yt-shorts', 'YouTube Shorts', PresetType.EXPORT,
            target_platform='youtube_shorts', category='export',
            tags=['youtube','shorts'], is_builtin=True,
            parameters=[
                PresetParameter('resolution','1080x1920','str'),
                PresetParameter('aspect_ratio','9:16','str'),
                PresetParameter('max_duration',60,'int'),
                PresetParameter('bitrate',20000000,'int'),
                PresetParameter('max_file_size_mb',500,'int')]),
    ]
```

### 4.6 Preset Kullanim Ornegi

```python
engine = PresetEngine()
for p in create_default_render_presets() + create_default_export_presets():
    engine._presets[p.id] = p

# Arama
results = engine.search(preset_type=PresetType.RENDER, tags=['default'])
print(f'{len(results)} render preseti bulundu')

# Preset uygulama
balanced = engine.load_preset('render-balanced')
params = balanced.apply_to_dict({})
print(f'Parametreler: {params}')

# Kullanici ozel preset
custom = engine.create_preset('Benim Efektim', PresetType.EFFECT,
    parameters=[PresetParameter('intensity', 0.75, 'float'),
                PresetParameter('blend_mode', 'overlay', 'str')],
    category='cinematic', tags=['custom'])
engine.save_preset(custom)

# Disa aktarma (paylasim)
export_json = engine.export_preset(custom.id)
imported = engine.import_preset(export_json)
print(f'Ice aktarilan: {imported.name} (yeni ID: {imported.id[:8]})')

# Bundle olusturma
bundle = engine.create_bundle('Tum Render Presetleri',
    [p.id for p in engine.search(preset_type=PresetType.RENDER)])
bundle_json = engine.export_bundle(bundle.id)
print(f'Bundle boyutu: {len(bundle_json)} byte')
```

---

## 5. Butunesme ve Etkilesim

### 5.1 Sistemler Arasi Etkilesim

```
+-------------------+     +-------------------+
|    Plugin SDK     |<--->|   Template SDK    |
|                   |     |                   |
| - Plugin'ler      |     | - Sablon icinde   |
|   efekt uygular   |     |   efekt isimleri  |
| - Sablon zaman    |     |   referans verir  |
|   cizelgesi       |     | - Sablon ciktisi  |
|   plugin cagrisi  |     |   plugin girdisi  |
|   icerir          |     |   olabilir        |
+---------+---------+     +---------+---------+
          |                           |
          v                           v
+-------------------+     +-------------------+
|   Theme Engine    |<--->|  Preset System    |
|                   |     |                   |
| - Tema renkleri   |     | - Efekt presetleri|
|   plugin'lerce    |     |   plugin param.   |
|   kullanilir      |     |   setlerini       |
| - Platform tema   |     |   kaydeder        |
|   ayarlari        |     | - Render preseti  |
|   export preseti  |     |   kalite/hiz      |
|   etkiler         |     |   dengesini       |
|                   |     |   belirler        |
+-------------------+     +-------------------+
```

### 5.2 Entegre Kullanim Senaryosu

```python
# Tam entegre video uretim is akisi

# 1. Tema ayarla
theme_engine = ThemeEngine()
dark = Theme(id='dark-cinema', name='Karanlik Sinema', is_dark=True,
    colors=ColorPalette('dark', '#E8A838', '#8B6914', '#FF6B35',
        '#0D0D0D', '#1A1A1A', '#000', '#FFF', '#FFF', '#F0F0F0', '#D0D0D0'),
    typography=TypographyTheme('typo', 'Inter'),
    animations=AnimationStylePreset('anim'),
    platform_overrides=create_default_platform_themes())
dark.typography.register_default_styles()
dark.animations.register_defaults()
theme_engine.register_theme(dark)
theme_engine.set_active('dark-cinema')

# 2. Platform icin coz
reels_theme = theme_engine.resolve_for_platform('instagram_reels')

# 3. Sablonu hazirla
registry = {}
tpl = Template(id='ig-reels', name='Instagram Reels',
    template_type=TemplateType.MONTAGE, aspect_ratio='9:16', resolution=(1080,1920),
    placeholders=[
        TemplatePlaceholder('{{video_clips}}', PlaceholderType.VIDEO_ARRAY, required=True),
        TemplatePlaceholder('{{title}}', PlaceholderType.TEXT, required=True, max_length=80),
        TemplatePlaceholder('{{music}}', PlaceholderType.AUDIO, required=True),
        TemplatePlaceholder('{{brand_color}}', PlaceholderType.COLOR,
            default=reels_theme.colors.primary),
    ],
    timeline_tracks=[
        TimelineTrackTemplate('video', 'video', source_placeholder='{{video_clips}}'),
        TimelineTrackTemplate('audio', 'audio', source_placeholder='{{music}}'),
        TimelineTrackTemplate('title', 'text', source_placeholder='{{title}}',
                              start='0s', end='3s'),
    ])
registry['ig-reels'] = tpl

# 4. Plugin'leri yukle
plugin_reg = PluginRegistry()
plugin_reg.register_path('~/.tuncay/plugins')
for m in plugin_reg.discover_all(): plugin_reg.load_plugin(m)

# 5. Preset sec
preset_engine = PresetEngine()
for p in create_default_render_presets() + create_default_export_presets():
    preset_engine._presets[p.id] = p
render_preset = preset_engine.load_preset('render-balanced')

# 6. Tum sistemler hazir - video uretimi baslatilabilir
print('Tum sistemler hazir')
```

---

**Belge Sonu**

| Sistem | Ana Veri Yapilari |
|--------|-------------------|
| Plugin SDK | `Plugin`, `PluginManifest`, `PluginParameter`, `PluginContext` |
| Template SDK | `Template`, `TemplatePlaceholder`, `TemplateRender` |
| Theme Engine | `Theme`, `ColorPalette`, `TypographyTheme`, `PlatformTheme` |
| Preset System | `Preset`, `PresetCategory`, `PresetBundle` |