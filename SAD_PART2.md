# SOFTWARE ARCHITECTURE DOCUMENT (SAD) — PART 2
# GPU Pipeline, Model Optimization & Inference Engine

---

# PART 6 — GPU PIPELINE

## 6.1 CUDA Fundamentals

### Neden GPU?

Video analiz pipeline'ında GPU kullanımı **zorunluluktur**, seçenek değildir:

```
Frame Analysis Latency Comparison (1080p single frame):

                    CPU (i7-12700K)    GPU (RTX 3080)    Speedup
Face Detection:     120 ms             3 ms              40x
Emotion Recognition: 85 ms            2 ms              42x
Pose Estimation:    95 ms             4 ms              24x
Object Detection:   110 ms            3 ms              37x
OCR:                200 ms            8 ms              25x
─────────────────────────────────────────────────────────────────
TOTAL (sequential): 610 ms            20 ms             30x
TOTAL (batched):    610 ms            8 ms              76x

At 2 FPS (500ms between frames):
  CPU: 610ms > 500ms → FRAME DROP, backlog accumulates
  GPU: 8ms << 500ms → Plenty of headroom for batch processing
```

### CUDA Execution Model

```
┌────────────────────────────────────────────────────────────┐
│                    NVIDIA GPU                               │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐        │
│  │   SM 0      │  │   SM 1      │  │   SM N      │        │
│  │ ┌───┐┌───┐ │  │ ┌───┐┌───┐ │  │ ┌───┐┌───┐ │        │
│  │ │CU ││CU │ │  │ │CU ││CU │ │  │ │CU ││CU │ │        │
│  │ └───┘└───┘ │  │ └───┘└───┘ │  │ └───┘└───┘ │        │
│  │ Shared Mem  │  │ Shared Mem  │  │ Shared Mem  │        │
│  └─────────────┘  └─────────────┘  └─────────────┘        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Global Memory (VRAM)                     │   │
│  │  RTX 3080: 10 GB    RTX 4090: 24 GB                 │   │
│  └─────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────┘

For our inference pipeline:
  - Model weights loaded into VRAM once (~2GB total for all models)
  - Frame data copied CPU→GPU per inference (~6MB per 1080p frame)
  - Inference runs on CUDA cores in parallel
  - Results copied GPU→CPU (~1KB per detection)
```

### CUDA Memory Transfer Optimization

```python
# services/video-analysis/inference/cuda_utils.py

import torch
import numpy as np

class CUDAMemoryManager:
    """
    Manages GPU memory for inference pipeline.

    Key optimizations:
    1. Pre-allocate GPU tensors (avoid allocation overhead)
    2. Use pinned memory for CPU→GPU transfers (2x faster)
    3. Reuse GPU buffers across frames
    4. Monitor VRAM usage to prevent OOM
    """

    def __init__(self, device: str = "cuda:0"):
        self.device = torch.device(device)
        self._preallocated: dict[str, torch.Tensor] = {}

        # Log GPU info
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_total = torch.cuda.get_device_properties(0).total_mem / 1e9
            logger.info(f"GPU: {gpu_name}, VRAM: {vram_total:.1f} GB")

    def create_pinned_buffer(self, name: str, shape: tuple, dtype=torch.float32):
        """
        Create a pinned (page-locked) CPU tensor.
        Pinned memory enables faster CPU→GPU DMA transfers.

        Normal transfer:  CPU buffer → staging buffer → GPU
        Pinned transfer:  CPU pinned buffer → GPU  (direct DMA, 2x faster)
        """
        pinned = torch.empty(shape, dtype=dtype, pin_memory=True)
        self._preallocated[f"pinned_{name}"] = pinned
        return pinned

    def create_gpu_buffer(self, name: str, shape: tuple, dtype=torch.float32):
        """Pre-allocate a GPU tensor to avoid runtime allocation"""
        gpu_tensor = torch.empty(shape, dtype=dtype, device=self.device)
        self._preallocated[f"gpu_{name}"] = gpu_tensor
        return gpu_tensor

    def frame_to_gpu(self, frame_bgr: np.ndarray) -> torch.Tensor:
        """
        Convert OpenCV BGR frame to GPU tensor efficiently.

        Pipeline:
        numpy BGR (H,W,3) uint8
            → torch tensor (pinned)
            → .to(device) [async copy]
            → permute to (3,H,W) [channel first]
            → normalize to [0,1]
        """
        # Use pre-allocated pinned buffer if available
        key = "pinned_frame"
        if key in self._preallocated:
            pinned = self._preallocated[key]
            # Copy numpy to pinned (fast, no allocation)
            torch.from_numpy(frame_bgr).to(pinned, non_blocking=False)
        else:
            pinned = torch.from_numpy(frame_bgr).pin_memory()

        # Async copy to GPU
        gpu_frame = pinned.to(self.device, non_blocking=True)

        # Convert BGR → RGB, HWC → CHW, uint8 → float32 [0,1]
        gpu_frame = gpu_frame.permute(2, 0, 1).float() / 255.0

        return gpu_frame

    def get_vram_usage(self) -> dict:
        """Monitor GPU memory usage"""
        if not torch.cuda.is_available():
            return {"available": False}

        allocated = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        total = torch.cuda.get_device_properties(0).total_mem / 1e9

        return {
            "available": True,
            "allocated_gb": round(allocated, 3),
            "reserved_gb": round(reserved, 3),
            "total_gb": round(total, 1),
            "utilization_pct": round(allocated / total * 100, 1),
        }
```

## 6.2 TensorRT

### Nedir ve Neden Kullanılır?

**TensorRT**, NVIDIA'nın inference optimization engine'idir. PyTorch/ONNX modellerini GPU-specific optimize eder:

```
Model Optimization Pipeline:

PyTorch Model (.pt)
    │
    ▼
ONNX Export (.onnx)
    │
    ▼
TensorRT Builder
    │
    ├─→ Layer Fusion          (Conv + BN + ReLU → tek kernel)
    ├─→ Precision Calibration  (FP32 → FP16 → INT8)
    ├─→ Kernel Auto-Tuning    (GPU-specific en iyi kernel seçimi)
    ├─→ Memory Optimization    (intermediate buffer'ları minimize)
    └─→ Dynamic Shapes        (farklı input boyutları için plan)
    │
    ▼
TensorRT Engine (.engine)
    │
    ▼
Runtime Inference (2-10x faster than PyTorch)
```

