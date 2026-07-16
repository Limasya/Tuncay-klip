# 09 - Performans Optimizasyonu

> **Modül:** Media Infrastructure SDD  
> **Odak:** GPU Bellek Optimizasyonu, Bellek Havuzu, Dosya Streaming, Render Performansı, Benchmark  
> **Dil:** Türkçe  
> **Versiyon:** 1.0.0

---

## İçindekiler

1. [GPU Bellek Optimizasyonu](#1-gpu-bellek-optimizasyonu)
2. [Bellek Havuzu Sistemi](#2-bellek-havuzu-sistemi)
3. [Dosya Streaming Motoru](#3-dosya-streaming-motoru)
4. [Performans Benchmark](#4-performans-benchmark)
5. [Render Performans Optimizasyonu](#5-render-performans-optimizasyonu)

---

## 1. GPU Bellek Optimizasyonu

### 1.1 Amaç

GPU tabanlı video işleme pipeline'larında bellek, en kritik kaynaktır. 4K/8K çözünürlüklerde tek bir kare (frame) 32-bit RGBA formatında yaklaşık 33 MB (3840x2160x4 byte) yer kaplar. Birden fazla akış (stream) aynı anda işlendiğinde, GPU belleği (VRAM) hızla tükenir. Bu modül, GPU bellek bütçesini yönetmek, bellek basıncını (pressure) algılamak ve yanıt vermek, çoklu akışlı encoding sınırlarını optimize etmek için kapsamlı bir altyapı sunar.

### 1.2 Mimari

```
+-----------------------------------------------------------+
|                  GPU Bellek Yonetim Katmani                |
|                                                           |
|  +-------------+  +--------------+  +---------------+     |
|  |  Butce       |  |  Basinç      |  |  VRAM         |     |
|  |  Yoneticisi  |  |  Algilayici  |  |  Izleyici     |     |
|  +------+------+  +------+-------+  +-------+-------+     |
|         |                |                   |             |
|  +------v----------------v-------------------v---------+  |
|  |              GPU Bellek Havuzu                       |  |
|  |  +----------+ +----------+ +------------------+     |  |
|  |  | texture  | | buffer   | | compute          |     |  |
|  |  | havuzu   | | havuzu   | | buffer havuzu    |     |  |
|  |  +----------+ +----------+ +------------------+     |  |
|  +---------------------------+-------------------------+  |
|                              |                            |
|  +----------------------------v-------------------------+  |
|  |              Spill Motoru                             |  |
|  |  GPU bellek dolu -> Sistem bellegine aktar           |  |
|  |  Gerektiginde geri yukle (reload on demand)          |  |
|  +------------------------------------------------------+  |
|                                                           |
|  +------------------------------------------------------+  |
|  |        NVENCE Session Yoneticisi                      |  |
|  |  Eszamanli encoding oturumlarini sinirla/planla     |  |
|  +------------------------------------------------------+  |
+-----------------------------------------------------------+
```

### 1.3 Veri Yapilari

#### GPUMemoryPool

GPU bellek havuzu, farkli turde GPU kaynaklarini (texture, buffer, compute buffer) tek bir koordineli havuzda yonetir. Her havuz segmenti, boyut araligina gore kategorize edilir ve serbest birakilan bloklar yeniden kullanilmak uzere serbest liste (free list) yapisinda tutulur.

```python
import time
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
from collections import defaultdict


class GPUResourceType(Enum):
    TEXTURE = auto()
    BUFFER = auto()
    COMPUTE_BUFFER = auto()
    RENDER_TARGET = auto()


class MemoryPressure(Enum):
    NONE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class GPUAllocation:
    allocation_id: int
    resource_type: GPUResourceType
    size_bytes: int
    device_offset: int = 0
    host_pointer: Optional[int] = None
    is_pinned: bool = False
    is_spilled: bool = False
    created_at: float = field(default_factory=time.monotonic)
    last_accessed_at: float = field(default_factory=time.monotonic)
    reference_count: int = 1
    stream_id: int = 0
    metadata: dict = field(default_factory=dict)

    @property
    def age_seconds(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def idle_seconds(self) -> float:
        return time.monotonic() - self.last_accessed_at

    @property
    def is_evictable(self) -> bool:
        return self.reference_count == 0 and self.idle_seconds > 5.0

    def touch(self) -> None:
        self.last_accessed_at = time.monotonic()

    def acquire(self) -> None:
        self.reference_count += 1
        self.touch()

    def release(self) -> None:
        self.reference_count = max(0, self.reference_count - 1)


@dataclass
class GPUAllocationRequest:
    resource_type: GPUResourceType
    size_bytes: int
    alignment: int = 256
    pinned: bool = False
    preferred_stream_id: int = 0
    allow_spill: bool = True
    priority: int = 5


@dataclass
class GPUMemoryStats:
    total_bytes: int = 0
    allocated_bytes: int = 0
    used_bytes: int = 0
    spilled_bytes: int = 0
    allocation_count: int = 0
    free_count: int = 0
    pressure: MemoryPressure = MemoryPressure.NONE
    fragmentation_ratio: float = 0.0

    @property
    def utilization(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return self.allocated_bytes / self.total_bytes

    @property
    def available_bytes(self) -> int:
        return max(0, self.total_bytes - self.allocated_bytes)

    @property
    def effective_available_bytes(self) -> int:
        return self.available_bytes + self.spilled_bytes
```

#### GPUMemoryPool Uygulamasi

```python
class GPUMemoryPool:
    PRESSURE_THRESHOLDS = {
        MemoryPressure.LOW: 0.70,
        MemoryPressure.MODERATE: 0.85,
        MemoryPressure.HIGH: 0.95,
        MemoryPressure.CRITICAL: 0.98,
    }

    def __init__(self, total_budget: int, device_id: int = 0):
        self._total_budget = total_budget
        self._device_id = device_id
        self._lock = threading.RLock()
        self._allocation_counter = 0
        self._active_allocations: dict[int, GPUAllocation] = {}
        self._free_lists: dict[str, list[GPUAllocation]] = defaultdict(list)
        self._size_bins = [
            (0, 64 * 1024),
            (64 * 1024, 1024 * 1024),
            (1024 * 1024, 16 * 1024 * 1024),
            (16 * 1024 * 1024, float('inf')),
        ]
        self._total_allocated_bytes = 0
        self._total_used_bytes = 0
        self._total_spilled_bytes = 0
        self._spill_store: dict[int, bytearray] = {}
        self._pressure_callbacks: list = []
        self._current_pressure = MemoryPressure.NONE

    def register_pressure_callback(self, callback) -> None:
        self._pressure_callbacks.append(callback)

    def allocate(self, request: GPUAllocationRequest) -> GPUAllocation:
        with self._lock:
            aligned_size = self._align_size(request.size_bytes, request.alignment)
            allocation = self._find_free_block(aligned_size, request.resource_type)

            if allocation is None:
                if self._total_allocated_bytes + aligned_size > self._total_budget:
                    if request.allow_spill:
                        self._perform_spill(aligned_size)
                    else:
                        raise MemoryError(
                            f"GPU bellek yetersiz: {aligned_size} byte gerekli, "
                            f"{self._total_budget - self._total_allocated_bytes} byte mevcut"
                        )

                allocation = self._create_allocation(
                    resource_type=request.resource_type,
                    size_bytes=aligned_size,
                    stream_id=request.preferred_stream_id,
                )
            else:
                allocation.acquire()

            self._active_allocations[allocation.allocation_id] = allocation
            self._total_used_bytes += aligned_size
            self._evaluate_pressure()
            return allocation

    def free(self, allocation_id: int) -> None:
        with self._lock:
            allocation = self._active_allocations.pop(allocation_id, None)
            if allocation is None:
                return
            allocation.release()
            if allocation.reference_count == 0:
                bin_key = self._get_size_bin(allocation.size_bytes)
                self._free_lists[bin_key].append(allocation)
                self._total_used_bytes -= allocation.size_bytes
            self._evaluate_pressure()

    def get_stats(self) -> GPUMemoryStats:
        with self._lock:
            pressure = self._calculate_pressure()
            active_count = len(self._active_allocations)
            free_count = sum(len(lst) for lst in self._free_lists.values())
            return GPUMemoryStats(
                total_bytes=self._total_budget,
                allocated_bytes=self._total_allocated_bytes,
                used_bytes=self._total_used_bytes,
                spilled_bytes=self._total_spilled_bytes,
                allocation_count=active_count + free_count,
                free_count=free_count,
                pressure=pressure,
                fragmentation_ratio=self._calculate_fragmentation(),
            )

    def defragment(self) -> int:
        with self._lock:
            freed_bytes = 0
            for bin_key in list(self._free_lists.keys()):
                free_list = self._free_lists[bin_key]
                if len(free_list) < 2:
                    continue
                free_list.sort(key=lambda a: a.device_offset)
                merged = []
                current = free_list[0]
                for next_alloc in free_list[1:]:
                    if (current.device_offset + current.size_bytes ==
                            next_alloc.device_offset):
                        current.size_bytes += next_alloc.size_bytes
                        freed_bytes += next_alloc.size_bytes
                    else:
                        merged.append(current)
                        current = next_alloc
                merged.append(current)
                self._free_lists[bin_key] = merged
            return freed_bytes

    def _align_size(self, size: int, alignment: int) -> int:
        return ((size + alignment - 1) // alignment) * alignment

    def _get_size_bin(self, size: int) -> str:
        for i, (low, high) in enumerate(self._size_bins):
            if low <= size < high:
                return f"bin_{i}"
        return "bin_large"

    def _find_free_block(self, size: int, resource_type: GPUResourceType) -> Optional[GPUAllocation]:
        bin_key = self._get_size_bin(size)
        free_list = self._free_lists.get(bin_key, [])
        best_match = None
        best_idx = -1
        for i, alloc in enumerate(free_list):
            if alloc.size_bytes >= size:
                if best_match is None or alloc.size_bytes < best_match.size_bytes:
                    best_match = alloc
                    best_idx = i
        if best_match is not None:
            free_list.pop(best_idx)
            remaining = best_match.size_bytes - size
            if remaining > 64 * 1024:
                split_alloc = GPUAllocation(
                    allocation_id=self._next_allocation_id(),
                    resource_type=best_match.resource_type,
                    size_bytes=remaining,
                    device_offset=best_match.device_offset + size,
                )
                split_bin = self._get_size_bin(remaining)
                self._free_lists[split_bin].append(split_alloc)
                best_match.size_bytes = size
            return best_match
        return None

    def _create_allocation(self, resource_type, size_bytes, stream_id) -> GPUAllocation:
        alloc_id = self._next_allocation_id()
        device_offset = self._total_allocated_bytes
        allocation = GPUAllocation(
            allocation_id=alloc_id,
            resource_type=resource_type,
            size_bytes=size_bytes,
            device_offset=device_offset,
            stream_id=stream_id,
        )
        self._total_allocated_bytes += size_bytes
        return allocation

    def _next_allocation_id(self) -> int:
        self._allocation_counter += 1
        return self._allocation_counter

    def _perform_spill(self, needed_bytes: int) -> None:
        candidates = [
            a for a in self._active_allocations.values()
            if a.is_evictable and not a.is_spilled
        ]
        candidates.sort(key=lambda a: (-a.size_bytes, a.idle_seconds))
        freed = 0
        for candidate in candidates:
            if freed >= needed_bytes:
                break
            self._spill_store[candidate.allocation_id] = bytearray(candidate.size_bytes)
            candidate.is_spilled = True
            candidate.host_pointer = id(self._spill_store[candidate.allocation_id])
            freed += candidate.size_bytes
            self._total_spilled_bytes += candidate.size_bytes

    def _calculate_pressure(self) -> MemoryPressure:
        utilization = self._total_allocated_bytes / self._total_budget if self._total_budget > 0 else 0
        result = MemoryPressure.NONE
        for pressure, threshold in sorted(self.PRESSURE_THRESHOLDS.items(), key=lambda x: x[1]):
            if utilization >= threshold:
                result = pressure
        return result

    def _evaluate_pressure(self) -> None:
        new_pressure = self._calculate_pressure()
        if new_pressure != self._current_pressure:
            old = self._current_pressure
            self._current_pressure = new_pressure
            for callback in self._pressure_callbacks:
                try:
                    callback(old, new_pressure)
                except Exception:
                    pass

    def _calculate_fragmentation(self) -> float:
        if self._total_allocated_bytes == 0:
            return 0.0
        total_free = 0
        largest_free = 0
        for free_list in self._free_lists.values():
            for alloc in free_list:
                total_free += alloc.size_bytes
                largest_free = max(largest_free, alloc.size_bytes)
        if total_free == 0:
            return 0.0
        return 1.0 - (largest_free / total_free)
```

### 1.4 Texture Streaming (Talep Uzerine Yukleme)

Texture streaming, GPU'ya yalnizca o an goruntulenen veya islenen texture'lari yukler. Uzak texture'lar dusuk cozunurluklu versiyonlari ile degistirilir; yakinlastikca yuksek cozunurluk versiyonlari yuklenir.

**Mimari Akis:**

```
Kamera Pozisyonu -> Mesafe Hesaplama -> LOD Seviyesi Belirleme
    |
    v
Texture Request Queue --> GPU Bellek Havuzu --> Texture Upload
    |                                                  |
    v                                                  v
Oncelikli Yukleme                             GPU Texture Cache
(Dusuk LOD -> Yuksek LOD)
```

**Algoritma:**
1. Her texture icin mesafe tabanli LOD (Level of Detail) hesapla
2. LOD 0 (tam cozunurluk) sadece ekrandaki texture'lar icin
3. LOD 1-2 arka plan texture'lari icin yeterli
4. LOD 3+ sadece bellekten sizzinti (spill) durumunda
5. FIFO oncelikli kuyruk ile GPU'ya yukle

### 1.5 Multi-Stream GPU Encoding (NVENC)

NVIDIA GPU'lar NVENC donanim encoder ile ayni anda sinirli sayida encoding oturumu calistirabilir. Bu yonetici, oturum sayisini izler ve encoding islerini planlar.

**NVENC Sinirlamalari (Ornek):**

| GPU Modeli          | Maks. Eszamanli Oturum | Maks. Cozunurluk | FPS Limiti |
|---------------------|------------------------|-------------------|------------|
| RTX 3060            | 5                      | 8K                | 60         |
| RTX 3080            | 8                      | 8K                | 120        |
| RTX 4090            | 16                     | 8K                | 240        |
| A100 (Veri Merkezi) | 32                     | 8K                | 240        |

```python
@dataclass
class NVENCSession:
    session_id: int
    stream_id: int
    width: int
    height: int
    codec: str
    fps: int
    bitrate: int
    created_at: float = field(default_factory=time.monotonic)
    is_active: bool = True


class NVENCSessionManager:
    def __init__(self, max_sessions: int = 8, gpu_name: str = "Unknown"):
        self._max_sessions = max_sessions
        self._gpu_name = gpu_name
        self._sessions: dict[int, NVENCSession] = {}
        self._lock = threading.Lock()
        self._session_counter = 0

    @property
    def active_count(self) -> int:
        return sum(1 for s in self._sessions.values() if s.is_active)

    @property
    def available_slots(self) -> int:
        return self._max_sessions - self.active_count

    def request_session(self, stream_id, width, height, codec, fps, bitrate):
        with self._lock:
            if self.available_slots <= 0:
                return None
            self._session_counter += 1
            session = NVENCSession(
                session_id=self._session_counter,
                stream_id=stream_id, width=width, height=height,
                codec=codec, fps=fps, bitrate=bitrate,
            )
            self._sessions[session.session_id] = session
            return session

    def release_session(self, session_id: int) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session:
                session.is_active = False
                del self._sessions[session_id]

    def get_session_stats(self) -> dict:
        with self._lock:
            return {
                "gpu_name": self._gpu_name,
                "max_sessions": self._max_sessions,
                "active_sessions": self.active_count,
                "available_slots": self.available_slots,
                "sessions": [
                    {
                        "id": s.session_id, "stream_id": s.stream_id,
                        "resolution": f"{s.width}x{s.height}",
                        "codec": s.codec, "fps": s.fps,
                        "bitrate_mbps": s.bitrate / 1_000_000,
                    }
                    for s in self._sessions.values()
                ],
            }
```

### 1.6 VRAM Izleme ve Profilleme

```python
class VRAMMonitor:
    def __init__(self, sample_interval: float = 1.0):
        self._sample_interval = sample_interval
        self._history: list[dict] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def _monitor_loop(self) -> None:
        while self._running:
            sample = self._take_sample()
            with self._lock:
                self._history.append(sample)
                if len(self._history) > 3600:
                    self._history = self._history[-3600:]
            time.sleep(self._sample_interval)

    def _take_sample(self) -> dict:
        return {
            "timestamp": time.time(),
            "vram_total_mb": 12288,
            "vram_used_mb": 8192,
            "vram_free_mb": 4096,
            "gpu_utilization_pct": 78.5,
            "memory_utilization_pct": 66.7,
            "temperature_c": 72,
            "power_watts": 250,
        }

    def detect_memory_leak(self, window_size: int = 300) -> Optional[dict]:
        with self._lock:
            if len(self._history) < window_size:
                return None
            recent = self._history[-window_size:]
            used_values = [s["vram_used_mb"] for s in recent]
            n = len(used_values)
            x_mean = (n - 1) / 2
            y_mean = sum(used_values) / n
            numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(used_values))
            denominator = sum((i - x_mean) ** 2 for i in range(n))
            if denominator == 0:
                return None
            slope = numerator / denominator
            samples_per_minute = 60 / self._sample_interval
            leak_rate = slope * samples_per_minute
            if leak_rate > 1.0:
                return {
                    "detected": True,
                    "leak_rate_mb_per_minute": round(leak_rate, 2),
                    "current_usage_mb": used_values[-1],
                    "confidence": min(1.0, leak_rate / 10.0),
                }
            return None

    def get_usage_summary(self) -> dict:
        with self._lock:
            if not self._history:
                return {"error": "Veri yok"}
            used = [s["vram_used_mb"] for s in self._history]
            return {
                "samples": len(self._history),
                "current_mb": used[-1],
                "peak_mb": max(used),
                "average_mb": round(sum(used) / len(used), 1),
                "min_mb": min(used),
            }
```

### 1.7 Darboğazlar ve Cozumleri

| Darboz | Belirti | Cozum |
|----------|---------|-------|
| VRAM tuknemesi | Cokme, kare kaybi | Texture streaming + spill |
| NVENC kuyruk | Encoding gecikmesi | Oturum planlama, onceliklendirme |
| Bellek parcalanmasi | Yetersiz buyuk blok | Defragmentasyon, arena allocator |
| GPU-CPU transfer darboz | CPU dusuk, GPU bos | Pinned memory, DMA transfer |
| Texture upload gecikmesi | Dusuk LOD uzun sure | Prefetch, async upload |

---

## 2. Bellek Havuzu Sistemi

### 2.1 Amaç

Video isleme pipeline'inda saniyelerce yuzlerce kare uretilir. Her kare icin yeni bellek tahsisi ve serbest birakma, hem bellek parcalanmasina hem de yuksek GC (garbage collection) yukune yol acar. Bellek havuzu sistemi, kare tamponlarini (frame buffer), pahali nesneleri ve render verilerini yeniden kullanarak bu sorunlari cozer.

### 2.2 Mimari

```
+-----------------------------------------------------------+
|               Bellek Havuzu Sistemi                        |
|                                                           |
|  +-----------------+  +------------------------------+    |
|  |  Kare Tamponu    |  |  Nesne Havuzu                 |    |
|  |  Havuzu          |  |  (Codec context, filter       |    |
|  |  (Boyut bazli    |  |   state, temp buffer)         |    |
|  |   kategoriler)   |  |                                |    |
|  +--------+--------+  +--------------+----------------+    |
|           |                          |                     |
|  +--------v--------------------------v-----------------+  |
|  |              Arena Allocator                          |  |
|  |  (Render verileri icin lineer tahsis)                |  |
|  +---------------------------+--------------------------+  |
|                              |                             |
|  +----------------------------v--------------------------+  |
|  |         Zero-Copy Pipeline                             |  |
|  |  Memory-mapped dosya -> GPU texture (eszamanli)       |  |
|  +------------------------------------------------------+  |
|                                                           |
|  +------------------------------------------------------+  |
|  |         Sizinti Tespiti & GC Ayarlama                 |  |
|  |  Referans sayaci izleme + periyodik dogrulama         |  |
|  +------------------------------------------------------+  |
+-----------------------------------------------------------+
```

### 2.3 Veri Yapilari

#### PooledFrame

```python
import mmap
import os
import ctypes
from dataclasses import dataclass, field
from collections import deque


class PooledFrame:
    def __init__(self, frame_id, width, height, stride, pixel_format, data):
        self.frame_id = frame_id
        self.width = width
        self.height = height
        self.stride = stride
        self.pixel_format = pixel_format
        self.data = data
        self.is_dirty = True
        self.pool_reference = None
        self.timestamp: float = 0.0
        self.is_keyframe: bool = False
        self._acquired = False

    @property
    def size_bytes(self) -> int:
        return len(self.data)

    @property
    def is_available(self) -> bool:
        return not self._acquired

    def clear(self) -> None:
        self.data[:] = b'\x00' * len(self.data)
        self.is_dirty = False

    def copy_from(self, source: bytes) -> None:
        size = min(len(source), len(self.data))
        self.data[:size] = source[:size]
        self.is_dirty = False

    def release(self) -> None:
        if self.pool_reference and self._acquired:
            self.pool_reference.release_frame(self)
            self._acquired = False

    def __del__(self):
        self.release()


@dataclass
class FrameSizeClass:
    name: str
    min_width: int
    max_width: int
    min_height: int
    max_height: int
    pool_size: int = 32

    def matches(self, width: int, height: int) -> bool:
        return (self.min_width <= width <= self.max_width and
                self.min_height <= height <= self.max_height)


FRAME_SIZE_CLASSES = [
    FrameSizeClass("sd", 320, 720, 240, 576, pool_size=16),
    FrameSizeClass("hd", 720, 1920, 480, 1080, pool_size=32),
    FrameSizeClass("fullhd", 1920, 2560, 1080, 1440, pool_size=24),
    FrameSizeClass("4k", 2560, 4320, 1440, 2160, pool_size=16),
    FrameSizeClass("8k", 4320, 8640, 2160, 4320, pool_size=8),
]
```

#### FrameBufferPool

```python
class FrameBufferPool:
    def __init__(self, custom_size_classes=None):
        self._size_classes = custom_size_classes or FRAME_SIZE_CLASSES
        self._pools: dict[str, deque[PooledFrame]] = {}
        self._all_frames: dict[int, PooledFrame] = {}
        self._lock = threading.Lock()
        self._frame_counter = 0
        self._acquire_count = 0
        self._release_count = 0
        self._create_count = 0
        self._miss_count = 0

        for size_class in self._size_classes:
            self._pools[size_class.name] = deque()

    def acquire(self, width, height, pixel_format="yuv420p", clear=True) -> PooledFrame:
        with self._lock:
            self._acquire_count += 1
            size_class = self._find_size_class(width, height)
            stride = self._calculate_stride(width, pixel_format)
            frame_size = self._calculate_frame_size(width, height, pixel_format)

            if size_class and self._pools[size_class.name]:
                frame = self._pools[size_class.name].popleft()
                frame.width = width
                frame.height = height
                frame.stride = stride
                frame.pixel_format = pixel_format
                frame._acquired = True
                if clear:
                    frame.clear()
                else:
                    frame.is_dirty = True
                return frame

            self._create_count += 1
            self._miss_count += 1
            self._frame_counter += 1
            frame = PooledFrame(
                frame_id=self._frame_counter,
                width=width, height=height, stride=stride,
                pixel_format=pixel_format, data=bytearray(frame_size),
            )
            frame.pool_reference = self
            frame._acquired = True
            self._all_frames[frame.frame_id] = frame
            if clear:
                frame.clear()
            return frame

    def release_frame(self, frame: PooledFrame) -> None:
        with self._lock:
            self._release_count += 1
            frame.is_dirty = True
            frame._acquired = False
            size_class = self._find_size_class(frame.width, frame.height)
            if size_class:
                pool = self._pools[size_class.name]
                if len(pool) < size_class.pool_size:
                    pool.append(frame)

    def get_stats(self) -> dict:
        with self._lock:
            pool_stats = {}
            for name, pool in self._pools.items():
                sc = next((sc for sc in self._size_classes if sc.name == name), None)
                pool_stats[name] = {
                    "available": len(pool),
                    "max": sc.pool_size if sc else 0,
                }
            return {
                "acquire_count": self._acquire_count,
                "release_count": self._release_count,
                "create_count": self._create_count,
                "miss_count": self._miss_count,
                "hit_rate": 1.0 - (self._miss_count / max(1, self._acquire_count)),
                "pool_details": pool_stats,
            }

    def _find_size_class(self, width, height):
        for sc in self._size_classes:
            if sc.matches(width, height):
                return sc
        return None

    @staticmethod
    def _calculate_stride(width, pixel_format):
        sizes = {"yuv420p": width, "yuv422p": width * 2, "yuv444p": width * 3,
                 "rgb24": width * 3, "rgba32": width * 4, "gray8": width}
        return sizes.get(pixel_format, width * 4)

    @staticmethod
    def _calculate_frame_size(width, height, pixel_format):
        mult = {"yuv420p": 1.5, "yuv422p": 2.0, "yuv444p": 3.0,
                "rgb24": 3.0, "rgba32": 4.0, "gray8": 1.0}
        return int(width * height * mult.get(pixel_format, 4.0))
```

#### ArenaAllocator

Arena allocator, render verileri icin lineer bellek tahsis stratejisi kullanir. Tum tahsisler bir blok (arena) icinde sirali olarak yerlestirilir. Arena'nin sonuna gelindiginde yeni bir arena bloku tahsis edilir. Tum arena'lar toplu olarak serbest birakilabilir.

```python
class ArenaAllocator:
    def __init__(self, block_size: int = 4 * 1024 * 1024):
        self._block_size = block_size
        self._blocks: list[memoryview] = []
        self._current_block: Optional[memoryview] = None
        self._offset = 0
        self._lock = threading.Lock()
        self._total_allocated = 0
        self._total_requests = 0
        self._block_count = 0

    def allocate(self, size: int, alignment: int = 16) -> memoryview:
        with self._lock:
            self._total_requests += 1
            aligned_offset = (self._offset + alignment - 1) & ~(alignment - 1)
            if (self._current_block is None or
                    aligned_offset + size > self._block_size):
                self._allocate_new_block()
                aligned_offset = 0
            result = self._current_block[aligned_offset:aligned_offset + size]
            self._offset = aligned_offset + size
            self._total_allocated += size
            return result

    def allocate_zeroed(self, size: int, alignment: int = 16) -> memoryview:
        block = self.allocate(size, alignment)
        block_bytes = bytearray(block)
        block_bytes[:] = b'\x00' * size
        return block

    def reset(self) -> None:
        with self._lock:
            self._offset = 0

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "block_size_mb": self._block_size / (1024 * 1024),
                "block_count": len(self._blocks),
                "current_offset_mb": self._offset / (1024 * 1024),
                "total_allocated_mb": self._total_allocated / (1024 * 1024),
                "total_requests": self._total_requests,
                "utilization": self._offset / self._block_size if self._blocks else 0,
            }

    def _allocate_new_block(self) -> None:
        try:
            buf = (ctypes.c_char * self._block_size)()
            self._current_block = memoryview(buf)
            self._blocks.append(self._current_block)
            self._offset = 0
            self._block_count += 1
        except MemoryError:
            raise MemoryError(f"Yeni arena bloku olusturulamadi: {self._block_size / 1024 / 1024:.1f} MB")
```

### 2.4 Zero-Copy Pipeline

```python
class ZeroCopyPipeline:
    def __init__(self):
        self._open_mappings: dict[str, mmap.mmap] = {}
        self._lock = threading.Lock()

    def open_file(self, file_path: str) -> mmap.mmap:
        with self._lock:
            if file_path in self._open_mappings:
                return self._open_mappings[file_path]
            f = open(file_path, 'rb')
            try:
                mapped = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
                self._open_mappings[file_path] = mapped
                return mapped
            except Exception:
                f.close()
                raise

    def close_file(self, file_path: str) -> None:
        with self._lock:
            mapped = self._open_mappings.pop(file_path, None)
            if mapped:
                mapped.close()

    def read_frame_from_mapping(self, file_path, offset, size) -> memoryview:
        mapped = self.open_file(file_path)
        return mapped[offset:offset + size]

    def __del__(self):
        for path in list(self._open_mappings.keys()):
            self.close_file(path)
```

### 2.5 Garbage Collection Ayarlama

```python
import gc
import sys


class GCTuner:
    def __init__(self):
        self._original_threshold = gc.get_threshold()
        self._original_debug = gc.get_debug()

    def optimize_for_video_processing(self) -> None:
        gc.set_threshold(7000, 100, 20)
        gc.set_debug(0)

    def restore_defaults(self) -> None:
        gc.set_threshold(*self._original_threshold)
        gc.set_debug(self._original_debug)

    def get_gc_stats(self) -> dict:
        gen_counts = gc.get_count()
        gen_thresholds = gc.get_threshold()
        return {
            "generation_counts": {"gen0": gen_counts[0], "gen1": gen_counts[1], "gen2": gen_counts[2]},
            "thresholds": {"gen0": gen_thresholds[0], "gen1": gen_thresholds[1], "gen2": gen_thresholds[2]},
            "total_objects": len(gc.get_objects()),
            "garbage_objects": len(gc.garbage),
        }

    def force_collect_if_needed(self, threshold_mb: float = 500) -> bool:
        try:
            import psutil
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            if mem_mb > threshold_mb:
                gc.collect()
                return True
        except ImportError:
            pass
        return False
```

### 2.6 Bellek Sizintisi Tespiti

```python
class MemoryLeakDetector:
    def __init__(self, check_interval: float = 30.0):
        self._check_interval = check_interval
        self._snapshots: list[dict] = []
        self._tracked_objects: dict[int, dict] = {}
        self._running = False
        self._lock = threading.Lock()

    def track(self, obj, name: str) -> None:
        with self._lock:
            self._tracked_objects[id(obj)] = {
                "name": name, "type": type(obj).__name__,
                "created_at": time.time(),
            }

    def take_snapshot(self) -> dict:
        with self._lock:
            type_counts = {}
            for info in self._tracked_objects.values():
                t = info["type"]
                type_counts[t] = type_counts.get(t, 0) + 1
            snapshot = {
                "timestamp": time.time(),
                "tracked_count": len(self._tracked_objects),
                "gc_objects": len(gc.get_objects()),
                "type_distribution": type_counts,
            }
            self._snapshots.append(snapshot)
            return snapshot

    def analyze_leaks(self) -> list[dict]:
        if len(self._snapshots) < 2:
            return []
        leaks = []
        first = self._snapshots[0]
        last = self._snapshots[-1]
        first_types = first.get("type_distribution", {})
        last_types = last.get("type_distribution", {})
        for type_name, last_count in last_types.items():
            first_count = first_types.get(type_name, 0)
            increase = last_count - first_count
            if increase > 10:
                leaks.append({
                    "type": type_name, "increase": increase,
                    "severity": "high" if increase > 100 else "medium",
                })
        return sorted(leaks, key=lambda x: -x["increase"])

    def start_monitoring(self) -> None:
        self._running = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def stop_monitoring(self) -> None:
        self._running = False

    def _monitor_loop(self) -> None:
        while self._running:
            self.take_snapshot()
            time.sleep(self._check_interval)
```

### 2.7 Darboğazlar ve Cozumleri

| Darboz | Belirti | Cozum |
|----------|---------|-------|
| Yuksek GC yukku | Periyodik duraklamalar | GC tuning, arena allocator |
| Kare tamponu olusturma | Pipeline baslangic gecikmesi | Frame buffer pool warm-up |
| Bellek parcalanmasi | Yavas yavas artan RSS | Arena allocator, periodic defrag |
| Zero-copy overhead | mmap syscall maliyeti | Batch mapping, OS page cache |
| Referans dongusu | GC bulamiyor nesneleri | Weak reference, explicit tracking |

---

## 3. Dosya Streaming Motoru

### 3.1 Amaç

Video dosyalari genellikle gigabyte boyutundadir ve tamamini bellege yuklemek imkansizdir. Dosya streaming motoru, dosyalari chunk'lar halinde okur, okuma onceden tahminde bulunur (read-ahead), ve disk I/O'yu verimli sekilde planlar.

### 3.2 Mimari

```
+-----------------------------------------------------------+
|                 Dosya Streaming Motoru                     |
|                                                           |
|  +-----------------------------------------------------+  |
|  |              Okuma Onceden Tahmini                    |  |
|  |  (Gelacak chunk'lari arka planda oku)                |  |
|  +---------------------------+---------------------------+  |
|                              |                             |
|  +----------------------------v--------------------------+  |
|  |              I/O Oncelik Planlayici                   |  |
|  |  (Elevator algoritmasi ile disk siralama)            |  |
|  +---------------------------+---------------------------+  |
|                              |                             |
|  +----------------------------v--------------------------+  |
|  |              Dosya Format Demuxer                      |  |
|  |  (Container parsing: MP4, MOV, MKV, MXF)             |  |
|  +---------------------------+---------------------------+  |
|                              |                             |
|  +----------------------------v--------------------------+  |
|  |              Ag Dosya Erisimi                         |  |
|  |  (S3 streaming, HTTP range requests)                 |  |
|  +------------------------------------------------------+  |
|                                                           |
|  +------------------------------------------------------+  |
|  |              Disk I/O Izleme                          |  |
|  |  (Throughput, latency, queue depth)                  |  |
|  +------------------------------------------------------+  |
+-----------------------------------------------------------+
```

### 3.3 Veri Yapilari

#### IOPriority

```python
from enum import IntEnum


class IOPriority(IntEnum):
    CRITICAL = 0
    REALTIME = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4
    BACKGROUND = 5


@dataclass
class IORequest:
    request_id: int
    file_path: str
    offset: int
    size: int
    priority: IOPriority = IOPriority.NORMAL
    callback: Optional[callable] = None
    created_at: float = field(default_factory=time.monotonic)
    is_completed: bool = False
    data: Optional[bytes] = None
    error: Optional[str] = None

    @property
    def wait_time(self) -> float:
        return time.monotonic() - self.created_at

    def complete(self, data: bytes) -> None:
        self.data = data
        self.is_completed = True
        if self.callback:
            self.callback(self)

    def fail(self, error: str) -> None:
        self.error = error
        self.is_completed = True
        if self.callback:
            self.callback(self)
```

#### ReadAheadBuffer

```python
@dataclass
class ReadAheadConfig:
    buffer_size: int = 4 * 1024 * 1024
    max_buffers: int = 8
    prefetch_distance: int = 3
    enable_adaptive: bool = True


class ReadAheadBuffer:
    def __init__(self, config=None):
        self._config = config or ReadAheadConfig()
        self._buffers: dict[int, bytes] = {}
        self._pending_requests: set[int] = set()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        return self._hits / total if total > 0 else 0.0

    def get(self, file_path: str, offset: int, size: int) -> Optional[bytes]:
        with self._lock:
            for buf_offset, buf_data in self._buffers.items():
                if buf_offset <= offset < buf_offset + len(buf_data):
                    inner_offset = offset - buf_offset
                    end = inner_offset + size
                    if end <= len(buf_data):
                        self._hits += 1
                        return buf_data[inner_offset:end]
            self._misses += 1
            return None

    def prefetch(self, file_path: str, next_offsets: list[int], size: int) -> None:
        with self._lock:
            for offset in next_offsets:
                if (offset not in self._buffers and
                        offset not in self._pending_requests and
                        len(self._buffers) < self._config.max_buffers):
                    self._pending_requests.add(offset)

    def clear(self) -> None:
        with self._lock:
            self._buffers.clear()
            self._pending_requests.clear()

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "buffer_count": len(self._buffers),
                "total_buffer_size_mb": sum(len(d) for d in self._buffers.values()) / (1024 * 1024),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": self.hit_rate,
                "pending_requests": len(self._pending_requests),
            }
```

#### FileStream

```python
from pathlib import Path


@dataclass
class StreamChunk:
    offset: int
    size: int
    data: bytes
    is_keyframe: bool = False
    timestamp: float = 0.0


class FileStream:
    def __init__(self, file_path, chunk_size=2 * 1024 * 1024, read_ahead_config=None):
        self._file_path = file_path
        self._chunk_size = chunk_size
        self._read_ahead = ReadAheadBuffer(read_ahead_config)
        self._lock = threading.Lock()
        self._file_size = os.path.getsize(file_path)
        self._total_chunks = (self._file_size + chunk_size - 1) // chunk_size
        self._read_count = 0
        self._total_bytes_read = 0
        self._read_latency_sum = 0.0
        self._io_errors = 0
        self._io_queue: list[IORequest] = []
        self._request_counter = 0

    @property
    def file_size(self) -> int:
        return self._file_size

    @property
    def total_chunks(self) -> int:
        return self._total_chunks

    def read_chunk(self, chunk_index: int, priority=IOPriority.NORMAL) -> StreamChunk:
        offset = chunk_index * self._chunk_size
        size = min(self._chunk_size, self._file_size - offset)
        cached = self._read_ahead.get(self._file_path, offset, size)
        if cached is not None:
            return StreamChunk(offset=offset, size=size, data=cached)
        start_time = time.monotonic()
        try:
            with open(self._file_path, 'rb') as f:
                f.seek(offset)
                data = f.read(size)
        except IOError as e:
            self._io_errors += 1
            raise IOError(f"Chunk okuma hatasi (offset={offset}): {e}")
        elapsed = time.monotonic() - start_time
        self._read_count += 1
        self._total_bytes_read += len(data)
        self._read_latency_sum += elapsed
        self._trigger_read_ahead(chunk_index)
        return StreamChunk(offset=offset, size=len(data), data=data)

    def read_range(self, offset: int, size: int, priority=IOPriority.NORMAL) -> bytes:
        start_chunk = offset // self._chunk_size
        end_chunk = (offset + size - 1) // self._chunk_size
        result = bytearray()
        for chunk_idx in range(start_chunk, end_chunk + 1):
            chunk = self.read_chunk(chunk_idx, priority)
            result.extend(chunk.data)
        start_inner = offset - start_chunk * self._chunk_size
        return bytes(result[start_inner:start_inner + size])

    def submit_io_request(self, offset, size, priority=IOPriority.NORMAL) -> IORequest:
        with self._lock:
            self._request_counter += 1
            request = IORequest(
                request_id=self._request_counter,
                file_path=self._file_path,
                offset=offset, size=size, priority=priority,
            )
            self._io_queue.append(request)
            self._io_queue.sort(key=lambda r: r.priority)
            return request

    def get_io_stats(self) -> dict:
        avg_latency = self._read_latency_sum / self._read_count if self._read_count > 0 else 0
        throughput = self._total_bytes_read / self._read_latency_sum if self._read_latency_sum > 0 else 0
        return {
            "file_path": self._file_path,
            "file_size_mb": self._file_size / (1024 * 1024),
            "chunk_size_mb": self._chunk_size / (1024 * 1024),
            "total_chunks": self._total_chunks,
            "read_count": self._read_count,
            "total_bytes_read_mb": self._total_bytes_read / (1024 * 1024),
            "avg_read_latency_ms": avg_latency * 1000,
            "throughput_mbps": throughput / (1024 * 1024),
            "io_errors": self._io_errors,
            "read_ahead": self._read_ahead.get_stats(),
        }

    def _trigger_read_ahead(self, current_chunk: int) -> None:
        next_chunks = [
            current_chunk + i + 1
            for i in range(self._read_ahead._config.prefetch_distance)
            if current_chunk + i + 1 < self._total_chunks
        ]
        self._read_ahead.prefetch(self._file_path, next_chunks, self._chunk_size)
```

### 3.4 I/O Zamanlayici (Elevator Algoritmasi)

```python
class IOScheduler:
    def __init__(self, batch_size: int = 16):
        self._batch_size = batch_size
        self._queue: list[IORequest] = []
        self._current_position = 0
        self._direction = 1
        self._lock = threading.Lock()

    def submit(self, request: IORequest) -> None:
        with self._lock:
            self._queue.append(request)

    def process_batch(self) -> list[IORequest]:
        with self._lock:
            if not self._queue:
                return []
            self._queue.sort(key=lambda r: (r.priority, r.offset))
            batch = []
            for _ in range(min(self._batch_size, len(self._queue))):
                if not self._queue:
                    break
                best_idx = self._find_best_request()
                if best_idx is not None:
                    batch.append(self._queue.pop(best_idx))
            return batch

    def _find_best_request(self) -> Optional[int]:
        if not self._queue:
            return None
        best_idx = None
        best_distance = float('inf')
        for i, req in enumerate(self._queue):
            distance = abs(req.offset - self._current_position)
            priority_bonus = req.priority * 1024 * 1024
            adjusted_distance = distance + priority_bonus
            if adjusted_distance < best_distance:
                best_distance = adjusted_distance
                best_idx = i
        if best_idx is not None:
            self._current_position = self._queue[best_idx].offset
        return best_idx
```

### 3.5 Ag Dosya Erisimi

```python
class NetworkFileStream:
    def __init__(self, base_url, chunk_size=8 * 1024 * 1024, max_concurrent=4):
        self._base_url = base_url
        self._chunk_size = chunk_size
        self._max_concurrent = max_concurrent
        self._semaphore = threading.Semaphore(max_concurrent)
        self._request_count = 0
        self._total_bytes = 0
        self._error_count = 0
        self._latency_sum = 0.0

    def read_range(self, offset: int, size: int) -> bytes:
        self._semaphore.acquire()
        try:
            start_time = time.monotonic()
            import urllib.request
            req = urllib.request.Request(self._base_url)
            end_byte = offset + size - 1
            req.add_header('Range', f'bytes={offset}-{end_byte}')
            try:
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = response.read()
            except Exception as e:
                self._error_count += 1
                raise IOError(f"Range request hatasi: {e}")
            elapsed = time.monotonic() - start_time
            self._request_count += 1
            self._total_bytes += len(data)
            self._latency_sum += elapsed
            return data
        finally:
            self._semaphore.release()

    def read_chunk_parallel(self, chunks: list[tuple[int, int]]) -> list[bytes]:
        results = [None] * len(chunks)

        def _read_one(idx, offset, size):
            results[idx] = self.read_range(offset, size)

        threads = []
        for i, (offset, size) in enumerate(chunks):
            t = threading.Thread(target=_read_one, args=(i, offset, size))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        return results

    def get_stats(self) -> dict:
        avg_latency = self._latency_sum / self._request_count if self._request_count > 0 else 0
        throughput = self._total_bytes / self._latency_sum if self._latency_sum > 0 else 0
        return {
            "base_url": self._base_url,
            "request_count": self._request_count,
            "total_bytes_mb": self._total_bytes / (1024 * 1024),
            "avg_latency_ms": avg_latency * 1000,
            "throughput_mbps": throughput / (1024 * 1024),
            "error_count": self._error_count,
        }
```

### 3.6 Disk I/O Izleme

```python
class DiskIOMonitor:
    def __init__(self, sample_interval: float = 1.0):
        self._sample_interval = sample_interval
        self._history: list[dict] = []
        self._running = False

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._monitor_loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def _monitor_loop(self) -> None:
        while self._running:
            self._history.append(self._take_sample())
            if len(self._history) > 3600:
                self._history = self._history[-3600:]
            time.sleep(self._sample_interval)

    def _take_sample(self) -> dict:
        return {
            "timestamp": time.time(),
            "read_throughput_mbps": 500.0,
            "write_throughput_mbps": 300.0,
            "read_latency_ms": 2.5,
            "write_latency_ms": 5.0,
            "queue_depth": 4,
            "iops": 15000,
        }

    def get_summary(self) -> dict:
        if not self._history:
            return {"error": "Veri yok"}
        return {
            "samples": len(self._history),
            "avg_read_throughput_mbps": sum(s["read_throughput_mbps"] for s in self._history) / len(self._history),
            "avg_write_throughput_mbps": sum(s["write_throughput_mbps"] for s in self._history) / len(self._history),
            "avg_read_latency_ms": sum(s["read_latency_ms"] for s in self._history) / len(self._history),
            "peak_queue_depth": max(s["queue_depth"] for s in self._history),
        }
```

### 3.7 Darboğazlar ve Cozumleri

| Darboz | Belirti | Cozum |
|----------|---------|-------|
| Disk seek gecikmesi | Yuksek okuma gecikmesi | Elevator algoritmasi, sirali erisim |
| Bandwidth darboz | Ag dosyalarinda yavaslik | Parallel range requests, connection pooling |
| Read-ahead israfi | Bellek israfi, cache thrashing | Adaptif prefetch, LRU eviction |
| Container parsing | Demux gecikmesi | Parallel demux, index-based seeking |
| Dosya boyutu | Buyuk dosyalarda timeout | Chunk-based okuma, streaming demux |

---

## 4. Performans Benchmark

### 4.1 Amaç

Media pipeline'in performansini sistematik olarak olcmek, karsilastirmak ve optimize etmek icin kapsamli benchmark altyapisi. Her pipeline adiminin (decode, encode, filter, composite, export) ayri ayri ve uctan uca (end-to-end) performansi olculur.

### 4.2 Mimari

```
+-----------------------------------------------------------+
|                  Performans Benchmark Sistemi              |
|                                                           |
|  +-----------------+  +------------------------------+    |
|  |  Benchmark       |  |  Benchmark Sonuclari          |    |
|  |  Calistirici     |  |  (BenchmarkResult)            |    |
|  |                  |  |                                |    |
|  |  - Decode        |  |  - FPS, latency               |    |
|  |  - Encode        |  |  - Bellek kullanimi           |    |
|  |  - Filter        |  |  - GPU kullanimi              |    |
|  |  - Composite     |  |  - CPU profili                |    |
|  |  - Export        |  |  - Karsilastirma raporlari    |    |
|  +--------+--------+  +--------------+----------------+    |
|           |                          |                     |
|  +--------v--------------------------v-----------------+  |
|  |              Izleme Katmani                           |  |
|  |  CPU profiler + GPU izleme + Bellek profili          |  |
|  +-----------------------------------------------------+  |
+-----------------------------------------------------------+
```

### 4.3 Veri Yapilari

#### BenchmarkResult

```python
@dataclass
class BenchmarkResult:
    name: str
    duration_seconds: float = 0.0
    frames_processed: int = 0
    fps: float = 0.0
    avg_frame_time_ms: float = 0.0
    p50_frame_time_ms: float = 0.0
    p95_frame_time_ms: float = 0.0
    p99_frame_time_ms: float = 0.0
    min_frame_time_ms: float = 0.0
    max_frame_time_ms: float = 0.0
    peak_memory_mb: float = 0.0
    avg_memory_mb: float = 0.0
    gpu_utilization_pct: float = 0.0
    cpu_utilization_pct: float = 0.0
    throughput_mbps: float = 0.0
    errors: int = 0
    metadata: dict = field(default_factory=dict)
    frame_times: list[float] = field(default_factory=list)
    memory_samples: list[float] = field(default_factory=list)

    def calculate_percentiles(self) -> None:
        if not self.frame_times:
            return
        sorted_times = sorted(self.frame_times)
        n = len(sorted_times)
        self.p50_frame_time_ms = sorted_times[int(n * 0.50)]
        self.p95_frame_time_ms = sorted_times[int(n * 0.95)]
        self.p99_frame_time_ms = sorted_times[int(n * 0.99)]
        self.min_frame_time_ms = sorted_times[0]
        self.max_frame_time_ms = sorted_times[-1]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "duration_seconds": round(self.duration_seconds, 3),
            "frames_processed": self.frames_processed,
            "fps": round(self.fps, 2),
            "frame_times_ms": {
                "avg": round(self.avg_frame_time_ms, 3),
                "p50": round(self.p50_frame_time_ms, 3),
                "p95": round(self.p95_frame_time_ms, 3),
                "p99": round(self.p99_frame_time_ms, 3),
            },
            "memory_mb": {
                "peak": round(self.peak_memory_mb, 1),
                "avg": round(self.avg_memory_mb, 1),
            },
            "gpu_utilization_pct": round(self.gpu_utilization_pct, 1),
            "cpu_utilization_pct": round(self.cpu_utilization_pct, 1),
            "throughput_mbps": round(self.throughput_mbps, 2),
            "errors": self.errors,
        }

    def summary_line(self) -> str:
        return (
            f"{self.name}: {self.fps:.1f} FPS | "
            f"P95: {self.p95_frame_time_ms:.1f}ms | "
            f"Peak: {self.peak_memory_mb:.0f}MB | "
            f"GPU: {self.gpu_utilization_pct:.0f}%"
        )
```

#### BenchmarkSuite

```python
@dataclass
class BenchmarkConfig:
    test_name: str
    input_file: str = ""
    width: int = 1920
    height: int = 1080
    fps: int = 30
    codec: str = "h264"
    bitrate: int = 8_000_000
    filter_chain: list[str] = field(default_factory=list)
    iterations: int = 3
    warmup_iterations: int = 1
    timeout: int = 300


class BenchmarkSuite:
    def __init__(self, output_dir: str = "./benchmarks"):
        self._output_dir = output_dir
        self._results: list[BenchmarkResult] = []
        os.makedirs(output_dir, exist_ok=True)

    def run_decode_benchmark(self, config: BenchmarkConfig) -> BenchmarkResult:
        return self._run_benchmark(f"decode_{config.test_name}", config, self._decode_operation)

    def run_encode_benchmark(self, config: BenchmarkConfig) -> BenchmarkResult:
        return self._run_benchmark(f"encode_{config.test_name}", config, self._encode_operation)

    def run_filter_benchmark(self, config: BenchmarkConfig) -> BenchmarkResult:
        return self._run_benchmark(f"filter_{config.test_name}", config, self._filter_operation)

    def run_composite_benchmark(self, config: BenchmarkConfig) -> BenchmarkResult:
        return self._run_benchmark(f"composite_{config.test_name}", config, self._composite_operation)

    def run_end_to_end_benchmark(self, config: BenchmarkConfig) -> BenchmarkResult:
        return self._run_benchmark(f"e2e_{config.test_name}", config, self._end_to_end_operation)

    def compare_results(self, baseline, current) -> dict:
        fps_change = ((current.fps - baseline.fps) / baseline.fps * 100) if baseline.fps > 0 else 0
        latency_change = ((current.p95_frame_time_ms - baseline.p95_frame_time_ms) / baseline.p95_frame_time_ms * 100) if baseline.p95_frame_time_ms > 0 else 0
        memory_change = ((current.peak_memory_mb - baseline.peak_memory_mb) / baseline.peak_memory_mb * 100) if baseline.peak_memory_mb > 0 else 0
        return {
            "baseline": baseline.name, "current": current.name,
            "fps": {"baseline": round(baseline.fps, 2), "current": round(current.fps, 2), "change_pct": round(fps_change, 2), "improved": fps_change > 0},
            "p95_latency_ms": {"baseline": round(baseline.p95_frame_time_ms, 2), "current": round(current.p95_frame_time_ms, 2), "change_pct": round(latency_change, 2), "improved": latency_change < 0},
            "peak_memory_mb": {"baseline": round(baseline.peak_memory_mb, 1), "current": round(current.peak_memory_mb, 1), "change_pct": round(memory_change, 2), "improved": memory_change < 0},
            "overall_verdict": self._calculate_verdict(fps_change, latency_change, memory_change),
        }

    def generate_report(self) -> str:
        lines = [
            "# Performans Benchmark Raporu",
            f"\n**Tarih:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Toplam Test:** {len(self._results)}", "",
            "## Sonuclar", "",
            "| Test | FPS | P95 (ms) | Peak Mem (MB) | GPU % | Durum |",
            "|------|-----|----------|---------------|-------|-------|",
        ]
        for result in self._results:
            status = "PASS" if result.errors == 0 else "FAIL"
            lines.append(f"| {result.name} | {result.fps:.1f} | {result.p95_frame_time_ms:.1f} | {result.peak_memory_mb:.0f} | {result.gpu_utilization_pct:.0f} | {status} |")
        lines.append("")
        lines.append("## Detayli Sonuclar\n")
        for result in self._results:
            import json
            lines.append(f"### {result.name}\n```json\n{json.dumps(result.to_dict(), indent=2, ensure_ascii=False)}\n```\n")
        return "\n".join(lines)

    def _run_benchmark(self, name, config, operation) -> BenchmarkResult:
        import tracemalloc
        result = BenchmarkResult(name=name)
        frame_times = []
        memory_samples = []

        for _ in range(config.warmup_iterations):
            try:
                operation(config)
            except Exception:
                pass

        tracemalloc.start()
        start_time = time.monotonic()
        frames_processed = 0
        errors = 0

        try:
            for iteration in range(config.iterations):
                iter_start = time.monotonic()
                try:
                    frames = operation(config)
                    frames_processed += frames if frames else 0
                except Exception:
                    errors += 1
                iter_elapsed = time.monotonic() - iter_start
                frame_times.append(iter_elapsed * 1000)
                _, peak = tracemalloc.get_traced_memory()
                memory_samples.append(peak / (1024 * 1024))
        except KeyboardInterrupt:
            pass

        total_time = time.monotonic() - start_time
        _, peak_mem = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        result.duration_seconds = total_time
        result.frames_processed = frames_processed
        result.fps = frames_processed / total_time if total_time > 0 else 0
        result.frame_times = frame_times
        result.memory_samples = memory_samples
        result.peak_memory_mb = peak_mem / (1024 * 1024)
        result.avg_memory_mb = sum(memory_samples) / len(memory_samples) if memory_samples else 0
        result.errors = errors

        if frame_times:
            result.avg_frame_time_ms = sum(frame_times) / len(frame_times)
            result.calculate_percentiles()

        self._results.append(result)
        return result

    def _decode_operation(self, config):
        frames = 0
        for _ in range(config.fps * 10):
            time.sleep(0.001)
            frames += 1
        return frames

    def _encode_operation(self, config):
        frames = 0
        for _ in range(config.fps * 10):
            time.sleep(0.002)
            frames += 1
        return frames

    def _filter_operation(self, config):
        frames = 0
        for _ in range(config.fps * 10):
            time.sleep(0.0005)
            frames += 1
        return frames

    def _composite_operation(self, config):
        frames = 0
        for _ in range(config.fps * 10):
            time.sleep(0.003)
            frames += 1
        return frames

    def _end_to_end_operation(self, config):
        frames = 0
        for _ in range(config.fps * 10):
            time.sleep(0.001)
            time.sleep(0.0005)
            time.sleep(0.002)
            frames += 1
        return frames

    @staticmethod
    def _calculate_verdict(fps_change, latency_change, memory_change):
        positive = 0
        if fps_change > 5:
            positive += 1
        if latency_change < -5:
            positive += 1
        if memory_change < -5:
            positive += 1
        if positive >= 2:
            return "significant_improvement"
        elif positive == 1:
            return "minor_improvement"
        elif fps_change < -5 or latency_change > 10:
            return "regression"
        return "no_change"
```

### 4.4 CPU Profiling Entegrasyonu

```python
import cProfile
import pstats
import io


class CPUProfiler:
    def __init__(self):
        self._profiler = None
        self._results: dict[str, pstats.Stats] = {}

    def start(self) -> None:
        self._profiler = cProfile.Profile()
        self._profiler.enable()

    def stop(self, label: str = "default"):
        if self._profiler is None:
            raise RuntimeError("Profil baslatilmamis")
        self._profiler.disable()
        stats = pstats.Stats(self._profiler)
        self._results[label] = stats
        return stats

    def get_top_functions(self, label: str, n: int = 20) -> list[dict]:
        stats = self._results.get(label)
        if stats is None:
            return []
        results = []
        for func_info, (cc, nc, tt, ct, callers) in stats.stats.items():
            filename, line, func_name = func_info
            results.append({
                "function": func_name, "filename": filename, "line": line,
                "total_time_s": round(tt, 6), "cumulative_time_s": round(ct, 6),
                "call_count": nc,
            })
        results.sort(key=lambda x: -x["total_time_s"])
        return results[:n]

    def generate_report(self, label: str) -> str:
        stats = self._results.get(label)
        if stats is None:
            return f"'{label}' etiketli profil bulunamadi"
        stream = io.StringIO()
        stats = pstats.Stats(stats, stream=stream)
        stats.sort_stats('cumulative')
        stats.print_stats(30)
        return stream.getvalue()
```

### 4.5 Benchmark Kullanim Ornegi

```python
def run_full_benchmark():
    suite = BenchmarkSuite(output_dir="./benchmark_results")

    decode_config = BenchmarkConfig(
        test_name="1080p_h264", width=1920, height=1080,
        fps=30, codec="h264", iterations=5, warmup_iterations=2,
    )
    decode_result = suite.run_decode_benchmark(decode_config)
    print(f"Decode: {decode_result.summary_line()}")

    encode_config = BenchmarkConfig(
        test_name="1080p_h264", width=1920, height=1080,
        fps=30, codec="h264", bitrate=8_000_000,
        iterations=5, warmup_iterations=2,
    )
    encode_result = suite.run_encode_benchmark(encode_config)
    print(f"Encode: {encode_result.summary_line()}")

    filter_config = BenchmarkConfig(
        test_name="1080p_sharpen", width=1920, height=1080,
        fps=30, filter_chain=["sharpen", "color_correct"], iterations=5,
    )
    filter_result = suite.run_filter_benchmark(filter_config)
    print(f"Filter: {filter_result.summary_line()}")

    decode_4k_config = BenchmarkConfig(
        test_name="4k_h264", width=3840, height=2160,
        fps=30, codec="h264", iterations=3,
    )
    decode_4k_result = suite.run_decode_benchmark(decode_4k_config)
    print(f"4K Decode: {decode_4k_result.summary_line()}")

    comparison = suite.compare_results(decode_result, decode_4k_result)
    print(f"\n1080p vs 4K Karsilastirma:")
    print(f"  FPS: {comparison['fps']['baseline']} -> {comparison['fps']['current']} ({comparison['fps']['change_pct']:+.1f}%)")

    report = suite.generate_report()
    with open("./benchmark_results/report.md", "w", encoding="utf-8") as f:
        f.write(report)
    return suite


if __name__ == "__main__":
    suite = run_full_benchmark()
```

### 4.6 Darboğazlar ve Cozumleri

| Darboz | Belirti | Cozum |
|----------|---------|-------|
| Warm-up etkisi | Ilk kareler yavas | Isinma iterasyonlari |
| GC pause'lari | Ani gecikme spike'lari | GC tuning, warm heap |
| CPU throttling | Uzun testlerde yavaslasma | Soguma bekleme, fan kontrolu |
| GPU thermal throttling | Encode FPS dususu | Sicaklik izleme, dinamik clock |
| Bellek pressure | Benchmark sirasinda swap | Bellek butce kontrolu |

---

## 5. Render Performans Optimizasyonu

### 5.1 Amaç

Video render pipeline'ini mumkun olan en yuksek hizda ve en dusuk gecikmeyle calistirmak icin paralel isleme, filtre optimizasyonu ve donanim hizlandirma stratejileri.

### 5.2 Mimari

```
+-----------------------------------------------------------+
|             Render Performans Optimizasyonu                 |
|                                                           |
|  +-----------------------------------------------------+  |
|  |         Kare Duzeyinde Paralellik                     |  |
|  |  Kareden bagimsiz isler -> thread havuzu             |  |
|  +-----------------------------------------------------+  |
|                                                           |
|  +-----------------------------------------------------+  |
|  |         Pipeline Paralellik                           |  |
|  |  Decode -> Process -> Encode (es zamanli)            |  |
|  |  Farkli kareler farkli asamalarda                   |  |
|  +-----------------------------------------------------+  |
|                                                           |
|  +-----------------------------------------------------+  |
|  |         Filtre Grafigi Optimizasyonu                  |  |
|  |  Filtre birlestirme, graf prunning                   |  |
|  +-----------------------------------------------------+  |
|                                                           |
|  +-----------------------------------------------------+  |
|  |         Donanim Hizlandirma Tespiti                   |  |
|  |  CUDA, OpenCL, VideoToolbox, VAAPI tespiti           |  |
|  +-----------------------------------------------------+  |
|                                                           |
|  +-----------------------------------------------------+  |
|  |         Thread Havuzu Yonetimi                        |  |
|  |  Dinamik thread sayisi, oncelik kuyruklari           |  |
|  +-----------------------------------------------------+  |
|                                                           |
|  +-----------------------------------------------------+  |
|  |         Toplu Isleme (Batch Processing)               |  |
|  |  Kareleri gruplayarak GPU verimliligini artir        |  |
|  +-----------------------------------------------------+  |
+-----------------------------------------------------------+
```

### 5.3 Veri Yapilari

#### RenderProfile

```python
from enum import Enum, auto


class RenderQuality(Enum):
    DRAFT = auto()
    NORMAL = auto()
    HIGH = auto()
    ULTRA = auto()


class HardwareAcceleration(Enum):
    NONE = auto()
    CUDA = auto()
    OPENCL = auto()
    VAAPI = auto()
    VIDEOTOOLBOX = auto()
    NVENC = auto()
    AMF = auto()
    QSV = auto()


@dataclass
class RenderProfile:
    name: str = "default"
    quality: RenderQuality = RenderQuality.NORMAL
    target_fps: int = 30
    max_memory_mb: int = 4096
    preferred_acceleration: HardwareAcceleration = HardwareAcceleration.NONE
    thread_count: int = 0
    batch_size: int = 1
    buffer_count: int = 3
    enable_gpu_filter: bool = False
    enable_gpu_encode: bool = False
    max_resolution: tuple[int, int] = (3840, 2160)


@dataclass
class ParallelConfig:
    enable_frame_parallelism: bool = True
    enable_pipeline_parallelism: bool = True
    frame_workers: int = 4
    pipeline_stages: int = 3
    decode_workers: int = 2
    process_workers: int = 4
    encode_workers: int = 2
    queue_size: int = 16
    use_double_buffer: bool = True
    use_triple_buffer: bool = False
```

### 5.4 Kare Duzeyinde Paralellik

```python
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import multiprocessing


class FrameParallelProcessor:
    def __init__(self, config: ParallelConfig):
        self._config = config
        self._worker_count = config.frame_workers or multiprocessing.cpu_count()
        self._process_pool: Optional[ProcessPoolExecutor] = None
        self._running = False

    def start(self, process_func: callable) -> None:
        self._running = True
        self._process_pool = ProcessPoolExecutor(max_workers=self._worker_count)
        self._process_func = process_func

    def submit_frame(self, frame_data, frame_id: int) -> None:
        if self._process_pool:
            self._process_pool.submit(self._process_func, frame_data, frame_id)

    def shutdown(self) -> None:
        self._running = False
        if self._process_pool:
            self._process_pool.shutdown(wait=True)

    def get_optimal_worker_count(self) -> int:
        cpu_count = multiprocessing.cpu_count()
        if self._config.enable_pipeline_parallelism:
            return max(cpu_count // 3, 2)
        return cpu_count
```

### 5.5 Pipeline Paralellik

```python
class PipelineParallelProcessor:
    def __init__(self, config: ParallelConfig):
        self._config = config
        self._decode_queue = multiprocessing.Queue(maxsize=config.queue_size)
        self._process_queue = multiprocessing.Queue(maxsize=config.queue_size)
        self._encode_queue = multiprocessing.Queue(maxsize=config.queue_size)
        self._output_queue = multiprocessing.Queue(maxsize=config.queue_size)
        self._workers: list[multiprocessing.Process] = []
        self._running = False

    def start(self, decode_func, process_func, encode_func) -> None:
        self._running = True

        for _ in range(self._config.decode_workers):
            p = multiprocessing.Process(
                target=self._decode_worker,
                args=(decode_func, self._decode_queue, self._process_queue),
                daemon=True,
            )
            self._workers.append(p)
            p.start()

        for _ in range(self._config.process_workers):
            p = multiprocessing.Process(
                target=self._process_worker,
                args=(process_func, self._process_queue, self._encode_queue),
                daemon=True,
            )
            self._workers.append(p)
            p.start()

        for _ in range(self._config.encode_workers):
            p = multiprocessing.Process(
                target=self._encode_worker,
                args=(encode_func, self._encode_queue, self._output_queue),
                daemon=True,
            )
            self._workers.append(p)
            p.start()

    def submit_work(self, frame_data, frame_id: int) -> None:
        self._decode_queue.put((frame_data, frame_id))

    def collect_results(self, timeout: float = 1.0) -> list:
        results = []
        while not self._output_queue.empty():
            try:
                results.append(self._output_queue.get(timeout=timeout))
            except Exception:
                break
        return results

    def shutdown(self) -> None:
        self._running = False
        for _ in range(self._config.decode_workers):
            self._decode_queue.put(None)
        for _ in range(self._config.process_workers):
            self._process_queue.put(None)
        for _ in range(self._config.encode_workers):
            self._encode_queue.put(None)
        for worker in self._workers:
            worker.join(timeout=10.0)
        self._workers.clear()

    def get_throughput_stats(self) -> dict:
        return {
            "decode_workers": self._config.decode_workers,
            "process_workers": self._config.process_workers,
            "encode_workers": self._config.encode_workers,
            "queue_sizes": {
                "decode": self._decode_queue.qsize(),
                "process": self._process_queue.qsize(),
                "encode": self._encode_queue.qsize(),
            },
            "pipeline_depth": (
                self._decode_queue.qsize() +
                self._process_queue.qsize() +
                self._encode_queue.qsize()
            ),
        }

    def _decode_worker(self, func, in_q, out_q) -> None:
        while True:
            item = in_q.get()
            if item is None:
                break
            frame_data, frame_id = item
            try:
                out_q.put(func(frame_data, frame_id))
            except Exception:
                out_q.put((frame_id, None))

    def _process_worker(self, func, in_q, out_q) -> None:
        while True:
            item = in_q.get()
            if item is None:
                break
            try:
                out_q.put(func(item))
            except Exception:
                out_q.put(None)

    def _encode_worker(self, func, in_q, out_q) -> None:
        while True:
            item = in_q.get()
            if item is None:
                break
            try:
                out_q.put(func(item))
            except Exception:
                out_q.put(None)
```

### 5.6 Filtre Grafigi Optimizasyonu

```python
@dataclass
class FilterNode:
    name: str
    params: dict = field(default_factory=dict)
    is_gpu: bool = False
    estimated_cost: float = 0.5
    dependencies: list[str] = field(default_factory=list)


class FilterGraphOptimizer:
    def __init__(self):
        self._merge_rules = {
            ("brightness", "contrast"): "auto_level",
            ("scale", "crop"): "scale_crop",
            ("sharpen", "blur"): "smart_sharpen",
        }

    def optimize(self, filter_chain: list[FilterNode]) -> list[FilterNode]:
        optimized = list(filter_chain)
        optimized = self._prune_unused(optimized)
        optimized = self._merge_filters(optimized)
        optimized = self._sort_by_cost(optimized)
        optimized = self._group_gpu_filters(optimized)
        return optimized

    def _prune_unused(self, chain):
        if len(chain) <= 1:
            return chain
        return chain

    def _merge_filters(self, chain):
        if len(chain) < 2:
            return chain
        merged = []
        i = 0
        while i < len(chain):
            if i + 1 < len(chain):
                key = (chain[i].name, chain[i + 1].name)
                if key in self._merge_rules:
                    merged.append(FilterNode(
                        name=self._merge_rules[key],
                        params={**chain[i].params, **chain[i + 1].params},
                        is_gpu=chain[i].is_gpu or chain[i + 1].is_gpu,
                        estimated_cost=max(chain[i].estimated_cost, chain[i + 1].estimated_cost) * 0.8,
                    ))
                    i += 2
                    continue
            merged.append(chain[i])
            i += 1
        return merged

    def _sort_by_cost(self, chain):
        return sorted(chain, key=lambda f: f.estimated_cost)

    def _group_gpu_filters(self, chain):
        gpu_filters = [f for f in chain if f.is_gpu]
        cpu_filters = [f for f in chain if not f.is_gpu]
        return cpu_filters + gpu_filters

    def estimate_total_cost(self, chain):
        return sum(f.estimated_cost for f in chain)

    def analyze_parallelism(self, chain):
        independent_pairs = []
        for i in range(len(chain)):
            for j in range(i + 1, len(chain)):
                if (chain[j].name not in chain[i].dependencies and
                        chain[i].name not in chain[j].dependencies):
                    independent_pairs.append((chain[i].name, chain[j].name))
        total = len(chain) * (len(chain) - 1) / 2
        return {
            "total_filters": len(chain),
            "gpu_filters": sum(1 for f in chain if f.is_gpu),
            "cpu_filters": sum(1 for f in chain if not f.is_gpu),
            "independent_pairs": len(independent_pairs),
            "parallelism_potential": len(independent_pairs) / max(1, total),
            "estimated_speedup": 1.0 + len(independent_pairs) * 0.3,
        }
```

### 5.7 Donanim Hizlandirma Tespiti

```python
class HardwareAccelerationDetector:
    def __init__(self):
        self._available: dict[HardwareAcceleration, dict] = {}
        self._detect_all()

    def _detect_all(self) -> None:
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                gpu_info = result.stdout.strip()
                self._available[HardwareAcceleration.CUDA] = {"name": gpu_info, "available": True}
                self._available[HardwareAcceleration.NVENC] = {"name": gpu_info, "available": True}
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        self._available[HardwareAcceleration.NONE] = {"name": "Software (CPU)", "available": True}

    def get_available(self) -> list[HardwareAcceleration]:
        return [k for k, v in self._available.items() if v.get("available")]

    def select_best(self, required_codec="h264", required_resolution=(1920, 1080)):
        available = self.get_available()
        priority_order = [
            HardwareAcceleration.NVENC, HardwareAcceleration.CUDA,
            HardwareAcceleration.VAAPI, HardwareAcceleration.VIDEOTOOLBOX,
            HardwareAcceleration.QSV, HardwareAcceleration.AMF,
            HardwareAcceleration.OPENCL, HardwareAcceleration.NONE,
        ]
        for accel in priority_order:
            if accel in available:
                return accel
        return HardwareAcceleration.NONE

    def get_report(self) -> dict:
        return {
            "available_count": len(self.get_available()),
            "accelerations": {k.name: v for k, v in self._available.items()},
            "recommended": self.select_best().name,
        }
```

### 5.8 Thread Havuzu Yonetimi

```python
class AdaptiveThreadPool:
    def __init__(self, min_threads=2, max_threads=16, scale_interval=5.0):
        self._min_threads = min_threads
        self._max_threads = max_threads
        self._scale_interval = scale_interval
        self._current_threads = min_threads
        self._pool: Optional[ThreadPoolExecutor] = None
        self._lock = threading.Lock()
        self._active_tasks = 0
        self._completed_tasks = 0

    def start(self) -> None:
        with self._lock:
            self._pool = ThreadPoolExecutor(max_workers=self._current_threads)

    def submit(self, func, *args, **kwargs):
        if self._pool is None:
            self.start()
        self._active_tasks += 1
        return self._pool.submit(self._wrapper, func, *args, **kwargs)

    def _wrapper(self, func, *args, **kwargs):
        self._active_tasks += 1
        try:
            result = func(*args, **kwargs)
            self._completed_tasks += 1
            return result
        finally:
            self._active_tasks -= 1

    def scale_based_on_load(self) -> int:
        with self._lock:
            try:
                import psutil
                cpu_percent = psutil.cpu_percent(interval=0.1)
            except ImportError:
                cpu_percent = 50.0

            if cpu_percent > 80 and self._current_threads > self._min_threads:
                self._current_threads = max(self._min_threads, self._current_threads - 1)
            elif cpu_percent < 50 and self._current_threads < self._max_threads:
                self._current_threads = min(self._max_threads, self._current_threads + 1)

            if self._pool:
                self._pool.shutdown(wait=False)
                self._pool = ThreadPoolExecutor(max_workers=self._current_threads)

            return self._current_threads

    def get_stats(self) -> dict:
        return {
            "current_threads": self._current_threads,
            "min_threads": self._min_threads,
            "max_threads": self._max_threads,
            "active_tasks": self._active_tasks,
            "completed_tasks": self._completed_tasks,
        }

    def shutdown(self) -> None:
        if self._pool:
            self._pool.shutdown(wait=True)
```

### 5.9 Toplu Isleme (Batch Processing)

```python
class BatchProcessor:
    """GPU verimliligini artirmak icin kareleri toplu isler.

    GPU'ya tek seferde birden fazla kare gondererek
    kernel launch overhead'ini azaltir ve GPU doluluk oranini
    artirir.

    Avantajlari:
    - Dusuk GPU kernel launch overhead
    - Daha iyi GPU kaynak kullanimi
    - Bellek bant genisliginden daha verimli yararlanma
    - Eszamanli isleme kapasitesini artirma
    """

    def __init__(self, batch_size: int = 8):
        self._batch_size = batch_size
        self._buffer: list = []
        self._lock = threading.Lock()
        self._total_batches = 0
        self._total_frames = 0

    def add_frame(self, frame_data) -> list:
        """Kareyi toplu isleme kuyruguna ekle.

        Kuyruk batch_size'a ulastiginda tum kareleri
        isler ve sonuclari dondurur.

        Args:
            frame_data: Islenecek kare verisi.

        Returns:
            Islenmis karelerin listesi (bos veya dolu).
        """
        with self._lock:
            self._buffer.append(frame_data)
            if len(self._buffer) >= self._batch_size:
                return self._flush_batch()
            return []

    def flush(self) -> list:
        """Mevcut kuyruktaki tum kareleri isle."""
        with self._lock:
            return self._flush_batch()

    def _flush_batch(self) -> list:
        if not self._buffer:
            return []

        batch = self._buffer[:]
        self._buffer.clear()
        self._total_batches += 1
        self._total_frames += len(batch)

        # Burada gercek GPU batch islemesi yapilir
        # Ornegin: toplu NVENC encode, toplu filtre uygulama
        results = []
        for frame in batch:
            results.append(frame)  # Simulasyon

        return results

    def get_stats(self) -> dict:
        with self._lock:
            return {
                "batch_size": self._batch_size,
                "buffered_frames": len(self._buffer),
                "total_batches": self._total_batches,
                "total_frames": self._total_frames,
                "avg_batch_utilization": (
                    self._total_frames / max(1, self._total_batches) / self._batch_size
                ),
            }
```

### 5.10 Darbozlar ve Cozumleri

| Darboz | Belirti | Cozum |
|----------|---------|-------|
| Kare bazli paralellik siniri | CPU cekirdek sayisiyla sinirli | Pipeline paralellik ekle |
| Pipeline kuyruk dolulugu | Throughput dususu | Dinamik kuyruk boyutu, backpressure |
| Filtre bagimliligi | Siralama kisitlamasi | DAG analizi, yeniden siralama |
| GPU bos kalmasi | Dusuk GPU kullanimi | Batch processing, daha buyuk batch |
| Thread yarisi (contention) | Kilit bekleme sureleri | Lock-free yapilar, ring buffer |
| Bellek bant genisligi | CPU-bound islemler | SIMD optimizasyonu, cache-friendly erisim |

---

## Ek: Performans Hedef Tablosu

| Metrik | Hedef (1080p) | Hedef (4K) | Kritik Esik |
|--------|---------------|------------|-------------|
| Decode FPS | >= 240 | >= 60 | < 30 FPS |
| Encode FPS | >= 120 | >= 30 | < 15 FPS |
| Filter FPS | >= 480 | >= 120 | < 60 FPS |
| End-to-End FPS | >= 60 | >= 24 | < 24 FPS |
| P99 Frame Time | < 5ms | < 15ms | > 50ms |
| Peak Memory | < 2GB | < 8GB | > 16GB |
| GPU Utilization | > 80% | > 70% | < 30% |
| CPU Utilization | > 85% | > 75% | > 98% (throttle) |
| Bellek Sizintisi | 0 MB/s | 0 MB/s | > 1 MB/dk |
| GC Pause | < 5ms | < 10ms | > 50ms |

---

> **Sonraki Modul:** [10 - Hata Yonetimi ve Dayaniklilik](./10-error-handling-resilience.md)
