# SOFTWARE ARCHITECTURE DOCUMENT (SAD)
# Real-Time AI Livestream Analysis System
# Kick Platform — Single Broadcaster Architecture

**Version:** 2.0.0
**Author:** Principal AI Architecture Team
**Classification:** Internal — Engineering Reference

---

## TABLE OF CONTENTS

```
PART  1 — Distributed System Architecture
PART  2 — Microservice Design
PART  3 — Service Communication (REST, gRPC, Kafka, RabbitMQ, Redis Streams)
PART  4 — Real-Time Video Pipeline
PART  5 — Rolling Buffer & Frame Sampling
PART  6 — GPU Pipeline (CUDA, TensorRT, ONNX Runtime, Model Optimization)
PART  7 — Inference Pipeline (Frame Queue, Backpressure)
PART  8 — Detection Models (YOLO, MediaPipe, OpenCV, Face, Pose, Emotion, OCR)
PART  9 — Audio Pipeline (Whisper, SER, VAD, Speaker Diarization)
PART 10 — Chat Analysis & NLP (Sentiment, Toxicity, LLM Decision Engine)
PART 11 — Highlight Scoring & Prediction
PART 12 — Feature Engineering, Vector DB, Embeddings, RAG, Semantic Search
PART 13 — Clip Candidate Generation, Ranking, Model Ensemble
PART 14 — Confidence Score, Threshold System, Event Graph
PART 15 — Rule Engine & State Machine
PART 16 — Analytics, Monitoring & Observability
PART 17 — Performance Optimization, Profiling & Scaling
PART 18 — Docker, Kubernetes & CI/CD
PART 19 — Testing, Logging, Error Recovery & Retry Strategy
PART 20 — Caching, Security, OAuth & Secrets Management
PART 21 — Database Design & Deployment Strategy
```

---

# PART 1 — DISTRIBUTED SYSTEM ARCHITECTURE

## 1.1 Neden Gerekli? (Why Is It Necessary?)

Bir canlı yayın analiz sistemi, doğası gereği **çoklu eşzamanlı veri akışı** ile çalışır:

- Video stream (30-60 FPS, ~6 Mbps)
- Audio stream (48kHz, stereo)
- Chat WebSocket stream (değişken hız, burst pattern)
- Viewer count API polling (periyodik)
- Platform API calls (OAuth, metadata)

Bu veri akışlarının her biri **farklı latency gereksinimlerine**, **farklı throughput kapasitelerine** ve **farklı hata toleranslarına** sahiptir. Tek bir monolitik servis bu yükü kaldıramaz çünkü:

1. **CPU-bound işlemler** (video decoding, frame extraction) GPU-bound işlemleri (model inference) bloklar
2. **I/O-bound işlemler** (API calls, database writes) CPU-intensive thread'leri bekletir
3. **Burst traffic** (chat explosion anında 1000 msg/s) diğer servisleri crash eder
4. **Model güncellemesi** tüm sistemi restart gerektirmeden yapılamaz

### Gerçek Dünya Örneği: Netflix'in Video Pipeline'ı