### Performance Comparison

```
Face Detection Model (RetinaFace, 640x640 input):

                    PyTorch FP32    ONNX FP32    TensorRT FP16    TensorRT INT8
RTX 3080:           12 ms          8 ms         3 ms             2 ms
RTX 4090:           6 ms           4 ms         1.5 ms           1 ms
Accuracy:           100%           100%         99.8%            98.5%

Emotion Recognition (ViT-base, 224x224 input):

                    PyTorch FP32    ONNX FP32    TensorRT FP16    TensorRT INT8
RTX 3080:           8 ms           5 ms         2 ms             1.5 ms
Accuracy:           100%           100%         99.9%            99.2%
```

### TensorRT Implementation

```python
# services/video-analysis/inference/tensorrt_runner.py

import tensorrt as trt
import numpy as np

class TensorRTRunner:
    """
    TensorRT inference engine.

    Lifecycle:
    1. Build engine from ONNX (one-time, ~5 minutes per model)
    2. Save engine to disk (.engine file)
    3. Load engine at service startup (~2 seconds)
    4. Run inference (~1-5ms per frame)

    The engine is hardware-specific and GPU-specific.
    An engine built on RTX 3080 won't work on RTX 4090.
    Rebuild when changing GPU hardware.
    """

    def __init__(
        self,
        onnx_path: str,
        engine_path: str,
        precision: str = "fp16",  # "fp32", "fp16", "int8"
        max_batch_size: int = 8,
        workspace_gb: float = 4.0,
    ):
        self.onnx_path = onnx_path
        self.engine_path = engine_path
        self.precision = precision
        self.max_batch_size = max_batch_size
        self.workspace_gb = workspace_gb

        # TensorRT logger
        self.trt_logger = trt.Logger(trt.Logger.WARNING)

        # Will be initialized in build/load
        self.engine = None
        self.context = None
        self.input_shape = None
        self.output_shapes = []

    def build_engine(self):
        """
        Build TensorRT engine from ONNX model.
        This is a one-time operation (5-15 minutes).
        """
        logger.info(f"Building TensorRT engine from {self.onnx_path}...")
        logger.info(f"Precision: {self.precision}, Max batch: {self.max_batch_size}")

        builder = trt.Builder(self.trt_logger)
        network = builder.create_network(
            1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
        )
        parser = trt.OnnxParser(network, self.trt_logger)

        # Parse ONNX model
        with open(self.onnx_path, "rb") as f:
            if not parser.parse(f.read()):
                for error in range(parser.num_errors):
                    logger.error(f"ONNX parse error: {parser.get_error(error)}")
                raise RuntimeError("Failed to parse ONNX model")

        # Create builder config
        config = builder.create_builder_config()
        config.set_memory_pool_limit(
            trt.MemoryPoolType.WORKSPACE,
            int(self.workspace_gb * (1 << 30)),
        )

        # Set precision
        if self.precision == "fp16":
            config.set_flag(trt.BuilderFlag.FP16)
        elif self.precision == "int8":
            config.set_flag(trt.BuilderFlag.INT8)
            # INT8 requires calibration data
            config.int8_calibrator = Int8Calibrator(self.calibration_data)

        # Set optimization profile for dynamic batch sizes
        profile = builder.create_optimization_profile()
        input_name = network.get_input(0).name
        input_shape = network.get_input(0).shape  # e.g., (-1, 3, 640, 640)

        # Define min/opt/max shapes
        min_shape = (1, *input_shape[1:])
        opt_shape = (min(4, self.max_batch_size), *input_shape[1:])
        max_shape = (self.max_batch_size, *input_shape[1:])

        profile.set_shape(input_name, min_shape, opt_shape, max_shape)
        config.add_optimization_profile(profile)

        # Build engine
        logger.info("Building engine (this may take 5-15 minutes)...")
        engine_bytes = builder.build_serialized_network(network, config)

        if engine_bytes is None:
            raise RuntimeError("Failed to build TensorRT engine")

        # Save engine
        with open(self.engine_path, "wb") as f:
            f.write(engine_bytes)

        logger.info(f"Engine saved to {self.engine_path}")

        # Load the engine
        self._load_engine()

    def _load_engine(self):
        """Load pre-built TensorRT engine"""
        runtime = trt.Runtime(self.trt_logger)

        with open(self.engine_path, "rb") as f:
            self.engine = runtime.deserialize_cuda_engine(f.read())

        self.context = self.engine.create_execution_context()

        # Get input/output shapes
        for i in range(self.engine.num_io_tensors):
            name = self.engine.get_tensor_name(i)
            mode = self.engine.get_tensor_mode(name)
            shape = self.engine.get_tensor_shape(name)

            if mode == trt.TensorIOMode.INPUT:
                self.input_shape = shape
            else:
                self.output_shapes.append((name, shape))

    def infer(self, input_data: np.ndarray) -> list[np.ndarray]:
        """
        Run inference on input data.

        Args:
            input_data: numpy array, shape=(batch, C, H, W), dtype=float32

        Returns:
            List of output numpy arrays
        """
        import cupy as cp  # CuPy for GPU array operations

        # Set input shape
        batch_size = input_data.shape[0]
        input_shape = (batch_size, *self.input_shape[1:])
        self.context.set_input_shape(
            self.engine.get_tensor_name(0),
            input_shape,
        )

        # Copy input to GPU
        d_input = cp.asarray(input_data)

        # Allocate output buffers
        outputs = []
        d_outputs = []
        for name, shape in self.output_shapes:
            out_shape = (batch_size, *shape[1:])
            d_out = cp.empty(out_shape, dtype=cp.float32)
            d_outputs.append(d_out)
            outputs.append(out_shape)

        # Set tensor addresses
        self.context.set_tensor_address(
            self.engine.get_tensor_name(0),
            d_input.data.ptr,
        )
        for i, (name, _) in enumerate(self.output_shapes):
            self.context.set_tensor_address(
                name,
                d_outputs[i].data.ptr,
            )

        # Execute inference
        self.context.execute_async_v3(cp.cuda.Stream.null.ptr)

        # Copy results back to CPU
        results = [cp.asnumpy(d_out) for d_out in d_outputs]

        return results


class Int8Calibrator:
    """
    INT8 calibration requires a representative dataset.
    This class provides calibration data from sample frames.
    """

    def __init__(self, calibration_data: list[np.ndarray], batch_size: int = 4):
        self.data = calibration_data
        self.batch_size = batch_size
        self.current_index = 0

    def get_batch(self):
        """Return next batch of calibration data"""
        batch = self.data[self.current_index:self.current_index + self.batch_size]
        self.current_index += self.batch_size
        return [np.stack(batch)]

    def get_batch_size(self):
        return self.batch_size
```

