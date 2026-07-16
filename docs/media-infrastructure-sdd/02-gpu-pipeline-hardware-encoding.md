# GPU Video Pipeline, FFmpeg Filter Graph, Hardware Encoding ve Dynamic Crop Engine

## Sistem Mimari Ozeti

Tuncay-klip platformu, Kick canli yayin kliplerini uretim kalitesinde isleyen bir NLE (Non-Linear Editing) altyapisidir. Bu belge, GPU tabanli video isleme pipeline'inin, FFmpeg filter graph mimarisinin, hardware encoding stratejilerinin ve dynamic crop engine'in detayli tasarimini kapsar.

**Teknoloji Yigini:** Python 3.12+ / FastAPI / FFmpeg 6.x / NVIDIA CUDA 12.x / PyCUDA / OpenCV CUDA / VA-API / Intel QSV / AMD AMF

---

## Icindekiler

1. [GPU Video Pipeline](#1-gpu-video-pipeline)
2. [FFmpeg Filter Graph Mimarisi](#2-ffmpeg-filter-graph-mimarisi)
3. [Hardware Encoding](#3-hardware-encoding)
4. [Dynamic Crop Engine](#4-dynamic-crop-engine)
5. [Auto Reframe](#5-auto-reframe)
6. [Motion Tracking](#6-motion-tracking)

---

# 1. GPU Video Pipeline

## 1.1 Amaç

GPU Video Pipeline, video karelerinin GPU bellek uzerinde yuksek performansli islenmesini saglar. CPU-GPU veri transferi overhead'ini en aza indirerek, real-time veya near-real-time video isleme kapasitesi sunar.

**Temel Hedefler:**
- 1080p60 kareler icin <5ms GPU processing suresi
- GPU bellek kullaniminda VRAM limitlerinde calismak
- Multi-GPU load balancing ile paralel is dagitimi
- GPU basarisiz oldugunda otomatik CPU fallback mekanizmasi

## 1.2 Mimari Tasarim

```
+---------------------------------------------------------------------+
|                        Application Layer                            |
|  FastAPI Endpoint -> Job Queue -> Pipeline Orchestrator             |
+---------------------------------------------------------------------+
|                      Pipeline Control Layer                          |
|  GPUContext Manager -> Memory Pool -> Transfer Scheduler            |
+---------------+---------------------------+------------------------+
|  CPU Domain   |      Transfer Layer        |     GPU Domain         |
|               |  Pinned Memory / Zero-Copy |                        |
|  Frame Pool   |<=========================>|  GPU Buffer Pool       |
|  CPU Filters  |  DMA Engine / PCIe BW      |  CUDA Kernels          |
|               |                            |  GPU Filters           |
+---------------+---------------------------+------------------------+
|                    Hardware Abstraction Layer                        |
|  CUDA Runtime | OpenCL | VA-API | VAAPI | Video Toolkit            |
+---------------------------------------------------------------------+
|                       GPU Hardware                                   |
|  NVIDIA (NVENC/NVDEC) | Intel (QSV) | AMD (AMF)                   |
+---------------------------------------------------------------------+
```

### Pipeline Akisi

```
Decode (CPU/GPU) -> Upload to GPU -> GPU Filter Chain -> Download to CPU -> Encode (CPU/GPU)
       |                  |                |                    |               |
       v                  v                v                    v               v
   FFmpeg HW        Pinned Memory    CUDA Kernels         DMA Transfer    NVENC/QSV
   Decoder          -> GPU Buffer    -> Scale/Crop         GPU -> CPU       Hardware
   (NVDEC)          Allocation        /Color/Resize       Pinned Buf      Encoder
```

## 1.3 GPU Bellek Yonetimi

### 1.3.1 Bellek Modeli

GPU bellek yonetimi uc katmandan olusur:

| Katman | Aciklama | Boyut | Erisim Hizi |
|--------|----------|-------|-------------|
| GPU Global Memory | GPU uzerindeki ana bellek | 8-80 GB (VRAM) | ~900 GB/s |
| Pinned (Page-locked) Memory | CPU tarafinda DMA-erisilebilir | Sistem RAM limitinde | ~32 GB/s (PCIe) |
| Unified Memory | CUDA Managed Memory | Paylasimli | Otomatik migrasyon |

**Bellek Hiyerarsisi Performans Karsilastirmasi:**

```
Kaynak              Bant Genisligi      Latans
-----------------------------------------------
GPU Global (HBM)    1.5-3.0 TB/s       ~100ns
GPU Global (GDDR)   500-900 GB/s       ~200ns
PCIe 4.0 x16        32 GB/s (teorik)   ~1us
PCIe 3.0 x16        16 GB/s (teorik)   ~1us
Pinned Memory       24-32 GB/s         ~0.5us
System Memory       40-80 GB/s         ~100ns (CPU erisimi)
```

### 1.3.2 Bellek Havuzu (Memory Pool)

Surekli bellek tahsisi ve serbest birakma operasyonlari yuksek overhead olusturur. Memory Pool, onceden tahsis edilmis bellek bloklarini yeniden kullanarak bu overhead'i ortadan kaldirir.

**Tasarim Ilkeleri:**
1. **Bucket-based allocation:** Bellek bloklari kategorize edilir, en yakin kovaya eslestirilir
2. **LRU eviction:** En az kullanilan bloklar once serbest birakilir
3. **Thread-safe:** RLock ile concurrent erisim korumasi
4. **Monitoring:** Tahsis, yeniden kullanma ve serbest birakma istatistikleri tutulur
### 1.3.3 Pinned Memory Transfer Optimizasyonu

Pinned memory, CPU tarafinda sayfa kilidi ekleyerek DMA engine'in dogrudan erismesini saglar. Bu, CPU-GPU transferlerinde %40-60 hizlanma saglar.

**Transfer Optimizasyon Stratejileri:**

```
Strateji                    Hiz Kazanci    Karmaisiklik
--------------------------------------------------------
Pinned Memory               %40-60         Dusuk
Async CUDA Streams          %20-40         Orta
Zero-Copy (Unified Memory)  Degisen        Dusuk
Multi-Stream Pipeline       %30-50         Yuksek
Overlap Transfer+Compute    %25-45         Yuksek
```

```python
import numpy as np
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional


class TransferMode(Enum):
    SYNCHRONOUS = auto()
    ASYNCHRONOUS = auto()
    ZERO_COPY = auto()


@dataclass
class TransferProfile:
    direction: str
    size_bytes: int
    bandwidth_gbps: float
    latency_ms: float
    mode: TransferMode
    is_pinned: bool
    device_id: int


class TransferScheduler:
    """
    CPU-GPU veri transferlerini zamanlayan ve optimize eden programci.
    Pinned memory kullanarak DMA transferlerini hizlandirir.
    """

    def __init__(
        self,
        memory_pool: MemoryPool,
        default_transfer_mode: TransferMode = TransferMode.ASYNCHRONOUS,
    ):
        self._pool = memory_pool
        self._default_mode = default_transfer_mode
        self._transfer_streams: dict[int, object] = {}
        self._transfer_profiles: list[TransferProfile] = []

    def host_to_device(
        self,
        host_array: np.ndarray,
        gpu_buffer: Optional[MemoryBlock] = None,
        device_id: int = 0,
        stream_id: int = 0,
    ) -> MemoryBlock:
        size_bytes = host_array.nbytes
        start_time = time.perf_counter()

        if gpu_buffer is None:
            gpu_buffer = self._pool.allocate(size_bytes, MemoryType.GPU_GLOBAL, device_id)

        if not host_array.flags["C_CONTIGUOUS"]:
            host_array = np.ascontiguousarray(host_array)

        pinned_buf = self._pool.allocate(size_bytes, MemoryType.CPU_PINNED, device_id)
        try:
            import pycuda.driver as cuda
            pinned_array = np.frombuffer(
                (ctypes.c_byte * size_bytes).from_address(pinned_buf.pointer),
                dtype=np.uint8,
            ).reshape(host_array.shape)
            np.copyto(pinned_array, host_array)
            stream = self._get_stream(device_id, stream_id)
            cuda.memcpy_htod_async(gpu_buffer.pointer, pinned_buf.pointer, size_bytes, stream)
        except ImportError:
            import pycuda.driver as cuda
            cuda.memcpy_htod(gpu_buffer.pointer, host_array)
        finally:
            self._pool.release(pinned_buf)

        elapsed = (time.perf_counter() - start_time) * 1000
        bandwidth = (size_bytes / (1024**3)) / (elapsed / 1000) if elapsed > 0 else 0
        self._transfer_profiles.append(TransferProfile(
            direction="H2D", size_bytes=size_bytes, bandwidth_gbps=bandwidth,
            latency_ms=elapsed, mode=self._default_mode, is_pinned=True, device_id=device_id,
        ))
        gpu_buffer.last_used_frame += 1
        return gpu_buffer

    def device_to_host(
        self, gpu_buffer: MemoryBlock, output_shape: tuple,
        dtype: np.dtype = np.uint8, device_id: int = 0, stream_id: int = 0,
    ) -> np.ndarray:
        size_bytes = gpu_buffer.size_bytes
        start_time = time.perf_counter()
        pinned_buf = self._pool.allocate(size_bytes, MemoryType.CPU_PINNED, device_id)
        try:
            import pycuda.driver as cuda
            stream = self._get_stream(device_id, stream_id)
            cuda.memcpy_dtoh_async(pinned_buf.pointer, gpu_buffer.pointer, size_bytes, stream)
            stream.synchronize()
            result = np.frombuffer(
                (ctypes.c_byte * size_bytes).from_address(pinned_buf.pointer),
                dtype=dtype,
            ).reshape(output_shape).copy()
        except ImportError:
            import pycuda.driver as cuda
            raw = np.empty(size_bytes, dtype=np.uint8)
            cuda.memcpy_dtoh(raw, gpu_buffer.pointer)
            result = raw.view(dtype).reshape(output_shape).copy()
        finally:
            self._pool.release(pinned_buf)

        elapsed = (time.perf_counter() - start_time) * 1000
        self._transfer_profiles.append(TransferProfile(
            direction="D2H", size_bytes=size_bytes,
            bandwidth_gbps=(size_bytes / (1024**3)) / (elapsed / 1000) if elapsed > 0 else 0,
            latency_ms=elapsed, mode=self._default_mode, is_pinned=True, device_id=device_id,
        ))
        return result

    def _get_stream(self, device_id, stream_id):
        import pycuda.driver as cuda
        key = (device_id, stream_id)
        if key not in self._transfer_streams:
            ctx = cuda.Device(device_id).make_context()
            self._transfer_streams[key] = cuda.Stream()
            ctx.pop()
        return self._transfer_streams[key]

    def get_transfer_stats(self) -> list[dict]:
        return [
            {
                "direction": p.direction, "size_mb": p.size_bytes / (1024 * 1024),
                "bandwidth_gbps": round(p.bandwidth_gbps, 2),
                "latency_ms": round(p.latency_ms, 3),
                "pinned": p.is_pinned, "device": p.device_id,
            }
            for p in self._transfer_profiles[-100:]
        ]
```

## 1.4 GPU Texture Pipeline

### 1.4.1 GPU Context ve Buffer Yonetimi

```python
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class GPUDevice:
    device_id: int
    name: str
    compute_capability: tuple[int, int]
    total_memory_mb: float
    free_memory_mb: float
    multiprocessor_count: int
    clock_rate_mhz: float
    supports_nvenc: bool = False
    supports_nvdec: bool = False
    supports_cuda: bool = True
    utilization_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_usage_watts: float = 0.0

    @property
    def memory_utilization(self) -> float:
        if self.total_memory_mb == 0:
            return 0.0
        return 1.0 - (self.free_memory_mb / self.total_memory_mb)


@dataclass
class GPUBuffer:
    buffer_id: str
    device_id: int
    width: int
    height: int
    channels: int = 3
    dtype: str = "uint8"
    memory_type: MemoryType = MemoryType.GPU_GLOBAL
    pointer: Optional[int] = None
    pitch: int = 0
    allocated: bool = False
    frame_number: int = -1
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)

    @property
    def size_bytes(self) -> int:
        return self.width * self.height * self.channels * np.dtype(self.dtype).itemsize

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)

    @property
    def shape(self) -> tuple[int, int, int]:
        return (self.height, self.width, self.channels)

    @property
    def age_seconds(self) -> float:
        return time.time() - self.created_at


class GPUContext:
    """
    GPU baglami yoneticisi.
    Her GPU device icin ayri context yonetir, bellek tahsisini koordine eder.
    """

    def __init__(
        self,
        device_ids: Optional[list[int]] = None,
        max_memory_per_device_mb: float = 4096,
    ):
        self._device_ids = device_ids or self._detect_devices()
        self._max_memory = max_memory_per_device_mb * 1024 * 1024
        self._contexts: dict[int, object] = {}
        self._streams: dict[tuple[int, int], object] = {}
        self._lock = threading.RLock()
        self._buffer_counter = 0
        self._memory_pools: dict[int, MemoryPool] = {}
        for dev_id in self._device_ids:
            self._memory_pools[dev_id] = MemoryPool(
                max_gpu_memory_mb=max_memory_per_device_mb,
                max_pinned_memory_mb=max_memory_per_device_mb / 4,
            )
        self._initialize_devices()

    def _detect_devices(self) -> list[int]:
        try:
            import pycuda.driver as cuda
            cuda.init()
            return list(range(cuda.Device.count()))
        except (ImportError, Exception) as e:
            logger.warning(f"GPU tespit edilemedi: {e}")
            return []

    def _initialize_devices(self) -> None:
        try:
            import pycuda.driver as cuda
            for dev_id in self._device_ids:
                device = cuda.Device(dev_id)
                ctx = device.make_context()
                self._contexts[dev_id] = ctx
                logger.info(f"GPU {dev_id} baslatildi: {device.name()}")
                ctx.pop()
        except ImportError:
            logger.error("PyCUDA yuklenemedi, GPU destegi devre disi")

    def get_device_info(self, device_id: int) -> GPUDevice:
        try:
            import pycuda.driver as cuda
            device = cuda.Device(device_id)
            attrs = device.get_attributes()
            cc = device.compute_capability()
            return GPUDevice(
                device_id=device_id, name=device.name(),
                compute_capability=cc,
                total_memory_mb=device.total_memory() / (1024 * 1024),
                free_memory_mb=device.get_memory_info().free / (1024 * 1024),
                multiprocessor_count=attrs.get(cuda.device_attribute.MULTIPROCESSOR_COUNT, 0),
                clock_rate_mhz=attrs.get(cuda.device_attribute.CLOCK_RATE, 0) / 1000,
                supports_nvenc=cc[0] >= 5, supports_nvdec=cc[0] >= 5,
            )
        except ImportError:
            return GPUDevice(device_id=device_id, name="Unknown", compute_capability=(0, 0),
                total_memory_mb=0, free_memory_mb=0, multiprocessor_count=0, clock_rate_mhz=0)

    def allocate_buffer(
        self, width: int, height: int, channels: int = 3,
        dtype: str = "uint8", device_id: Optional[int] = None,
    ) -> GPUBuffer:
        if device_id is None:
            device_id = self._select_best_device()
        size = width * height * channels * np.dtype(dtype).itemsize
        with self._lock:
            self._buffer_counter += 1
            buffer_id = f"buf_{device_id}_{self._buffer_counter}"
            pool = self._memory_pools[device_id]
            block = pool.allocate(size_bytes=size, memory_type=MemoryType.GPU_GLOBAL, device_id=device_id)
            return GPUBuffer(
                buffer_id=buffer_id, device_id=device_id, width=width, height=height,
                channels=channels, dtype=dtype, pointer=block.pointer, allocated=True,
            )

    def free_buffer(self, buffer: GPUBuffer) -> None:
        with self._lock:
            pool = self._memory_pools[buffer.device_id]
            block = MemoryBlock(memory_type=MemoryType.GPU_GLOBAL, size_bytes=buffer.size_bytes,
                pointer=buffer.pointer, device_id=buffer.device_id)
            pool.release(block)
            buffer.allocated = False

    def _select_best_device(self, required_memory_mb: float = 0) -> int:
        best_id = self._device_ids[0] if self._device_ids else 0
        best_free = 0
        for dev_id in self._device_ids:
            try:
                import pycuda.driver as cuda
                device = cuda.Device(dev_id)
                free = device.get_memory_info().free
                if free > best_free and free > required_memory_mb * 1024 * 1024:
                    best_free = free
                    best_id = dev_id
            except Exception:
                continue
        return best_id

    def shutdown(self) -> None:
        with self._lock:
            for ctx in self._contexts.values():
                ctx.push()
                try:
                    ctx.pop()
                except Exception:
                    pass
            self._contexts.clear()
            self._streams.clear()
```

## 1.5 GPU Filtre Zinciri

```python
from __future__ import annotations

import numpy as np
from dataclasses import dataclass
from enum import Enum, auto


class GPUFilterType(Enum):
    SCALE = auto()
    CROP = auto()
    COLOR_CONVERT = auto()
    RESIZE = auto()
    BLUR = auto()
    SHARPEN = auto()
    DENOISE = auto()
    BRIGHTNESS = auto()
    CONTRAST = auto()


@dataclass
class GPUFilterParams:
    filter_type: GPUFilterType
    src_width: int
    src_height: int
    dst_width: int = 0
    dst_height: int = 0
    crop_x: int = 0
    crop_y: int = 0
    crop_w: int = 0
    crop_h: int = 0
    scale_factor: float = 1.0
    color_space: str = "BT.709"
    pixel_format: str = "RGB"
    interpolation: str = "bicubic"
    strength: float = 1.0
    kernel_size: int = 3
    sigma: float = 1.0

    @property
    def is_passthrough(self) -> bool:
        return (self.dst_width == self.src_width and
                self.dst_height == self.src_height and
                self.filter_type in (GPUFilterType.BRIGHTNESS, GPUFilterType.CONTRAST))


class GPUFilterChain:
    """
    GPU uzerinde zincirleme filtre uygulama motoru.
    Filtreleri optimal sirayla siralar, gereksiz intermediate buffer'lari kaldirir.
    """

    def __init__(self, gpu_context: GPUContext):
        self._ctx = gpu_context
        self._filters: list[GPUFilterParams] = []
        self._compiled_kernels: dict[str, object] = {}

    def add_filter(self, params: GPUFilterParams) -> GPUFilterChain:
        self._filters.append(params)
        return self

    def add_scale(self, src_w, src_h, dst_w, dst_h, interpolation="bicubic") -> GPUFilterChain:
        return self.add_filter(GPUFilterParams(
            filter_type=GPUFilterType.SCALE, src_width=src_w, src_height=src_h,
            dst_width=dst_w, dst_height=dst_h, interpolation=interpolation))

    def add_crop(self, width, height, x, y, crop_w, crop_h) -> GPUFilterChain:
        return self.add_filter(GPUFilterParams(
            filter_type=GPUFilterType.CROP, src_width=width, src_height=height,
            dst_width=crop_w, dst_height=crop_h, crop_x=x, crop_y=y,
            crop_w=crop_w, crop_h=crop_h))

    def add_color_convert(self, width, height, src_format="NV12", dst_format="RGB") -> GPUFilterChain:
        return self.add_filter(GPUFilterParams(
            filter_type=GPUFilterType.COLOR_CONVERT, src_width=width, src_height=height,
            dst_width=width, dst_height=height, pixel_format=f"{src_format}_to_{dst_format}"))

    def optimize(self) -> list[GPUFilterParams]:
        optimized = [f for f in self._filters if not f.is_passthrough]
        optimized = self._merge_adjacent_scales(optimized)
        optimized = self._merge_crop_scale(optimized)
        return optimized

    def _merge_adjacent_scales(self, filters):
        if not filters:
            return filters
        result = []
        i = 0
        while i < len(filters):
            current = filters[i]
            if current.filter_type == GPUFilterType.SCALE:
                while i + 1 < len(filters) and filters[i + 1].filter_type == GPUFilterType.SCALE:
                    nxt = filters[i + 1]
                    current = GPUFilterParams(
                        filter_type=GPUFilterType.SCALE, src_width=current.src_width,
                        src_height=current.src_height, dst_width=nxt.dst_width,
                        dst_height=nxt.dst_height, interpolation=nxt.interpolation)
                    i += 1
            result.append(current)
            i += 1
        return result

    def _merge_crop_scale(self, filters):
        if not filters:
            return filters
        result = []
        i = 0
        while i < len(filters):
            current = filters[i]
            if (current.filter_type == GPUFilterType.CROP and i + 1 < len(filters) and
                    filters[i + 1].filter_type == GPUFilterType.SCALE):
                nxt = filters[i + 1]
                result.append(GPUFilterParams(
                    filter_type=GPUFilterType.SCALE, src_width=current.src_width,
                    src_height=current.src_height, dst_width=nxt.dst_width,
                    dst_height=nxt.dst_height, crop_x=current.crop_x,
                    crop_y=current.crop_y, crop_w=current.crop_w, crop_h=current.crop_h))
                i += 2
            else:
                result.append(current)
                i += 1
        return result

    def execute(self, input_buffer: GPUBuffer, device_id: int = 0) -> GPUBuffer:
        import pycuda.driver as cuda
        import pycuda.autoinit
        optimized = self.optimize()
        current = input_buffer
        for fp in optimized:
            out = self._ctx.allocate_buffer(fp.dst_width, fp.dst_height, current.channels, device_id=device_id)
            self._apply_filter(current, out, fp)
            if current is not input_buffer:
                self._ctx.free_buffer(current)
            current = out
        return current

    def _apply_filter(self, inp, out, params):
        dispatch = {
            GPUFilterType.SCALE: self._gpu_scale,
            GPUFilterType.CROP: self._gpu_crop,
            GPUFilterType.COLOR_CONVERT: self._gpu_color_convert,
            GPUFilterType.BLUR: self._gpu_blur,
            GPUFilterType.SHARPEN: self._gpu_sharpen,
        }
        handler = dispatch.get(params.filter_type)
        if handler:
            handler(inp, out, params)

    def _gpu_scale(self, inp, out, p):
        kernel = self._get_or_compile_kernel("scale_bicubic")
        grid = ((out.width + 15) // 16, (out.height + 15) // 16)
        kernel.prepared_async_call(grid, (16, 16, 1), 0,
            inp.pointer, out.pointer, inp.width, inp.height, out.width, out.height, p.scale_factor)

    def _gpu_crop(self, inp, out, p):
        kernel = self._get_or_compile_kernel("crop")
        grid = ((out.width + 15) // 16, (out.height + 15) // 16)
        kernel.prepared_async_call(grid, (16, 16, 1), 0,
            inp.pointer, out.pointer, inp.width, inp.height, p.crop_x, p.crop_y, p.crop_w, p.crop_h)

    def _gpu_color_convert(self, inp, out, p):
        kernel = self._get_or_compile_kernel("nv12_to_rgb")
        grid = ((out.width + 15) // 16, (out.height + 15) // 16)
        kernel.prepared_async_call(grid, (16, 16, 1), 0, inp.pointer, out.pointer, inp.width, inp.height)

    def _gpu_blur(self, inp, out, p):
        kernel = self._get_or_compile_kernel("gaussian_blur")
        grid = ((out.width + 15) // 16, (out.height + 15) // 16)
        kernel.prepared_async_call(grid, (16, 16, 1), 0,
            inp.pointer, out.pointer, inp.width, inp.height, p.kernel_size, p.sigma)

    def _gpu_sharpen(self, inp, out, p):
        kernel = self._get_or_compile_kernel("unsharp_mask")
        grid = ((out.width + 15) // 16, (out.height + 15) // 16)
        kernel.prepared_async_call(grid, (16, 16, 1), 0,
            inp.pointer, out.pointer, inp.width, inp.height, p.strength)

    def _get_or_compile_kernel(self, name):
        if name not in self._compiled_kernels:
            self._compiled_kernels[name] = self._compile_kernel(name)
        return self._compiled_kernels[name]

    def _compile_kernel(self, kernel_name):
        from pycuda.compiler import SourceModule
        sources = {
            "scale_bicubic": """
                __global__ void scale_bicubic(unsigned char* src, unsigned char* dst,
                    int src_w, int src_h, int dst_w, int dst_h, float scale) {
                    int x = blockIdx.x * blockDim.x + threadIdx.x;
                    int y = blockIdx.y * blockDim.y + threadIdx.y;
                    if (x >= dst_w || y >= dst_h) return;
                    float src_x = x / scale; float src_y = y / scale;
                    int sx = min((int)src_x, src_w - 1);
                    int sy = min((int)src_y, src_h - 1);
                    for (int c = 0; c < 3; c++)
                        dst[(y * dst_w + x) * 3 + c] = src[(sy * src_w + sx) * 3 + c];
                }""",
            "crop": """
                __global__ void crop(unsigned char* src, unsigned char* dst,
                    int src_w, int src_h, int crop_x, int crop_y, int crop_w, int crop_h) {
                    int x = blockIdx.x * blockDim.x + threadIdx.x;
                    int y = blockIdx.y * blockDim.y + threadIdx.y;
                    if (x >= crop_w || y >= crop_h) return;
                    int sx = crop_x + x; int sy = crop_y + y;
                    if (sx >= src_w || sy >= src_h) return;
                    for (int c = 0; c < 3; c++)
                        dst[(y * crop_w + x) * 3 + c] = src[(sy * src_w + sx) * 3 + c];
                }""",
            "nv12_to_rgb": """
                __global__ void nv12_to_rgb(unsigned char* nv12, unsigned char* rgb, int w, int h) {
                    int x = blockIdx.x * blockDim.x + threadIdx.x;
                    int y = blockIdx.y * blockDim.y + threadIdx.y;
                    if (x >= w || y >= h) return;
                    int yv = nv12[y * w + x];
                    int uv = (y / 2) * w + (x / 2) * 2;
                    int u = nv12[w * h + uv] - 128;
                    int v = nv12[w * h + uv + 1] - 128;
                    int r = yv + (int)(1.402 * v);
                    int g = yv - (int)(0.344 * u) - (int)(0.714 * v);
                    int b = yv + (int)(1.772 * u);
                    int i = (y * w + x) * 3;
                    rgb[i] = max(0, min(255, r));
                    rgb[i+1] = max(0, min(255, g));
                    rgb[i+2] = max(0, min(255, b));
                }""",
            "gaussian_blur": """
                __global__ void gaussian_blur(unsigned char* src, unsigned char* dst,
                    int width, int height, int ksize, float sigma) {
                    int x = blockIdx.x * blockDim.x + threadIdx.x;
                    int y = blockIdx.y * blockDim.y + threadIdx.y;
                    if (x >= width || y >= height) return;
                    int half = ksize / 2;
                    float sr = 0, sg = 0, sb = 0, ws = 0;
                    for (int dy = -half; dy <= half; dy++) {
                        for (int dx = -half; dx <= half; dx++) {
                            int sx = min(max(x+dx,0), width-1);
                            int sy = min(max(y+dy,0), height-1);
                            float w = expf(-(dx*dx+dy*dy)/(2*sigma*sigma));
                            int idx = (sy*width+sx)*3;
                            sr += src[idx]*w; sg += src[idx+1]*w; sb += src[idx+2]*w; ws += w;
                        }
                    }
                    int o = (y*width+x)*3;
                    dst[o] = (unsigned char)(sr/ws);
                    dst[o+1] = (unsigned char)(sg/ws);
                    dst[o+2] = (unsigned char)(sb/ws);
                }""",
            "unsharp_mask": """
                __global__ void unsharp_mask(unsigned char* src, unsigned char* dst,
                    int width, int height, float strength) {
                    int x = blockIdx.x * blockDim.x + threadIdx.x;
                    int y = blockIdx.y * blockDim.y + threadIdx.y;
                    if (x >= width || y >= height) return;
                    int idx = (y*width+x)*3;
                    for (int c = 0; c < 3; c++) {
                        float center = src[idx+c]; float blur_val = 0; int cnt = 0;
                        for (int dy = -1; dy <= 1; dy++)
                            for (int dx = -1; dx <= 1; dx++) {
                                int sx = min(max(x+dx,0),width-1);
                                int sy = min(max(y+dy,0),height-1);
                                blur_val += src[(sy*width+sx)*3+c]; cnt++;
                            }
                        blur_val /= cnt;
                        float sharp = center + strength * (center - blur_val);
                        dst[idx+c] = (unsigned char)max(0.0f, min(255.0f, sharp));
                    }
                }""",
        }
        mod = SourceModule(sources[kernel_name])
        return mod.get_function(kernel_name)
```

## 1.6 Multi-GPU Destegi

### 1.6.1 Load Balancing Stratejisi

```python
import time
from dataclasses import dataclass, field
from enum import Enum, auto


class LoadBalancingStrategy(Enum):
    ROUND_ROBIN = auto()
    LEAST_LOADED = auto()
    MEMORY_AWARE = auto()
    GPU_AFFINITY = auto()


@dataclass
class GPUWorkload:
    device_id: int
    active_jobs: int = 0
    queued_jobs: int = 0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    utilization_percent: float = 0.0
    avg_frame_time_ms: float = 0.0
    last_updated: float = field(default_factory=time.time)

    @property
    def memory_free_mb(self) -> float:
        return self.memory_total_mb - self.memory_used_mb

    @property
    def load_score(self) -> float:
        """0.0 (bosta) - 1.0 (tam yuklu) arasi yuk skoru."""
        mem_score = self.memory_used_mb / max(self.memory_total_mb, 1)
        job_score = min(self.active_jobs / 8.0, 1.0)
        util_score = self.utilization_percent / 100.0
        return 0.4 * mem_score + 0.3 * job_score + 0.3 * util_score


class MultiGPUBalancer:
    """
    Multi-GPU is dagitimi ve yuk dengeleme.
    Mevcut GPU durumlarini izler, en uygun GPU'yu secer.
    """

    def __init__(
        self, gpu_context: GPUContext,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.LEAST_LOADED,
    ):
        self._ctx = gpu_context
        self._strategy = strategy
        self._workloads: dict[int, GPUWorkload] = {}
        self._round_robin_index = 0
        for dev_id in gpu_context._device_ids:
            info = gpu_context.get_device_info(dev_id)
            self._workloads[dev_id] = GPUWorkload(
                device_id=dev_id, memory_total_mb=info.total_memory_mb)

    def select_gpu(self, required_memory_mb: float = 0) -> int:
        dispatch = {
            LoadBalancingStrategy.ROUND_ROBIN: self._select_round_robin,
            LoadBalancingStrategy.LEAST_LOADED: self._select_least_loaded,
            LoadBalancingStrategy.MEMORY_AWARE: self._select_memory_aware,
            LoadBalancingStrategy.GPU_AFFINITY: self._select_by_affinity,
        }
        return dispatch[self._strategy](required_memory_mb)

    def _select_round_robin(self, _=0) -> int:
        ids = list(self._workloads.keys())
        dev_id = ids[self._round_robin_index % len(ids)]
        self._round_robin_index += 1
        return dev_id

    def _select_least_loaded(self, required_mb=0) -> int:
        best_id = min(self._workloads.keys(), key=lambda d: self._workloads[d].load_score)
        if required_mb > 0 and self._workloads[best_id].memory_free_mb < required_mb:
            for did, wl in sorted(self._workloads.items(), key=lambda x: x[1].memory_free_mb, reverse=True):
                if wl.memory_free_mb >= required_mb:
                    return did
        return best_id

    def _select_memory_aware(self, required_mb=0) -> int:
        candidates = [(d, w) for d, w in self._workloads.items() if w.memory_free_mb >= required_mb]
        if not candidates:
            return min(self._workloads.keys(), key=lambda d: self._workloads[d].load_score)
        return min(candidates, key=lambda x: x[1].load_score)[0]

    def _select_by_affinity(self, _=0) -> int:
        for did, wl in self._workloads.items():
            info = self._ctx.get_device_info(did)
            if info.supports_nvenc and wl.load_score < 0.7:
                return did
        return self._select_least_loaded()

    def update_workload(self, device_id: int, **kwargs):
        if device_id in self._workloads:
            for k, v in kwargs.items():
                if hasattr(self._workloads[device_id], k):
                    setattr(self._workloads[device_id], k, v)
            self._workloads[device_id].last_updated = time.time()

    def get_all_workloads(self) -> dict[int, dict]:
        return {
            did: {"device_id": wl.device_id, "active_jobs": wl.active_jobs,
                  "memory_free_mb": round(wl.memory_free_mb, 1),
                  "load_score": round(wl.load_score, 3)}
            for did, wl in self._workloads.items()
        }
```

## 1.7 GPU Fallback Mekanizmasi

```python
import time
from dataclasses import dataclass
from typing import Callable, Any


@dataclass
class FallbackResult:
    success: bool
    result: Any = None
    used_gpu: bool = True
    error_message: str = ""
    processing_time_ms: float = 0.0


class GPUFallbackManager:
    """
    GPU basarisiz oldugunda otomatik CPU fallback.
    Her GPU islemi icin bir CPU karsiligi tanimlanir.
    """

    def __init__(self, gpu_context: Optional[GPUContext] = None):
        self._ctx = gpu_context
        self._gpu_registry: dict[str, Callable] = {}
        self._cpu_registry: dict[str, Callable] = {}
        self._consecutive_failures: dict[int, int] = {}
        self._max_failures = 3

    def register_operation(self, name, gpu_func=None, cpu_func=None):
        if gpu_func:
            self._gpu_registry[name] = gpu_func
        if cpu_func:
            self._cpu_registry[name] = cpu_func

    def execute(self, operation_name: str, device_id: int = 0, **kwargs) -> FallbackResult:
        start = time.perf_counter()
        failures = self._consecutive_failures.get(device_id, 0)
        if failures >= self._max_failures:
            return self._execute_cpu(operation_name, start, **kwargs)

        if operation_name in self._gpu_registry and self._ctx:
            try:
                result = self._gpu_registry[operation_name](device_id=device_id, **kwargs)
                self._consecutive_failures[device_id] = 0
                elapsed = (time.perf_counter() - start) * 1000
                return FallbackResult(success=True, result=result, used_gpu=True, processing_time_ms=elapsed)
            except Exception as e:
                self._consecutive_failures[device_id] = failures + 1
                logger.error(f"GPU hatasi ({operation_name}): {e}")

        return self._execute_cpu(operation_name, start, **kwargs)

    def _execute_cpu(self, name, start, **kwargs):
        if name not in self._cpu_registry:
            return FallbackResult(success=False, error_message=f"CPU fallback tanimli degil: {name}")
        try:
            result = self._cpu_registry[name](**kwargs)
            elapsed = (time.perf_counter() - start) * 1000
            return FallbackResult(success=True, result=result, used_gpu=False, processing_time_ms=elapsed)
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return FallbackResult(success=False, used_gpu=False, error_message=str(e), processing_time_ms=elapsed)
```

## 1.8 Performans Darboğazlari ve Cozumleri

| Darboz | Belirti | Cozum |
|--------|---------|-------|
| PCIe Bandwidth darboz | GPU upload/download suresi yuksek | Pinned memory + async streams, bulk transfer |
| GPU Bellek fragmentasyonu | allocation basarisiz, OOM | Memory pool + bucket allocation |
| Kernel launch overhead | Kucuk batch'larda GPU yavas | Kernel batching, occupancy optimization |
| CPU-GPU senkronizasyon | GPU idle bekleme | Double buffering, pipeline overlap |
| Texture alignment | Unaligned pitch erisimi yavas | 512-byte pitch alignment |
| GPU context switching | Multi-job'da overhead | Per-thread context, CUDA MPS |
| Filtre zinciri overhead | Gereksiz intermediate buffer | Filtre birlestirme optimizasyonu |

**Double Buffering Stratejisi:**

```
Kare 0: [Upload-GPU0] [Process-GPU0] [Download]
Kare 1:              [Upload-GPU1] [Process-GPU1] [Download]
Kare 2:                           [Upload-GPU0] [Process-GPU0] [Download]
              ^ Overlap: GPU islerken CPU bir sonraki kareyi hazirlar
```

## 1.9 Entegrasyon Noktalari

```
FastAPI Endpoint
    |
    +-- POST /api/v1/jobs/gpu-process
    |       -> GPUJobRequest: {input_url, filters, output_format}
    |       -> PipelineOrchestrator.process()
    |
    +-- GET /api/v1/gpu/status
    |       -> MultiGPUBalancer.get_all_workloads()
    |
    +-- GET /api/v1/gpu/memory-stats
    |       -> MemoryPool.stats
    |
    +-- POST /api/v1/gpu/transfer-profile
            -> TransferScheduler.get_transfer_stats()
```

---

# 2. FFmpeg Filter Graph Mimarisi

## 2.1 Amaç

FFmpeg filter graph, video ve audio akislarinin kaynak (source) hedef (sink) arasinda filtreler uzerinden yonlendirildigi bir graph-based isleme modelidir. Bu mimari, karmaşık filtreleme senaryolarini (ornegin ayni kareden birden fazla ciktil olusturma, coklu kaynagi birlestirme) destekler.

**Neden Filter Graph?**
- GPU filtreleri (bolum 1) tek bir girdi-cikti hattinda calisirken, filter graph coklu kaynak/hedef destekler
- FFmpeg'in kendi GPU hizlandirma (hwupload/hwdownload) filtreleri ile entegrasyon saglar
- Dinamik filtre ekleme/cikarma (hot-swap) mumkun kilar
- Kompleks senaryolar: ses video senkronizasyon, alt yazi ekleme, coklu kamera secimi

## 2.2 Mimari Tasarim

```
Giris Kaynaklari              Filtreler                Cikis Hedefleri
+--------------+          +-----------------+         +--------------+
| File Source   |-------> | Scale (1920x1080)|-------> | File Sink     |
| (decode)      |         +-----------------+         | (encode)      |
+--------------+          | Crop (100,50)   |         +--------------+
                          +-----------------+
+--------------+          | Color Convert   |         +--------------+
| RTMP Stream   |-------> | (NV12->YUV420)  |-------> | RTMP Sink     |
| (demux)      |         +-----------------+         | (encode)      |
+--------------+          | Text Overlay    |         +--------------+
                          +-----------------+
+--------------+          | Scale (1280x720)|
| Image Overlay |-------> +-----------------+-------> Null Sink
+--------------+
```

### Filter Graph Soz dizimi ornegini

```
# Karmaşık ornek: 2 kaynagi birlestir, filtrele, cikti olustur
ffmpeg -i input1.mp4 -i input2.mp4 -i logo.png \
  -filter_complex "
    [0:v]scale=1920:1080,format=yuv420p[v0];
    [1:v]scale=1920:1080,format=yuv420p[v1];
    [2:v]scale=200:60[logo];
    [v0][v1]hstack=inputs=2[combined];
    [combined][logo]overlay=10:10[out]
  " -map "[out]" -map 0:a output.mp4
```

## 2.3 Filter Graph Veri Yapilari

```python
from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class FilterType(Enum):
    VIDEO = auto()
    AUDIO = auto()
    SPLITTER = auto()
    JOINER = auto()
    SOURCE = auto()
    SINK = auto()


class LinkMediaType(Enum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
    DATA = "data"


@dataclass
class FilterOption:
    """Tek bir filtre parametresi."""
    key: str
    value: str

    def to_ffmpeg_string(self) -> str:
        return f"{self.key}={self.value}"


@dataclass
class FilterLink:
    """
    Iki filtre arasindaki baglanti.
    Bir filtre cikisi, diger filtre girisine baglanir.
    """
    source_filter: str       # Kaynak filtre adi
    source_output: int = 0   # Kaynak cikis indexi (label yoksa 0)
    source_label: str = ""   # Opsiyonel cikis etiketi (ornegin [v0])
    target_filter: str = ""  # Hedef filtre adi
    target_input: int = 0    # Hedef giris indexi
    target_label: str = ""   # Opsiyonel giris etiketi
    media_type: LinkMediaType = LinkMediaType.VIDEO

    @property
    def is_labeled(self) -> bool:
        return bool(self.source_label or self.target_label)


@dataclass
class FilterNode:
    """
    Filter graph icindeki tek bir filtre dugumu.
    Filtre adini, parametrelerini ve baglanti bilgilerini tutar.
    """
    name: str                    # Filtre adi (ornegin "scale", "crop")
    instance_id: str = ""        # Benzersiz ornek ID (ornegin "scale_0")
    filter_type: FilterType = FilterType.VIDEO
    options: list[FilterOption] = field(default_factory=list)
    input_links: list[FilterLink] = field(default_factory=list)
    output_links: list[FilterLink] = field(default_factory=list)
    enabled: bool = True

    @property
    def input_count(self) -> int:
        return len(self.input_links)

    @property
    def output_count(self) -> int:
        return len(self.output_links)

    def get_option(self, key: str) -> Optional[str]:
        for opt in self.options:
            if opt.key == key:
                return opt.value
        return None

    def set_option(self, key: str, value: str) -> None:
        for opt in self.options:
            if opt.key == key:
                opt.value = value
                return
        self.options.append(FilterOption(key=key, value=value))

    def to_ffmpeg_string(self) -> str:
        """FFmpeg filter soz dizimine cevir."""
        params = ",".join(opt.to_ffmpeg_string() for opt in self.options)
        if params:
            return f"{self.name}={params}"
        return self.name


class FilterGraph:
    """
    FFmpeg filter graph yapisini temsil eden sinif.

    Filtreleri ve baglantilarini yonetir, FFmpeg soz dizimi olusturur,
    graf dogrulamasi yapar ve optimizasyon uygular.

    Ornek kullanim:
        graph = FilterGraph()
        graph.add_filter("scale", width=1920, height=1080, instance_id="scale1")
        graph.add_filter("crop", x=100, y=50, w=800, h=600, instance_id="crop1")
        graph.link("scale1", "crop1")
        ffmpeg_str = graph.build()
    """

    def __init__(self):
        self._filters: dict[str, FilterNode] = {}
        self._links: list[FilterLink] = []
        self._input_labels: dict[str, str] = {}   # label -> kaynak (input index veya filtre adi)
        self._output_labels: dict[str, str] = {}   # label -> hedef
        self._label_counter = 0

    def add_filter(
        self,
        name: str,
        instance_id: Optional[str] = None,
        filter_type: FilterType = FilterType.VIDEO,
        **options,
    ) -> FilterGraph:
        """
        Filter graph'a filtre ekle.

        Args:
            name: FFmpeg filtre adi (ornegin "scale", "crop", "overlay")
            instance_id: Benzersiz ornek ID (otomatik olusturulur)
            filter_type: Filtre turu (VIDEO, AUDIO, vb.)
            **options: Filtre parametreleri

        Returns:
            Self (builder pattern icin)
        """
        if instance_id is None:
            instance_id = f"{name}_{len(self._filters)}"

        node = FilterNode(
            name=name, instance_id=instance_id, filter_type=filter_type,
            options=[FilterOption(key=k, value=str(v)) for k, v in options.items()],
        )
        self._filters[instance_id] = node
        return self

    def link(
        self,
        source_id: str,
        target_id: str,
        source_output: int = 0,
        target_input: int = 0,
        source_label: str = "",
        target_label: str = "",
    ) -> FilterGraph:
        """
        Iki filtre arasinda baglanti olustur.

        Args:
            source_id: Kaynak filtre instance_id
            target_id: Hedef filtre instance_id
            source_output: Kaynak cikis portu
            target_input: Hedef giris portu
            source_label: Opsiyonel cikis etiketi (ornegin "[v0]")
            target_label: Opsiyonel giris etiketi (ornegin "[v1]")

        Returns:
            Self (builder pattern icin)
        """
        if source_id not in self._filters:
            raise ValueError(f"Kaynak filtre bulunamadi: {source_id}")
        if target_id not in self._filters:
            raise ValueError(f"Hedef filtre bulunamadi: {target_id}")

        source_filter = self._filters[source_id]
        target_filter = self._filters[target_id]

        link = FilterLink(
            source_filter=source_id, source_output=source_output,
            source_label=source_label, target_filter=target_id,
            target_input=target_input, target_label=target_label,
            media_type=source_filter.filter_type == FilterType.AUDIO
                and LinkMediaType.AUDIO or LinkMediaType.VIDEO,
        )

        source_filter.output_links.append(link)
        target_filter.input_links.append(link)
        self._links.append(link)

        if source_label:
            self._input_labels[source_label] = source_id
        if target_label:
            self._output_labels[target_label] = target_id

        return self

    def create_label(self) -> str:
        """Yeni bir label olustur."""
        self._label_counter += 1
        return f"[_label{self._label_counter}]"

    def set_input(self, label: str, stream_index: int = 0) -> FilterGraph:
        """Harici giris atamasi yap."""
        self._input_labels[label] = f"input_{stream_index}"
        return self

    def set_output(self, label: str, stream_index: int = 0) -> FilterGraph:
        """Harici cikis atamasi yap."""
        self._output_labels[label] = f"output_{stream_index}"
        return self

    def validate(self) -> list[str]:
        """
        Filter graph'i dogrula.

        Kontroller:
        1. Her filtrenin gerekli sayida girisi var mi?
        2. Döngü (cycle) var mi?
        3. Bagimsiz dugum var mi?
        4. Baglanti turu eslesiyor mu?

        Returns:
            Hata mesajlari listesi (bos = gecerli)
        """
        errors = []

        # Her filtrenin giris sayisini kontrol et
        expected_inputs = {
            "overlay": 2, "hstack": 2, "vstack": 2, "concat": 2,
            "amix": 2, "amerge": 2, "join": 2,
        }
        for fid, node in self._filters.items():
            if node.name in expected_inputs:
                expected = expected_inputs[node.name]
                actual = len([l for l in self._links if l.target_filter == fid])
                if actual < expected:
                    errors.append(
                        f"Filtre '{fid}' ({node.name}) icin {expected} giris gerekli, "
                        f"{actual} giris mevcut"
                    )

        # Dongu kontrolu (basit DFS)
        visited = set()
        rec_stack = set()

        def _has_cycle(fid):
            visited.add(fid)
            rec_stack.add(fid)
            for link in self._links:
                if link.source_filter == fid:
                    nxt = link.target_filter
                    if nxt not in visited:
                        if _has_cycle(nxt):
                            return True
                    elif nxt in rec_stack:
                        errors.append(f"Dongu tespit edildi: {fid} -> {nxt}")
                        return True
            rec_stack.discard(fid)
            return False

        for fid in self._filters:
            if fid not in visited:
                _has_cycle(fid)

        # Bagimsiz dugum kontrolu
        connected = set()
        for link in self._links:
            connected.add(link.source_filter)
            connected.add(link.target_filter)
        orphans = set(self._filters.keys()) - connected
        if orphans and len(self._filters) > 1:
            errors.append(f"Bagimsiz filtreler: {orphans}")

        return errors

    def optimize(self) -> FilterGraph:
        """
        Filter graph'i optimize et.

        Optimizasyonlar:
        1. ArdIsIk ayni filtreleri birlestir
        2. Gereksiz format donusumlerini kaldir
        3. Scale + crop birlestirmesi
        """
        # ArdIsikalik tespiti: ayni filtre adi, arka arkaya
        to_remove = set()
        for link in self._links:
            src = self._filters.get(link.source_filter)
            tgt = self._filters.get(link.target_filter)
            if src and tgt and src.name == tgt.name:
                # Iki ayni filtre arka arkaya - birlestir
                if src.name in ("scale", "crop"):
                    logger.info(f"Birlestiriliyor: {src.instance_id} + {tgt.instance_id}")
                    to_remove.add(tgt.instance_id)

        for fid in to_remove:
            self._remove_filter(fid)

        return self

    def _remove_filter(self, filter_id: str) -> None:
        """Bir filtreyi graph'tan kaldir."""
        if filter_id not in self._filters:
            return
        # Ilgili linkleri kaldir
        self._links = [
            l for l in self._links
            if l.source_filter != filter_id and l.target_filter != filter_id
        ]
        del self._filters[filter_id]

    def build(self) -> str:
        """
        FFmpeg -filter_complex icin soz dizimi olustur.

        Ornegin cikti:
            "[0:v]scale=1920:1080[_s1];[_s1]crop=x=100:y=50:w=800:h=600[_c1];[_c1]format=yuv420p[_out]"

        Returns:
            FFmpeg filter_complex string
        """
        if not self._filters:
            return ""

        # Topolojik siralama (DAG)
        ordered = self._topological_sort()

        parts = []
        for fid in ordered:
            node = self._filters[fid]
            if not node.enabled:
                continue

            # Giris etiketleri
            input_labels = []
            for link in self._links:
                if link.target_filter == fid:
                    if link.source_label:
                        input_labels.append(f"[{link.source_label}]")
                    elif link.source_filter:
                        src_node = self._filters.get(link.source_filter)
                        if src_node:
                            # Kaynak filtre cikisi
                            input_labels.append(f"[_{link.source_filter}]")

            # Filtre ismi ve parametreler
            filter_str = node.to_ffmpeg_string()

            # Cikis etiketi
            output_label = ""
            if node.output_links:
                out_link = node.output_links[0]
                if out_link.source_label:
                    output_label = f"[{out_link.source_label}]"
                else:
                    output_label = f"[_{fid}]"

            # Birlesik ifade
            inputs = "".join(input_labels)
            outputs = output_label if output_label else ""
            if outputs:
                parts.append(f"{inputs}{filter_str}{outputs}")
            elif input_labels:
                parts.append(f"{inputs}{filter_str}")

        return ";".join(parts)

    def _topological_sort(self) -> list[str]:
        """Topolojik siralama (girisden cikisa dogru)."""
        in_degree = defaultdict(int)
        adj = defaultdict(list)

        for link in self._links:
            adj[link.source_filter].append(link.target_filter)
            in_degree[link.target_filter] += 1

        queue = [
            fid for fid in self._filters
            if in_degree[fid] == 0
        ]
        result = []
        while queue:
            fid = queue.pop(0)
            result.append(fid)
            for nxt in adj[fid]:
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        # Dongu varsa, kalan dugumleri ekle
        for fid in self._filters:
            if fid not in result:
                result.append(fid)

        return result

    def get_node(self, instance_id: str) -> Optional[FilterNode]:
        return self._filters.get(instance_id)

    def get_all_nodes(self) -> dict[str, FilterNode]:
        return dict(self._filters)

    def to_dict(self) -> dict:
        """Graph'i sozluk formatina cevir (serialization icin)."""
        return {
            "filters": {
                fid: {
                    "name": n.name, "type": n.filter_type.name,
                    "options": {o.key: o.value for o in n.options},
                    "enabled": n.enabled,
                }
                for fid, n in self._filters.items()
            },
            "links": [
                {
                    "source": l.source_filter, "target": l.target_filter,
                    "source_output": l.source_output, "target_input": l.target_input,
                    "source_label": l.source_label, "target_label": l.target_label,
                }
                for l in self._links
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> FilterGraph:
        """Sozlukdan FilterGraph olustur."""
        graph = cls()
        for fid, fdata in data.get("filters", {}).items():
            ftype = FilterType[fdata.get("type", "VIDEO")]
            opts = {k: v for k, v in fdata.get("options", {}).items()}
            graph.add_filter(fdata["name"], instance_id=fid, filter_type=ftype, **opts)
        for ldata in data.get("links", []):
            graph.link(
                ldata["source"], ldata["target"],
                source_output=ldata.get("source_output", 0),
                target_input=ldata.get("target_input", 0),
                source_label=ldata.get("source_label", ""),
                target_label=ldata.get("target_label", ""),
            )
        return graph
```

## 2.4 Filtre Turkleri ve Ornegin FFmpeg Karsilikalari

| Filtre Turu | FFmpeg Filtresi | Giris | Cikis | Parametreler |
|-------------|-----------------|-------|-------|-------------|
| Olcekleme   | `scale`         | 1     | 1     | width, height, flags |
| Kirtma      | `crop`          | 1     | 1     | x, y, w, h |
| Renk Donusumu | `format`     | 1     | 1     | pix_fmt |
| Hizalama    | `pad`           | 1     | 1     | width, height, x, y, color |
| Ustuste     | `overlay`       | 2     | 1     | x, y |
| Birlestirme | `concat`        | N     | 1     | n, v, a |
| Ayirma      | `split`         | 1     | N     | - |
| Yazi        | `drawtext`      | 1     | 1     | text, fontfile, fontsize, x, y |
| bulaniklastirma | `boxblur`  | 1     | 1     | luma_radius, luma_power |
| Hizlandirma | `scale_cuda`    | 1     | 1     | w, h, interp_algo |
| GPU Upload  | `hwupload`      | 1     | 1     | cuda_device, format |
| GPU Download | `hwdownload`   | 1     | 1     | - |

## 2.5 Ornek: Kick Klip Icin Filtre Graph Olusturma

```python
class KickClipFilterBuilder:
    """
    Kick canli yayin klipleri icin on tanimli filtre graph sablonlari olusturur.
    """

    @staticmethod
    def standard_recode(
        target_width: int = 1920,
        target_height: int = 1080,
        crop_region: Optional[tuple[int, int, int, int]] = None,
    ) -> FilterGraph:
        """
        Standart yeniden kodlama filtresi.
        Opsiyonel crop + scale + format donusumu.
        """
        graph = FilterGraph()

        if crop_region:
            x, y, w, h = crop_region
            graph.add_filter("crop", instance_id="crop1", x=x, y=y, w=w, h=h)

        graph.add_filter(
            "scale", instance_id="scale1",
            width=target_width, height=target_height,
            flags="lanczos+accurate_rnd",
        )
        graph.add_filter("format", instance_id="fmt1", pix_fmt="yuv420p")

        # Baglantilari kur
        prev = None
        for fid in ["crop1", "scale1", "fmt1"]:
            if graph.get_node(fid):
                if prev:
                    graph.link(prev, fid)
                prev = fid

        return graph

    @staticmethod
    def multi_output(
        resolutions: list[tuple[int, int]],
        crop_region: Optional[tuple[int, int, int, int]] = None,
    ) -> FilterGraph:
        """
        Coklu cikitli filtre graph.
        Ayni kaynaktan farkli cozunurluklerde ciktilar olusturur.
        """
        graph = FilterGraph()

        # Kaynak split
        graph.add_filter("split", instance_id="split1", n=len(resolutions))

        prev_split = "split1"
        for i, (w, h) in enumerate(resolutions):
            if crop_region:
                cx, cy, cw, ch = crop_region
                graph.add_filter("crop", instance_id=f"crop{i}", x=cx, y=cy, w=cw, h=ch)
                graph.link(prev_split, f"crop{i}", source_output=i)
                graph.add_filter("scale", instance_id=f"scale{i}", width=w, height=h, flags="lanczos")
                graph.link(f"crop{i}", f"scale{i}")
            else:
                graph.add_filter("scale", instance_id=f"scale{i}", width=w, height=h, flags="lanczos")
                graph.link(prev_split, f"scale{i}", source_output=i)

            graph.add_filter("format", instance_id=f"fmt{i}", pix_fmt="yuv420p")
            graph.link(f"scale{i}", f"fmt{i}")

        return graph

    @staticmethod
    def with_watermark(
        watermark_position: str = "top_right",
        watermark_opacity: float = 0.7,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> FilterGraph:
        """Filigran eklenmis filtre graph."""
        graph = FilterGraph()

        graph.add_filter("scale", instance_id="scale1", width=target_width, height=target_height, flags="lanczos")
        graph.add_filter("format", instance_id="fmt1", pix_fmt="yuv420p")

        # Filigran konum hesaplama
        pos_map = {
            "top_right": "main_w-overlay_w-10:10",
            "top_left": "10:10",
            "bottom_right": "main_w-overlay_w-10:main_h-overlay_h-10",
            "bottom_left": "10:main_h-overlay_h-10",
            "center": "(main_w-overlay_w)/2:(main_h-overlay_h)/2",
        }
        overlay_expr = pos_map.get(watermark_position, pos_map["top_right"])

        graph.add_filter("overlay", instance_id="overlay1", x=overlay_expr.split(":")[0], y=overlay_expr.split(":")[1])
        graph.link("fmt1", "overlay1", target_input=0)
        graph.set_input("[0:v]", 0)
        graph.set_input("[1:v]", 1)

        return graph
```

## 2.6 Hardware Upload/Download Filtreleri

GPU pipeline ile FFmpeg filter graph'i birlestiren kritik filtreler:

```
# CPU -> GPU transfer (FFmpeg icin)
[0:v]format=nv12,hwupload=cuda:0[hw_in]

# GPU uzerinde isleme
[hw_in]scale_cuda=1920:1080,crop_cuda=x=100:y=50:w=800:h=600[hw_processed]

# GPU -> CPU transfer
[hw_processed]hwdownload,format=nv12[cpu_out]
```

```python
class HWFilterGraphBuilder:
    """
    GPU hizlandirma iceren FFmpeg filter graph olusturucu.
    hwupload/hwdownload filtrelerini otomatik olarak yerlestirir.
    """

    def __init__(self, gpu_device: int = 0):
        self._gpu_device = gpu_device

    def build_gpu_pipeline(
        self,
        gpu_filters: list[dict],
        input_format: str = "nv12",
        output_format: str = "yuv420p",
    ) -> str:
        """
        GPU filtre iceren tam bir filter graph olustur.

        Args:
            gpu_filters: [{"name": "scale_cuda", "params": {"w": 1920, "h": 1080}}, ...]
            input_format: Giris piksel formati
            output_format: Cikis piksel formati

        Returns:
            FFmpeg filter_complex string
        """
        parts = []

        # 1. Format donusumu + GPU upload
        parts.append(
            f"format={input_format},"
            f"hwupload=cuda={self._gpu_device}"
            f"[hw_in]"
        )

        # 2. GPU filtrelerini uygula
        prev_label = "hw_in"
        for i, gf in enumerate(gpu_filters):
            name = gf["name"]
            params = gf.get("params", {})
            param_str = ":".join(f"{k}={v}" for k, v in params.items())
            out_label = f"hw_f{i}"
            parts.append(f"[{prev_label}]{name}={param_str}[{out_label}]")
            prev_label = out_label

        # 3. GPU download + format donusumu
        parts.append(
            f"[{prev_label}]hwdownload,"
            f"format={output_format}[out]"
        )

        return ";".join(parts)

    def build_hardware_encode_pipeline(
        self,
        codec: str = "h264_nvenc",
        preset: str = "p4",
        bitrate: str = "6M",
        gpu_filters: Optional[list[dict]] = None,
    ) -> str:
        """
        Tam hardware encode pipeline: decode -> GPU filtre -> HW encode.

        FFmpeg komutu ornegi:
        ffmpeg -hwaccel cuda -i input.mp4 \
          -filter_complex "...GPU filtreler..." \
          -c:v h264_nvenc -preset p4 -b:v 6M output.mp4
        """
        parts = []

        # GPU filtreler varsa uygula
        if gpu_filters:
            parts.append(f"format=nv12,hwupload=cuda={self._gpu_device}[hw_in]")
            prev = "hw_in"
            for i, gf in enumerate(gpu_filters):
                name = gf["name"]
                params = gf.get("params", {})
                param_str = ":".join(f"{k}={v}" for k, v in params.items())
                out = f"hw{i}"
                parts.append(f"[{prev}]{name}={param_str}[{out}]")
                prev = out
            # Son GPU filtresi encode'a gonder (hwdownload gerekmez, NVENC dogrudan GPU'dan okur)
            parts.append(f"[{prev}]hwdownload,format=nv12[enc_in]")
            filter_str = ";".join(parts)
        else:
            filter_str = "format=nv12"

        return filter_str
```

## 2.7 Filter Graph Dogrulama Algoritmasi

```python
class FilterGraphValidator:
    """
    Filter graph dogrulama motoru.
    Filtre uyumlulugu, baglanti tutarliligini ve kaynak gereksinimlerini kontrol eder.
    """

    # FFmpeg filtre max giris/cikis sayilari
    FILTER_IO = {
        "scale": (1, 1), "crop": (1, 1), "format": (1, 1),
        "pad": (1, 1), "overlay": (2, 1), "concat": (-1, 1),
        "split": (1, -1), "hstack": (2, 1), "vstack": (2, 1),
        "drawtext": (1, 1), "boxblur": (1, 1), "scale_cuda": (1, 1),
        "hwupload": (1, 1), "hwdownload": (1, 1), "crop_cuda": (1, 1),
    }

    def validate(self, graph: FilterGraph) -> list[str]:
        errors = []
        errors.extend(self._validate_io_counts(graph))
        errors.extend(self._validate_connectivity(graph))
        errors.extend(self._validate_format_chain(graph))
        return errors

    def _validate_io_counts(self, graph: FilterGraph) -> list[str]:
        errors = []
        for fid, node in graph.get_all_nodes().items():
            if node.name in self.FILTER_IO:
                min_in, max_in = self.FILTER_IO[node.name]
                if min_in > 0 and node.input_count < min_in:
                    errors.append(f"{fid} ({node.name}): minimum {min_in} giris gerekli, {node.input_count} mevcut")
                if max_in > 0 and node.input_count > max_in:
                    errors.append(f"{fid} ({node.name}): maksimum {max_in} giris izinli, {node.input_count} mevcut")
        return errors

    def _validate_connectivity(self, graph: FilterGraph) -> list[str]:
        errors = []
        orphans = []
        for fid in graph.get_all_nodes():
            node = graph.get_node(fid)
            if node and node.input_count == 0 and node.output_count == 0:
                orphans.append(fid)
        if orphans and len(graph.get_all_nodes()) > 1:
            errors.append(f"Bagimsiz dugumler: {orphans}")
        return errors

    def _validate_format_chain(self, graph: FilterGraph) -> list[str]:
        errors = []
        # GPU filtrelerin giris formatini kontrol et
        gpu_filters = {"scale_cuda", "crop_cuda", "hwupload", "hwdownload"}
        for fid, node in graph.get_all_nodes().items():
            if node.name in gpu_filters:
                # Onceki filtrenin cikis formatini kontrol et
                for link in graph._links:
                    if link.target_filter == fid:
                        prev = graph.get_node(link.source_filter)
                        if prev and prev.name not in gpu_filters and prev.name != "format":
                            errors.append(
                                f"Uyarsizlik: {prev.name} -> {node.name}. "
                                f"GPU filtresi icin hwupload veya format=nv12 gerekli."
                            )
        return errors
```

## 2.8 Dinamik Filter Graph Guncelleme (Hot-Swap)

```python
class DynamicFilterManager:
    """
    Calisan FFmpeg surecinde filter graph'i dinamik olarak guncelleme.
    Filtre ekleme, cikarma ve parametre degisikligi destegi.
    """

    def __init__(self, base_graph: FilterGraph):
        self._base_graph = base_graph
        self._pending_changes: list[dict] = []
        self._active_pipelines: dict[str, dict] = {}  # pipeline_id -> durum

    def add_filter_live(
        self, pipeline_id: str, filter_name: str, params: dict, position: int = -1,
    ) -> bool:
        """
        Calisan pipeline'a filtre ekle.
        Yeni filter graph olusturur ve FFmpeg surecini yeniden baslatir.
        """
        graph_copy = FilterGraph.from_dict(self._base_graph.to_dict())
        fid = f"{filter_name}_live_{len(graph_copy.get_all_nodes())}"
        graph_copy.add_filter(filter_name, instance_id=fid, **params)

        validation_errors = graph_copy.validate()
        if validation_errors:
            logger.error(f"Dogrulama hatasi: {validation_errors}")
            return False

        new_cmd = graph_copy.build()
        self._pending_changes.append({
            "pipeline_id": pipeline_id,
            "old_graph": self._base_graph.build(),
            "new_graph": new_cmd,
            "operation": "add_filter",
        })
        return True

    def remove_filter_live(self, pipeline_id: str, filter_id: str) -> bool:
        """Calisan pipeline'dan filtre kaldir."""
        graph_copy = FilterGraph.from_dict(self._base_graph.to_dict())
        graph_copy._remove_filter(filter_id)
        new_cmd = graph_copy.build()
        self._pending_changes.append({
            "pipeline_id": pipeline_id,
            "old_graph": self._base_graph.build(),
            "new_graph": new_cmd,
            "operation": "remove_filter",
        })
        return True

    def update_filter_params(
        self, pipeline_id: str, filter_id: str, params: dict,
    ) -> bool:
        """Filtre parametrelerini guncelle."""
        graph_copy = FilterGraph.from_dict(self._base_graph.to_dict())
        node = graph_copy.get_node(filter_id)
        if not node:
            return False
        for k, v in params.items():
            node.set_option(k, str(v))
        new_cmd = graph_copy.build()
        self._pending_changes.append({
            "pipeline_id": pipeline_id,
            "old_graph": self._base_graph.build(),
            "new_graph": new_cmd,
            "operation": "update_params",
        })
        return True

    def apply_changes(self, pipeline_id: str) -> Optional[str]:
        """Bekleyen degisiklikleri uygula ve yeni FFmpeg komutunu dondur."""
        for change in self._pending_changes:
            if change["pipeline_id"] == pipeline_id:
                self._pending_changes.remove(change)
                return change["new_graph"]
        return None
```

## 2.9 FFmpeg Komut Olusturma Ornekleri

```python
class FFmpegCommandBuilder:
    """
    FFmpeg komut satiri olusturucu.
    Filter graph, encoder, decoder ve diger secenekleri yonetir.
    """

    def __init__(self):
        self._input_args: list[str] = []
        self._output_args: list[str] = []
        self._filter_complex: str = ""
        self._maps: list[str] = []
        self._global_args: list[str] = ["-hide_banner", "-y"]

    def input(self, path: str, hwaccel: Optional[str] = None, **kwargs) -> FFmpegCommandBuilder:
        if hwaccel:
            self._input_args.extend(["-hwaccel", hwaccel])
            if hwaccel == "cuda":
                self._input_args.extend(["-hwaccel_output_format", "cuda"])
        for k, v in kwargs.items():
            self._input_args.extend([f"-{k}", str(v)])
        self._input_args.extend(["-i", path])
        return self

    def filter_complex(self, graph: FilterGraph) -> FFmpegCommandBuilder:
        self._filter_complex = graph.build()
        return self

    def filter_complex_string(self, fc: str) -> FFmpegCommandBuilder:
        self._filter_complex = fc
        return self

    def map(self, stream: str) -> FFmpegCommandBuilder:
        self._maps.extend(["-map", stream])
        return self

    def video_codec(self, codec: str) -> FFmpegCommandBuilder:
        self._output_args.extend(["-c:v", codec])
        return self

    def audio_codec(self, codec: str) -> FFmpegCommandBuilder:
        self._output_args.extend(["-c:a", codec])
        return self

    def preset(self, preset: str) -> FFmpegCommandBuilder:
        self._output_args.extend(["-preset", preset])
        return self

    def bitrate(self, rate: str) -> FFmpegCommandBuilder:
        self._output_args.extend(["-b:v", rate])
        return self

    def crf(self, value: int) -> FFmpegCommandBuilder:
        self._output_args.extend(["-crf", str(value)])
        return self

    def extra(self, *args) -> FFmpegCommandBuilder:
        self._output_args.extend(args)
        return self

    def output(self, path: str) -> list[str]:
        cmd = ["ffmpeg"] + self._global_args + self._input_args
        if self._filter_complex:
            cmd.extend(["-filter_complex", self._filter_complex])
        cmd.extend(self._maps)
        cmd.extend(self._output_args)
        cmd.append(path)
        return cmd

    def build_command_string(self, output_path: str) -> str:
        return " ".join(self.output(output_path))
```

---

# 3. Hardware Encoding

## 3.1 Amaç

Hardware encoding, video karelerinin GPU uzerindeki ozel encoding birimleri (ASIC) kullanilarak H.264/H.265/AV1 formatlarina donusturulmesini saglar. CPU tabanli software encoding'e kiyasla 5-20x hizlanma saglar, bu da canli yayin kliplerinin hizli bir sekilde uretilmesi icin kritiktir.

**NPU/Hardware Encoding Avantajlari:**
- Dusuk gecikme suresi (latency): ~5-10ms per frame
- Dusuk CPU kullanimi: %5-15 (CPU encoding'de %80-100)
- Enerji verimliligi: ~10x daha az watt/fps
- Paralel is destegi: Ayni GPU'da decode + encode + filtre

## 3.2 Hardware Encoder Platform Destekleri

### 3.2.1 NVIDIA NVENC

```
Codec Destekleri:
  H.264 (AVC)  : Baslangictan beri destek (Tesla M2090+)
  H.265 (HEVC) : Maxwell Gen 2+ (GTX 950+)
  AV1          : Ada Lovelace (RTX 40+)

Max Cozunurluk:
  H.264  : 4096x4096
  HEVC   : 8192x8192
  AV1    : 8192x8192

Max FPS (1080p):
  H.264  : 240 fps
  HEVC   : 120 fps
  AV1    : 60 fps (RTX 4090)
```

### 3.2.2 Intel Quick Sync (QSV)

```
Codec Destekleri:
  H.264 (AVC)  : Sandy Bridge+
  H.265 (HEVC) : Skylake+
  AV1          : Arc (Alchemist)+

Max Cozunurluk:
  H.264  : 4096x4096
  HEVC   : 8192x8192 (10-bit destekli)
  AV1    : 8192x8192
```

### 3.2.3 AMD AMF (Advanced Media Framework)

```
Codec Destekleri:
  H.264 (AVC)  : GCN 1.0+ (Radeon HD 7000+)
  H.265 (HEVC) : GCN 3.0+ (Radeon R9 285+)

Max Cozunurluk:
  H.264  : 4096x4096
  HEVC   : 4096x4096
```

### 3.2.4 Apple VideoToolbox

```
Codec Destekleri:
  H.264 (AVC)  : Tüm macOS / iOS
  H.265 (HEVC) : macOS 10.13+, A10+ chip
  ProRes       : M1+ (encode/decode)

Max Cozunurluk:
  H.264  : 4096x2160
  HEVC   : 8192x4320
  ProRes : 8192x4320
```

## 3.3 Encoder Kapasite Tespiti

```python
import subprocess
import json
import re
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


class HWEncoderType(Enum):
    NVENC = auto()
    QSV = auto()
    AMF = auto()
    VIDEOTOOLBOX = auto()
    SOFTWARE = auto()


class VideoCodec(Enum):
    H264 = "h264"
    HEVC = "hevc"
    AV1 = "av1"
    PRORES = "prores"


class EncodingPreset(Enum):
    # NVENC presets
    NVENC_P1 = "p1"       # En hizli, en dusuk kalite
    NVENC_P2 = "p2"       # Hizli
    NVENC_P3 = "p3"       # Dengeli
    NVENC_P4 = "p4"       # Daha yuksek kalite (varsayilan)
    NVENC_P5 = "p5"       # Yuksek kalite
    NVENC_P6 = "p6"       # Cok yuksek kalite
    NVENC_P7 = "p7"       # En yuksek kalite (yavas)

    # QSV presets
    QSV_SPEED = "speed"
    QSV_BALANCED = "balanced"
    QSV_QUALITY = "quality"

    # Genel presets
    ULTRAFAST = "ultrafast"
    SUPERFAST = "superfast"
    VERYFAST = "veryfast"
    FASTER = "faster"
    FAST = "fast"
    MEDIUM = "medium"
    SLOW = "slow"
    SLOWER = "slower"
    VERYSLOW = "veryslow"


class RateControlMode(Enum):
    CBR = "const_bitrate"      # Sabit bit hizi
    VBR = "variable_bitrate"   # Degisken bit hizi
    CQ = "const_quality"       # Sabit kalite (CRF/CQ)
    QVBR = "qvbr"              # Quality-graded VBR (AMF)


@dataclass
class EncoderCapability:
    """Bir hardware encoder'in kapasite bilgisi."""
    encoder_type: HWEncoderType
    codec: VideoCodec
    supported: bool
    max_width: int = 0
    max_height: int = 0
    max_fps: float = 0
    max_bitrate_mbps: float = 0
    max_slices: int = 0
    supports_bframes: bool = False
    supports_interlace: bool = False
    supports_10bit: bool = False
    supports_hdr: bool = False
    profiles: list[str] = field(default_factory=list)
    rate_control_modes: list[RateControlMode] = field(default_factory=list)
    gpu_device_id: int = 0

    @property
    def supports_4k(self) -> bool:
        return self.max_width >= 3840 and self.max_height >= 2160

    @property
    def supports_8k(self) -> bool:
        return self.max_width >= 7680 and self.max_height >= 4320


@dataclass
class HWEncoderConfig:
    """Hardware encoder konfigurasyonu."""
    encoder_type: HWEncoderType = HWEncoderType.NVENC
    codec: VideoCodec = VideoCodec.H264
    preset: EncodingPreset = EncodingPreset.NVENC_P4
    rate_control: RateControlMode = RateControlMode.CQ
    target_bitrate_kbps: int = 6000
    max_bitrate_kbps: int = 8000
    bufsize_kbps: int = 12000
    cq_level: int = 23              # CQ modunda kalite seviyesi (0-51, dusuk = iyi)
    keyframe_interval: int = 2      # saniye
    bframes: int = 3                # B-frame sayisi
    refs: int = 3                   # Referans frame sayisi
    slices: int = 1                 # Slice sayisi
    gpu_device_id: int = 0
    pixel_format: str = "yuv420p"
    profile: str = "high"           # H.264: baseline/main/high, HEVC: main/main10
    tune: str = "hq"                # hq, ll, ull, ls (NVENC)

    # Gelistirilmis parametreler
    spatial_aq: bool = True         # Spatial Adaptive Quantization
    temporal_aq: bool = True        # Temporal Adaptive Quantization
    weighted_pred: str = "auto"     # Weighted prediction
    rc_lookahead: int = 32          # Rate control lookahead (frame)

    def to_ffmpeg_args(self) -> list[str]:
        """FFmpeg encoder argumanlarina cevir."""
        args = []

        codec_map = {
            HWEncoderType.NVENC: {
                VideoCodec.H264: "h264_nvenc",
                VideoCodec.HEVC: "hevc_nvenc",
                VideoCodec.AV1: "av1_nvenc",
            },
            HWEncoderType.QSV: {
                VideoCodec.H264: "h264_qsv",
                VideoCodec.HEVC: "hevc_qsv",
                VideoCodec.AV1: "av1_qsv",
            },
            HWEncoderType.AMF: {
                VideoCodec.H264: "h264_amf",
                VideoCodec.HEVC: "hevc_amf",
            },
        }

        codec_str = codec_map.get(self.encoder_type, {}).get(self.codec, "libx264")
        args.extend(["-c:v", codec_str])

        # Preset
        if self.encoder_type == HWEncoderType.NVENC:
            args.extend(["-preset", self.preset.value])
        elif self.encoder_type == HWEncoderType.QSV:
            args.extend(["-preset", self.preset.value])

        # Rate control
        if self.rate_control == RateControlMode.CBR:
            args.extend(["-b:v", f"{self.target_bitrate_kbps}k"])
            args.extend(["-maxrate", f"{self.max_bitrate_kbps}k"])
            args.extend(["-bufsize", f"{self.bufsize_kbps}k"])
        elif self.rate_control == RateControlMode.VBR:
            args.extend(["-b:v", f"{self.target_bitrate_kbps}k"])
            args.extend(["-maxrate", f"{self.max_bitrate_kbps}k"])
        elif self.rate_control == RateControlMode.CQ:
            args.extend(["-cq", str(self.cq_level)])
            args.extend(["-b:v", f"{self.target_bitrate_kbps}k"])
            args.extend(["-maxrate", f"{self.max_bitrate_kbps}k"])

        # Keyframe
        args.extend(["-g", str(self.keyframe_interval * 30)])  # ~30fps varsayim
        args.extend(["-keyint_min", str(self.keyframe_interval * 30)])

        # B-frame
        if self.supports_bframes:
            args.extend(["-bf", str(self.bframes)])

        # Pixel format
        args.extend(["-pix_fmt", self.pixel_format])

        # Profile
        args.extend(["-profile:v", self.profile])

        # NVENC ozel parametreler
        if self.encoder_type == HWEncoderType.NVENC:
            if self.spatial_aq:
                args.extend(["-spatial-aq", "1"])
            if self.temporal_aq:
                args.extend(["-temporal-aq", "1"])
            args.extend(["-rc-lookahead", str(self.rc_lookahead)])
            args.extend(["-tune", self.tune])

        # GPU device
        if self.encoder_type == HWEncoderType.NVENC:
            args.extend(["-gpu", str(self.gpu_device_id)])

        return args

    @property
    def supports_bframes(self) -> bool:
        if self.encoder_type == HWEncoderType.NVENC:
            return self.codec in (VideoCodec.H264, VideoCodec.HEVC)
        return self.bframes > 0


class HWEncoderDetector:
    """
    Sistemdeki hardware encoder'lari tespit eder ve kapasitelerini ogrenir.
    FFmpeg -encoders ciktisini parse ederek calisir.
    """

    @staticmethod
    def detect_encoders() -> list[EncoderCapability]:
        """FFmpeg ile mevcut hardware encoder'lari tespit et."""
        encoders = []

        try:
            result = subprocess.run(
                ["ffmpeg", "-hide_banner", "-encoders"],
                capture_output=True, text=True, timeout=10,
            )
            output = result.stdout + result.stderr
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error(f"FFmpeg calistirilamadi: {e}")
            return encoders

        # NVENC tespiti
        nvenc_patterns = {
            "h264_nvenc": VideoCodec.H264,
            "hevc_nvenc": VideoCodec.HEVC,
            "av1_nvenc": VideoCodec.AV1,
        }
        for pattern, codec in nvenc_patterns.items():
            if pattern in output:
                enc = HWEncoderDetector._probe_nvenc(codec)
                if enc:
                    encoders.append(enc)

        # QSV tespiti
        qsv_patterns = {
            "h264_qsv": VideoCodec.H264,
            "hevc_qsv": VideoCodec.HEVC,
            "av1_qsv": VideoCodec.AV1,
        }
        for pattern, codec in qsv_patterns.items():
            if pattern in output:
                encoders.append(EncoderCapability(
                    encoder_type=HWEncoderType.QSV, codec=codec, supported=True,
                    max_width=4096, max_height=4096, max_fps=60,
                    max_bitrate_mbps=100,
                ))

        # AMF tespiti
        amf_patterns = {
            "h264_amf": VideoCodec.H264,
            "hevc_amf": VideoCodec.HEVC,
        }
        for pattern, codec in amf_patterns.items():
            if pattern in output:
                encoders.append(EncoderCapability(
                    encoder_type=HWEncoderType.AMF, codec=codec, supported=True,
                    max_width=4096, max_height=4096, max_fps=60,
                    max_bitrate_mbps=100,
                ))

        return encoders

    @staticmethod
    def _probe_nvenc(codec: VideoCodec) -> Optional[EncoderCapability]:
        """NVENC encoder kapasitesini test et."""
        codec_name = {
            VideoCodec.H264: "h264_nvenc",
            VideoCodec.HEVC: "hevc_nvenc",
            VideoCodec.AV1: "av1_nvenc",
        }.get(codec)
        if not codec_name:
            return None

        try:
            # Test encode ile kapasiteyi ogren
            test_cmd = [
                "ffmpeg", "-f", "lavfi", "-i",
                "testsrc=duration=1:size=3840x2160:rate=30",
                "-c:v", codec_name, "-f", "null", "-",
            ]
            result = subprocess.run(
                test_cmd, capture_output=True, text=True, timeout=15,
            )
            success = result.returncode == 0

            return EncoderCapability(
                encoder_type=HWEncoderType.NVENC, codec=codec,
                supported=success,
                max_width=8192 if success else 0,
                max_height=8192 if success else 0,
                max_fps=240 if success else 0,
                max_bitrate_mbps=500 if success else 0,
                supports_bframes=codec in (VideoCodec.H264, VideoCodec.HEVC),
                profiles=["baseline", "main", "high"] if codec == VideoCodec.H264 else ["main"],
                rate_control_modes=[RateControlMode.CBR, RateControlMode.VBR, RateControlMode.CQ],
            )
        except Exception as e:
            logger.error(f"NVENC tespit hatasi: {e}")
            return None

    @staticmethod
    def select_best_encoder(
        required_codec: VideoCodec,
        required_width: int = 1920,
        required_height: int = 1080,
    ) -> Optional[EncoderCapability]:
        """Gereksinimlere en uygun encoder'i sec."""
        available = HWEncoderDetector.detect_encoders()
        compatible = [
            e for e in available
            if e.supported and e.codec == required_codec
            and e.max_width >= required_width
            and e.max_height >= required_height
        ]

        if not compatible:
            return None

        # Oncelik: NVENC > QSV > AMF > Software
        priority = {
            HWEncoderType.NVENC: 0,
            HWEncoderType.QSV: 1,
            HWEncoderType.AMF: 2,
            HWEncoderType.VIDEOTOOLBOX: 3,
            HWEncoderType.SOFTWARE: 4,
        }
        compatible.sort(key=lambda e: priority.get(e.encoder_type, 99))
        return compatible[0]
```

## 3.4 Bitrate Allocation Stratejileri

```python
from dataclasses import dataclass
from typing import Optional


@dataclass
class BitrateAllocation:
    """Bitrate dagitim stratejisi."""
    target_bitrate_kbps: int
    max_bitrate_kbps: int
    min_bitrate_kbps: int
    buffer_size_kbps: int
    quality_factor: float   # 0.0 (en dusuk) - 1.0 (en yuksek)
    complexity_boost: float  # Karmasiklik artis carpani

    @classmethod
    def for_platform(
        cls,
        platform: str,
        resolution: tuple[int, int],
        fps: int = 30,
    ) -> BitrateAllocation:
        """
        Platform bazli on tanimli bitrate dagitim.

        Platformlar:
        - youtube_1080p: YouTube 1080p
        - youtube_4k: YouTube 4K
        - twitch_1080p: Twitch 1080p
        - kick_1080p: Kick 1080p
        - social_vertical: Dikey sosyal medya (TikTok, Shorts)
        - archival: Arsivleme (yuksek kalite)
        """
        w, h = resolution
        pixels = w * h
        fps_factor = fps / 30.0

        platform_profiles = {
            "kick_1080p": {"bits_per_pixel": 0.08, "max_bpp": 0.12, "buf_factor": 2.0},
            "twitch_1080p": {"bits_per_pixel": 0.07, "max_bpp": 0.11, "buf_factor": 2.0},
            "youtube_1080p": {"bits_per_pixel": 0.07, "max_bpp": 0.10, "buf_factor": 2.0},
            "youtube_4k": {"bits_per_pixel": 0.10, "max_bpp": 0.15, "buf_factor": 2.5},
            "social_vertical": {"bits_per_pixel": 0.06, "max_bpp": 0.09, "buf_factor": 2.0},
            "archival": {"bits_per_pixel": 0.15, "max_bpp": 0.25, "buf_factor": 3.0},
        }

        profile = platform_profiles.get(platform, platform_profiles["kick_1080p"])
        target = int(pixels * fps * profile["bits_per_pixel"] / 1000)
        maximum = int(pixels * fps * profile["max_bpp"] / 1000)
        minimum = int(target * 0.5)
        buf_size = int(maximum * profile["buf_factor"])

        return cls(
            target_bitrate_kbps=target,
            max_bitrate_kbps=maximum,
            min_bitrate_kbps=minimum,
            buffer_size_kbps=buf_size,
            quality_factor=0.8,
            complexity_boost=1.0,
        )

    @classmethod
    def for_content_type(
        cls,
        content_type: str,
        resolution: tuple[int, int],
        fps: int = 30,
    ) -> BitrateAllocation:
        """
        Icerik turune gore bitrate dagitim.
        Yuksek hareket = daha fazla bitrate gerekir.
        """
        w, h = resolution
        pixels = w * fps

        content_multipliers = {
            "gaming": 1.3,       # Hareketli oyun icerikleri
            "talking_head": 0.7, # Statik konusma
            "sports": 1.5,       # Cok yuksek hareket
            "music": 1.1,        # Orta hareket
            "tutorial": 0.6,     # Dusuk hareket
            "stream": 1.0,       # Varsayilan
        }

        multiplier = content_multipliers.get(content_type, 1.0)
        base_bpp = 0.08

        target = int(pixels * base_bpp * multiplier * fps / 30 / 1000)
        maximum = int(target * 1.5)
        minimum = int(target * 0.5)

        return cls(
            target_bitrate_kbps=target,
            max_bitrate_kbps=maximum,
            min_bitrate_kbps=minimum,
            buffer_size_kbps=int(maximum * 2),
            quality_factor=min(1.0, 0.6 + multiplier * 0.3),
            complexity_boost=multiplier,
        )
```

## 3.5 Two-Pass Encoding

```python
class TwoPassEncoder:
    """
    Two-pass hardware encoding motoru.
    Iki asamali kodlama ile daha iyi bitrate dagitimi saglar.
    """

    def __init__(self, config: HWEncoderConfig):
        self._config = config

    def get_pass1_command(
        self, input_path: str, stats_file: str, output_path: str,
    ) -> list[str]:
        """
        Pass 1: Analiz asamasi.
        Frame complexity haritasi olusturulur, gercek ciktilik olusturulmaz.
        """
        cmd = ["ffmpeg", "-hide_banner", "-y"]

        # HW input
        if self._config.encoder_type == HWEncoderType.NVENC:
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])

        cmd.extend(["-i", input_path])

        # Encoder args
        enc_args = self._config.to_ffmpeg_args()

        # Pass 1 ozel parametreler
        if self._config.encoder_type == HWEncoderType.NVENC:
            # NVENC two-pass: pass=5 (analyze), pass=10 (full)
            enc_args.extend(["-multipass", "fullres"])
        elif "libx264" in str(enc_args) or "libx265" in str(enc_args):
            enc_args.extend(["-pass", "1", "-passlogfile", stats_file])
            enc_args.extend(["-an", "-f", "null"])

        cmd.extend(enc_args)
        cmd.append(output_path if "libx26" in str(enc_args) else "/dev/null")
        return cmd

    def get_pass2_command(
        self, input_path: str, stats_file: str, output_path: str,
    ) -> list[str]:
        """
        Pass 2: Kodlama asamasi.
        Pass 1 analiz sonuclarina gore optimal bitrate dagitimi yapilir.
        """
        cmd = ["ffmpeg", "-hide_banner", "-y"]

        if self._config.encoder_type == HWEncoderType.NVENC:
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])

        cmd.extend(["-i", input_path])
        enc_args = self._config.to_ffmpeg_args()

        if self._config.encoder_type == HWEncoderType.NVENC:
            enc_args.extend(["-multipass", "fullres"])
        elif "libx264" in str(enc_args) or "libx265" in str(enc_args):
            enc_args.extend(["-pass", "2", "-passlogfile", stats_file])

        cmd.extend(enc_args)
        cmd.append(output_path)
        return cmd


class SinglePassOptimizer:
    """
    Tek-pass encoding optimizasyonu.
    Real-time streaming icin gerekli olan hizli kodlama stratejisi.
    Rate control lookahead ve adaptive bitrate ile kaliteyi optimize eder.
    """

    @staticmethod
    def create_optimized_config(
        encoder_type: HWEncoderType,
        codec: VideoCodec,
        resolution: tuple[int, int],
        fps: int,
        content_type: str = "stream",
        platform: str = "kick_1080p",
    ) -> HWEncoderConfig:
        """Optimize edilmis encoder konfigurasyonu olustur."""
        allocation = BitrateAllocation.for_content_type(content_type, resolution, fps)

        # Preset secimi: stream icin hizli, archival icin yuksek kalite
        preset_map = {
            "gaming": EncodingPreset.NVENC_P4,
            "talking_head": EncodingPreset.NVENC_P6,
            "sports": EncodingPreset.NVENC_P3,
            "music": EncodingPreset.NVENC_P4,
            "tutorial": EncodingPreset.NVENC_P5,
            "stream": EncodingPreset.NVENC_P4,
            "archival": EncodingPreset.NVENC_P7,
        }

        profile_map = {
            VideoCodec.H264: "high",
            VideoCodec.HEVC: "main",
            VideoCodec.AV1: "main",
        }

        return HWEncoderConfig(
            encoder_type=encoder_type,
            codec=codec,
            preset=preset_map.get(content_type, EncodingPreset.NVENC_P4),
            rate_control=RateControlMode.CQ,
            target_bitrate_kbps=allocation.target_bitrate_kbps,
            max_bitrate_kbps=allocation.max_bitrate_kbps,
            bufsize_kbps=allocation.buffer_size_kbps,
            cq_level=23,
            keyframe_interval=2,
            bframes=3 if codec in (VideoCodec.H264, VideoCodec.HEVC) else 0,
            profile=profile_map.get(codec, "high"),
            tune="hq",
            spatial_aq=True,
            temporal_aq=True,
            rc_lookahead=32,
        )
```

## 3.6 FFmpeg Hardware Encoding Komut Ornekleri

### 3.6.1 NVENC H.264 - Kick Klip Encoding

```python
# Kick klip icin standart NVENC H.264 encoding
def build_kick_clip_encode_command(
    input_path: str,
    output_path: str,
    target_bitrate: int = 6000,
    max_bitrate: int = 8000,
    resolution: tuple[int, int] = (1920, 1080),
    fps: int = 60,
) -> list[str]:
    w, h = resolution
    gop = fps * 2  # 2 saniye keyframe araligi

    return [
        "ffmpeg", "-hide_banner", "-y",
        # GPU hardware decode
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", input_path,
        # Video filtre: GPU'da scale + format
        "-filter_complex",
        f"[0:v]scale_cuda={w}:{h}:interp_algo=lanczos,format=nv12[enc]",
        "-map", "[enc]", "-map", "0:a?",
        # NVENC H.264 encoder
        "-c:v", "h264_nvenc",
        "-preset", "p4",
        "-tune", "hq",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        # Bitrate kontrolu
        "-b:v", f"{target_bitrate}k",
        "-maxrate", f"{max_bitrate}k",
        "-bufsize", f"{max_bitrate * 2}k",
        # Keyframe
        "-g", str(gop),
        "-keyint_min", str(gop),
        # B-frame
        "-bf", "3",
        # Adaptive Quantization
        "-spatial-aq", "1",
        "-temporal-aq", "1",
        # Rate control lookahead
        "-rc-lookahead", "32",
        # Audio
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
```

**FFmpeg komutu ciktisi:**

```bash
ffmpeg -hide_banner -y \
  -hwaccel cuda -hwaccel_output_format cuda \
  -i /data/kicks/clip_12345.mp4 \
  -filter_complex "[0:v]scale_cuda=1920:1080:interp_algo=lanczos,format=nv12[enc]" \
  -map "[enc]" -map 0:a? \
  -c:v h264_nvenc -preset p4 -tune hq -profile:v high -pix_fmt yuv420p \
  -b:v 6000k -maxrate 8000k -bufsize 16000k \
  -g 120 -keyint_min 120 \
  -bf 3 -spatial-aq 1 -temporal-aq 1 -rc-lookahead 32 \
  -c:a aac -b:a 128k \
  /data/output/clip_12345_reencode.mp4
```

### 3.6.2 NVENC HEVC - Yuksek Kalite

```python
def build_hevc_encode_command(
    input_path: str, output_path: str,
    quality_level: str = "high",
) -> list[str]:
    """HEVC encode - %50 daha dusuk bitrate ile ayni kalite."""
    quality_presets = {
        "low": {"preset": "p2", "cq": 30, "bitrate": "3000k", "max": "4500k"},
        "medium": {"preset": "p4", "cq": 25, "bitrate": "4000k", "max": "6000k"},
        "high": {"preset": "p6", "cq": 20, "bitrate": "5000k", "max": "7500k"},
    }
    q = quality_presets.get(quality_level, quality_presets["high"])

    return [
        "ffmpeg", "-hide_banner", "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", input_path,
        "-c:v", "hevc_nvenc",
        "-preset", q["preset"],
        "-tune", "hq",
        "-profile:v", "main",
        "-pix_fmt", "yuv420p",
        "-cq", q["cq"],
        "-b:v", q["bitrate"],
        "-maxrate", q["max"],
        "-spatial-aq", "1",
        "-temporal-aq", "1",
        "-rc-lookahead", "32",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
```

### 3.6.3 NVENC AV1 - En Yeni Codec

```python
def build_av1_encode_command(
    input_path: str, output_path: str,
    target_bitrate: int = 3000,
) -> list[str]:
    """AV1 encode - HEVC'den ~30% daha iyi sikistirma."""
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", input_path,
        "-c:v", "av1_nvenc",
        "-preset", "p4",
        "-tune", "hq",
        "-pix_fmt", "yuv420p",
        "-b:v", f"{target_bitrate}k",
        "-maxrate", f"{int(target_bitrate * 1.5)}k",
        "-spatial-aq", "1",
        "-temporal-aq", "1",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
```

### 3.6.4 Intel QSV Encoding

```python
def build_qsv_encode_command(
    input_path: str, output_path: str,
    codec: str = "h264",
    bitrate: int = 5000,
) -> list[str]:
    """Intel Quick Sync encoding."""
    codec_map = {"h264": "h264_qsv", "hevc": "hevc_qsv", "av1": "av1_qsv"}
    qsv_codec = codec_map.get(codec, "h264_qsv")

    return [
        "ffmpeg", "-hide_banner", "-y",
        "-hwaccel", "qsv", "-hwaccel_output_format", "qsv",
        "-i", input_path,
        "-c:v", qsv_codec,
        "-preset", "balanced",
        "-b:v", f"{bitrate}k",
        "-maxrate", f"{int(bitrate * 1.5)}k",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ]
```

### 3.6.5 Multi-Output Encode (Ayni anda birden fazla cozunurluk)

```python
def build_multi_output_encode_command(
    input_path: str,
    outputs: dict[str, str],
) -> list[str]:
    """
    Ayni anda birden fazla cozunurlukte encode.
    Ornegin: 1080p + 720p + 480p ayni anda.

    outputs = {
        "1080p": "/output/clip_1080p.mp4",
        "720p": "/output/clip_720p.mp4",
        "480p": "/output/clip_480p.mp4",
    }
    """
    resolutions = {
        "1080p": (1920, 1080),
        "720p": (1280, 720),
        "480p": (854, 480),
        "360p": (640, 360),
    }

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", input_path,
    ]

    # Filter complex: split + scale her cikit icin
    filter_parts = []
    output_maps = []
    idx = 0
    for label, res in resolutions.items():
        if label in outputs:
            w, h = res
            filter_parts.append(
                f"[0:v]split=3[{label}_a][{label}_b][{label}_c];"
                f"[{label}_a]scale_cuda={w}:{h}:interp_algo=lanczos,"
                f"format=nv12[vt{idx}]"
            )
            output_maps.extend(["-map", f"[vt{idx}]"])
            idx += 1

    # Cikit argumanlari
    for i, (label, path) in enumerate(outputs.items()):
        cmd.extend(["-map", f"[vt{i}]"])
        cmd.extend(["-c:v", "h264_nvenc", "-preset", "p4"])
        w, h = resolutions.get(label, (1920, 1080))
        cmd.extend(["-b:v", f"{3000 + i * 2000}k"])

    cmd.extend(["-filter_complex", ";".join(filter_parts)])
    cmd.extend(["-c:a", "aac", "-b:a", "128k"])

    for path in outputs.values():
        cmd.append(path)

    return cmd
```

## 3.7 Encoder Kalite Karsilastirmasi

```
Kodlayici       | Bitrate (1080p30) | VRAM  | CPU %  | Gecikme
----------------|-------------------|-------|--------|--------
x264 (medium)   | 5000 kbps        | 0 MB  | 90%    | 50ms
x264 (fast)     | 6000 kbps        | 0 MB  | 70%    | 30ms
h264_nvenc (p4) | 6000 kbps        | 150MB | 8%     | 5ms
hevc_nvenc (p4) | 3500 kbps        | 200MB | 10%    | 8ms
av1_nvenc (p4)  | 2500 kbps        | 250MB | 12%    | 10ms
h264_qsv        | 6000 kbps        | 50MB  | 5%     | 6ms
hevc_qsv        | 3500 kbps        | 80MB  | 7%     | 9ms
```

## 3.8 Entegrasyon Noktalari

```python
class HWEncodingService:
    """
    FastAPI servis katmani ile entegrasyon.
    Encoding isteklerini alir, encoder secer ve FFmpeg komutu olusturur.
    """

    def __init__(self):
        self._detected_encoders = HWEncoderDetector.detect_encoders()
        self._encoder_configs: dict[str, HWEncoderConfig] = {}

    async def encode_clip(
        self,
        input_url: str,
        output_url: str,
        target_codec: str = "h264",
        resolution: tuple[int, int] = (1920, 1080),
        fps: int = 60,
        quality: str = "medium",
    ) -> dict:
        codec_map = {"h264": VideoCodec.H264, "hevc": VideoCodec.HEVC, "av1": VideoCodec.AV1}
        codec = codec_map.get(target_codec, VideoCodec.H264)

        encoder = HWEncoderDetector.select_best_encoder(
            codec, resolution[0], resolution[1],
        )
        if not encoder:
            return {"error": "Uygun hardware encoder bulunamadi"}

        config = SinglePassOptimizer.create_optimized_config(
            encoder.encoder_type, encoder.codec, resolution, fps,
        )

        return {
            "encoder": encoder.encoder_type.name,
            "codec": encoder.codec.value,
            "ffmpeg_args": config.to_ffmpeg_args(),
        }

    def get_available_encoders(self) -> list[dict]:
        return [
            {
                "type": e.encoder_type.name,
                "codec": e.codec.value,
                "max_resolution": f"{e.max_width}x{e.max_height}",
                "max_fps": e.max_fps,
                "profiles": e.profiles,
            }
            for e in self._detected_encoders if e.supported
        ]
```

---

# 4. Dynamic Crop Engine

## 4.1 Amaç

Dynamic Crop Engine, video karelerinin icerigine gore dinamik olarak crop bolgesi belirleyen bir sistemdir. Yuz algilama, hareket takibi ve kompozisyon analizi kullanarak, icerigin en onemli bolumunu otomatik olarak kadir ve farkli en-boy oranlarina donusturur.

**Kullanim Alanlari:**
- 16:9 yayin klibini 9:16 (TikTok/Shorts) donusturme
- Yuz odakli kirsilalama (face-aware crop)
- Hareket takipli otomatik pan/scan
- Kompozisyon optimizasyonu (rule of thirds)

## 4.2 Mimari Tasarim

```
Giris Kareleri
      |
      v
+-------------------+
| Frame Analyzer     | -> Yuz algilama, hareket analizi, icerik tespiti
+-------------------+
      |
      v
+-------------------+
| Crop Strategy      | -> hangi strateji ne zaman kullanilir
| Selection Engine   |
+-------------------+
      |
      v
+-------------------+
| Crop Calculator    | -> Frame bazli crop bolgeleri hesapla
+-------------------+
      |
      v
+-------------------+
| Keyframe           | -> Crop bolgelerini yumusak gecislerle
| Smoother           |    animasyona donustur
+-------------------+
      |
      v
+-------------------+
| Crop Executor      | -> FFmpeg crop filteri ile uygula
+-------------------+
      |
      v
Iscilmis Kareler (Farkli en-boy oraninda)
```

## 4.3 Veri Yapilari

```python
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


class CropStrategy(Enum):
    CENTER = auto()              # Ortadan kir
    FACE_AWARE = auto()          # Yuzu takip et
    MOTION_FOLLOW = auto()       # Hareketi takip et
    RULE_OF_THIRDS = auto()      # Ucte bir kurali
    SALIENT_OBJECT = auto()      # Dikkat cekici nesneyi takip et
    PAN_SCAN = auto()            # Pan ve scan otomasyonu
    STATIC = auto()              # Sabit crop (animasyonsuz)


class AspectRatio(Enum):
    R16_9 = (16, 9)
    R9_16 = (9, 16)
    R4_3 = (4, 3)
    R3_4 = (3, 4)
    R1_1 = (1, 1)
    R4_5 = (4, 5)
    R21_9 = (21, 9)

    @property
    def width_ratio(self) -> int:
        return self.value[0]

    @property
    def height_ratio(self) -> int:
        return self.value[1]

    @property
    def float_ratio(self) -> float:
        return self.value[0] / self.value[1]


@dataclass
class CropRegion:
    """Tek bir kare icin crop bolgesi."""
    x: int
    y: int
    width: int
    height: int
    confidence: float = 1.0    # 0.0 - 1.0 arasi guven skoru
    frame_number: int = 0
    timestamp_ms: float = 0.0

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def area(self) -> int:
        return self.width * self.height

    def intersection_over_union(self, other: CropRegion) -> float:
        """Iki crop bolgesi arasindaki IoU hesapla."""
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.x + self.width, other.x + other.width)
        y2 = min(self.y + self.height, other.y + other.height)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)
        union = self.area + other.area - intersection
        return intersection / max(union, 1)

    def clamp(self, max_width: int, max_height: int) -> CropRegion:
        """Crop bolgesini sinirlar icerisinde sinirla."""
        x = max(0, min(self.x, max_width - self.width))
        y = max(0, min(self.y, max_height - self.height))
        w = min(self.width, max_width)
        h = min(self.height, max_height)
        return CropRegion(x=x, y=y, width=w, height=h)


@dataclass
class CropKeyframe:
    """Crop animasyonu icin bir anahtar kare."""
    frame_number: int
    crop_region: CropRegion
    timestamp_ms: float = 0.0
    easing: str = "ease_in_out"   # linear, ease_in, ease_out, ease_in_out

    def interpolate_to(self, next_keyframe: CropKeyframe, frame: int) -> CropRegion:
        """
        Iki anahtar kare arasinda dogrusal interpolasyon.
        Kullanilan easing fonksiyonuna gore yumusak gecis saglar.
        """
        total_frames = next_keyframe.frame_number - self.frame_number
        if total_frames <= 0:
            return self.crop_region

        t = (frame - self.frame_number) / total_frames
        t = max(0.0, min(1.0, t))

        # Easing uygula
        t = self._apply_easing(t, self.easing)

        x = int(self.crop_region.x + t * (next_keyframe.crop_region.x - self.crop_region.x))
        y = int(self.crop_region.y + t * (next_keyframe.crop_region.y - self.crop_region.y))
        w = int(self.crop_region.width + t * (next_keyframe.crop_region.width - self.crop_region.width))
        h = int(self.crop_region.height + t * (next_keyframe.crop_region.height - self.crop_region.height))

        return CropRegion(x=x, y=y, width=w, height=h, frame_number=frame)

    @staticmethod
    def _apply_easing(t: float, easing: str) -> float:
        if easing == "linear":
            return t
        elif easing == "ease_in":
            return t * t
        elif easing == "ease_out":
            return 1 - (1 - t) ** 2
        elif easing == "ease_in_out":
            if t < 0.5:
                return 2 * t * t
            return 1 - (-2 * t + 2) ** 2 / 2
        return t


@dataclass
class CropStrategyConfig:
    """Crop stratejisi konfigurasyonu."""
    strategy: CropStrategy
    target_aspect: AspectRatio = AspectRatio.R9_16
    source_width: int = 1920
    source_height: int = 1080
    smoothing_window: int = 5        # Yumusatma penceresi (kare sayisi)
    max_pan_speed: float = 50.0      # Maksimum pan hizi (piksel/kare)
    confidence_threshold: float = 0.5
    keyframe_interval: int = 30      # Her 30 karede bir anahtar kare


@dataclass
class DynamicCrop:
    """
    Tum crop sonuclarini tutar.
    Frame bazli crop bolgeleri ve metadata.
    """
    strategy: CropStrategy
    target_aspect: AspectRatio
    source_width: int
    source_height: int
    keyframes: list[CropKeyframe] = field(default_factory=list)
    total_frames: int = 0
    avg_confidence: float = 0.0
    processing_time_ms: float = 0.0

    @property
    def crop_width(self) -> int:
        if self.keyframes:
            return self.keyframes[0].crop_region.width
        return self.source_width

    @property
    def crop_height(self) -> int:
        if self.keyframes:
            return self.keyframes[0].crop_region.height
        return self.source_height

    def get_crop_for_frame(self, frame_number: int) -> CropRegion:
        """Belirli bir kare icin crop bolgesini dondur (interpolasyonlu)."""
        if not self.keyframes:
            # Tum kareler icin sabit crop
            w, h = self._calculate_target_dimensions()
            x = (self.source_width - w) // 2
            y = (self.source_height - h) // 2
            return CropRegion(x=x, y=y, width=w, height=h)

        # Karsi anahtar kareyi bul
        for i in range(len(self.keyframes) - 1):
            if self.keyframes[i].frame_number <= frame_number <= self.keyframes[i + 1].frame_number:
                return self.keyframes[i].interpolate_to(self.keyframes[i + 1], frame_number)

        # Son keyframe'den sonraki kareler
        return self.keyframes[-1].crop_region

    def _calculate_target_dimensions(self) -> tuple[int, int]:
        """Hedef boyutlari hesapla."""
        src_ratio = self.source_width / self.source_height
        tgt_ratio = self.target_aspect.float_ratio

        if tgt_ratio > src_ratio:
            # Hedef daha genis: yukselt
            w = self.source_width
            h = int(w / tgt_ratio)
        else:
            # Hedef daha dar: daralt
            h = self.source_height
            w = int(h * tgt_ratio)

        return w, h
```

## 4.4 Crop Stratejisi Algoritmalari

### 4.4.1 Yuz Odakli Dynamic Crop (Face-Aware)

```python
import cv2
import numpy as np
from typing import Optional


class FaceAwareCropStrategy:
    """
    Yuz algilama ve takibi kullanan dynamic crop stratejisi.

    Algoritma:
    1. Her karede yuz algilama (Haar Cascade veya DNN)
    2. Yuz merkezini hesapla
    3. Birden fazla yuz varsa en buyugu veya ortaya yakin olani sec
    4. Yuz uzerinde crop bolgesi olustur
    5. Yumusak gecis animasyonu uygula
    """

    def __init__(
        self,
        target_aspect: AspectRatio,
        face_margin: float = 1.5,      # Yuz etrafinda %50 bosluk
        headroom_ratio: float = 0.15,   # Yuz ustunde %15 bosluk
    ):
        self._target_aspect = target_aspect
        self._face_margin = face_margin
        self._headroom_ratio = headroom_ratio
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._prev_face_center: Optional[tuple[float, float]] = None
        self._tracking_box: Optional[tuple[int, int, int, int]] = None

    def calculate_crop(
        self, frame: np.ndarray, frame_number: int, source_w: int, source_h: int,
    ) -> CropRegion:
        """Tek bir kare icin crop bolgesi hesapla."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60),
        )

        if len(faces) == 0:
            return self._fallback_center_crop(source_w, source_h, frame_number)

        # En buyuk yuzu sec (veya ortaya en yakin)
        best_face = self._select_best_face(faces, source_w, source_h)
        fx, fy, fw, fh = best_face

        # Yuz merkezi
        face_center_x = fx + fw / 2
        face_center_y = fy + fh / 2

        # Hedef boyutlari hesapla
        crop_w, crop_h = self._calculate_target_dimensions(source_w, source_h)

        # Yuz uzerinde crop bolgesi hesapla
        # Yuz ustunde headroom birak
        crop_center_y = face_center_y - fh * self._headroom_ratio

        # Crop bolgesini sinirlara sigdir
        crop_x = int(face_center_x - crop_w / 2)
        crop_y = int(crop_center_y - crop_h / 2)

        # Sinir kontrolu
        crop_x = max(0, min(crop_x, source_w - crop_w))
        crop_y = max(0, min(crop_y, source_h - crop_h))

        # Yuz takibi icin sonraki kare icin tahmin
        self._prev_face_center = (face_center_x, face_center_y)

        confidence = min(1.0, (fw * fh) / (source_w * source_h) * 100)

        return CropRegion(
            x=crop_x, y=crop_y, width=crop_w, height=crop_h,
            confidence=confidence, frame_number=frame_number,
        )

    def _select_best_face(
        self, faces: np.ndarray, source_w: int, source_h: int,
    ) -> tuple[int, int, int, int]:
        """En uygun yuzu sec."""
        if len(faces) == 1:
            return tuple(faces[0])

        # Ekranin merkezine en yakin ve en buyuk yuzu sec
        center_x, center_y = source_w / 2, source_h / 2
        best_score = -1
        best_face = tuple(faces[0])

        for (x, y, w, h) in faces:
            face_cx = x + w / 2
            face_cy = y + h / 2
            # Merkeze uzaklik (kucuk = iyi)
            dist = math.sqrt((face_cx - center_x) ** 2 + (face_cy - center_y) ** 2)
            # Boyut (buyuk = iyi)
            area = w * h
            # Skor: boyut / uzaklik
            score = area / max(dist, 1)
            if score > best_score:
                best_score = score
                best_face = (x, y, w, h)

        return best_face

    def _calculate_target_dimensions(
        self, source_w: int, source_h: int,
    ) -> tuple[int, int]:
        """Hedef boyutlari hesapla."""
        src_ratio = source_w / source_h
        tgt_ratio = self._target_aspect.float_ratio

        if tgt_ratio > src_ratio:
            w = source_w
            h = int(w / tgt_ratio)
        else:
            h = source_h
            w = int(h * tgt_ratio)

        return w, h

    def _fallback_center_crop(
        self, source_w: int, source_h: int, frame_number: int,
    ) -> CropRegion:
        """Yuz bulunamazsa merkez crop."""
        w, h = self._calculate_target_dimensions(source_w, source_h)
        x = (source_w - w) // 2
        y = (source_h - h) // 2
        return CropRegion(x=x, y=y, width=w, height=h, confidence=0.3, frame_number=frame_number)


class MotionAwareCropStrategy:
    """
    Hareket odakli dynamic crop.
    Optik akis analizi ile en cok hareket olan bolgeyi takip eder.
    """

    def __init__(
        self,
        target_aspect: AspectRatio,
        motion_weight: float = 0.6,
        center_weight: float = 0.4,
    ):
        self._target_aspect = target_aspect
        self._motion_weight = motion_weight
        self._center_weight = center_weight
        self._prev_gray: Optional[np.ndarray] = None
        self._optical_flow = cv2.calcOpticalFlowFarneback

    def calculate_crop(
        self, frame: np.ndarray, frame_number: int, source_w: int, source_h: int,
    ) -> CropRegion:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        crop_w, crop_h = self._calculate_target_dimensions(source_w, source_h)

        if self._prev_gray is None:
            self._prev_gray = gray
            x = (source_w - crop_w) // 2
            y = (source_h - crop_h) // 2
            return CropRegion(x=x, y=y, width=crop_w, height=crop_h, frame_number=frame_number)

        # Optik akis hesapla
        flow = cv2.calcOpticalFlowFarneback(
            self._prev_gray, gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )

        # Hareket genligi haritasi
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])

        # Hareket dagilimini analiz et
        h_blocks = 4
        w_blocks = 4
        block_h = source_h // h_blocks
        block_w = source_w // w_blocks
        motion_scores = np.zeros((h_blocks, w_blocks))

        for by in range(h_blocks):
            for bx in range(w_blocks):
                y1 = by * block_h
                y2 = (by + 1) * block_h
                x1 = bx * block_w
                x2 = (bx + 1) * block_w
                motion_scores[by, bx] = np.mean(magnitude[y1:y2, x1:x2])

        # Hareket merkezini hesapla
        total_motion = np.sum(motion_scores)
        if total_motion > 0:
            grid_y, grid_x = np.mgrid[0:h_blocks, 0:w_blocks]
            motion_cx = np.sum(grid_x * motion_scores) / total_motion * block_w + block_w / 2
            motion_cy = np.sum(grid_y * motion_scores) / total_motion * block_h + block_h / 2
        else:
            motion_cx = source_w / 2
            motion_cy = source_h / 2

        # Merkez ile hareket noktasi arasinda agirlikli ortalama
        target_x = (self._center_weight * source_w / 2 + self._motion_weight * motion_cx)
        target_y = (self._center_weight * source_h / 2 + self._motion_weight * motion_cy)

        # Crop bolgesini sinirla
        crop_x = int(max(0, min(target_x - crop_w / 2, source_w - crop_w)))
        crop_y = int(max(0, min(target_y - crop_h / 2, source_h - crop_h)))

        self._prev_gray = gray

        confidence = min(1.0, total_motion / (source_w * source_h) * 1000)
        return CropRegion(
            x=crop_x, y=crop_y, width=crop_w, height=crop_h,
            confidence=confidence, frame_number=frame_number,
        )

    def _calculate_target_dimensions(self, source_w, source_h):
        src_ratio = source_w / source_h
        tgt_ratio = self._target_aspect.float_ratio
        if tgt_ratio > src_ratio:
            return source_w, int(source_w / tgt_ratio)
        else:
            return int(source_h * tgt_ratio), source_h


class RuleOfThirdsCropStrategy:
    """
    Ucte bir kompozisyon kurali kullanan crop stratejisi.
    Kural: Onemli unsurlarin kesme noktalarinin ustune yerlestirilmesi.
    """

    def __init__(self, target_aspect: AspectRatio):
        self._target_aspect = target_aspect

    def calculate_crop(
        self, frame: np.ndarray, frame_number: int, source_w: int, source_h: int,
    ) -> CropRegion:
        crop_w, crop_h = self._calculate_target_dimensions(source_w, source_h)

        # Ucte bir noktalari hesapla (4 kesme noktasi)
        third_x1 = source_w // 3
        third_x2 = source_w * 2 // 3
        third_y1 = source_h // 3
        third_y2 = source_h * 2 // 3

        # En iyi kesme noktasini sec (soldan ust)
        crop_x = third_x1 - crop_w // 3
        crop_y = third_y1 - crop_h // 3

        crop_x = max(0, min(crop_x, source_w - crop_w))
        crop_y = max(0, min(crop_y, source_h - crop_h))

        return CropRegion(x=crop_x, y=crop_y, width=crop_w, height=crop_h, frame_number=frame_number)

    def _calculate_target_dimensions(self, source_w, source_h):
        src_ratio = source_w / source_h
        tgt_ratio = self._target_aspect.float_ratio
        if tgt_ratio > src_ratio:
            return source_w, int(source_w / tgt_ratio)
        else:
            return int(source_h * tgt_ratio), source_h
```

## 4.5 Crop Keyframe Animasyon Motoru

```python
class CropKeyframeAnimator:
    """
    Crop bolgelerini yumusak animasyona donusturur.
    Anahtar kareler arasinda easing fonksiyonlari ile interpolasyon yapar.
    """

    def __init__(self, config: CropStrategyConfig):
        self._config = config
        self._keyframes: list[CropKeyframe] = []

    def add_keyframe(self, keyframe: CropKeyframe) -> None:
        """Anahtar kare ekle ve sirala."""
        self._keyframes.append(keyframe)
        self._keyframes.sort(key=lambda kf: kf.frame_number)

    def generate_smooth_keyframes(
        self, raw_crops: list[CropRegion],
    ) -> list[CropKeyframe]:
        """
        Ham crop bolgelerinden yumusak anahtar kareler olustur.

        Algoritma:
        1. Her keyframe_interval'da bir ornek al
        2. Ornnekler arasinda interpolasyon yap
        3. Maksimum pan hizini kontrol et
        4. Yumusak gecisler icin easing uygula
        """
        if not raw_crops:
            return []

        keyframes = []
        interval = self._config.keyframe_interval

        for i in range(0, len(raw_crops), interval):
            crop = raw_crops[i]

            # Maksimum pan hizi kontrolu
            if keyframes:
                last_kf = keyframes[-1]
                dx = abs(crop.center_x - last_kf.crop_region.center_x)
                dy = abs(crop.center_y - last_kf.crop_region.center_y)
                max_pan = self._config.max_pan_speed * interval

                if dx > max_pan or dy > max_pan:
                    # Pan hizi siniri asildi - sinirla
                    scale = max_pan / max(dx, dy, 1)
                    new_cx = last_kf.crop_region.center_x + (crop.center_x - last_kf.crop_region.center_x) * scale
                    new_cy = last_kf.crop_region.center_y + (crop.center_y - last_kf.crop_region.center_y) * scale
                    crop = CropRegion(
                        x=int(new_cx - crop.width / 2),
                        y=int(new_cy - crop.height / 2),
                        width=crop.width, height=crop.height,
                        confidence=crop.confidence, frame_number=crop.frame_number,
                    )

            kf = CropKeyframe(
                frame_number=i,
                crop_region=crop,
                timestamp_ms=i * 1000 / 30,  # 30fps varsayim
                easing="ease_in_out",
            )
            keyframes.append(kf)

        self._keyframes = keyframes
        return keyframes

    def smooth_keyframes(
        self, keyframes: list[CropKeyframe], window_size: int = 5,
    ) -> list[CropKeyframe]:
        """
        Anahtar kareleri hareketli ortalama ile yumusat.

        Bu, ani sarsilmalari onler ve daha dogal kamera hareketi saglar.
        """
        if len(keyframes) <= 2:
            return keyframes

        smoothed = []
        half_window = window_size // 2

        for i, kf in enumerate(keyframes):
            # Pencere icindeki kareleri topla
            start = max(0, i - half_window)
            end = min(len(keyframes), i + half_window + 1)
            window = keyframes[start:end]

            # Ortalama koordinatlar
            avg_x = sum(k.crop_region.x for k in window) / len(window)
            avg_y = sum(k.crop_region.y for k in window) / len(window)
            avg_w = sum(k.crop_region.width for k in window) / len(window)
            avg_h = sum(k.crop_region.height for k in window) / len(window)

            smoothed.append(CropKeyframe(
                frame_number=kf.frame_number,
                crop_region=CropRegion(
                    x=int(avg_x), y=int(avg_y),
                    width=int(avg_w), height=int(avg_h),
                    confidence=kf.crop_region.confidence,
                    frame_number=kf.frame_number,
                ),
                timestamp_ms=kf.timestamp_ms,
                easing=kf.easing,
            ))

        return smoothed

    def animate(
        self, total_frames: int, fps: int = 30,
    ) -> list[CropRegion]:
        """
        Tum kareler icin crop bolgelerini hesapla (interpolasyonlu).
        FFmpeg crop filter'i icin kullanilir.
        """
        if not self._keyframes:
            return []

        frames = []
        for frame_num in range(total_frames):
            crop = self._get_crop_for_frame(frame_num)
            frames.append(crop)

        return frames

    def _get_crop_for_frame(self, frame_number: int) -> CropRegion:
        """Tek bir kare icin crop bolgesi (interpolasyonlu)."""
        if not self._keyframes:
            raise ValueError("Anahtar kare yok")

        if frame_number <= self._keyframes[0].frame_number:
            return self._keyframes[0].crop_region

        if frame_number >= self._keyframes[-1].frame_number:
            return self._keyframes[-1].crop_region

        for i in range(len(self._keyframes) - 1):
            kf1 = self._keyframes[i]
            kf2 = self._keyframes[i + 1]
            if kf1.frame_number <= frame_number <= kf2.frame_number:
                return kf1.interpolate_to(kf2, frame_number)

        return self._keyframes[-1].crop_region

    def to_ffmpeg_crop_filter(self, total_frames: int) -> str:
        """
        FFmpeg crop filter expression olustur.
        Zaman bazli crop icin enable expression kullanir.
        """
        if not self._keyframes:
            return "crop=1920:1080:0:0"

        if len(self._keyframes) <= 1:
            kf = self._keyframes[0]
            return f"crop={kf.crop_region.width}:{kf.crop_region.height}:{kf.crop_region.x}:{kf.crop_region.y}"

        # Karmaşık FFmpeg crop expression
        # Her keyframe araligi icin farkli crop degerleri
        expressions = []
        for i in range(len(self._keyframes) - 1):
            kf1 = self._keyframes[i]
            kf2 = self._keyframes[i + 1]

            t1 = kf1.frame_number
            t2 = kf2.frame_number

            dx = (kf2.crop_region.x - kf1.crop_region.x) / max(1, t2 - t1)
            dy = (kf2.crop_region.y - kf1.crop_region.y) / max(1, t2 - t1)

            # enable expression: belirli kare araliginda aktif
            enable = f"between(n,{t1},{t2})"
            x_expr = f"{kf1.crop_region.x}+{dx:.4f}*(n-{t1})"
            y_expr = f"{kf1.crop_region.y}+{dy:.4f}*(n-{t1})"
            w = kf1.crop_region.width
            h = kf1.crop_region.height

            expressions.append(f"crop={w}:{h}:{x_expr}:{y_expr}:enable='{enable}'")

        # Birden fazla crop filter'i uygula (enable ile)
        # Gercek uygulamada tek bir filterComplex olarak birlestirilir
        return ";".join(expressions[:1])  # Basit: ilk keyframe grubunu kullan
```

## 4.6 Crop vs Resize Kalite Karsilastirmasi

```
Islem        | Kalite Kaybi | Hiz    | Bitrate Etkisi | Kullanim
-------------|-------------|--------|----------------|--------
Crop         | Sifir       | Cok hz | Dusuk          | Gereksiz bolgeleri kaldirma
Resize       | Dusuk       | Hizli  | Dusuk          | Boyut degisikligi
Crop+Resize  | Dusuk       | Hizli  | Optimal        | Yeni boyut + odak
Scale Down   | Dusuk       | Hizli  | Dusuk          | Kutuphane/preview
Scale Up     | Yuksek      | Yavas  | Yuksek         | Kalite dususu (onedilen degil)
```

**Optimal Strateji:**
1. Once crop ile gereksiz bolgeyi kaldir (kalite kaybi yok)
2. Sonra resize ile hedef boyuta getir
3. Asla buyutme yapma (kucultme tercih et)

---

# 5. Auto Reframe

## 5.1 Amaç

Auto Reframe, videonun icerigine gore otomatik olarak yeniden cerceveleme (reframe) yaparak farkli platform formatlarina donusturur. Content-aware resizing ile dikey (9:16), kare (1:1) veya diger en-boy oranlarinda icerigin en onemli bolumunu korur.

**Kullanim Senaryolari:**
- 16:9 Kick yayin klibi -> TikTok/YouTube Shorts (9:16)
- 16:9 video -> Instagram Feed (1:1 veya 4:5)
- 16:9 video -> Instagram Stories (9:16)
- 4:3 eski video -> 16:9 genis ekran

## 5.2 Auto Reframe Pipeline

```
Giris Videosu (16:9, 1920x1080)
      |
      v
+-------------------+
| Content Analysis   |
|  - Face Detection  |
|  - Object Tracking |
|  - Motion Analysis |
|  - Scene Detection |
+-------------------+
      |
      v
+-------------------+
| Reframe Strategy   |
|  - Per-platform    |
|  - Safe area mgmt  |
|  - Smoothing       |
+-------------------+
      |
      v
+-------------------+
| Track Generation   |
|  - Center of int.  |
|  - Bounding boxes  |
|  - Track paths     |
+-------------------+
      |
      v
+-------------------+
| Crop Animation     |
|  - Keyframes       |
|  - Easing          |
|  - Pan/scan        |
+-------------------+
      |
      v
+-------------------+
| FFmpeg Execution   |
|  - Dynamic crop    |
|  - HW encode       |
+-------------------+
      |
      v
Cikis Videosu (9:16, 1080x1920)
```

## 5.3 Veri Yapilari

```python
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class ReframePlatform(Enum):
    TIKTOK = "tiktok"           # 9:16
    YOUTUBE_SHORTS = "shorts"   # 9:16
    INSTAGRAM_REELS = "reels"   # 9:16
    INSTAGRAM_FEED = "feed"     # 1:1
    INSTAGRAM_STORIES = "stories"  # 9:16
    TWITTER = "twitter"         # 16:9 veya 1:1
    KICK_CLIP = "kick"          # 16:9 (orijinal)
    SQUARE = "square"           # 1:1
    VERTICAL = "vertical"       # 9:16
    CINEMATIC = "cinematic"     # 21:9


PLATFORM_SPECS = {
    ReframePlatform.TIKTOK: {"aspect": (9, 16), "width": 1080, "height": 1920, "max_fps": 60},
    ReframePlatform.YOUTUBE_SHORTS: {"aspect": (9, 16), "width": 1080, "height": 1920, "max_fps": 60},
    ReframePlatform.INSTAGRAM_REELS: {"aspect": (9, 16), "width": 1080, "height": 1920, "max_fps": 30},
    ReframePlatform.INSTAGRAM_FEED: {"aspect": (1, 1), "width": 1080, "height": 1080, "max_fps": 30},
    ReframePlatform.INSTAGRAM_STORIES: {"aspect": (9, 16), "width": 1080, "height": 1920, "max_fps": 30},
    ReframePlatform.SQUARE: {"aspect": (1, 1), "width": 1080, "height": 1080, "max_fps": 30},
    ReframePlatform.VERTICAL: {"aspect": (9, 16), "width": 1080, "height": 1920, "max_fps": 60},
    ReframePlatform.CINEMATIC: {"aspect": (21, 9), "width": 1920, "height": 816, "max_fps": 60},
    ReframePlatform.KICK_CLIP: {"aspect": (16, 9), "width": 1920, "height": 1080, "max_fps": 60},
}


@dataclass
class ReframeProfile:
    """Reframe konfigurasyonu."""
    platform: ReframePlatform
    source_width: int
    source_height: int
    output_width: int = 0
    output_height: int = 0
    safe_area_margin: float = 0.05   # %5 guvenli alan
    smoothing_strength: float = 0.8  # 0.0 (ham) - 1.0 (cok yumusak)
    max_pan_speed: float = 30.0      # Maksimum pan hizi (piksel/kare)
    face_priority: float = 0.7       # Yuz onceligi (0.0-1.0)
    motion_priority: float = 0.3     # Hareket onceligi (0.0-1.0)
    fps: int = 30
    keyframe_interval: int = 15

    def __post_init__(self):
        spec = PLATFORM_SPECS.get(self.platform, {"aspect": (16, 9), "width": 1920, "height": 1080})
        if self.output_width == 0:
            self.output_width = spec["width"]
        if self.output_height == 0:
            self.output_height = spec["height"]

    @property
    def aspect_ratio(self) -> tuple[int, int]:
        return PLATFORM_SPECS[self.platform]["aspect"]

    @property
    def aspect_float(self) -> float:
        return self.aspect_ratio[0] / self.aspect_ratio[1]


@dataclass
class ReframeTrackPoint:
    """Tek bir kare icin reframe takip noktasi."""
    frame_number: int
    center_x: float
    center_y: float
    confidence: float
    source: str       # "face", "motion", "salient", "default"
    timestamp_ms: float = 0.0


@dataclass
class ReframeTrack:
    """
    Tum video icin reframe takip verisi.
    Her kare icin merkez noktasi ve guven skoru.
    """
    points: list[ReframeTrackPoint] = field(default_factory=list)
    total_frames: int = 0
    face_frames: int = 0
    motion_frames: int = 0
    default_frames: int = 0

    def add_point(self, point: ReframeTrackPoint) -> None:
        self.points.append(point)
        if point.source == "face":
            self.face_frames += 1
        elif point.source == "motion":
            self.motion_frames += 1
        else:
            self.default_frames += 1

    @property
    def face_coverage(self) -> float:
        return self.face_frames / max(1, self.total_frames)

    def get_smoothed_path(self, window: int = 5) -> list[tuple[float, float]]:
        """Hareketli ortalama ile yumusatilmis yolu dondur."""
        if not self.points:
            return []
        path = [(p.center_x, p.center_y) for p in self.points]
        smoothed = []
        half = window // 2
        for i in range(len(path)):
            start = max(0, i - half)
            end = min(len(path), i + half + 1)
            avg_x = sum(p[0] for p in path[start:end]) / (end - start)
            avg_y = sum(p[1] for p in path[start:end]) / (end - start)
            smoothed.append((avg_x, avg_y))
        return smoothed


@dataclass
class ReframeKeyframe:
    """Reframe animasyonu icin anahtar kare."""
    frame_number: int
    crop_x: int
    crop_y: int
    crop_width: int
    crop_height: int
    confidence: float = 1.0
    easing: str = "ease_in_out"

    def interpolate_to(self, next_kf: ReframeKeyframe, frame: int) -> tuple[int, int]:
        """Iki anahtar kare arasinda interpolasyon."""
        total = next_kf.frame_number - self.frame_number
        if total <= 0:
            return self.crop_x, self.crop_y

        t = (frame - self.frame_number) / total
        t = max(0.0, min(1.0, t))

        # Cubic easing
        if self.easing == "ease_in_out":
            t = t * t * (3 - 2 * t)

        x = int(self.crop_x + t * (next_kf.crop_x - self.crop_x))
        y = int(self.crop_y + t * (next_kf.crop_y - self.crop_y))
        return x, y
```

## 5.4 Auto Reframe Motoru

```python
import cv2


class AutoReframeEngine:
    """
    Content-aware otomatik reframe motoru.

    Icerik analizi, yuz algilama, hareket takibi ve kompozisyon
    optimizasyonunu birlestirerek farkli platformlar icin optimal
    cerceveleme yapar.
    """

    def __init__(self, profile: ReframeProfile):
        self._profile = profile
        self._face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        self._track = ReframeTrack(total_frames=0)

    def analyze_video(self, video_path: str) -> ReframeTrack:
        """
        Videoyu analiz et ve reframe takip noktalarini olustur.

        Adimlar:
        1. Her kareyi oku
        2. Yuz algilama yap
        3. Hareket analizi yap
        4. Dikkat cekici nesne tespit et
        5. Agirlikli merkez noktasi hesapla
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Video acilamadi: {video_path}")
            return self._track

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        self._track.total_frames = total_frames
        prev_gray = None
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # 1. Yuz algilama
            face_center = self._detect_faces(gray, src_w, src_h)

            # 2. Hareket analizi
            motion_center = None
            if prev_gray is not None:
                motion_center = self._analyze_motion(prev_gray, gray, src_w, src_h)
            prev_gray = gray

            # 3. Agirlikli merkez hesapla
            center_x, center_y, confidence, source = self._compute_weighted_center(
                face_center, motion_center, src_w, src_h,
            )

            point = ReframeTrackPoint(
                frame_number=frame_idx,
                center_x=center_x, center_y=center_y,
                confidence=confidence, source=source,
                timestamp_ms=frame_idx * 1000 / fps,
            )
            self._track.add_point(point)
            frame_idx += 1

        cap.release()
        return self._track

    def _detect_faces(
        self, gray: np.ndarray, src_w: int, src_h: int,
    ) -> Optional[tuple[float, float]]:
        """Yuz algilama ve merkez noktasi dondur."""
        faces = self._face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50),
        )
        if len(faces) == 0:
            return None

        # En buyuk yuzu sec
        best = max(faces, key=lambda f: f[2] * f[3])
        fx, fy, fw, fh = best
        return (fx + fw / 2, fy + fh / 2)

    def _analyze_motion(
        self, prev_gray: np.ndarray, curr_gray: np.ndarray, src_w: int, src_h: int,
    ) -> Optional[tuple[float, float]]:
        """Optik akis ile hareket analizi."""
        try:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, curr_gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
            )
            magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])

            # Toplam hareket cok dusukse None dondur
            total_motion = np.sum(magnitude)
            if total_motion < src_w * src_h * 0.001:
                return None

            # Hareket merkezini hesapla
            grid_y, grid_x = np.mgrid[0:src_h:16, 0:src_w:16]
            motion_cx = np.sum(grid_x * magnitude[::16, ::16]) / max(total_motion, 1)
            motion_cy = np.sum(grid_y * magnitude[::16, ::16]) / max(total_motion, 1)

            return (float(motion_cx), float(motion_cy))
        except Exception:
            return None

    def _compute_weighted_center(
        self,
        face_center: Optional[tuple[float, float]],
        motion_center: Optional[tuple[float, float]],
        src_w: int, src_h: int,
    ) -> tuple[float, float, float, str]:
        """Agirlikli merkez noktasi hesapla."""
        fp = self._profile.face_priority
        mp = self._profile.motion_priority

        if face_center and motion_center:
            cx = fp * face_center[0] + mp * motion_center[0]
            cy = fp * face_center[1] + mp * motion_center[1]
            return cx, cy, 1.0, "face"
        elif face_center:
            return face_center[0], face_center[1], 0.8, "face"
        elif motion_center:
            return motion_center[0], motion_center[1], 0.6, "motion"
        else:
            return src_w / 2, src_h / 2, 0.3, "default"

    def generate_crop_keyframes(
        self, track: Optional[ReframeTrack] = None,
    ) -> list[ReframeKeyframe]:
        """
        Takip verisinden crop anahtar kareleri olustur.

        Her keyframe_interval'da bir ornek al,
        guvenli alani hesapla,
        animasyon icin anahtar kare olustur.
        """
        if track is None:
            track = self._track

        if not track.points:
            return []

        src_w = self._profile.source_width
        src_h = self._profile.source_height
        out_w = self._profile.output_width
        out_h = self._profile.output_height
        safe_margin = self._profile.safe_area_margin

        # Kaynak ve hedef en-boy oranlarini hesapla
        src_ratio = src_w / src_h
        out_ratio = out_w / out_h

        if out_ratio > src_ratio:
            # Hedef daha genis: yukselt
            crop_w = src_w
            crop_h = int(src_w / out_ratio)
        else:
            # Hedef daha dar: daralt
            crop_h = src_h
            crop_w = int(src_h * out_ratio)

        # Guvenli alan sinirlari
        safe_min_x = int(src_w * safe_margin)
        safe_max_x = int(src_w * (1 - safe_margin) - crop_w)
        safe_min_y = int(src_h * safe_margin)
        safe_max_y = int(src_h * (1 - safe_margin) - crop_h)

        keyframes = []
        smoothed_path = track.get_smoothed_path(window=7)

        for i in range(0, len(smoothed_path), self._profile.keyframe_interval):
            cx, cy = smoothed_path[i]
            confidence = track.points[i].confidence

            # Merkezden crop bolgesi
            crop_x = int(cx - crop_w / 2)
            crop_y = int(cy - crop_h / 2)

            # Guvenli alana sinirla
            crop_x = max(safe_min_x, min(crop_x, safe_max_x))
            crop_y = max(safe_min_y, min(crop_y, safe_max_y))

            kf = ReframeKeyframe(
                frame_number=i,
                crop_x=crop_x, crop_y=crop_y,
                crop_width=crop_w, crop_height=crop_h,
                confidence=confidence,
                easing="ease_in_out",
            )
            keyframes.append(kf)

        # Yumusatma
        keyframes = self._smooth_keyframes(keyframes)
        return keyframes

    def _smooth_keyframes(
        self, keyframes: list[ReframeKeyframe], window: int = 5,
    ) -> list[ReframeKeyframe]:
        """Anahtar kareleri yumusat."""
        if len(keyframes) <= 2:
            return keyframes

        half = window // 2
        smoothed = []
        for i, kf in enumerate(keyframes):
            start = max(0, i - half)
            end = min(len(keyframes), i + half + 1)
            avg_x = sum(k.crop_x for k in keyframes[start:end]) / (end - start)
            avg_y = sum(k.crop_y for k in keyframes[start:end]) / (end - start)
            smoothed.append(ReframeKeyframe(
                frame_number=kf.frame_number,
                crop_x=int(avg_x), crop_y=int(avg_y),
                crop_width=kf.crop_width, crop_height=kf.crop_height,
                confidence=kf.confidence, easing=kf.easing,
            ))
        return smoothed

    def build_ffmpeg_command(
        self,
        input_path: str,
        output_path: str,
        keyframes: list[ReframeKeyframe],
        encoder_config: Optional[HWEncoderConfig] = None,
    ) -> list[str]:
        """
        FFmpeg komutu olustur.
        Dinamik crop icin crop filter expression kullanir.
        """
        src_w = self._profile.source_width
        src_h = self._profile.source_height
        out_w = self._profile.output_width
        out_h = self._profile.output_height

        if not keyframes:
            # Sabit merkez crop
            crop_w = out_w if src_w / src_h > out_w / out_h else int(src_h * out_w / out_h)
            crop_h = int(crop_w * out_h / out_w)
            crop_x = (src_w - crop_w) // 2
            crop_y = (src_h - crop_h) // 2
            crop_filter = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y}"
        else:
            # Dinamik crop expression olustur
            crop_filter = self._build_dynamic_crop_expression(keyframes)

        scale_filter = f"scale={out_w}:{out_h}:flags=lanczos"
        filter_complex = f"[0:v]{crop_filter},{scale_filter}[out]"

        cmd = ["ffmpeg", "-hide_banner", "-y", "-i", input_path]

        if encoder_config:
            cmd.extend(["-filter_complex", filter_complex, "-map", "[out]"])
            cmd.extend(encoder_config.to_ffmpeg_args())
        else:
            cmd.extend(["-filter_complex", filter_complex, "-map", "[out]"])
            cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "23"])

        cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        cmd.append(output_path)
        return cmd

    def _build_dynamic_crop_expression(self, keyframes: list[ReframeKeyframe]) -> str:
        """Dinamik crop FFmpeg expression olustur."""
        if len(keyframes) <= 1:
            kf = keyframes[0]
            return f"crop={kf.crop_width}:{kf.crop_height}:{kf.crop_x}:{kf.crop_y}"

        # Her keyframe araligi icin enable expression ile crop
        parts = []
        for i in range(len(keyframes)):
            kf = keyframes[i]
            if i < len(keyframes) - 1:
                next_kf = keyframes[i + 1]
                t1 = kf.frame_number
                t2 = next_kf.frame_number

                dx = (next_kf.crop_x - kf.crop_x) / max(1, t2 - t1)
                dy = (next_kf.crop_y - kf.crop_y) / max(1, t2 - t1)

                enable = f"between(n\\,{t1}\\,{t2})"
                x_expr = f"{kf.crop_x}+{dx:.2f}*(n-{t1})"
                y_expr = f"{kf.crop_y}+{dy:.2f}*(n-{t1})"
                w = kf.crop_width
                h = kf.crop_height

                parts.append(f"crop={w}:{h}:{x_expr}:{y_expr}:enable='{enable}'")
            else:
                enable = f"gte(n\\,{kf.frame_number})"
                parts.append(
                    f"crop={kf.crop_width}:{kf.crop_height}:{kf.crop_x}:{kf.crop_y}:enable='{enable}'"
                )

        return ",".join(parts[:1])

    @staticmethod
    def reframe_for_platform(
        video_path: str,
        output_path: str,
        platform: ReframePlatform,
        source_width: int = 1920,
        source_height: int = 1080,
        fps: int = 30,
    ) -> dict:
        """
        Platform bazli otomatik reframe.

        Kullanim:
            result = AutoReframeEngine.reframe_for_platform(
                "input.mp4", "output_tiktok.mp4",
                ReframePlatform.TIKTOK,
            )
        """
        profile = ReframeProfile(
            platform=platform,
            source_width=source_width,
            source_height=source_height,
            fps=fps,
        )

        engine = AutoReframeEngine(profile)
        track = engine.analyze_video(video_path)
        keyframes = engine.generate_crop_keyframes(track)

        return {
            "platform": platform.value,
            "output_resolution": f"{profile.output_width}x{profile.output_height}",
            "total_frames": track.total_frames,
            "face_coverage": f"{track.face_coverage:.1%}",
            "keyframe_count": len(keyframes),
        }
```

## 5.5 Per-Platform Reframe Ornekleri

```python
class PlatformReframePresets:
    """Platform bazli on tanimli reframe profil ornekleri."""

    @staticmethod
    def kick_to_tiktok() -> ReframeProfile:
        return ReframeProfile(
            platform=ReframePlatform.TIKTOK,
            source_width=1920, source_height=1080,
            output_width=1080, output_height=1920,
            safe_area_margin=0.05,
            smoothing_strength=0.85,
            max_pan_speed=25.0,
            face_priority=0.7,
            motion_priority=0.3,
            fps=60,
        )

    @staticmethod
    def kick_to_instagram_reels() -> ReframeProfile:
        return ReframeProfile(
            platform=ReframePlatform.INSTAGRAM_REELS,
            source_width=1920, source_height=1080,
            output_width=1080, output_height=1920,
            safe_area_margin=0.08,
            smoothing_strength=0.9,
            max_pan_speed=20.0,
            face_priority=0.8,
            motion_priority=0.2,
            fps=30,
        )

    @staticmethod
    def kick_to_instagram_feed() -> ReframeProfile:
        return ReframeProfile(
            platform=ReframePlatform.INSTAGRAM_FEED,
            source_width=1920, source_height=1080,
            output_width=1080, output_height=1080,
            safe_area_margin=0.05,
            smoothing_strength=0.8,
            max_pan_speed=30.0,
            face_priority=0.6,
            motion_priority=0.4,
            fps=30,
        )

    @staticmethod
    def kick_to_youtube_shorts() -> ReframeProfile:
        return ReframeProfile(
            platform=ReframePlatform.YOUTUBE_SHORTS,
            source_width=1920, source_height=1080,
            output_width=1080, output_height=1920,
            safe_area_margin=0.05,
            smoothing_strength=0.8,
            max_pan_speed=30.0,
            face_priority=0.7,
            motion_priority=0.3,
            fps=60,
        )
```

## 5.6 FFmpeg Komut Ornekleri

### Kick -> TikTok (9:16)

```python
# Basit merkez crop (animasyonsuz)
ffmpeg -i kick_clip.mp4 \
  -filter_complex "[0:v]crop=608:1080:656:0,scale=1080:1920:flags=lanczos[out]" \
  -map "[out]" -map 0:a \
  -c:v h264_nvenc -preset p4 -b:v 4000k \
  -c:a aac -b:a 128k \
  tiktok_output.mp4
```

### Kick -> Instagram Feed (1:1)

```python
ffmpeg -i kick_clip.mp4 \
  -filter_complex "[0:v]crop=1080:1080:420:0,scale=1080:1080[out]" \
  -map "[out]" -map 0:a \
  -c:v h264_nvenc -preset p4 -b:v 3000k \
  -c:a aac -b:a 128k \
  instagram_feed.mp4
```

---

# 6. Motion Tracking

## 6.1 Amaç

Motion Tracking, videoda belirli nesnelerin, yuzlerin veya bolgelerin kareler arasi hareketini takip eden sistemdir. Dynamic crop ve auto reframe icin gerekli olan hareket verilerini saglar. Ayrica efekt, metin ve grafiklerin video uzerinde yerlestirilmesi icin track verisi sunar.

**Kullanim Alanlari:**
- Dynamic crop icin hareket takibi
- Auto reframe icin kamera hareket analizi
- Metin/grafik yerlestirme (motion tracking effects)
- Video stabilizasyonu
- Nesne takibi (spor, gaming, aksiyon)

## 6.2 Tracking Algoritmalari

```
Algoritma          | Hiz    | Dogruluk | Coklu Nesne | Gecikme
-------------------|--------|----------|-------------|--------
Optik Akis (Farne) | Orta   | Yuksek   | Hayir       | Dusuk
Lucas-Kanade       | Hizli  | Orta     | Hayir       | Cok Dusuk
Template Matching  | Cok Hz | Dusuk    | Hayir       | Cok Dusuk
ORB Features       | Hizli  | Orta     | Evet        | Dusuk
SIFT Features      | Yavas  | Cok Yks  | Evet        | Orta
CSRT Tracker       | Orta   | Cok Yks  | Hayir       | Orta
KCF Tracker        | Hizli  | Orta     | Hayir       | Dusuk
MOSSE Tracker      | Cok Hz | Orta     | Hayir       | Cok Dusuk
```

## 6.3 Veri Yapilari

```python
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class TrackMethod(Enum):
    OPTICAL_FLOW_FARNEBACK = auto()
    OPTICAL_FLOW_LUCAS_KANADE = auto()
    TEMPLATE_MATCHING = auto()
    ORB_FEATURES = auto()
    SIFT_FEATURES = auto()
    CSRT = auto()
    KCF = auto()
    MOSSE = auto()
    FACE_DETECTION = auto()


@dataclass
class TrackPoint:
    """Tek bir kare icin takip noktasi."""
    frame_number: int
    x: float
    y: float
    width: float = 0.0
    height: float = 0.0
    confidence: float = 1.0
    timestamp_ms: float = 0.0

    @property
    def center_x(self) -> float:
        return self.x + self.width / 2

    @property
    def center_y(self) -> float:
        return self.y + self.height / 2

    @property
    def center(self) -> tuple[float, float]:
        return (self.center_x, self.center_y)

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass
class TrackPath:
    """
    Bir nesnenin tum karelerdeki takip yolu.
    """
    object_id: str
    points: list[TrackPoint] = field(default_factory=list)
    method: TrackMethod = TrackMethod.CSRT
    label: str = ""

    def add_point(self, point: TrackPoint) -> None:
        self.points.append(point)

    def get_positions(self) -> list[tuple[float, float]]:
        return [(p.center_x, p.center_y) for p in self.points]

    def get_bounding_boxes(self) -> list[tuple[float, float, float, float]]:
        return [(p.x, p.y, p.width, p.height) for p in self.points]

    def get_velocities(self) -> list[tuple[float, float]]:
        """Her kare icin hiz vektoru (piksel/kare)."""
        velocities = []
        for i in range(1, len(self.points)):
            dx = self.points[i].center_x - self.points[i - 1].center_x
            dy = self.points[i].center_y - self.points[i - 1].center_y
            velocities.append((dx, dy))
        return velocities

    def get_accelerations(self) -> list[tuple[float, float]]:
        """Her kare icin ivme vektoru."""
        velocities = self.get_velocities()
        accelerations = []
        for i in range(1, len(velocities)):
            ax = velocities[i][0] - velocities[i - 1][0]
            ay = velocities[i][1] - velocities[i - 1][1]
            accelerations.append((ax, ay))
        return accelerations

    def smooth_path(self, window: int = 5) -> list[tuple[float, float]]:
        """Hareketli ortalama ile yolu yumusat."""
        positions = self.get_positions()
        if not positions or window <= 1:
            return positions

        smoothed = []
        half = window // 2
        for i in range(len(positions)):
            start = max(0, i - half)
            end = min(len(positions), i + half + 1)
            avg_x = sum(p[0] for p in positions[start:end]) / (end - start)
            avg_y = sum(p[1] for p in positions[start:end]) / (end - start)
            smoothed.append((avg_x, avg_y))
        return smoothed

    def get_bounding_box(self) -> tuple[float, float, float, float]:
        """Tum takip noktalarini iceren sinir kutusu."""
        if not self.points:
            return (0, 0, 0, 0)
        min_x = min(p.x for p in self.points)
        min_y = min(p.y for p in self.points)
        max_x = max(p.x + p.width for p in self.points)
        max_y = max(p.y + p.height for p in self.points)
        return (min_x, min_y, max_x - min_x, max_y - min_y)

    def export_for_effects(self) -> dict:
        """Efekt/yerlestirme icin export formati."""
        return {
            "object_id": self.object_id,
            "label": self.label,
            "method": self.method.name,
            "total_points": len(self.points),
            "positions": [
                {"frame": p.frame_number, "x": p.x, "y": p.y,
                 "w": p.width, "h": p.height, "conf": p.confidence}
                for p in self.points
            ],
            "smoothed_path": [
                {"x": x, "y": y}
                for x, y in self.smooth_path()
            ],
            "bbox": self.get_bounding_box(),
        }


@dataclass
class MotionTrack:
    """
    Video uzerindeki tum takip verilerini tutar.
    Coklu nesne takibi destegi.
    """
    tracks: dict[str, TrackPath] = field(default_factory=dict)
    video_width: int = 0
    video_height: int = 0
    total_frames: int = 0
    fps: float = 30.0
    tracking_time_ms: float = 0.0

    def add_track(self, track: TrackPath) -> None:
        self.tracks[track.object_id] = track

    def get_track(self, object_id: str) -> Optional[TrackPath]:
        return self.tracks.get(object_id)

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    def get_dominant_track(self) -> Optional[TrackPath]:
        """En cok takip edilen (en fazla noktaya sahip) yolu dondur."""
        if not self.tracks:
            return None
        return max(self.tracks.values(), key=lambda t: len(t.points))

    def get_all_positions_for_frame(self, frame_number: int) -> dict[str, tuple[float, float]]:
        """Belirli bir karedeki tum nesne konumlarini dondur."""
        result = {}
        for oid, track in self.tracks.items():
            for point in track.points:
                if point.frame_number == frame_number:
                    result[oid] = (point.center_x, point.center_y)
                    break
        return result
```

## 6.4 Tracking Motoru

```python
import cv2


class MotionTracker:
    """
    Video uzerinde coklu nesne takibi.
    Farkli tracking algoritmalarini destekler.
    """

    def __init__(
        self,
        method: TrackMethod = TrackMethod.CSRT,
        max_objects: int = 10,
        min_confidence: float = 0.3,
    ):
        self._method = method
        self._max_objects = max_objects
        self._min_confidence = min_confidence
        self._trackers: dict[str, cv2.Tracker] = {}
        self._feature_detector = None

        if method == TrackMethod.ORB_FEATURES:
            self._feature_detector = cv2.ORB_create(nfeatures=500)
        elif method == TrackMethod.SIFT_FEATURES:
            self._feature_detector = cv2.SIFT_create()

    def track_video(
        self,
        video_path: str,
        initial_regions: Optional[list[tuple[int, int, int, int]]] = None,
    ) -> MotionTrack:
        """
        Videoyu takip et.

        Args:
            video_path: Video dosya yolu
            initial_regions: Baslangic bolgeleri [(x,y,w,h), ...]
                             None ise otomatik yuz algilama kullanilir
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logger.error(f"Video acilamadi: {video_path}")
            return MotionTrack()

        src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        result = MotionTrack(
            video_width=src_w, video_height=src_h,
            total_frames=total_frames, fps=fps,
        )

        start_time = time.perf_counter()
        frame_idx = 0
        prev_gray = None
        active_trackers: dict[str, dict] = {}

        # Baslangic bolgeleri
        if initial_regions is None:
            initial_regions = self._auto_detect_initial_regions(cap)

        # Tracker'lari baslat
        for i, (x, y, w, h) in enumerate(initial_regions[:self._max_objects]):
            oid = f"obj_{i}"
            tracker = self._create_tracker()
            ret = tracker.init(
                cv2.cvtColor(cap.read()[1], cv2.COLOR_BGR2GRAY) if cap.read()[1] is not None else np.zeros((src_h, src_w), dtype=np.uint8),
                (x, y, w, h),
            )
            if ret:
                active_trackers[oid] = {
                    "tracker": tracker,
                    "last_bbox": (x, y, w, h),
                    "track_path": TrackPath(
                        object_id=oid, method=self._method,
                        label=f"Object {i}",
                    ),
                }

        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Her aktif tracker'i guncelle
            for oid, tracker_info in list(active_trackers.items()):
                tracker = tracker_info["tracker"]
                ret, bbox = tracker.update(gray)

                if ret:
                    x, y, w, h = bbox
                    confidence = self._estimate_confidence(
                        gray, x, y, w, h, tracker_info["last_bbox"],
                    )

                    point = TrackPoint(
                        frame_number=frame_idx,
                        x=float(x), y=float(y),
                        width=float(w), height=float(h),
                        confidence=confidence,
                        timestamp_ms=frame_idx * 1000 / fps,
                    )
                    tracker_info["track_path"].add_point(point)
                    tracker_info["last_bbox"] = (x, y, w, h)
                else:
                    logger.debug(f"Tracker {oid} kayboldu kare {frame_idx}")

            # Optik akis ile kaybolan tracker'lari kurtarmaya calis
            if prev_gray is not None and self._method in (
                TrackMethod.OPTICAL_FLOW_FARNEBACK, TrackMethod.OPTICAL_FLOW_LUCAS_KANADE
            ):
                self._retrack_with_optical_flow(
                    prev_gray, gray, active_trackers, frame_idx, fps,
                )

            prev_gray = gray
            frame_idx += 1

        cap.release()

        # Track path'leri sonuc'a ekle
        for oid, info in active_trackers.items():
            result.add_track(info["track_path"])

        result.tracking_time_ms = (time.perf_counter() - start_time) * 1000
        return result

    def _create_tracker(self) -> cv2.Tracker:
        """Seçilen yonteme gore tracker olustur."""
        if self._method == TrackMethod.CSRT:
            return cv2.TrackerCSRT_create()
        elif self._method == TrackMethod.KCF:
            return cv2.TrackerKCF_create()
        elif self._method == TrackMethod.MOSSE:
            return cv2.TrackerMOSSE_create()
        else:
            return cv2.TrackerCSRT_create()

    def _auto_detect_initial_regions(
        self, cap: cv2.VideoCapture,
    ) -> list[tuple[int, int, int, int]]:
        """Otomatik baslangic bolgeleri tespit et (yuz algilama)."""
        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        ret, frame = cap.read()
        if not ret:
            return []

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50),
        )

        regions = []
        for (x, y, w, h) in sorted(faces, key=lambda f: f[2] * f[3], reverse=True):
            # Yuz etrafinda %30 bosluk ekle
            margin_x = int(w * 0.3)
            margin_y = int(h * 0.3)
            x = max(0, x - margin_x)
            y = max(0, y - margin_y)
            w = w + margin_x * 2
            h = h + margin_y * 2
            regions.append((x, y, w, h))

        return regions[:self._max_objects]

    def _estimate_confidence(
        self, gray: np.ndarray, x: int, y: int, w: int, h: int,
        prev_bbox: tuple[int, int, int, int],
    ) -> float:
        """Takip guven skorunu tahmin et."""
        if w <= 0 or h <= 0:
            return 0.0

        # Gorsel homojenligi kontrol et (dusuk homojenlik = guvensiz)
        roi = gray[y:min(y + h, gray.shape[0]), x:min(x + w, gray.shape[1])]
        if roi.size == 0:
            return 0.0

        std_dev = np.std(roi) / 255.0

        # Onceki bolge ile overlap
        px, py, pw, ph = prev_bbox
        ix1 = max(x, px)
        iy1 = max(y, py)
        ix2 = min(x + w, px + pw)
        iy2 = min(y + h, py + ph)
        intersection = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        union = w * h + pw * ph - intersection
        iou = intersection / max(union, 1)

        confidence = 0.5 * std_dev + 0.5 * iou
        return max(0.0, min(1.0, confidence))

    def _retrack_with_optical_flow(
        self, prev_gray, curr_gray, trackers, frame_idx, fps,
    ) -> None:
        """Optik akis ile kaybolan nesneleri tekrar bul."""
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, curr_gray, None,
            pyr_scale=0.5, levels=3, winsize=15,
            iterations=3, poly_n=5, poly_sigma=1.2, flags=0,
        )
        magnitude, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])

        # Buyuk hareket bolgelerini tespit et
        motion_threshold = np.percentile(magnitude, 95)
        hotspots = np.where(magnitude > motion_threshold)

        if len(hotspots[0]) > 0:
            cy = np.mean(hotspots[0])
            cx = np.mean(hotspots[1])

            # Yeni tracker baslat
            for oid, info in trackers.items():
                if info["last_bbox"] == (0, 0, 0, 0):
                    new_tracker = self._create_tracker()
                    search_size = 100
                    x1 = max(0, int(cx - search_size / 2))
                    y1 = max(0, int(cy - search_size / 2))
                    new_tracker.init(curr_gray, (x1, y1, search_size, search_size))
                    info["tracker"] = new_tracker
                    info["last_bbox"] = (x1, y1, search_size, search_size)


class MultiObjectTracker:
    """
    Coklu nesne takibi yoneticisi.
    Farkli nesneler icin farkli algoritmalar kullanabilir.
    """

    def __init__(self, video_width: int, video_height: int, fps: float = 30):
        self._video_width = video_width
        self._video_height = video_height
        self._fps = fps
        self._trackers: dict[str, MotionTracker] = {}
        self._results: dict[str, MotionTrack] = {}

    def add_tracker(
        self, object_id: str, method: TrackMethod = TrackMethod.CSRT, label: str = "",
    ) -> None:
        self._trackers[object_id] = MotionTracker(method=method)
        logger.info(f"Tracker eklendi: {object_id} ({method.name})")

    def track_all(self, video_path: str) -> MotionTrack:
        """Tum tracker'lari paralel olarak calistir."""
        combined = MotionTrack(
            video_width=self._video_width,
            video_height=self._video_height,
            fps=self._fps,
        )

        for oid, tracker in self._trackers.items():
            result = tracker.track_video(video_path)
            for track_id, track in result.tracks.items():
                new_id = f"{oid}_{track_id}"
                track.object_id = new_id
                combined.add_track(track)

        return combined
```

## 6.5 Track Yumusatma ve Stabilizasyon

```python
class TrackSmoother:
    """
    Takip verilerini yumusat ve video stabilizasyonu icin kullanilabilir
    hale getir.
    """

    @staticmethod
    def smooth_savitzky_golay(
        positions: list[tuple[float, float]], window: int = 11, poly: int = 3,
    ) -> list[tuple[float, float]]:
        """
        Savitzky-Golay filtresi ile yumusatma.
        Daha dogal gorunen kamer hareketi saglar.
        """
        from scipy.signal import savgol_filter

        if len(positions) < window:
            return positions

        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]

        smooth_x = savgol_filter(xs, window, poly)
        smooth_y = savgol_filter(ys, window, poly)

        return list(zip(smooth_x.tolist(), smooth_y.tolist()))

    @staticmethod
    def smooth_kalman(
        positions: list[tuple[float, float]],
        process_noise: float = 1e-3,
        measurement_noise: float = 1e-1,
    ) -> list[tuple[float, float]]:
        """
        Kalman filtresi ile yumusatma.
        Gercek zamanli isleme icin uygundur.
        """
        if not positions:
            return []

        # Durum: [x, y, vx, vy]
        state = np.array([positions[0][0], positions[0][1], 0.0, 0.0])
        P = np.eye(4) * 100  # Baslangic kovaryansi

        # Donusum matrisi (durusum modeli)
        F = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])

        # Olcum matrisi
        H = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ])

        # Process noise
        Q = np.eye(4) * process_noise

        # Measurement noise
        R = np.eye(2) * measurement_noise

        smoothed = []
        for x, y in positions:
            # Tahmin
            state = F @ state
            P = F @ P @ F.T + Q

            # Guncelleme
            z = np.array([x, y])
            y_residual = z - H @ state
            S = H @ P @ H.T + R
            K = P @ H.T @ np.linalg.inv(S)
            state = state + K @ y_residual
            P = (np.eye(4) - K @ H) @ P

            smoothed.append((float(state[0]), float(state[1])))

        return smoothed

    @staticmethod
    def smooth_exponential_moving_average(
        positions: list[tuple[float, float]], alpha: float = 0.3,
    ) -> list[tuple[float, float]]:
        """
        Ustel hareketli ortalama (EMA) ile yumusatma.
        alpha yukseldikce daha responsive, dustukce daha yumusak.
        """
        if not positions:
            return []

        smoothed = [positions[0]]
        for i in range(1, len(positions)):
            sx = alpha * positions[i][0] + (1 - alpha) * smoothed[-1][0]
            sy = alpha * positions[i][1] + (1 - alpha) * smoothed[-1][1]
            smoothed.append((sx, sy))

        return smoothed


class VideoStabilizer:
    """
    Takip verilerini kullanarak video stabilizasyonu.

    Sarsilmali kamerali videolari duzeltmek icin kullanilir.
    """

    def __init__(self, crop_margin: float = 0.05):
        self._crop_margin = crop_margin

    def stabilize_from_track(
        self, track: MotionTrack, source_width: int, source_height: int,
    ) -> list[tuple[int, int]]:
        """
        Takip verisinden stabilizasyon ofsetleri hesapla.

        Returns:
            Her kare icin (dx, dy) ofsetleri
        """
        dominant = track.get_dominant_track()
        if not dominant or len(dominant.points) < 2:
            return [(0, 0)] * track.total_frames

        positions = dominant.get_positions()
        smoothed = TrackSmoother.smooth_savitzky_golay(positions, window=11)

        offsets = []
        for i in range(len(positions)):
            dx = int(positions[i][0] - smoothed[i][0])
            dy = int(positions[i][1] - smoothed[i][1])
            offsets.append((dx, dy))

        return offsets

    def build_stabilize_ffmpeg_command(
        self, input_path: str, output_path: str,
        offsets: list[tuple[int, int]],
    ) -> str:
        """
        Stabilizasyon icin FFmpeg crop filter expression olustur.
        """
        if not offsets:
            return ""

        # Basit stabilize: ortalamadan sapmalari hesapla
        avg_dx = sum(o[0] for o in offsets) / len(offsets)
        avg_dy = sum(o[1] for o in offsets) / len(offsets)

        # Crop ile sabit merkez korunur
        crop_expr = f"crop=iw-{int(abs(avg_dx)*2)}:ih-{int(abs(avg_dy)*2)}:{int(abs(avg_dx))}:{int(abs(avg_dy))}"

        return f"ffmpeg -i {input_path} -vf \"{crop_expr}\" {output_path}"
```

## 6.6 Track Export/Import

```python
import json
from pathlib import Path


class TrackIO:
    """
    Takip verilerini dosyaya kaydet/yukle.
    Efekt, metin ve grafik yerlestirme icin kullanilir.
    """

    @staticmethod
    def export_track(track: TrackPath, output_path: str) -> None:
        """Takip verisini JSON dosyasina kaydet."""
        data = track.export_for_effects()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Track export edildi: {output_path} ({len(track.points)} nokta)")

    @staticmethod
    def import_track(input_path: str) -> TrackPath:
        """JSON dosyasindan takip verisi yukle."""
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        track = TrackPath(
            object_id=data["object_id"],
            method=TrackMethod[data["method"]],
            label=data.get("label", ""),
        )

        for p in data.get("positions", []):
            track.add_point(TrackPoint(
                frame_number=p["frame"],
                x=p["x"], y=p["y"],
                width=p.get("w", 0), height=p.get("h", 0),
                confidence=p.get("conf", 1.0),
            ))

        return track

    @staticmethod
    def export_motion_track(motion_track: MotionTrack, output_path: str) -> None:
        """Tam MotionTrack verisini export et."""
        data = {
            "video_width": motion_track.video_width,
            "video_height": motion_track.video_height,
            "total_frames": motion_track.total_frames,
            "fps": motion_track.fps,
            "tracks": {},
        }
        for oid, track in motion_track.tracks.items():
            data["tracks"][oid] = track.export_for_effects()

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    @staticmethod
    def import_motion_track(input_path: str) -> MotionTrack:
        """JSON dosyasindan MotionTrack yukle."""
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        mt = MotionTrack(
            video_width=data["video_width"],
            video_height=data["video_height"],
            total_frames=data["total_frames"],
            fps=data["fps"],
        )

        for oid, tdata in data.get("tracks", {}).items():
            track = TrackPath(
                object_id=oid,
                method=TrackMethod[tdata["method"]],
                label=tdata.get("label", ""),
            )
            for p in tdata.get("positions", []):
                track.add_point(TrackPoint(
                    frame_number=p["frame"], x=p["x"], y=p["y"],
                    width=p.get("w", 0), height=p.get("h", 0),
                    confidence=p.get("conf", 1.0),
                ))
            mt.add_track(track)

        return mt
```

## 6.7 Entegrasyon Ornegi: Kick Klip Icin Tam Pipeline

```python
class KickClipPipeline:
    """
    Kick canli yayin klipleri icin tam isleme pipeline'i.
    Track -> Crop -> Reframe -> Encode.
    """

    async def process_clip(
        self,
        input_path: str,
        output_path: str,
        target_platform: ReframePlatform = ReframePlatform.TIKTOK,
        target_codec: str = "h264",
        enable_stabilization: bool = False,
    ) -> dict:
        """
        Kick klip isleme pipeline'i.

        Adimlar:
        1. Videoyu analiz et (tracking)
        2. Reframe takip noktalarini olustur
        3. Crop keyframe'leri hesapla
        4. FFmpeg komutu olustur ve calistir
        5. Sonuclari kaydet
        """
        import subprocess
        start_time = time.perf_counter()

        # 1. Reframe profili olustur
        profile = ReframeProfile(
            platform=target_platform,
            source_width=1920,
            source_height=1080,
            fps=60,
        )

        # 2. Auto reframe analizi
        engine = AutoReframeEngine(profile)
        track = engine.analyze_video(input_path)

        # 3. Crop keyframe'leri
        keyframes = engine.generate_crop_keyframes(track)

        # 4. FFmpeg komutu olustur
        encoder_config = HWEncoderConfig(
            encoder_type=HWEncoderType.NVENC,
            codec=VideoCodec.H264 if target_codec == "h264" else VideoCodec.HEVC,
            preset=EncodingPreset.NVENC_P4,
            rate_control=RateControlMode.CQ,
            cq_level=23,
            target_bitrate_kbps=4000,
            max_bitrate_kbps=6000,
        )

        cmd = engine.build_ffmpeg_command(
            input_path, output_path, keyframes, encoder_config,
        )

        # 5. FFmpeg calistir
        logger.info(f"FFmpeg komutu: {' '.join(cmd)}")
        process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        elapsed = (time.perf_counter() - start_time) * 1000

        # 6. Track verisini kaydet
        track_path = output_path.replace(".mp4", "_track.json")
        TrackIO.export_motion_track(track, track_path)

        return {
            "output_path": output_path,
            "track_path": track_path,
            "platform": target_platform.value,
            "output_resolution": f"{profile.output_width}x{profile.output_height}",
            "total_frames": track.total_frames,
            "face_coverage": f"{track.face_coverage:.1%}",
            "keyframe_count": len(keyframes),
            "processing_time_ms": round(elapsed, 1),
            "success": process.returncode == 0,
        }
```

## 6.8 Performans Optimizasyonlari

```
Teknik                    | Hiz Kazanci  | Iyilestirme Alani
--------------------------|---------------|------------------
ROI (Region of Interest)  | %40-60       | Tam kare yerine bolge takibi
Pyrdown on-isleme         | %30-50       | Kucuk boyutta takip, buyuk koordinat
Frame atlama              | %50-70       | Her 2-3 karede bir takip
GPU Optik Akis            | %200-400     | CUDA-based optical flow
Paralel tracker           | %100-200     # Coklu tracker ayni anda
Adaptive resolution       | %30-50       # Hareket yuksekken kucuk, dusukken buyuk
```

## 6.9 Hata Yonetimi ve Fallback

```python
class TrackingFallbackManager:
    """Tracking basarisiz oldugunda fallback stratejileri yonetir."""

    def __init__(self):
        self._strategies = [
            TrackMethod.CSRT,
            TrackMethod.KCF,
            TrackMethod.MOSSE,
            TrackMethod.OPTICAL_FLOW_FARNEBACK,
        ]

    def track_with_fallback(
        self, video_path: str, initial_regions: list[tuple[int, int, int, int]],
    ) -> MotionTrack:
        """Her strateji basarisiz olana kadar dene."""
        for method in self._strategies:
            try:
                tracker = MotionTracker(method=method)
                result = tracker.track_video(video_path, initial_regions)
                if result.track_count > 0:
                    dominant = result.get_dominant_track()
                    if dominant and len(dominant.points) > result.total_frames * 0.5:
                        logger.info(f"Tracking basarili: {method.name}")
                        return result
            except Exception as e:
                logger.warning(f"Tracking basarisiz ({method.name}): {e}")
                continue

        # Tum stratejiler basarisiz: sabit merkez fallback
        logger.error("Tum tracking stratejileri basarisiz, merkez fallback kullaniliyor")
        return self._create_center_fallback(video_path)

    def _create_center_fallback(self, video_path: str) -> MotionTrack:
        """Merkez noktali fallback takip olustur."""
        cap = cv2.VideoCapture(video_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()

        track = MotionTrack(video_width=w, video_height=h, total_frames=total)
        path = TrackPath(object_id="center_fallback", method=TrackMethod.FACE_DETECTION, label="Center")

        for i in range(total):
            path.add_point(TrackPoint(
                frame_number=i, x=w / 4, y=h / 4,
                width=w / 2, height=h / 2, confidence=0.1,
            ))

        track.add_track(path)
        return track
```

## 6.10 Entegrasyon Noktalari

```
FastAPI Endpoints:
  POST /api/v1/tracking/analyze
    - Video analizi baslat
    - Method parametresi: csrt, kcf, optical_flow, orb
    - Returns: track_id, total_frames, track_count

  GET /api/v1/tracking/{track_id}
    - Takip sonucunu al
    - Returns: MotionTrack JSON

  POST /api/v1/tracking/{track_id}/export
    - Takip verisini export et
    - Format: JSON, CSV

  POST /api/v1/pipeline/process
    - Tam pipeline: track -> reframe -> encode
    - Input: video_url, platform, codec
    - Returns: output_url, track_url, metadata

  GET /api/v1/tracking/{track_id}/status
    - Takip durumunu sorgula
    - Returns: progress, estimated_time, errors
```

---

*Bu belge Tuncay-klip GPU video isleme altyapisinin kapsamli teknik tasarimini sunmaktadir. Her bolum, amaci, mimariyi, veri yapilarini, algoritmalari, API sozlesmelerini, performans darboğazlarini ve cozumleri icerir.*