Netflix, video işleme pipeline'ını tamamen distributed yapmıştır:
- **Video Ingestion** → ayrı servis (Apache Kafka'ya yazar)
- **Encoding** → ayrı GPU cluster (AWS EC2 P3 instances)
- **Quality Analysis** → ayrı ML inference cluster
- **Metadata Extraction** → ayrı NLP servisi
- **CDN Distribution** → ayrı edge network

Her servis bağımsız scale edilir. Encoding cluster 1000 instance'a çıkarken, metadata servisi 5 instance'da kalabilir.

### Bizim Sistemimiz İçin Analog

```
┌─────────────────────────────────────────────────────────────────────┐
│                        EVENT BUS (Kafka)                            │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐      │
│  │stream│  │frame │  │audio │  │chat  │  │event │  │clip  │      │
│  │events│  │events│  │chunks│  │msgs  │  │events│  │events│      │
│  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘      │
│     │         │         │         │         │         │            │
└─────┼─────────┼─────────┼─────────┼─────────┼─────────┼────────────┘
      │         │         │         │         │         │
   ┌──▼──┐  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐  ┌──▼──┐
   │Stream│  │Frame│  │Audio│  │Chat │  │Event│  │Clip │
   │Captur│  │Extr.│  │Anal.│  │Anal.│  │Detec│  │Gen. │
   │e Svc │  │Svc  │  │Svc  │  │Svc  │  │t Svc│  │Svc  │
   └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘  └──┬───┘
      │         │         │         │         │         │
      ▼         ▼         ▼         ▼         ▼         ▼
   HLS/RTMP  OpenCV   Whisper  NLP    Rule     FFmpeg
   FFmpeg    GPU      GPU      CPU    Engine   GPU+CPU
```

## 1.2 Nasıl Çalışıyor? (How Does It Work?)

### Core Principle: Event Sourcing + CQRS

Sistemimiz **Event Sourcing** pattern'ini kullanır. Her state değişikliği bir **event** olarak kaydedilir:

```python
# Her şey bir event'tir
@dataclass
class SystemEvent:
    event_id: str                    # UUID v7 (time-sortable)
    event_type: str                  # "stream.started", "frame.extracted", etc.
    timestamp: datetime              # UTC microsecond precision
    source_service: str              # "stream-capture", "audio-analysis", etc.
    payload: dict                    # Event-specific data
    correlation_id: str              # Request tracing
    causation_id: Optional[str]      # Parent event (causal chain)
    metadata: EventMetadata          # Retry count, TTL, priority
```

### Event Flow — Tam Akış

```
STREAM_LIVE_STARTED
  │
  ├─→ StreamCaptureService.start()
  │     │
  │     ├─→ FRAME_EXTRACTED (her 500ms'de bir, 2 FPS)
  │     │     │
  │     │     ├─→ FaceDetectionService.process(frame)
  │     │     │     └─→ FACE_DETECTED { bbox, confidence, landmarks }
  │     │     │           │
  │     │     │           └─→ EmotionRecognitionService.process(face_crop)
  │     │     │                 └─→ EMOTION_DETECTED { label, confidence, scores }
  │     │     │
  │     │     ├─→ PoseDetectionService.process(frame)
  │     │     │     └─→ POSE_DETECTED { keypoints, gesture_type }
  │     │     │
  │     │     ├─→ OCRService.process(frame)
  │     │     │     └─→ TEXT_DETECTED { text, bbox, confidence }
  │     │     │
  │     │     └─→ ObjectDetectionService.process(frame)
  │     │           └─→ OBJECT_DETECTED { class, bbox, confidence }
  │     │
  │     ├─→ AUDIO_CHUNK_READY (her 1 saniyede bir)
  │     │     │
  │     │     ├─→ AudioAnalysisService.process(chunk)
  │     │     │     ├─→ AUDIO_FEATURES { rms, zcr, spectral_centroid, mfcc }
  │     │     │     ├─→ VAD_DETECTED { is_speech, probability }
  │     │     │     └─→ AUDIO_SPIKE { magnitude, duration }
  │     │     │
  │     │     ├─→ SpeechRecognitionService.process(chunk)
  │     │     │     └─→ TRANSCRIPT_READY { text, language, confidence }
  │     │     │
  │     │     └─→ SpeakerDiarizationService.process(chunk)
  │     │           └─→ SPEAKER_IDENTIFIED { speaker_id, segment }
  │     │
  │     └─→ ROLLING_BUFFER_UPDATED { buffer_size, oldest_ts, newest_ts }
  │
  ├─→ ChatAnalysisService.start_polling()
  │     │
  │     ├─→ CHAT_MESSAGE_RECEIVED { user, text, badges }
  │     │     ├─→ SENTIMENT_ANALYZED { score, label, emotions }
  │     │     └─→ TOXICITY_DETECTED { score, category }
  │     │
  │     └─→ CHAT_SPIKE_DETECTED { msg_per_sec, delta, sentiment_shift }
  │
  ├─→ ViewerCountService.start_polling()
  │     └─→ VIEWER_COUNT_UPDATED { count, delta, trend }
  │
  └─→ EventDetectionService (aggregator)
        │
        ├─→ Consumes: EMOTION_DETECTED, POSE_DETECTED, AUDIO_SPIKE,
        │             CHAT_SPIKE_DETECTED, VIEWER_COUNT_UPDATED
        │
        ├─→ EVENT_TRIGGERED { event_type, score, evidence[] }
        │
        └─→ DecisionEngine.process(event)
              │
              ├─→ CLIP_CANDIDATE { start_ts, end_ts, score, reason }
              │     │
              │     └─→ ClipGenerationService.execute(candidate)
              │           ├─→ CLIP_CREATED { file_path, duration, metadata }
              │           ├─→ SubtitleService.generate(clip)
              │           │     └─→ SUBTITLE_READY { srt_path, language }
              │           ├─→ ClipClassificationService.classify(clip)
              │           │     └─→ CLIP_CLASSIFIED { category, tags, labels }
              │           └─→ UploadService.publish(clip)
              │                 └─→ CLIP_PUBLISHED { platform, url }
              │
              └─→ CLIP_REJECTED { reason, score_below_threshold }
```

## 1.3 Neden Bu Teknoloji Seçildi?

| Bileşen | Seçim | Neden? |
|---------|-------|--------|
| Event Bus | Apache Kafka | Persistent, replayable, partitioned, ordered |
| Fast Message Queue | RabbitMQ | Routing flexibility, dead-letter queues, TTL |
| Cache + Pub/Sub | Redis Streams | Sub-ms latency, pub/sub + stream semantics |
| Service Framework | FastAPI (Python) | Async native, Pydantic validation, OpenAPI |
| GPU Inference | PyTorch + ONNX Runtime | Best Python ML ecosystem, TensorRT export |
| Video Processing | FFmpeg + OpenCV | Industry standard, hardware acceleration |
| Container | Docker + K8s | Immutable deployment, auto-scaling |

### Alternatifler ve Neden Seçilmediler

**Event Bus Alternatifleri:**
- **Apache Pulsar**: Daha iyi multi-tenancy ama operasyonel karmaşıklık yüksek. Netflix-tier scale'de tercih edilir. Bizim ölçeğimizde overkill.
- **AWS Kinesis**: Managed ama vendor lock-in. Fiyat tahmin edilemez. On-premise çalışamaz.
- **NATS JetStream**: Çok hızlı, lightweight. Ama ecosystem Kafka kadar geniş değil. Connectors az.
- **RabbitMQ (sole)**: Message loss riski var (acknowledge edilmemiş mesajlar restart'ta kaybolabilir). Kafka'nın persistent log yapısı kritik.

**Framework Alternatifleri:**
- **gRPC (sole)**: Binary protocol, çok hızlı. Ama browser'dan doğrudan erişilemez. REST gateway gerekir. Hybrid kullanıyoruz.
- **Flask**: Async desteği zayıf. Thread-per-request modeli GPU inference ile çalışmaz.
- **Django**: ORM avantaj ama async pipeline için ağır. Template engine'e ihtiyacımız yok.

## 1.4 Klasör Yapısı (Project Structure)

```
klip-system/
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
├── .env.example
│
├── proto/                          # gRPC Protocol Buffers
│   ├── frame.proto
│   ├── inference.proto
│   └── clip.proto
│
├── services/                       # Microservices
│   ├── stream-capture/             # HLS/RTMP stream ingestion
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── capture_engine.py       # FFmpeg subprocess manager
│   │   ├── rolling_buffer.py       # Ring buffer (deque + numpy)
│   │   ├── frame_sampler.py        # Frame extraction at target FPS
│   │   └── event_publisher.py      # Kafka producer
│   │
│   ├── video-analysis/             # GPU-bound analysis
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── pipeline.py             # Orchestration of all visual models
│   │   ├── models/
│   │   │   ├── face_detector.py    # YOLO-Face / RetinaFace
│   │   │   ├── emotion_recognizer.py  # FER / AffectNet models
│   │   │   ├── pose_estimator.py   # MediaPipe / HRNet
│   │   │   ├── object_detector.py  # YOLOv8
│   │   │   └── ocr_engine.py       # EasyOCR / PaddleOCR
│   │   ├── inference/
│   │   │   ├── onnx_runner.py      # ONNX Runtime session manager
│   │   │   ├── tensorrt_runner.py  # TensorRT engine builder
│   │   │   ├── batch_scheduler.py  # Dynamic batching
│   │   │   └── model_registry.py   # Model versioning + hot-reload
│   │   └── config.py
│   │
│   ├── audio-analysis/             # Audio processing
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── feature_extractor.py    # Librosa features (MFCC, spectral)
│   │   ├── vad_engine.py           # Silero VAD
│   │   ├── speech_recognizer.py    # Faster-Whisper
│   │   ├── emotion_recognizer.py   # Speech Emotion Recognition
│   │   ├── diarizer.py             # PyAnnote speaker diarization
│   │   └── spike_detector.py       # Energy-based spike detection
│   │
│   ├── chat-analysis/              # NLP processing
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── sentiment_analyzer.py   # DistilBERT sentiment
│   │   ├── toxicity_detector.py    # Perspective API / local model
│   │   ├── entity_extractor.py     # NER for names, brands, topics
│   │   ├── spike_detector.py       # Chat velocity analyzer
│   │   └── emoji_analyzer.py       # Emoji frequency + sentiment
│   │
│   ├── event-detector/             # Event aggregation + scoring
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── event_aggregator.py     # Windowed event collection
│   │   ├── scoring_engine.py       # Multi-signal scoring
│   │   ├── rule_engine.py          # Configurable rules
│   │   ├── state_machine.py        # Stream state tracking
│   │   └── highlight_predictor.py  # Temporal pattern recognition
│   │
│   ├── decision-engine/            # Clip decision making
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── decision_pipeline.py    # Score → Decision flow
│   │   ├── clip_ranker.py          # Rank candidates
│   │   ├── ensemble_scorer.py      # Multi-model ensemble
│   │   └── threshold_manager.py    # Dynamic thresholds
│   │
│   ├── clip-generator/             # Clip creation + post-processing
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── clip_cutter.py          # FFmpeg trim from buffer
│   │   ├── subtitle_generator.py   # Whisper full transcription
│   │   ├── classifier.py           # CLIP zero-shot classification
│   │   ├── video_editor.py         # Transitions, effects, resize
│   │   └── thumbnail_generator.py  # Best frame selection
│   │
│   ├── upload-service/             # Multi-platform publishing
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── youtube_uploader.py
│   │   ├── tiktok_uploader.py
│   │   ├── kick_uploader.py
│   │   └── metadata_generator.py   # AI title/description/tags
│   │
│   └── api-gateway/                # REST + WebSocket API
│       ├── Dockerfile
│       ├── main.py
│       ├── routers/
│       │   ├── clips.py
│       │   ├── system.py
│       │   ├── analytics.py
│       │   └── preferences.py
│       ├── websocket.py            # Real-time dashboard updates
│       ├── auth.py                 # JWT + OAuth2
│       └── middleware/
│           ├── rate_limiter.py
│           ├── cors.py
│           └── request_logger.py
│
├── shared/                         # Shared libraries
│   ├── event_bus/
│   │   ├── kafka_producer.py
│   │   ├── kafka_consumer.py
│   │   ├── rabbitmq_publisher.py
│   │   ├── redis_streams.py
│   │   └── event_schemas.py        # Pydantic event definitions
│   ├── models/
│   │   ├── database.py             # SQLAlchemy async models
│   │   ├── enums.py
│   │   └── migrations/
│   ├── utils/
│   │   ├── logging.py              # Structured logging (JSON)
│   │   ├── metrics.py              # Prometheus metrics
│   │   ├── tracing.py              # OpenTelemetry tracing
│   │   ├── retry.py                # Exponential backoff + circuit breaker
│   │   └── config.py               # Pydantic settings
│   └── video/
│       ├── ffmpeg_wrapper.py       # FFmpeg subprocess helper
│       ├── buffer_utils.py         # Frame buffer utilities
│       └── codec_utils.py          # Pixel format conversion
│
├── deploy/                         # Deployment configs
│   ├── kubernetes/
│   │   ├── namespace.yaml
│   │   ├── kafka/
│   │   ├── services/
│   │   ├── monitoring/
│   │   └── ingress.yaml
│   ├── docker/
│   │   ├── docker-compose.dev.yml
│   │   └── docker-compose.prod.yml
│   └── terraform/
│       └── aws/
│
├── scripts/
│   ├── setup_gpu.sh                # NVIDIA driver + CUDA setup
│   ├── download_models.py          # Pre-download all ML models
│   └── benchmark.py                # Performance benchmarking
│
└── tests/
    ├── unit/
    ├── integration/
    ├── e2e/
    └── load/
```

## 1.5 API Tasarımı

### REST API (api-gateway)

```yaml
# Clip Management
GET    /api/v1/clips                    # List clips (paginated, filtered)
GET    /api/v1/clips/{clip_id}          # Get clip detail
POST   /api/v1/clips                    # Manual clip creation
PATCH  /api/v1/clips/{clip_id}          # Update clip metadata
DELETE /api/v1/clips/{clip_id}          # Delete clip
POST   /api/v1/clips/{clip_id}/export   # Export in format
POST   /api/v1/clips/{clip_id}/publish  # Publish to platform

# System Control
POST   /api/v1/system/start             # Start monitoring
POST   /api/v1/system/stop              # Stop monitoring
GET    /api/v1/system/status             # System health + metrics
GET    /api/v1/system/stream             # Current stream info

# Analytics
GET    /api/v1/analytics/dashboard       # Aggregated metrics
GET    /api/v1/analytics/events          # Event timeline
GET    /api/v1/analytics/scores          # Score distribution

# Preferences
GET    /api/v1/preferences              # User preferences
PUT    /api/v1/preferences              # Update preferences

# Real-time (WebSocket)
WS     /ws/v1/events                    # Live event stream
WS     /ws/v1/metrics                   # Live metrics
WS     /ws/v1/clips                     # New clip notifications
```

### gRPC (internal service-to-service)

```protobuf
// proto/inference.proto
syntax = "proto3";

service InferenceService {
  // Synchronous single frame inference
  rpc InferFrame(InferFrameRequest) returns (InferFrameResponse);

  // Streaming batch inference (GPU optimization)
  rpc BatchInfer(stream FrameBatch) returns (stream BatchResult);

  // Model management
  rpc GetModelInfo(ModelInfoRequest) returns (ModelInfoResponse);
  rpc ReloadModel(ReloadModelRequest) returns (ReloadModelResponse);
}

message InferFrameRequest {
  bytes frame_data = 1;          // Raw BGR frame bytes
  int32 width = 2;
  int32 height = 3;
  string model_name = 4;         // "face_detector", "emotion_recognizer"
  map<string, string> params = 5;
}

message InferFrameResponse {
  repeated Detection detections = 1;
  float inference_time_ms = 2;
  string model_version = 3;
}

message Detection {
  string class_name = 1;
  float confidence = 2;
  BoundingBox bbox = 3;
  map<string, float> attributes = 4;
}

message BoundingBox {
  float x1 = 1;
  float y1 = 2;
  float x2 = 3;
  float y2 = 4;
}
```

## 1.6 Veri Akışı (Data Flow)

### Frame Processing Pipeline — Detailed

```
HLS Stream (FFmpeg)
    │
    ▼
┌─────────────────┐
│  Frame Decoder  │  FFmpeg subprocess, raw BGR output
│  (capture_engine│  pipe://stdout → numpy.frombuffer()
│   .py)          │  shape=(H, W, 3), dtype=uint8
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Frame Sampler  │  Target: 2 FPS (configurable)
│  (frame_sampler │  Drop frames to maintain target rate
│   .py)          │  Every Nth frame where N = source_fps / target_fps
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌────────┐ ┌─────────────────┐
│ Rolling│ │ Event Publisher │  Kafka topic: "frames.raw"
│ Buffer │ │ (Kafka produce) │  Key: stream_id
│(deque) │ └─────────────────┘
└───┬────┘
    │ Buffer stores last N seconds of frames
    │ for clip extraction (default: 30s)
    │
    ▼ (consumed by analysis services via Kafka)
┌─────────────────────────────────────────────────────┐
│                 VIDEO ANALYSIS SERVICE                │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ Face     │  │ Pose     │  │ OCR      │          │
│  │ Detector │  │ Estimator│  │ Engine   │          │
│  │ (GPU)    │  │ (GPU)    │  │ (GPU)    │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │              │              │                 │
│       ▼              ▼              ▼                 │
│  ┌──────────────────────────────────────────┐        │
│  │          Inference Batch Scheduler       │        │
│  │  - Groups detections per frame           │        │
│  │  - Dynamic batching (max_batch=8)        │        │
│  │  - Priority queue (faces > pose > OCR)   │        │
│  └──────────────────┬───────────────────────┘        │
│                     │                                 │
│                     ▼                                 │
│  ┌──────────────────────────────────────────┐        │
│  │          Results Aggregator              │        │
│  │  - Merge all model outputs per frame     │        │
│  │  - Publish to Kafka: "analysis.results"  │        │
│  └──────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────┘
```

## 1.7 Production Problemleri ve Çözümleri

### Problem 1: Frame Backpressure
**Senaryo:** GPU inference 50ms/frame sürüyor ama frame 33ms'de bir geliyor (30 FPS). Queue şişer, memory overflow.

**Çözüm:**
```python
class BackpressureManager:
    """
    Frame rate'i inference hızına göre dinamik ayarlar.
    GPU utilization > 90% ise frame drop başlar.
    """
    def __init__(self, target_fps: int = 2, max_queue_size: int = 10):
        self.target_fps = target_fps
        self.max_queue_size = max_queue_size
        self.current_drop_rate = 0
        self._gpu_util_history = deque(maxlen=100)

    async def should_process_frame(self) -> bool:
        queue_size = self.get_queue_size()
        gpu_util = await self.get_gpu_utilization()

        self._gpu_util_history.append(gpu_util)
        avg_gpu = sum(self._gpu_util_history) / len(self._gpu_util_history)

        if queue_size > self.max_queue_size * 0.8:
            # Queue %80 dolu → aggressive drop
            self.current_drop_rate = min(self.current_drop_rate + 1, 5)
            return self._should_drop(self.current_drop_rate)
        elif avg_gpu > 90:
            # GPU sıcak → moderate drop
            self.current_drop_rate = min(self.current_drop_rate + 1, 3)
            return self._should_drop(self.current_drop_rate)
        elif queue_size < self.max_queue_size * 0.3 and avg_gpu < 60:
            # Queue boş + GPU soğuk → recover
            self.current_drop_rate = max(self.current_drop_rate - 1, 0)

        return True
```

### Problem 2: Model Cold Start
**Senaryo:** İlk inference 5-10 saniye sürüyor (model loading + CUDA warmup). Bu sırada frame'ler kaybolur.

**Çözüm:**
```python
class ModelWarmup:
    """
    Servis başlarken tüm modelleri pre-load eder.
    Dummy inference ile CUDA kernel'ları compile eder.
    """
    async def warmup_all(self):
        # 1. Model dosyalarını yükle
        await self._load_models()

        # 2. Dummy tensor ile CUDA warmup
        dummy_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
        dummy_batch = torch.zeros(1, 3, 640, 640).cuda()

        # 3. Her model için 3 dummy inference (CUDA graph capture)
        for model in self.models.values():
            for _ in range(3):
                _ = model.predict(dummy_frame)

        logger.info("All models warmed up and ready")
```

### Problem 3: Event Ordering
**Senaryo:** Kafka'da event'ler sırasız varıyor (partition rebalancing). Frame 100'ün emotion sonucu, frame 99'dan önce geliyor.

**Çözüm:**
```python
class EventOrderer:
    """
    Sliding window ile event'leri sıralar.
    max_delay=500ms bekler, sonra flush eder.
    """
    def __init__(self, window_ms: int = 500):
        self.window_ms = window_ms
        self.buffer: list[SystemEvent] = []
        self.last_emitted_ts = 0

    async def add_and_flush(self, event: SystemEvent) -> list[SystemEvent]:
        self.buffer.append(event)

        # Window dışındaki eski event'leri flush et
        cutoff = event.timestamp - timedelta(milliseconds=self.window_ms)
        ready = [e for e in self.buffer if e.timestamp <= cutoff]
        self.buffer = [e for e in self.buffer if e.timestamp > cutoff]

        # Sort by timestamp
        ready.sort(key=lambda e: e.timestamp)
        return ready
```

---

# PART 2 — MICROSERVICE DESIGN

## 2.1 Neden Microservice?

### Monolith vs Microservice — Bu Proje İçin Karşılaştırma

```
MONOLITH PROBLEMLERI:
┌─────────────────────────────────────────────┐
│              MONOLITHIC APP                  │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐          │
│  │Video│ │Audio│ │Chat │ │Clip │  ← Hepsi  │
│  │Anal │ │Anal │ │Anal │ │Gen  │    aynı   │
│  │(GPU)│ │(GPU)│ │(CPU)│ │(GPU)│    process│
│  └─────┘ └─────┘ └─────┘ └─────┘          │
│                                             │
│  ❌ GPU OOM → Tüm sistem crash             │
│  ❌ Chat spike → Video analysis yavaşlar    │
│  ❌ Model update → Full restart             │
│  ❌ Scale = Tüm uygulamayı çoğalt           │
└─────────────────────────────────────────────┘

MICROSERVICE AVANTAJLARI:
┌─────┐    ┌─────┐    ┌─────┐    ┌─────┐
│Video│    │Audio│    │Chat │    │Clip │
│Anal │◄──►│Anal │◄──►│Anal │◄──►│Gen  │
│(GPU)│    │(GPU)│    │(CPU)│    │(GPU)│
└──┬──┘    └──┬──┘    └──┬──┘    └──┬──┘
   │          │          │          │
   └──── Kafka / RabbitMQ / Redis ──┘

  ✅ GPU OOM → Sadece video-analysis restart
  ✅ Chat spike → Chat-analysis auto-scale
  ✅ Model update → Rolling deployment
  ✅ Scale = Her servis bağımsız
```

## 2.2 Service Decomposition

### Service Boundary'leri Nasıl Belirlenir?

Her servisin **tek bir responsibility**'si olmalı (SRP — Single Responsibility Principle):

| Service | Responsibility | Input | Output | Resource |
|---------|---------------|-------|--------|----------|
| stream-capture | Stream ingestion + frame extraction | HLS URL | Raw frames + events | CPU + Network |
| video-analysis | Visual AI inference | Frames | Detections + features | GPU |
| audio-analysis | Audio AI processing | Audio chunks | Transcripts + features | GPU |
| chat-analysis | NLP on chat messages | Chat text | Sentiment + toxicity | CPU |
| event-detector | Event aggregation + scoring | All events | Scored events | CPU |
| decision-engine | Clip/no-clip decision | Scored events | Clip candidates | CPU |
| clip-generator | Video cutting + post-process | Clip candidate | Final clip file | GPU + CPU |
| upload-service | Multi-platform publishing | Clip + metadata | Published URL | Network |
| api-gateway | External API + dashboard | HTTP/WS | JSON responses | CPU |

### Service Interface Contracts

Her servis **contract-first** tasarlanır:

```python
# shared/event_schemas.py
# Tüm servisler bu schema'ları import eder

from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from enum import Enum

class EventType(str, Enum):
    # Stream events
    STREAM_STARTED = "stream.started"
    STREAM_ENDED = "stream.ended"
    STREAM_ERROR = "stream.error"

    # Frame events
    FRAME_EXTRACTED = "frame.extracted"

    # Analysis events
    FACE_DETECTED = "analysis.face_detected"
    EMOTION_DETECTED = "analysis.emotion_detected"
    POSE_DETECTED = "analysis.pose_detected"
    OBJECT_DETECTED = "analysis.object_detected"
    TEXT_DETECTED = "analysis.text_detected"

    # Audio events
    AUDIO_FEATURES = "audio.features"
    AUDIO_SPIKE = "audio.spike"
    TRANSCRIPT_READY = "audio.transcript_ready"
    VAD_DETECTED = "audio.vad_detected"
    SPEAKER_IDENTIFIED = "audio.speaker_identified"

    # Chat events
    CHAT_MESSAGE = "chat.message"
    CHAT_SENTIMENT = "chat.sentiment"
    CHAT_TOXICITY = "chat.toxicity"
    CHAT_SPIKE = "chat.spike"

    # Viewer events
    VIEWER_COUNT = "viewer.count"

    # Decision events
    EVENT_TRIGGERED = "decision.event_triggered"
    CLIP_CANDIDATE = "decision.clip_candidate"
    CLIP_CREATED = "clip.created"
    CLIP_REJECTED = "clip.rejected"

    # Post-processing events
    SUBTITLE_READY = "clip.subtitle_ready"
    CLIP_CLASSIFIED = "clip.classified"
    CLIP_PUBLISHED = "clip.published"

class AnalysisResult(BaseModel):
    """Video analysis result for a single frame"""
    frame_id: str
    timestamp: datetime
    faces: list[FaceDetection] = []
    emotions: list[EmotionResult] = []
    poses: list[PoseResult] = []
    objects: list[ObjectDetection] = []
    texts: list[OCRResult] = []
    inference_time_ms: float

class FaceDetection(BaseModel):
    face_id: str
    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    confidence: float
    landmarks: Optional[dict] = None         # 5-point landmarks

class EmotionResult(BaseModel):
    face_id: str
    label: str                               # "happy", "surprised", "angry", etc.
    confidence: float
    scores: dict[str, float]                 # All emotion probabilities

class AudioFeatures(BaseModel):
    """Audio analysis result for a chunk"""
    chunk_id: str
    timestamp: datetime
    rms_energy: float
    zero_crossing_rate: float
    spectral_centroid: float
    mfcc: list[float]                        # 13 coefficients
    is_speech: bool
    speech_probability: float
    is_spike: bool
    spike_magnitude: float
```

## 2.3 Service Lifecycle

```
                    ┌─────────────┐
                    │   STARTUP   │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        Load Config   Connect to    Warmup Models
        (.env)        Event Bus     (if GPU service)
              │            │            │
              └────────────┼────────────┘
                           │
                    ┌──────▼──────┐
                    │   READY     │ ← Health check returns 200
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Consume      Process      Publish
         Events       Events       Results
         (Kafka)      (Pipeline)   (Kafka)
              │            │            │
              └────────────┼────────────┘
                           │ (loop)
                    ┌──────▼──────┐
                    │ SHUTTING    │ ← Graceful shutdown
                    │ DOWN        │    Drain queue
                    └──────┬──────┘    Finish in-flight
                           │
                    ┌──────▼──────┐
                    │   STOPPED   │
                    └─────────────┘
```

### Graceful Shutdown Pattern

```python
import asyncio
import signal
from contextlib import asynccontextmanager

class ServiceLifecycle:
    """
    Her microservice bu lifecycle manager'ı kullanır.
    SIGTERM geldiğinde:
    1. Yeni event kabul etmeyi bırak
    2. In-flight event'leri tamamla (max 30s)
    3. Kafka consumer offset'ini commit et
    4. Connections'ları kapat
    """

    def __init__(self):
        self.is_shutting_down = False
        self.in_flight_tasks: set[asyncio.Task] = set()
        self._shutdown_timeout = 30  # seconds

    async def shutdown(self):
        logger.info("Shutdown signal received, starting graceful shutdown...")
        self.is_shutting_down = True

        # Stop accepting new events
        await self.kafka_consumer.stop()

        # Wait for in-flight tasks
        if self.in_flight_tasks:
            logger.info(f"Waiting for {len(self.in_flight_tasks)} in-flight tasks...")
            done, pending = await asyncio.wait(
                self.in_flight_tasks,
                timeout=self._shutdown_timeout
            )
            if pending:
                logger.warning(f"Cancelling {len(pending)} remaining tasks")
                for task in pending:
                    task.cancel()

        # Commit offsets
        await self.kafka_consumer.commit()

        # Close connections
        await self.kafka_consumer.close()
        await self.kafka_producer.close()
        await self.db_engine.dispose()

        logger.info("Graceful shutdown complete")
```

## 2.4 Scaling Stratejisi

### Her Servis İçin Scaling Profili

```yaml
# Kubernetes HPA (Horizontal Pod Autoscaler) per service

# stream-capture: Sabit 1 replica (single stream, stateful buffer)
stream-capture:
  replicas: 1
  resources:
    cpu: "2"
    memory: "4Gi"
  # Scale edilmez — tek stream, stateful rolling buffer

# video-analysis: GPU-bound, auto-scale by GPU utilization
video-analysis:
  replicas: 1-3
  resources:
    nvidia.com/gpu: 1
    cpu: "4"
    memory: "8Gi"
  hpa:
    metric: gpu_utilization
    target: 70%
  # GPU utilization > 70% → scale up
  # GPU utilization < 30% → scale down

# audio-analysis: GPU-bound but lighter than video
audio-analysis:
  replicas: 1-2
  resources:
    nvidia.com/gpu: 1  # shared GPU (MIG or time-slicing)
    cpu: "2"
    memory: "4Gi"

# chat-analysis: CPU-bound, burst-scalable
chat-analysis:
  replicas: 1-5
  resources:
    cpu: "1"
    memory: "2Gi"
  hpa:
    metric: kafka_lag (consumer group lag)
    target: 100 messages

# event-detector: CPU-bound, single instance (stateful windows)
event-detector:
  replicas: 1
  resources:
    cpu: "2"
    memory: "4Gi"

# decision-engine: CPU-bound, single instance
decision-engine:
  replicas: 1
  resources:
    cpu: "1"
    memory: "2Gi"

# clip-generator: GPU+CPU, queue-based scaling
clip-generator:
  replicas: 1-3
  resources:
    nvidia.com/gpu: 1
    cpu: "4"
    memory: "8Gi"
  hpa:
    metric: clip_queue_depth
    target: 5 clips

# upload-service: I/O-bound, burst-scalable
upload-service:
  replicas: 1-3
  resources:
    cpu: "1"
    memory: "1Gi"
```

---

# PART 3 — SERVICE COMMUNICATION

## 3.1 Hangi Durumda Hangisi Kullanılmalı?

### Decision Matrix

```
┌───────────────────┬────────┬─────────┬────────────┬──────────────┐
│ Use Case          │ REST   │ gRPC    │ Kafka      │ RabbitMQ     │
├───────────────────┼────────┼─────────┼────────────┼──────────────┤
│ External API      │ ✅ YES │ ❌ NO   │ ❌ NO      │ ❌ NO        │
│ Dashboard queries │ ✅ YES │ ❌ NO   │ ❌ NO      │ ❌ NO        │
│ Frame streaming   │ ❌ NO  │ ✅ YES  │ ✅ YES*    │ ❌ NO        │
│ Analysis results  │ ❌ NO  │ ❌ NO   │ ✅ YES     │ ❌ NO        │
│ Event processing  │ ❌ NO  │ ❌ NO   │ ✅ YES     │ ❌ NO        │
│ Task queuing      │ ❌ NO  │ ❌ NO   │ ❌ NO      │ ✅ YES       │
│ Notifications     │ ❌ NO  │ ❌ NO   │ ❌ NO      │ ✅ YES       │
│ Real-time metrics │ ❌ NO  │ ❌ NO   │ ❌ NO      │ Redis Stream │
│ Clip generation   │ ❌ NO  │ ❌ NO   │ ❌ NO      │ ✅ YES       │
│ Upload tasks      │ ❌ NO  │ ❌ NO   │ ❌ NO      │ ✅ YES       │
└───────────────────┴────────┴─────────┴────────────┴──────────────┘

* Kafka preferred for frames due to persistence + replay capability
```

### Neden Her Birini Seçiyoruz?

#### REST (FastAPI) — External Communication
```
Browser/Dashboard  ──REST──►  API Gateway  ──Kafka──►  Internal Services
Mobile App         ──REST──►  API Gateway
External Webhooks  ──REST──►  API Gateway
```

**Neden REST?**
- Browser'dan doğrudan erişilebilir (WebSocket upgrade ile)
- Swagger/OpenAPI otomatik dökümantasyon
- HTTP caching, CDN, load balancer uyumlu
- Her dil/framework destekler

**Dezavantaj:**
- JSON serialization overhead (~10x slower than protobuf)
- Her request/response yeni TCP connection (HTTP/2 ile mitigated)
- Bidirectional streaming yok (WebSocket gerekli)

#### gRPC — Internal High-Throughput Communication
```
stream-capture  ──gRPC──►  video-analysis   (frame streaming)
video-analysis  ──gRPC──►  model-server     (inference calls)
```

**Neden gRPC?**
- Protobuf binary serialization → %90 daha az network traffic
- HTTP/2 multiplexing → tek connection'da çoklu stream
- Bidirectional streaming → frame batch gönderme
- Code generation → type-safe client/server
- Deadline propagation → timeout cascading

**Dezavantaj:**
- Browser'dan doğrudan erişilemez (grpc-web proxy gerekir)
- Load balancing daha karmaşık (L7 load balancer gerekir)
- Debugging zor (binary payload, Wireshark'ta okunamaz)

```python
# gRPC Frame Streaming Example
# services/stream-capture/frame_streamer.py

import grpc
from proto import inference_pb2, inference_pb2_grpc

class FrameStreamClient:
    """
    stream-capture → video-analysis arası frame gönderme.
    Bidirectional streaming: frame gönder, sonuç al.
    """

    def __init__(self, server_address: str = "video-analysis:50051"):
        self.channel = grpc.aio.insecure_channel(
            server_address,
            options=[
                ("grpc.max_send_message_length", 50 * 1024 * 1024),  # 50MB
                ("grpc.max_receive_message_length", 10 * 1024 * 1024),  # 10MB
                ("grpc.keepalive_time_ms", 10000),
                ("grpc.keepalive_timeout_ms", 5000),
            ]
        )
        self.stub = inference_pb2_grpc.InferenceServiceStub(self.channel)

    async def stream_frames(self, frame_iterator):
        """
        Async generator ile frame stream et.
        GPU backpressure'e göre rate adjust edilir.
        """
        async def request_generator():
            async for frame_id, frame_bytes, width, height in frame_iterator:
                yield inference_pb2.InferFrameRequest(
                    frame_data=frame_bytes,
                    width=width,
                    height=height,
                    model_name="all",  # Run all models
                )

        # Bidirectional streaming call
        async for response in self.stub.BatchInfer(request_generator()):
            yield self._parse_response(response)

    def _parse_response(self, response):
        return {
            "detections": [
                {
                    "class": d.class_name,
                    "confidence": d.confidence,
                    "bbox": (d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2),
                    "attributes": dict(d.attributes),
                }
                for d in response.detections
            ],
            "inference_time_ms": response.inference_time_ms,
            "model_version": response.model_version,
        }
```

#### Apache Kafka — Event Backbone

**Neden Kafka (RabbitMQ değil)?**

```
KAFKA:
┌──────────────────────────────────────────────┐
│  Topic: analysis.results                      │
│  ┌──────┬──────┬──────┬──────┬──────┐       │
│  │ P-0  │ P-1  │ P-2  │ P-3  │ P-4  │       │
│  │ msg  │ msg  │ msg  │ msg  │ msg  │       │
│  │ msg  │ msg  │ msg  │ msg  │ msg  │       │
│  │ msg  │ msg  │ msg  │ msg  │ msg  │       │
│  └──────┴──────┴──────┴──────┴──────┘       │
│                                               │
│  ✅ Persistent log (7 gün retention)         │
│  ✅ Replay capability (offset rewind)        │
│  ✅ Multiple consumers (consumer groups)     │
│  ✅ Ordering guarantee per partition         │
│  ✅ High throughput (1M msg/s)               │
└──────────────────────────────────────────────┘

RABBITMQ:
┌──────────────────────────────────────────────┐
│  Queue: clip_tasks                            │
│  ┌──────────────────────────────────────┐    │
│  │ [task1] [task2] [task3] [task4]      │    │
│  └──────────────────────────────────────┘    │
│                                               │
│  ✅ Complex routing (exchanges + bindings)   │
│  ✅ Dead-letter queues (failed tasks)        │
│  ✅ Per-message TTL                          │
│  ✅ Priority queues                          │
│  ✅ Message acknowledgment                   │
│  ❌ No replay (consumed = gone)              │
│  ❌ Lower throughput (~50K msg/s)            │
└──────────────────────────────────────────────┘
```

**Bizim kullanımımız:**

| Data Type | Technology | Reason |
|-----------|-----------|--------|
| Frame events | Kafka | Replayable, persistent, high-throughput |
| Analysis results | Kafka | Multiple consumers, audit trail |
| Event stream | Kafka | Ordered, partitioned, replayable |
| Clip generation tasks | RabbitMQ | Task queue, ack, dead-letter, retry |
| Upload tasks | RabbitMQ | Priority queue, retry with backoff |
| Dashboard real-time | Redis Streams | Sub-ms pub/sub, ephemeral |
| Notifications | RabbitMQ | Fanout exchange, TTL |

#### Kafka Topic Design

```python
# shared/event_bus/kafka_config.py

KAFKA_TOPICS = {
    # High-throughput, high-volume topics
    "frames.raw": {
        "partitions": 4,
        "replication_factor": 1,  # 3 in production
        "retention_ms": 3600000,  # 1 hour (frames are ephemeral)
        "compression": "lz4",
        "description": "Raw frame data from stream capture",
    },

    "analysis.results": {
        "partitions": 4,
        "replication_factor": 1,
        "retention_ms": 86400000,  # 24 hours (useful for replay)
        "compression": "lz4",
        "description": "AI analysis results per frame",
    },

    # Medium-throughput event topics
    "events.all": {
        "partitions": 2,
        "replication_factor": 1,
        "retention_ms": 604800000,  # 7 days (event history)
        "compression": "snappy",
        "description": "All system events (emotion, pose, audio, chat)",
    },

    "events.scored": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 604800000,
        "compression": "snappy",
        "description": "Scored events from event detector",
    },

    # Low-throughput, high-importance topics
    "clip.candidates": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 2592000000,  # 30 days
        "compression": "none",
        "description": "Clip candidates from decision engine",
    },

    "clip.results": {
        "partitions": 1,
        "replication_factor": 1,
        "retention_ms": 2592000000,
        "compression": "none",
        "description": "Generated clip metadata",
    },

    # Chat and viewer topics
    "chat.messages": {
        "partitions": 2,
        "replication_factor": 1,
        "retention_ms": 86400000,
        "compression": "snappy",
        "description": "Raw chat messages from Kick API",
    },

    "chat.analysis": {
        "partitions": 2,
        "replication_factor": 1,
        "retention_ms": 86400000,
        "compression": "snappy",
        "description": "Chat sentiment and toxicity results",
    },
}
```

#### Kafka Producer/Consumer Implementation

```python
# shared/event_bus/kafka_producer.py

import json
import asyncio
from aiokafka import AIOKafkaProducer
from datetime import datetime
from typing import Optional

class EventProducer:
    """
    Async Kafka producer with:
    - Automatic serialization (Pydantic → JSON)
    - Key-based partitioning (same stream_id → same partition)
    - Retry with exponential backoff
    - Delivery confirmation
    """

    def __init__(
        self,
        bootstrap_servers: str = "kafka:9092",
        client_id: str = "klip-producer",
    ):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=bootstrap_servers,
            client_id=client_id,
            value_serializer=lambda v: json.dumps(v, default=str).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            acks="all",                    # Wait for all replicas
            retries=5,                     # Retry on transient failure
            retry_backoff_ms=100,          # Exponential backoff
            max_batch_size=16384,          # 16KB batch
            linger_ms=10,                  # Wait 10ms to fill batch
            compression_type="lz4",        # Fast compression
            enable_idempotence=True,       # No duplicates
        )

    async def start(self):
        await self._producer.start()

    async def stop(self):
        await self._producer.stop()

    async def publish(
        self,
        topic: str,
        event_type: str,
        payload: dict,
        key: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        """
        Publish an event to Kafka.

        Args:
            topic: Kafka topic name
            event_type: Event type string (e.g., "analysis.emotion_detected")
            payload: Event data (must be JSON-serializable)
            key: Partition key (stream_id for ordering)
            correlation_id: For distributed tracing
        """
        message = {
            "event_id": generate_uuid7(),
            "event_type": event_type,
            "timestamp": datetime.utcnow().isoformat(),
            "payload": payload,
            "correlation_id": correlation_id,
            "metadata": {
                "producer": self._producer._client_id,
                "schema_version": "1.0",
            }
        }

        result = await self._producer.send_and_wait(
            topic,
            value=message,
            key=key,
        )

        return result

    async def publish_batch(
        self,
        topic: str,
        events: list[dict],
        key: Optional[str] = None,
    ):
        """Batch publish for high-throughput scenarios"""
        futures = []
        for event in events:
            future = await self._producer.send(
                topic,
                value=event,
                key=key,
            )
            futures.append(future)

        # Wait for all to complete
        results = await asyncio.gather(*futures, return_exceptions=True)
        successes = sum(1 for r in results if not isinstance(r, Exception))
        return successes, len(results) - successes
```

```python
# shared/event_bus/kafka_consumer.py

from aiokafka import AIOKafkaConsumer
from typing import AsyncIterator, Callable

class EventConsumer:
    """
    Async Kafka consumer with:
    - Consumer group (auto-rebalance)
    - Automatic offset commit
    - Dead-letter queue for failed messages
    - Metrics (lag, throughput)
    """

    def __init__(
        self,
        topics: list[str],
        group_id: str,
        bootstrap_servers: str = "kafka:9092",
        auto_offset_reset: str = "latest",
    ):
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=True,
            auto_commit_interval_ms=5000,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
            key_deserializer=lambda k: k.decode("utf-8") if k else None,
            max_poll_records=100,           # Max records per poll
            max_poll_interval_ms=300000,    # 5 minutes
            session_timeout_ms=30000,       # 30 seconds
            heartbeat_interval_ms=10000,    # 10 seconds
        )
        self._dlq_producer = None  # Dead-letter queue producer

    async def start(self):
        await self._consumer.start()

    async def consume_loop(
        self,
        handler: Callable,
        error_handler: Optional[Callable] = None,
    ):
        """
        Main consume loop.

        Args:
            handler: Async function to process each message
            error_handler: Async function for failed messages (→ DLQ)
        """
        async for message in self._consumer:
            try:
                await handler(
                    topic=message.topic,
                    key=message.key,
                    value=message.value,
                    partition=message.partition,
                    offset=message.offset,
                    timestamp=message.timestamp,
                )
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

                if error_handler:
                    await error_handler(message, e)
                else:
                    # Default: send to dead-letter queue
                    await self._send_to_dlq(message, e)

                # Continue processing (don't block on one bad message)
                continue

    async def _send_to_dlq(self, message, error: Exception):
        """Send failed message to dead-letter topic"""
        dlq_topic = f"{message.topic}.dlq"
        dlq_message = {
            "original_topic": message.topic,
            "original_partition": message.partition,
            "original_offset": message.offset,
            "original_value": message.value,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "failed_at": datetime.utcnow().isoformat(),
        }
        if self._dlq_producer:
            await self._dlq_producer.publish(dlq_topic, "dlq.message", dlq_message)
```

#### RabbitMQ — Task Queue Pattern

```python
# shared/event_bus/rabbitmq_publisher.py

import aio_pika
from typing import Optional

class TaskQueuePublisher:
    """
    RabbitMQ publisher for task queues.
    Used for: clip generation, upload tasks, notifications.

    Why RabbitMQ over Kafka for tasks?
    - Per-message acknowledgment (task completed = message acked)
    - Dead-letter exchange (failed tasks → retry queue)
    - Priority queues (urgent clips first)
    - Per-message TTL (expire old tasks)
    - Fair dispatch (round-robin to workers)
    """

    def __init__(self, url: str = "amqp://guest:guest@rabbitmq:5672/"):
        self._url = url
        self._connection = None
        self._channel = None

    async def connect(self):
        self._connection = await aio_pika.connect_robust(self._url)
        self._channel = await self._connection.channel()
        await self._channel.set_qos(prefetch_count=1)  # Fair dispatch

    async def declare_task_queue(
        self,
        queue_name: str,
        durable: bool = True,
        priority_levels: int = 10,
        message_ttl: Optional[int] = None,
    ):
        """
        Declare a task queue with dead-letter exchange.

        Architecture:
        ┌──────────────┐    fail    ┌──────────────┐
        │  Main Queue  │ ─────────► │  DLX Queue   │
        │  (tasks)     │            │  (failed)    │
        └──────────────┘            └──────────────┘
              │                            │
              │ ack                        │ retry after delay
              ▼                            │
         [Worker]                    ┌─────▼─────┐
                                     │  Retry    │
                                     │  Queue    │
                                     │  (delay)  │
                                     └───────────┘
        """
        # Dead-letter exchange
        dlx_name = f"{queue_name}.dlx"
        await self._channel.declare_exchange(dlx_name, aio_pika.ExchangeType.DIRECT)

        # Dead-letter queue
        dlq = await self._channel.declare_queue(
            f"{queue_name}.dead_letter",
            durable=durable,
        )
        dlx_exchange = await self._channel.get_exchange(dlx_name)
        await dlq.bind(dlx_exchange, routing_key=queue_name)

        # Main queue with DLX
        arguments = {
            "x-dead-letter-exchange": dlx_name,
            "x-dead-letter-routing-key": queue_name,
            "x-max-priority": priority_levels,
        }
        if message_ttl:
            arguments["x-message-ttl"] = message_ttl

        queue = await self._channel.declare_queue(
            queue_name,
            durable=durable,
            arguments=arguments,
        )

        return queue

    async def publish_task(
        self,
        queue_name: str,
        task_data: dict,
        priority: int = 5,
        expiration: Optional[int] = None,
    ):
        """Publish a task to the queue"""
        exchange = await self._channel.get_exchange("")  # Default exchange

        message = aio_pika.Message(
            body=json.dumps(task_data, default=str).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            priority=priority,
            expiration=str(expiration) if expiration else None,
            content_type="application/json",
        )

        await exchange.publish(
            message,
            routing_key=queue_name,
        )

    async def close(self):
        if self._connection:
            await self._connection.close()
```

#### Redis Streams — Real-Time Dashboard Updates

```python
# shared/event_bus/redis_streams.py

import redis.asyncio as redis

class RedisStreamPubSub:
    """
    Redis Streams for real-time dashboard updates.

    Why Redis Streams over Kafka for dashboard?
    - Sub-millisecond latency
    - Simple pub/sub semantics
    - Built-in consumer groups
    - Auto-expiry (TTL)
    - Already in the stack for caching

    Use cases:
    - Live metrics (viewer count, chat velocity)
    - Real-time event notifications
    - Dashboard WebSocket push
    - Health check aggregation
    """

    def __init__(self, url: str = "redis://redis:6379/0"):
        self._redis = redis.from_url(url, decode_responses=True)

    async def publish_metric(self, metric_name: str, value: dict):
        """Publish a metric to Redis Stream"""
        await self._redis.xadd(
            f"metrics:{metric_name}",
            mapping={"data": json.dumps(value, default=str)},
            maxlen=1000,  # Keep last 1000 entries
        )
        # Also publish to pub/sub channel for instant notification
        await self._redis.publish(
            f"notifications:{metric_name}",
            json.dumps(value, default=str),
        )

    async def subscribe_stream(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
    ) -> AsyncIterator[dict]:
        """Subscribe to a Redis Stream with consumer group"""
        # Create consumer group if not exists
        try:
            await self._redis.xgroup_create(
                stream_name, group_name, id="0", mkstream=True
            )
        except redis.ResponseError:
            pass  # Group already exists

        while True:
            messages = await self._redis.xreadgroup(
                group_name,
                consumer_name,
                streams={stream_name: ">"},
                count=10,
                block=1000,  # 1 second timeout
            )

            for stream, entries in messages:
                for msg_id, data in entries:
                    yield {
                        "id": msg_id,
                        "data": json.loads(data["data"]),
                    }
                    # Acknowledge processed
                    await self._redis.xack(stream_name, group_name, msg_id)

    async def subscribe_pubsub(self, channel: str) -> AsyncIterator[str]:
        """Subscribe to a Redis pub/sub channel"""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)

        async for message in pubsub.listen():
            if message["type"] == "message":
                yield message["data"]
```

## 3.2 Communication Patterns — Özet Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    COMMUNICATION FLOW                            │
│                                                                  │
│  ┌──────────┐    gRPC (streaming)    ┌──────────────┐          │
│  │  Stream  │ ─────────────────────► │    Video     │          │
│  │ Capture  │                        │   Analysis   │          │
│  │          │ ───── Kafka ─────────► │              │          │
│  └──────────┘   (frame events)      └──────┬───────┘          │
│                                            │                   │
│                                     Kafka (results)             │
│                                            │                   │
│  ┌──────────┐    Kafka              ┌──────▼───────┐          │
│  │  Audio   │ ────────────────────► │    Event     │          │
│  │ Analysis │                       │   Detector   │          │
│  └──────────┘                       └──────┬───────┘          │
│                                            │                   │
│  ┌──────────┐    Kafka              ┌──────▼───────┐          │
│  │  Chat    │ ────────────────────► │  Decision    │          │
│  │ Analysis │                       │   Engine     │          │
│  └──────────┘                       └──────┬───────┘          │
│                                            │                   │
│  ┌──────────┐    Kafka              ┌──────▼───────┐          │
│  │ Viewer   │ ────────────────────► │    Clip      │          │
│  │  Count   │                       │  Generator   │          │
│  └──────────┘                       └──────┬───────┘          │
│                                            │                   │
│                                     RabbitMQ (tasks)            │
│                                            │                   │
│                                     ┌──────▼───────┐          │
│                                     │   Upload     │          │
│                                     │   Service    │          │
│                                     └──────────────┘          │
│                                                                  │
│  ┌──────────┐    REST + WS          ┌──────────────┐          │
│  │ Browser  │ ◄───────────────────► │  API Gateway │          │
│  │Dashboard │    Redis Streams      │              │          │
│  └──────────┘                       └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

# PART 4 — REAL-TIME VIDEO PIPELINE

## 4.1 Neden Özel Bir Pipeline?

Canlı yayın video'su, normal video dosyasından fundamentally farklıdır:

| Özellik | Video Dosyası | Canlı Yayın |
|---------|--------------|-------------|
| Duration | Bilinir | Bilinmez (saatlerce sürebilir) |
| Seek | Mümkün | İmkansız (live only) |
| Bitrate | Sabit | Değişken (network conditions) |
| Buffer | İhtiyaç yok | Zorunlu (jitter handling) |
| Error Recovery | Retry | Skip + continue |
| Format | MP4/MKV/etc | HLS/RTMP segments |

### HLS (HTTP Live Streaming) Nasıl Çalışır?

```
Kick Streaming Server
    │
    │ (RTMP push from OBS)
    ▼
┌───────────────┐
│  Transcoder   │  1080p60 → Multiple renditions
│  (Kick CDN)   │  720p30, 480p30, 360p30
└───────┬───────┘
        │
        ▼
┌───────────────┐     ┌──────────────────────────────┐
│  .m3u8        │     │  Segment 1 (2s)              │
│  Playlist     │────►│  Segment 2 (2s)              │
│  (index)      │     │  Segment 3 (2s) ← current    │
│               │     │  Segment 4 (2s) ← latest     │
└───────────────┘     └──────────────────────────────┘
        │
        │ HTTP GET (her 2 saniyede)
        ▼
┌───────────────┐
│  Our Capture  │  Download .ts segment → Decode → Extract frames
│  Service      │
└───────────────┘
```

## 4.2 Stream Capture Engine — Implementation

```python
# services/stream-capture/capture_engine.py

import asyncio
import subprocess
import numpy as np
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, AsyncIterator, Callable

@dataclass
class Frame:
    """Single video frame with metadata"""
    frame_id: str
    timestamp: datetime
    image: np.ndarray            # BGR format, shape=(H, W, 3)
    width: int
    height: int
    fps: float
    stream_time_seconds: float   # Seconds since stream start

@dataclass
class StreamInfo:
    """Current stream metadata"""
    stream_id: str
    platform: str
    channel_slug: str
    title: str
    started_at: datetime
    viewer_count: int
    resolution: tuple[int, int]
    fps: float

class RollingBuffer:
    """
    Ring buffer for storing recent frames.

    Memory calculation:
    - 1080p frame (1920x1080x3) = 6.2 MB uncompressed
    - 2 FPS × 30 seconds = 60 frames
    - 60 × 6.2 MB = 372 MB

    For 720p:
    - 720p frame (1280x720x3) = 2.8 MB
    - 60 frames = 168 MB

    The buffer uses numpy views to avoid copies where possible.
    """

    def __init__(
        self,
        max_seconds: int = 30,
        target_fps: int = 2,
        resolution: tuple[int, int] = (1280, 720),
    ):
        self.max_seconds = max_seconds
        self.target_fps = target_fps
        self.resolution = resolution
        self.max_frames = max_seconds * target_fps

        self._frames: deque[Frame] = deque(maxlen=self.max_frames)
        self._frame_index: dict[str, int] = {}  # frame_id → buffer index

    def add(self, frame: Frame):
        """Add frame to buffer, evicting oldest if full"""
        self._frame_index[frame.frame_id] = len(self._frames)
        self._frames.append(frame)

    def get_range(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        start_seconds: Optional[float] = None,
        end_seconds: Optional[float] = None,
    ) -> list[Frame]:
        """
        Get frames in a time range.

        Supports both absolute datetime and relative stream-time.
        """
        frames = list(self._frames)

        if start_time and end_time:
            return [
                f for f in frames
                if start_time <= f.timestamp <= end_time
            ]
        elif start_seconds is not None and end_seconds is not None:
            return [
                f for f in frames
                if start_seconds <= f.stream_time_seconds <= end_seconds
            ]
        return frames

    def get_latest(self, n: int = 1) -> list[Frame]:
        """Get the N most recent frames"""
        return list(self._frames)[-n:]

    @property
    def oldest_timestamp(self) -> Optional[datetime]:
        return self._frames[0].timestamp if self._frames else None

    @property
    def newest_timestamp(self) -> Optional[datetime]:
        return self._frames[-1].timestamp if self._frames else None

    @property
    def duration_seconds(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        return (self._frames[-1].timestamp - self._frames[0].timestamp).total_seconds()

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def memory_usage_mb(self) -> float:
        """Approximate memory usage"""
        if not self._frames:
            return 0.0
        frame_size = self._frames[0].image.nbytes / (1024 * 1024)
        return frame_size * len(self._frames)


class StreamCaptureEngine:
    """
    Captures HLS stream using FFmpeg subprocess.

    Architecture:
    ┌────────────────────────────────────────────────────┐
    │ FFmpeg Subprocess                                   │
    │                                                     │
    │ Input: HLS URL (-i https://...m3u8)               │
    │ Filter: fps=2 (-vf fps=2)                          │
    │ Output: Raw BGR pipe (-f rawvideo -pix_fmt bgr24)  │
    │                                                     │
    │ stdout ──────► numpy.frombuffer() ──► Frame        │
    └────────────────────────────────────────────────────┘

    Why FFmpeg subprocess instead of OpenCV VideoCapture?
    - OpenCV VideoCapture doesn't handle HLS well (buffering issues)
    - FFmpeg has better error recovery for network interruptions
    - FFmpeg handles codec negotiation automatically
    - Can use hardware acceleration (NVDEC, VAAPI)
    - Better control over buffering (-fflags nobuffer)
    """

    def __init__(
        self,
        stream_url: str,
        target_fps: int = 2,
        buffer_seconds: int = 30,
        resolution: Optional[tuple[int, int]] = None,
    ):
        self.stream_url = stream_url
        self.target_fps = target_fps
        self.buffer_seconds = buffer_seconds
        self.resolution = resolution

        self.rolling_buffer = RollingBuffer(
            max_seconds=buffer_seconds,
            target_fps=target_fps,
        )

        self._process: Optional[subprocess.Popen] = None
        self._is_running = False
        self._frame_counter = 0
        self._start_time: Optional[datetime] = None
        self._frame_callbacks: list[Callable] = []

    def on_frame(self, callback: Callable):
        """Register a callback for each new frame"""
        self._frame_callbacks.append(callback)

    async def start(self):
        """Start capturing the stream"""
        if self._is_running:
            raise RuntimeError("Capture already running")

        # Build FFmpeg command
        cmd = self._build_ffmpeg_command()
        logger.info(f"Starting FFmpeg capture: {' '.join(cmd)}")

        # Start FFmpeg subprocess
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8,  # 100MB buffer
        )

        self._is_running = True
        self._start_time = datetime.utcnow()

        # Start reading frames in background
        await self._read_loop()

    def _build_ffmpeg_command(self) -> list[str]:
        """Build the FFmpeg command for HLS capture"""
        cmd = [
            "ffmpeg",

            # Input options
            "-fflags", "nobuffer",         # Minimize input buffering
            "-flags", "low_delay",         # Low latency mode
            "-reconnect", "1",             # Auto-reconnect on disconnect
            "-reconnect_streamed", "1",    # Reconnect for streaming
            "-reconnect_delay_max", "5",   # Max 5s reconnect delay
            "-i", self.stream_url,         # Input URL

            # Video filter
            "-vf", f"fps={self.target_fps}",  # Target FPS
        ]

        # Optional resolution scaling
        if self.resolution:
            w, h = self.resolution
            cmd.extend(["-s", f"{w}x{h}"])

        # Output options
        cmd.extend([
            "-f", "rawvideo",              # Raw output
            "-pix_fmt", "bgr24",           # BGR format (OpenCV compatible)
            "-an",                         # No audio (separate audio pipeline)
            "pipe:1",                      # Output to stdout
        ])

        return cmd

    async def _read_loop(self):
        """
        Main frame reading loop.

        Reads raw BGR bytes from FFmpeg stdout pipe,
        converts to numpy arrays, and stores in rolling buffer.
        """
        # Determine frame size
        if self.resolution:
            width, height = self.resolution
        else:
            width, height = 1920, 1080  # Default, will be detected

        frame_size = width * height * 3  # BGR = 3 bytes per pixel

        while self._is_running and self._process.poll() is None:
            # Read one frame from pipe
            raw_data = await asyncio.get_event_loop().run_in_executor(
                None,
                self._process.stdout.read,
                frame_size,
            )

            if len(raw_data) < frame_size:
                # Stream ended or error
                logger.warning(f"Incomplete frame: {len(raw_data)}/{frame_size} bytes")
                break

            # Convert to numpy array
            frame_array = np.frombuffer(raw_data, dtype=np.uint8).reshape(
                (height, width, 3)
            )

            # Create Frame object
            now = datetime.utcnow()
            frame = Frame(
                frame_id=f"frame_{self._frame_counter:08d}",
                timestamp=now,
                image=frame_array,
                width=width,
                height=height,
                fps=self.target_fps,
                stream_time_seconds=(now - self._start_time).total_seconds(),
            )

            # Store in rolling buffer
            self.rolling_buffer.add(frame)
            self._frame_counter += 1

            # Notify callbacks
            for callback in self._frame_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(frame)
                    else:
                        callback(frame)
                except Exception as e:
                    logger.error(f"Frame callback error: {e}")

    async def stop(self):
        """Stop the capture"""
        self._is_running = False
        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

    def extract_clip(
        self,
        start_time: datetime,
        end_time: datetime,
        output_path: str,
        pre_seconds: float = 2.0,
        post_seconds: float = 2.0,
    ) -> Optional[str]:
        """
        Extract a clip from the rolling buffer.

        This is the KEY advantage of the rolling buffer approach:
        When an event is detected, we can immediately extract a clip
        from the buffer WITHOUT waiting for FFmpeg to finish a segment.

        Args:
            start_time: Event detection timestamp
            end_time: End of interesting segment
            output_path: Where to save the clip
            pre_seconds: Extra seconds before start (context)
            post_seconds: Extra seconds after end (context)

        Returns:
            Path to saved clip file, or None if insufficient buffer
        """
        # Calculate actual time range with context
        clip_start = start_time - timedelta(seconds=pre_seconds)
        clip_end = end_time + timedelta(seconds=post_seconds)

        # Get frames from buffer
        frames = self.rolling_buffer.get_range(
            start_time=clip_start,
            end_time=clip_end,
        )

        if not frames:
            logger.warning("No frames in buffer for clip extraction")
            return None

        logger.info(f"Extracting clip: {len(frames)} frames, "
                    f"{frames[0].timestamp} → {frames[-1].timestamp}")

        # Write frames to temporary AVI first (fast, no encoding)
        temp_path = output_path + ".temp.avi"
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(
            temp_path,
            fourcc,
            self.target_fps,
            (frames[0].width, frames[0].height),
        )

        for frame in frames:
            writer.write(frame.image)

        writer.release()

        # Re-encode to final format with FFmpeg (proper timestamps, audio mux)
        subprocess.run([
            "ffmpeg", "-y",
            "-i", temp_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            "-movflags", "+faststart",
            output_path,
        ], capture_output=True, timeout=60)

        # Clean up temp file
        os.remove(temp_path)

        return output_path
```

## 4.3 Frame Sampling Strategies

```python
# services/stream-capture/frame_sampler.py

class FrameSampler:
    """
    Controls how frames are sampled from the source stream.

    Different analysis tasks need different sampling rates:

    | Task              | Target FPS | Reason                        |
    |-------------------|-----------|-------------------------------|
    | Face Detection    | 2-5 FPS   | Faces don't move that fast    |
    | Emotion Detection | 1-2 FPS   | Emotions change slowly        |
    | Pose Detection    | 5-10 FPS  | Body movements are faster     |
    | OCR              | 0.5 FPS   | Text changes rarely           |
    | Object Detection  | 1-2 FPS   | Objects appear/disappear      |
    | Scene Detection   | 1 FPS     | Scene changes are rare        |

    Strategy: Sample at highest needed rate (e.g., 5 FPS for pose),
    then sub-sample for slower tasks.
    """

    class SamplingStrategy(Enum):
        UNIFORM = "uniform"           # Every Nth frame
        ADAPTIVE = "adaptive"         # Adjust based on scene motion
        KEYFRAME_ONLY = "keyframe"    # Only I-frames (scene changes)
        BURST = "burst"              # High FPS for short periods

    def __init__(
        self,
        source_fps: float = 30.0,
        target_fps: float = 2.0,
        strategy: SamplingStrategy = SamplingStrategy.UNIFORM,
    ):
        self.source_fps = source_fps
        self.target_fps = target_fps
        self.strategy = strategy
        self.frame_interval = max(1, int(source_fps / target_fps))
        self._frame_count = 0
        self._motion_history: deque[float] = deque(maxlen=30)

    def should_sample(self, frame_index: int, motion_score: float = 0.0) -> bool:
        """
        Determine if this frame should be sampled.

        UNIFORM: Every Nth frame
        ADAPTIVE: More frames when motion is high, fewer when static
        KEYFRAME: Only when scene change detected
        BURST: High FPS burst when event detected
        """
        if self.strategy == self.SamplingStrategy.UNIFORM:
            return frame_index % self.frame_interval == 0

        elif self.strategy == self.SamplingStrategy.ADAPTIVE:
            self._motion_history.append(motion_score)
            avg_motion = sum(self._motion_history) / len(self._motion_history)

            if motion_score > avg_motion * 2:
                # High motion → sample every frame
                return True
            elif motion_score < avg_motion * 0.3:
                # Low motion → sample less
                return frame_index % (self.frame_interval * 2) == 0
            else:
                return frame_index % self.frame_interval == 0

        elif self.strategy == self.SamplingStrategy.KEYFRAME_ONLY:
            # Scene change detection via motion score threshold
            return motion_score > 0.8

        elif self.strategy == self.SamplingStrategy.BURST:
            # Burst mode: 10 FPS for 5 seconds, then back to 2 FPS
            # Controlled externally via set_burst()
            return True

        return False
```

---

# PART 5 — ROLLING BUFFER & FRAME SAMPLING (Deep Dive)

## 5.1 Memory-Optimized Rolling Buffer

The naive approach of storing raw frames in memory is wasteful. Production systems use several optimizations:

### Approach 1: JPEG Compression In-Memory

```python
class CompressedRollingBuffer:
    """
    Stores frames as JPEG-compressed bytes in memory.

    Memory comparison:
    - Raw 1080p BGR: 6.2 MB per frame
    - JPEG quality=70: ~150 KB per frame (40x reduction)
    - 60 frames: 372 MB → 9 MB

    Trade-off: JPEG decode adds ~2ms per frame retrieval
    """

    def __init__(self, max_frames: int = 60, jpeg_quality: int = 70):
        self.max_frames = max_frames
        self.jpeg_quality = jpeg_quality
        self._buffer: deque[tuple[str, datetime, bytes, int, int]] = deque(
            maxlen=max_frames
        )  # (frame_id, timestamp, jpeg_bytes, width, height)

    def add(self, frame: Frame):
        # Compress to JPEG
        _, jpeg_bytes = cv2.imencode(
            ".jpg",
            frame.image,
            [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality],
        )
        self._buffer.append((
            frame.frame_id,
            frame.timestamp,
            jpeg_bytes.tobytes(),
            frame.width,
            frame.height,
        ))

    def get_frame(self, frame_id: str) -> Optional[Frame]:
        for fid, ts, jpeg_data, w, h in self._buffer:
            if fid == frame_id:
                # Decode JPEG back to numpy
                image = cv2.imdecode(
                    np.frombuffer(jpeg_data, dtype=np.uint8),
                    cv2.IMREAD_COLOR,
                )
                return Frame(
                    frame_id=fid,
                    timestamp=ts,
                    image=image,
                    width=w,
                    height=h,
                    fps=0,
                    stream_time_seconds=0,
                )
        return None
```

### Approach 2: Shared Memory with FFmpeg

```python
class SharedMemoryBuffer:
    """
    Uses FFmpeg to write frames to a shared memory ring buffer
    instead of Python process memory.

    Benefits:
    - Zero-copy frame access (mmap)
    - Survives Python GC pauses
    - Can be shared across processes
    """

    def __init__(self, max_frames: int = 60, frame_shape: tuple = (720, 1280, 3)):
        from multiprocessing import shared_memory

        frame_size = frame_shape[0] * frame_shape[1] * frame_shape[2]
        total_size = max_frames * frame_size

        self._shm = shared_memory.SharedMemory(
            create=True,
            size=total_size,
            name="klip_frame_buffer",
        )
        self._frame_size = frame_size
        self._max_frames = max_frames
        self._write_index = 0
        self._frame_shape = frame_shape

    def write_frame(self, frame: np.ndarray):
        """Write frame to shared memory at current index"""
        offset = self._write_index * self._frame_size
        self._shm.buf[offset:offset + self._frame_size] = frame.tobytes()
        self._write_index = (self._write_index + 1) % self._max_frames

    def read_frame(self, index: int) -> np.ndarray:
        """Read frame from shared memory"""
        offset = index * self._frame_size
        data = bytes(self._shm.buf[offset:offset + self._frame_size])
        return np.frombuffer(data, dtype=np.uint8).reshape(self._frame_shape)
```

## 5.2 Clip Extraction from Buffer

The critical path: **Event Detected → Clip Extracted**

```
Timeline:
─────────────────────────────────────────────────────────►
│     Rolling Buffer (30 seconds)     │
│  [f1] [f2] [f3] ... [f58] [f59] [f60] │
│                                        │
│           Event at f45                 │
│           ┌────┐                       │
│           │ 💥 │                       │
│           └────┘                       │
│                                        │
│  Pre-context: f35 to f45 (5 seconds)  │
│  Post-context: f45 to f55 (5 seconds) │
│                                        │
│  Clip = f35 → f55 (10 seconds)        │
─────────────────────────────────────────────────────────►

Challenge: Post-context frames haven't arrived yet!

Solution: Delayed extraction
1. Event detected at T=0
2. Wait for post_seconds (5s)
3. Extract clip from buffer at T=5
4. All frames now available in buffer
```

```python
class ClipExtractor:
    """
    Extracts clips from the rolling buffer with delayed extraction.

    Flow:
    Event Detected
        │
        ▼
    Wait post_seconds (collect more frames)
        │
        ▼
    Extract frames from buffer
        │
        ▼
    Write temporary video file
        │
        ▼
    Re-encode with proper codec
        │
        ▼
    Clip Ready
    """

    def __init__(
        self,
        buffer: RollingBuffer,
        pre_seconds: float = 5.0,
        post_seconds: float = 5.0,
        max_clip_duration: float = 60.0,
        output_dir: str = "data/clips",
    ):
        self.buffer = buffer
        self.pre_seconds = pre_seconds
        self.post_seconds = post_seconds
        self.max_clip_duration = max_clip_duration
        self.output_dir = output_dir

        os.makedirs(output_dir, exist_ok=True)

    async def extract_on_event(
        self,
        event_timestamp: datetime,
        event_type: str,
        event_score: float,
        clip_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        Extract a clip centered around an event.

        This is called immediately when an event is detected.
        It waits for post_seconds to collect enough frames,
        then extracts from the rolling buffer.
        """
        clip_id = clip_id or generate_uuid7()

        # Calculate time window
        clip_start = event_timestamp - timedelta(seconds=self.pre_seconds)
        clip_end = event_timestamp + timedelta(seconds=self.post_seconds)

        # Wait for post-context frames
        logger.info(
            f"Waiting {self.post_seconds}s for post-context frames "
            f"(clip: {clip_start} → {clip_end})"
        )
        await asyncio.sleep(self.post_seconds)

        # Get frames from buffer
        frames = self.buffer.get_range(start_time=clip_start, end_time=clip_end)

        if len(frames) < 3:
            logger.warning(f"Insufficient frames ({len(frames)}) for clip {clip_id}")
            return None

        # Limit clip duration
        actual_duration = (frames[-1].timestamp - frames[0].timestamp).total_seconds()
        if actual_duration > self.max_clip_duration:
            frames = frames[:int(self.max_clip_duration * frames[0].fps)]

        # Write clip
        output_path = os.path.join(
            self.output_dir,
            f"clip_{clip_id}_{event_type}.mp4",
        )

        return self._write_clip(frames, output_path)

    def _write_clip(self, frames: list[Frame], output_path: str) -> str:
        """Write frames to video file using OpenCV + FFmpeg"""
        if not frames:
            return None

        # Step 1: Write raw frames to temporary AVI
        temp_path = output_path + ".temp.avi"
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(
            temp_path,
            fourcc,
            frames[0].fps or 2.0,
            (frames[0].width, frames[0].height),
        )

        for frame in frames:
            writer.write(frame.image)
        writer.release()

        # Step 2: Re-encode to H.264 MP4
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", temp_path,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "18",             # High quality
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                output_path,
            ],
            capture_output=True,
            timeout=120,
        )

        # Cleanup
        os.remove(temp_path)

        file_size = os.path.getsize(output_path)
        logger.info(
            f"Clip saved: {output_path} "
            f"({len(frames)} frames, {file_size / 1024 / 1024:.1f} MB)"
        )

        return output_path
```