## 6.3 ONNX Runtime

### TensorRT vs ONNX Runtime — Ne Zaman Hangisi?

```
┌─────────────────────┬───────────────────────┬───────────────────────┐
│                     │ TensorRT              │ ONNX Runtime           │
├─────────────────────┼───────────────────────┼───────────────────────┤
│ Speed               │ En hızlı (optimized)  │ Hızlı (near-TensorRT) │
│ Portability         │ NVIDIA GPU only       │ CPU + GPU + NPU        │
│ Build time          │ 5-15 min per model    │ Instant               │
│ Precision           │ FP32/FP16/INT8       │ FP32/FP16              │
│ Dynamic shapes      │ Sınırlı              │ İyi destek             │
│ Setup complexity    │ Yüksek (CUDA toolkit) │ Orta (pip install)     │
│ GPU required        │ Evet (NVIDIA)         │ Hayır (CPU da çalışır) │
│ Model hot-reload    │ Zor (rebuild gerekir) │ Kolay                  │
└─────────────────────┴───────────────────────┴───────────────────────┘

Bizim stratejimiz:
  - Production: TensorRT FP16 (maximum speed)
  - Development: ONNX Runtime (hızlı iterasyon)
  - Fallback: ONNX Runtime CPU (GPU yoksa)
  - Model testing: ONNX Runtime (TensorRT build süresini bekleme)
```

### ONNX Runtime Implementation

```python
# services/video-analysis/inference/onnx_runner.py

import onnxruntime as ort
import numpy as np
from typing import Optional

class ONNXRunner:
    """
    ONNX Runtime inference engine.

    Supports multiple execution providers:
    1. TensorrtExecutionProvider (NVIDIA GPU, TensorRT)
    2. CUDAExecutionProvider (NVIDIA GPU, vanilla CUDA)
    3. CPUExecutionProvider (fallback)

    Priority: TensorRT > CUDA > CPU
    """

    def __init__(
        self,
        model_path: str,
        providers: Optional[list[str]] = None,
        session_options: Optional[dict] = None,
    ):
        self.model_path = model_path

        # Provider priority
        if providers is None:
            self.providers = self._detect_providers()
        else:
            self.providers = providers

        # Session options
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opts.intra_op_num_threads = 4
        opts.inter_op_num_threads = 2
        opts.log_severity_level = 3  # Suppress warnings

        if session_options:
            for key, value in session_options.items():
                setattr(opts, key, value)

        # Create session
        logger.info(f"Loading ONNX model: {model_path}")
        logger.info(f"Execution providers: {self.providers}")

        self.session = ort.InferenceSession(
            model_path,
            sess_options=opts,
            providers=self.providers,
        )

        # Get model metadata
        self.input_names = [inp.name for inp in self.session.get_inputs()]
        self.output_names = [out.name for out in self.session.get_outputs()]
        self.input_shapes = {
            inp.name: inp.shape for inp in self.session.get_inputs()
        }

        logger.info(f"Model inputs: {self.input_shapes}")

    def _detect_providers(self) -> list[str]:
        """Auto-detect available execution providers"""
        available = ort.get_available_providers()
        priority = [
            "TensorrtExecutionProvider",
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]

        selected = [p for p in priority if p in available]
        if not selected:
            selected = ["CPUExecutionProvider"]

        return selected

    def infer(self, inputs: dict[str, np.ndarray]) -> list[np.ndarray]:
        """
        Run inference.

        Args:
            inputs: dict mapping input names to numpy arrays

        Returns:
            List of output numpy arrays
        """
        return self.session.run(self.output_names, inputs)

    def infer_single(self, input_name: str, data: np.ndarray) -> list[np.ndarray]:
        """Convenience method for single-input models"""
        return self.session.run(self.output_names, {input_name: data})

    def warmup(self, iterations: int = 5):
        """
        Run dummy inferences to warm up CUDA kernels.
        First few inferences are slower due to lazy initialization.
        """
        for name, shape in self.input_shapes.items():
            # Replace dynamic dimensions with concrete values
            concrete_shape = []
            for dim in shape:
                if isinstance(dim, str) or dim is None or dim < 0:
                    concrete_shape.append(1)  # batch=1 for warmup
                else:
                    concrete_shape.append(dim)

            dummy = np.random.randn(*concrete_shape).astype(np.float32)
            for _ in range(iterations):
                self.session.run(self.output_names, {name: dummy})

        logger.info(f"Warmup complete: {iterations} iterations")
```

## 6.4 Model Optimization Pipeline

### Full Pipeline: PyTorch → ONNX → TensorRT

```python
# services/video-analysis/inference/model_optimizer.py

import torch
import onnx
from onnxsim import simplify

class ModelOptimizer:
    """
    End-to-end model optimization pipeline.

    Flow:
    PyTorch Model (.pt)
        │
        ├─→ TorchScript trace (optional)
        │
        ├─→ ONNX Export
        │     ├─→ Opset 17 (latest stable)
        │     ├─→ Dynamic axes (batch, height, width)
        │     └─→ Constant folding
        │
        ├─→ ONNX Simplification
        │     ├─→ Shape inference
        │     ├─→ Dead code elimination
        │     └─→ Operator fusion
        │
        ├─→ Quantization (optional)
        │     ├─→ Dynamic quantization (INT8 weights)
        │     └─→ Static quantization (INT8 weights + activations)
        │
        └─→ TensorRT Engine Build
              ├─→ FP16 precision (2x speedup, minimal accuracy loss)
              └─→ INT8 precision (4x speedup, needs calibration)
    """

    @staticmethod
    def pytorch_to_onnx(
        model: torch.nn.Module,
        dummy_input: torch.Tensor,
        output_path: str,
        input_names: list[str] = None,
        output_names: list[str] = None,
        dynamic_axes: dict = None,
        opset_version: int = 17,
    ):
        """Export PyTorch model to ONNX format"""

        model.eval()
        model.cuda()
        dummy_input = dummy_input.cuda()

        if input_names is None:
            input_names = ["input"]
        if output_names is None:
            output_names = ["output"]
        if dynamic_axes is None:
            dynamic_axes = {
                "input": {0: "batch_size"},
                "output": {0: "batch_size"},
            }

        torch.onnx.export(
            model,
            dummy_input,
            output_path,
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
            opset_version=opset_version,
            do_constant_folding=True,
        )

        logger.info(f"ONNX model exported to {output_path}")

    @staticmethod
    def simplify_onnx(input_path: str, output_path: str):
        """Simplify ONNX model (remove redundant ops)"""
        model = onnx.load(input_path)
        model_simplified, check = simplify(
            model,
            dynamic_input_shape=True,
            input_shapes=None,
        )

        if check:
            onnx.save(model_simplified, output_path)
            logger.info(f"Simplified ONNX model saved to {output_path}")
        else:
            logger.warning("ONNX simplification validation failed, using original")
            onnx.save(model, output_path)

    @staticmethod
    def quantize_onnx(input_path: str, output_path: str, method: str = "dynamic"):
        """
        Quantize ONNX model for faster inference.

        Dynamic quantization: Weights → INT8, activations → FP32
        Static quantization: Both → INT8 (needs calibration data)
        """
        from onnxruntime.quantization import quantize_dynamic, quantize_static, QuantType

        if method == "dynamic":
            quantize_dynamic(
                input_path,
                output_path,
                weight_type=QuantType.QUInt8,
            )
        elif method == "static":
            # Requires calibration dataset
            quantize_static(
                input_path,
                output_path,
                calibration_data_reader=CalibrationDataReader(),
                quant_format=QuantFormat.QDQ,
            )

        logger.info(f"Quantized model saved to {output_path}")
```

## 6.5 Batch Scheduler — Dynamic Batching

```python
# services/video-analysis/inference/batch_scheduler.py

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

@dataclass
class InferenceRequest:
    """Single inference request"""
    request_id: str
    frame_data: np.ndarray
    model_name: str
    priority: int = 5        # 1 (highest) to 10 (lowest)
    timestamp: float = 0     # When request was created
    callback: Optional[asyncio.Future] = None

class DynamicBatchScheduler:
    """
    Batches inference requests for GPU efficiency.

    Why batching?
    - GPU is massively parallel
    - Processing 1 frame: 3ms (mostly kernel launch overhead)
    - Processing 8 frames: 8ms (amortized overhead, 8x throughput)

    Strategy:
    - Wait up to max_wait_ms for batch to fill
    - Process when batch_size reached OR max_wait_ms elapsed
    - Priority queue: faces > pose > OCR > objects

    ┌─────────────────────────────────────────┐
    │            Request Queue                │
    │  [req1:pri1] [req2:pri3] [req3:pri1]   │
    └────────────────┬────────────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────────────┐
    │          Batch Builder                  │
    │  - Collect requests (max_batch_size=8)  │
    │  - Wait max 10ms                        │
    │  - Sort by priority                     │
    │  - Stack into single tensor             │
    └────────────────┬────────────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────────────┐
    │          GPU Inference                  │
    │  - Single forward pass for entire batch │
    │  - Results split back per request       │
    └────────────────┬────────────────────────┘
                     │
                     ▼
    ┌─────────────────────────────────────────┐
    │          Result Dispatcher              │
    │  - Route results to callbacks           │
    │  - Set asyncio.Future results           │
    └─────────────────────────────────────────┘
    """

    def __init__(
        self,
        model_runner,  # ONNXRunner or TensorRTRunner
        max_batch_size: int = 8,
        max_wait_ms: float = 10.0,
        priority_levels: int = 10,
    ):
        self.model_runner = model_runner
        self.max_batch_size = max_batch_size
        self.max_wait_ms = max_wait_ms

        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._running = False
        self._metrics = {
            "batches_processed": 0,
            "frames_processed": 0,
            "avg_batch_size": 0.0,
            "avg_latency_ms": 0.0,
        }

    async def submit(self, request: InferenceRequest) -> asyncio.Future:
        """Submit an inference request (non-blocking)"""
        future = asyncio.get_event_loop().create_future()
        request.callback = future
        request.timestamp = time.time()

        # Priority queue: lower number = higher priority
        await self._queue.put((request.priority, request.timestamp, request))

        return future

    async def run(self):
        """Main batch scheduling loop"""
        self._running = True

        while self._running:
            batch: list[InferenceRequest] = []

            # Collect requests up to max_batch_size
            try:
                # Wait for first request (blocking)
                priority, timestamp, request = await self._queue.get()
                batch.append(request)
            except asyncio.CancelledError:
                break

            # Try to fill batch within max_wait_ms
            deadline = time.time() + (self.max_wait_ms / 1000)

            while len(batch) < self.max_batch_size and time.time() < deadline:
                try:
                    remaining = deadline - time.time()
                    priority, timestamp, request = await asyncio.wait_for(
                        self._queue.get(),
                        timeout=max(0, remaining),
                    )
                    batch.append(request)
                except asyncio.TimeoutError:
                    break

            # Process batch
            if batch:
                await self._process_batch(batch)

    async def _process_batch(self, batch: list[InferenceRequest]):
        """Process a batch of inference requests"""
        start_time = time.time()

        try:
            # Stack all frame data into single tensor
            batch_input = np.stack([req.frame_data for req in batch])

            # Run model inference (single GPU call)
            results = self.model_runner.infer({"input": batch_input})

            # Split results and dispatch to callbacks
            batch_size = len(batch)
            for i, request in enumerate(batch):
                # Extract this request's results
                single_result = [r[i:i+1] for r in results]

                if request.callback and not request.callback.done():
                    request.callback.set_result(single_result)

        except Exception as e:
            # On error, fail all futures in batch
            for request in batch:
                if request.callback and not request.callback.done():
                    request.callback.set_exception(e)

        # Update metrics
        elapsed = (time.time() - start_time) * 1000
        self._metrics["batches_processed"] += 1
        self._metrics["frames_processed"] += len(batch)
        self._metrics["avg_batch_size"] = (
            self._metrics["avg_batch_size"] * 0.9 + len(batch) * 0.1
        )
        self._metrics["avg_latency_ms"] = (
            self._metrics["avg_latency_ms"] * 0.9 + elapsed * 0.1
        )
```

---

# PART 7 — INFERENCE PIPELINE

## 7.1 Frame Queue Architecture

```python
# services/video-analysis/pipeline.py

import asyncio
from enum import Enum

class AnalysisTask(Enum):
    """Types of analysis tasks with their priorities"""
    FACE_DETECTION = 1        # Highest priority
    EMOTION_RECOGNITION = 2
    POSE_ESTIMATION = 3
    OBJECT_DETECTION = 4
    OCR = 5                  # Lowest priority

class AnalysisPipeline:
    """
    Orchestrates the full video analysis pipeline for each frame.

    Architecture:
    ┌──────────────┐
    │ Frame Queue  │ ← Frames from stream capture
    │ (max 10)     │
    └──────┬───────┘
           │
           ▼
    ┌──────────────────────────────────────────────┐
    │           FRAME PREPROCESSOR                  │
    │  1. Resize to model input size               │
    │  2. Normalize (mean/std)                     │
    │  3. Convert BGR → RGB                        │
    │  4. To tensor (GPU)                          │
    └──────────────────┬───────────────────────────┘
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
    ┌────────────┐ ┌────────┐ ┌────────┐
    │Face Detect │ │Pose    │ │OCR     │
    │(GPU batch) │ │(GPU)   │ │(GPU)   │
    └─────┬──────┘ └───┬────┘ └───┬────┘
          │             │          │
          ▼             │          │
    ┌────────────┐      │          │
    │Emotion Rec │      │          │
    │(face crops)│      │          │
    └─────┬──────┘      │          │
          │             │          │
          └─────────────┼──────────┘
                        │
                        ▼
              ┌──────────────────┐
              │Result Aggregator │
              │(merge all)       │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │Event Publisher   │ → Kafka
              └──────────────────┘

    Key Design Decisions:
    1. Face detection runs FIRST (other tasks depend on face crops)
    2. Emotion recognition uses face crops from detection
    3. Pose, OCR, Object run in PARALLEL (independent)
    4. All models share the same GPU (time-sliced)
    """

    def __init__(
        self,
        face_detector,
        emotion_recognizer,
        pose_estimator,
        object_detector,
        ocr_engine,
        event_producer,
        max_queue_size: int = 10,
    ):
        self.face_detector = face_detector
        self.emotion_recognizer = emotion_recognizer
        self.pose_estimator = pose_estimator
        self.object_detector = object_detector
        self.ocr_engine = ocr_engine
        self.event_producer = event_producer

        self.frame_queue = asyncio.Queue(maxsize=max_queue_size)
        self.backpressure = BackpressureManager(
            target_fps=2,
            max_queue_size=max_queue_size,
        )

        # Metrics
        self._frames_processed = 0
        self._total_inference_time = 0.0

    async def process_frame(self, frame: Frame):
        """
        Process a single frame through all analysis models.

        This is the main entry point called by the frame consumer.
        """
        if not await self.backpressure.should_process_frame():
            return  # Drop frame due to backpressure

        start_time = time.time()
        frame_id = frame.frame_id

        # Step 1: Face Detection (must run first)
        face_results = await self.face_detector.detect(frame.image)

        # Step 2: Emotion Recognition on detected faces (depends on step 1)
        emotion_results = []
        if face_results:
            face_crops = [
                self._crop_face(frame.image, face.bbox)
                for face in face_results
            ]
            emotion_results = await self.emotion_recognizer.recognize_batch(face_crops)

        # Step 3: Parallel analysis (independent of faces)
        pose_task = asyncio.create_task(
            self.pose_estimator.estimate(frame.image)
        )
        object_task = asyncio.create_task(
            self.object_detector.detect(frame.image)
        )
        ocr_task = asyncio.create_task(
            self.ocr_engine.recognize(frame.image)
        )

        # Wait for all parallel tasks
        pose_results, object_results, ocr_results = await asyncio.gather(
            pose_task, object_task, ocr_task,
            return_exceptions=True,
        )

        # Handle exceptions gracefully
        if isinstance(pose_results, Exception):
            pose_results = []
        if isinstance(object_results, Exception):
            object_results = []
        if isinstance(ocr_results, Exception):
            ocr_results = []

        # Step 4: Aggregate results
        analysis_result = AnalysisResult(
            frame_id=frame_id,
            timestamp=frame.timestamp,
            faces=face_results,
            emotions=emotion_results,
            poses=pose_results,
            objects=object_results,
            texts=ocr_results,
            inference_time_ms=(time.time() - start_time) * 1000,
        )

        # Step 5: Publish to Kafka
        await self.event_producer.publish(
            topic="analysis.results",
            event_type="analysis.complete",
            payload=analysis_result.model_dump(),
            key=frame_id,
        )

        # Update metrics
        self._frames_processed += 1
        self._total_inference_time += analysis_result.inference_time_ms

    def _crop_face(
        self,
        frame: np.ndarray,
        bbox: tuple[float, float, float, float],
        padding: float = 0.2,
    ) -> np.ndarray:
        """Crop face region with padding"""
        x1, y1, x2, y2 = bbox
        h, w = frame.shape[:2]

        # Add padding
        face_w = x2 - x1
        face_h = y2 - y1
        pad_x = int(face_w * padding)
        pad_y = int(face_h * padding)

        x1 = max(0, int(x1) - pad_x)
        y1 = max(0, int(y1) - pad_y)
        x2 = min(w, int(x2) + pad_x)
        y2 = min(h, int(y2) + pad_y)

        return frame[y1:y2, x1:x2]
```

---

# PART 8 — DETECTION MODELS

## 8.1 YOLO (You Only Look Once) — Object & Face Detection

### Neden YOLO?

```
Object Detection Model Comparison:

Model           | Speed    | Accuracy (mAP) | Size   | Best For
────────────────┼──────────┼────────────────┼────────┼───────────────
YOLOv8-nano     | 1.2 ms   | 37.3           | 6 MB   | Edge devices
YOLOv8-small    | 2.3 ms   | 44.9           | 22 MB  | Real-time
YOLOv8-medium   | 5.4 ms   | 50.2           | 52 MB  | Balance
YOLOv8-large    | 8.9 ms   | 52.9           | 84 MB  | Accuracy
YOLOv8-xlarge   | 14.2 ms  | 53.9           | 136 MB | Max accuracy
────────────────┼──────────┼────────────────┼────────┼───────────────
Faster R-CNN    | 50 ms    | 42.0           | 165 MB | Research
DETR            | 28 ms    | 43.3           | 159 MB | End-to-end
SSD-MobileNet   | 3.5 ms   | 29.3           | 27 MB  | Mobile
EfficientDet    | 7.1 ms   | 51.0           | 66 MB  | Efficient

For our use case:
  - Need <10ms per frame (multiple models share GPU time)
  - Need high accuracy for clip decisions
  - Best choice: YOLOv8-small for objects, YOLO-Face for faces
```

### YOLO Face Detection Implementation

```python
# services/video-analysis/models/face_detector.py

import numpy as np
import torch
from ultralytics import YOLO
from typing import Optional

class YOLOFaceDetector:
    """
    Face detection using YOLOv8-Face.

    Why YOLO-Face over alternatives?
    - RetinaFace: Slower (~15ms), better on tiny faces
    - MTCNN: Very slow (~50ms), cascade architecture
    - MediaPipe Face: Fast but CPU-only, no batch
    - Dlib HOG: Fast but low accuracy on occluded faces

    YOLOv8-Face advantages:
    - Single-stage detector (fast, ~3ms on GPU)
    - Detects faces + 5 landmarks in one pass
    - Handles occlusion, rotation, varying scales
    - Supports batch inference
    - ONNX/TensorRT export available

    Model: yolov8n-face (nano, fastest)
    Input: 640x640 RGB image
    Output: [x1, y1, x2, y2, confidence, lm1_x, lm1_y, ..., lm5_x, lm5_y]
    """

    def __init__(
        self,
        model_path: str = "models/yolov8n-face.pt",
        confidence_threshold: float = 0.5,
        nms_threshold: float = 0.45,
        device: str = "cuda:0",
    ):
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.device = device

        # Load model
        self.model = YOLO(model_path)
        self.model.to(device)

        logger.info(f"Face detector loaded: {model_path} on {device}")

    async def detect(self, frame_bgr: np.ndarray) -> list[FaceDetection]:
        """
        Detect faces in a frame.

        Args:
            frame_bgr: OpenCV BGR image (H, W, 3)

        Returns:
            List of FaceDetection results
        """
        # Preprocess: BGR → RGB, resize to 640x640
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        # Run inference
        results = self.model.predict(
            frame_rgb,
            conf=self.confidence_threshold,
            iou=self.nms_threshold,
            device=self.device,
            verbose=False,
        )

        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue

            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                confidence = float(box.conf[0].cpu().numpy())

                # Extract landmarks if available
                landmarks = None
                if hasattr(result, 'keypoints') and result.keypoints is not None:
                    kps = result.keypoints[i].cpu().numpy()
                    landmarks = {
                        "left_eye": (kps[0], kps[1]),
                        "right_eye": (kps[2], kps[3]),
                        "nose": (kps[4], kps[5]),
                        "left_mouth": (kps[6], kps[7]),
                        "right_mouth": (kps[8], kps[9]),
                    }

                detections.append(FaceDetection(
                    face_id=f"face_{i}_{int(time.time()*1000)}",
                    bbox=(float(x1), float(y1), float(x2), float(y2)),
                    confidence=confidence,
                    landmarks=landmarks,
                ))

        return detections

    async def detect_batch(self, frames: list[np.ndarray]) -> list[list[FaceDetection]]:
        """Batch detection for multiple frames (GPU efficiency)"""
        batch_rgb = [cv2.cvtColor(f, cv2.COLOR_BGR2RGB) for f in frames]

        results = self.model.predict(
            batch_rgb,
            conf=self.confidence_threshold,
            iou=self.nms_threshold,
            device=self.device,
            verbose=False,
        )

        return [self._parse_results(r) for r in results]
```

## 8.2 Emotion Detection

### Neden Multi-Model Approach?

```
Emotion Detection Accuracy Comparison:

Model                    | Accuracy  | Speed   | Size   | Classes
─────────────────────────┼───────────┼─────────┼────────┼──────────
FER (CNN-based)          | 65.8%     | 2 ms    | 15 MB  | 7
AffectNet (ResNet50)     | 72.1%     | 5 ms    | 98 MB  | 8
ViT-Face-Expression      | 74.5%     | 4 ms    | 86 MB  | 7
DeepFace (ensemble)      | 76.3%     | 15 ms   | 300 MB | 7
Multi-task (face+emotion)| 78.2%     | 6 ms    | 120 MB | 7+AU

Production Strategy:
  Primary: ViT-Face-Expression (best speed/accuracy ratio)
  Fallback: FER (when GPU overloaded, runs on CPU)
  Validation: Periodic DeepFace check for accuracy monitoring
```

```python
# services/video-analysis/models/emotion_recognizer.py

from transformers import pipeline, ViTForImageClassification, ViTFeatureExtractor

class EmotionRecognizer:
    """
    Emotion recognition using Vision Transformer (ViT).

    Model: trpakov/vit-face-expression
    Input: 224x224 face crop (RGB)
    Output: 7 emotion probabilities

    Emotions: angry, disgust, fear, happy, sad, surprise, neutral

    Architecture:
    ┌──────────────────────────────────────┐
    │  Face Crop (224x224 RGB)             │
    │       │                               │
    │       ▼                               │
    │  Patch Embedding (16x16 patches)     │
    │       │                               │
    │       ▼                               │
    │  Transformer Encoder (12 layers)     │
    │       │                               │
    │       ▼                               │
    │  Classification Head                  │
    │       │                               │
    │       ▼                               │
    │  [angry:0.01, disgust:0.02, ...]     │
    │  [happy:0.89, surprise:0.05, ...]    │
    └──────────────────────────────────────┘

    Real-World Consideration:
    - Streamer's "neutral" face may have high arousal (focused gaming)
    - Need to combine emotion with audio/motion for true excitement
    - Emotion alone is NOT sufficient for clip decision
    """

    EMOTION_LABELS = [
        "angry", "disgust", "fear", "happy",
        "sad", "surprise", "neutral"
    ]

    # Emotions that indicate potential highlight moments
    HIGHLIGHT_EMOTIONS = {"happy", "surprise", "fear", "angry"}

    def __init__(
        self,
        model_name: str = "trpakov/vit-face-expression",
        device: str = "cuda:0",
        threshold: float = 0.6,
    ):
        self.threshold = threshold
        self.device = device

        # Load model
        self.model = ViTForImageClassification.from_pretrained(model_name)
        self.feature_extractor = ViTFeatureExtractor.from_pretrained(model_name)
        self.model.to(device)
        self.model.eval()

        logger.info(f"Emotion recognizer loaded: {model_name}")

    async def recognize(self, face_crop_bgr: np.ndarray) -> Optional[EmotionResult]:
        """Recognize emotion from a face crop"""
        if face_crop_bgr is None or face_crop_bgr.size == 0:
            return None

        # Preprocess
        face_rgb = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2RGB)
        face_resized = cv2.resize(face_rgb, (224, 224))

        inputs = self.feature_extractor(
            images=face_resized,
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Inference
        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            probabilities = torch.softmax(logits, dim=-1)[0]

        # Parse results
        scores = {
            self.EMOTION_LABELS[i]: float(probabilities[i].cpu())
            for i in range(len(self.EMOTION_LABELS))
        }

        top_label = max(scores, key=scores.get)
        top_confidence = scores[top_label]

        if top_confidence < self.threshold:
            return None  # Low confidence, skip

        return EmotionResult(
            face_id="unknown",  # Set by caller
            label=top_label,
            confidence=top_confidence,
            scores=scores,
        )

    async def recognize_batch(
        self,
        face_crops: list[np.ndarray],
    ) -> list[EmotionResult]:
        """Batch emotion recognition for multiple face crops"""
        if not face_crops:
            return []

        # Preprocess all faces
        processed = []
        for crop in face_crops:
            face_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            face_resized = cv2.resize(face_rgb, (224, 224))
            processed.append(face_resized)

        inputs = self.feature_extractor(
            images=processed,
            return_tensors="pt",
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        # Single batch inference
        with torch.no_grad():
            outputs = self.model(**inputs)
            all_probs = torch.softmax(outputs.logits, dim=-1)

        results = []
        for i, probs in enumerate(all_probs):
            scores = {
                self.EMOTION_LABELS[j]: float(probs[j].cpu())
                for j in range(len(self.EMOTION_LABELS))
            }
            top_label = max(scores, key=scores.get)
            top_confidence = scores[top_label]

            if top_confidence >= self.threshold:
                results.append(EmotionResult(
                    face_id=f"face_{i}",
                    label=top_label,
                    confidence=top_confidence,
                    scores=scores,
                ))

        return results

    def compute_emotion_intensity(self, current: EmotionResult, previous: Optional[EmotionResult] = None) -> float:
        """
        Compute emotion intensity for highlight detection.

        High intensity = sudden emotion change OR extreme emotion.
        This is a key signal for clip-worthy moments.
        """
        # Base intensity from confidence × emotion type
        base_intensity = current.confidence
        if current.label in self.HIGHLIGHT_EMOTIONS:
            base_intensity *= 1.5  # Boost highlight emotions

        # Change intensity (sudden shifts are interesting)
        change_intensity = 0.0
        if previous:
            # KL divergence between emotion distributions
            current_dist = np.array([current.scores[e] for e in self.EMOTION_LABELS])
            previous_dist = np.array([previous.scores[e] for e in self.EMOTION_LABELS])
            kl_div = np.sum(current_dist * np.log(current_dist / (previous_dist + 1e-10)))
            change_intensity = min(kl_div, 2.0)  # Cap at 2.0

        return base_intensity + change_intensity
```

## 8.3 Pose Detection — MediaPipe + HRNet

### Neden İki Model?

```
MediaPipe BlazePose:
  ✅ 33 keypoints, very fast (CPU: 15ms, GPU: 3ms)
  ✅ Full body (hands, feet, face landmarks)
  ✅ Built-in gesture recognition
  ❌ Single person only
  ❌ Less accurate than HRNet on occluded poses

HRNet (High-Resolution Net):
  ✅ 17 keypoints, very accurate (COCO state-of-art)
  ✅ Multi-person support
  ✅ Better on occluded/complex poses
  ❌ Slower (~10ms GPU)
  ❌ No hand/face keypoints

Strategy:
  - MediaPipe for real-time gesture detection (hand raise, victory sign)
  - HRNet for accurate pose analysis when needed
  - MediaPipe runs on EVERY frame, HRNet only on event frames
```

```python
# services/video-analysis/models/pose_estimator.py

import mediapipe as mp
import numpy as np

class PoseEstimator:
    """
    Dual-model pose estimation.

    MediaPipe for real-time gesture detection:
    - Hand raise (celebration)
    - Victory sign
    - Head tilt (confusion)
    - Leaning forward (intense focus)
    - Standing up (rage quit / celebration)

    These gestures are STRONG signals for clip-worthy moments.
    A streamer raising both hands after a kill = high-value clip.
    """

    # Gesture definitions with confidence thresholds
    GESTURES = {
        "hand_raise": {
            "description": "One or both hands raised above shoulders",
            "signal_strength": 0.8,
        },
        "victory_sign": {
            "description": "V sign with fingers",
            "signal_strength": 0.7,
        },
        "head_tilt": {
            "description": "Head tilted significantly",
            "signal_strength": 0.4,
        },
        "lean_forward": {
            "description": "Upper body leaning forward",
            "signal_strength": 0.5,
        },
        "arms_spread": {
            "description": "Both arms spread wide",
            "signal_strength": 0.9,
        },
        "face_palm": {
            "description": "Hand covering face",
            "signal_strength": 0.6,
        },
        "table_slam": {
            "description": "Rapid downward hand movement",
            "signal_strength": 0.95,
        },
    }

    def __init__(self):
        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose(
            static_image_mode=True,
            model_complexity=1,          # 0=lite, 1=full, 2=heavy
            min_detection_confidence=0.5,
        )

        # Track previous poses for motion analysis
        self._pose_history: list[dict] = []

    async def estimate(self, frame_bgr: np.ndarray) -> list[PoseResult]:
        """Estimate pose and detect gestures"""
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self.pose.process(frame_rgb)

        if not results.pose_landmarks:
            return []

        landmarks = results.pose_landmarks.landmark

        # Convert to dict for easier access
        pose_data = self._landmarks_to_dict(landmarks)

        # Detect gestures
        detected_gestures = self._detect_gestures(pose_data)

        # Calculate pose motion (compare with history)
        motion_score = self._compute_motion(pose_data)

        self._pose_history.append(pose_data)
        if len(self._pose_history) > 30:
            self._pose_history.pop(0)

        return [PoseResult(
            keypoints=pose_data,
            gestures=[g["name"] for g in detected_gestures],
            gesture_scores={g["name"]: g["confidence"] for g in detected_gestures},
            motion_score=motion_score,
        )]

    def _detect_gestures(self, pose: dict) -> list[dict]:
        """Detect predefined gestures from pose landmarks"""
        gestures = []

        # Hand raise detection
        left_wrist = pose.get("left_wrist", {})
        right_wrist = pose.get("right_wrist", {})
        left_shoulder = pose.get("left_shoulder", {})
        right_shoulder = pose.get("right_shoulder", {})

        if left_wrist and left_shoulder:
            if left_wrist["y"] < left_shoulder["y"] - 0.15:
                gestures.append({
                    "name": "hand_raise",
                    "confidence": min(1.0, (left_shoulder["y"] - left_wrist["y"]) / 0.3),
                    "hand": "left",
                })

        if right_wrist and right_shoulder:
            if right_wrist["y"] < right_shoulder["y"] - 0.15:
                gestures.append({
                    "name": "hand_raise",
                    "confidence": min(1.0, (right_shoulder["y"] - right_wrist["y"]) / 0.3),
                    "hand": "right",
                })

        # Both hands raise = stronger signal
        hand_raises = [g for g in gestures if g["name"] == "hand_raise"]
        if len(hand_raises) >= 2:
            gestures.append({
                "name": "arms_spread",
                "confidence": 0.9,
            })

        # Lean forward detection
        nose = pose.get("nose", {})
        mid_hip = pose.get("left_hip", {})
        if nose and mid_hip:
            forward_lean = nose["z"]  # z-axis in MediaPipe = depth
            if forward_lean < -0.2:
                gestures.append({
                    "name": "lean_forward",
                    "confidence": min(1.0, abs(forward_lean) / 0.5),
                })

        return gestures

    def _compute_motion(self, current_pose: dict) -> float:
        """Compute body motion intensity from pose history"""
        if len(self._pose_history) < 2:
            return 0.0

        previous = self._pose_history[-1]
        total_motion = 0.0
        count = 0

        for key in current_pose:
            if key in previous:
                dx = current_pose[key]["x"] - previous[key]["x"]
                dy = current_pose[key]["y"] - previous[key]["y"]
                total_motion += np.sqrt(dx**2 + dy**2)
                count += 1

        return total_motion / max(count, 1)
```

## 8.4 OCR — Text Detection

```python
# services/video-analysis/models/ocr_engine.py

import easyocr

class OCREngine:
    """
    OCR for detecting on-screen text in game streams.

    Why OCR matters for clip detection:
    - "VICTORY" / "DEFEAT" text → game outcome
    - Kill feed text → multi-kill detection
    - Score changes → important moments
    - Chat overlay messages → viewer interaction

    Model: EasyOCR (supports 80+ languages)
    Alternative: PaddleOCR (faster, Chinese-focused)
    Alternative: Tesseract (slow, legacy)

    Performance:
    - EasyOCR GPU: ~8ms per frame
    - PaddleOCR GPU: ~5ms per frame
    - Tesseract: ~200ms (too slow)
    """

    # Important keywords that indicate highlight moments
    HIGHLIGHT_KEYWORDS = {
        "victory", "winner", "champion", "first place",
        "defeat", "game over", "eliminated",
        "kill", "double kill", "triple kill", "quadra", "penta",
        "level up", "achievement", "record",
        "gg", "ez", "pog", "hype",
    }

    def __init__(
        self,
        languages: list[str] = None,
        gpu: bool = True,
    ):
        if languages is None:
            languages = ["en", "tr"]  # English + Turkish

        self.reader = easyocr.Reader(
            languages,
            gpu=gpu,
            model_storage_directory="models/easyocr",
        )

    async def recognize(self, frame_bgr: np.ndarray) -> list[OCRResult]:
        """Detect and recognize text in frame"""
        results = self.reader.readtext(
            frame_bgr,
            detail=1,
            paragraph=False,
        )

        ocr_results = []
        for bbox, text, confidence in results:
            # Check for highlight keywords
            is_highlight = any(
                keyword in text.lower()
                for keyword in self.HIGHLIGHT_KEYWORDS
            )

            ocr_results.append(OCRResult(
                text=text,
                bbox=bbox,
                confidence=confidence,
                is_highlight_keyword=is_highlight,
            ))

        return ocr_results
```
