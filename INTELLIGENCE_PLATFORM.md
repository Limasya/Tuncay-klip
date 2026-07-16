# INTELLIGENCE PLATFORM — System Architecture Document

## AI Content Analysis Platform for YouTube, Twitch & Kick Scale

**Version:** 3.0.0
**Classification:** Internal — Engineering Reference
**Scope:** Full Intelligence Platform (beyond clip selection — end-to-end AI content intelligence)

---

## Document Purpose

Bu doküman, mevcut "klip seçen AI" sistemini, YouTube/Twitch/Kick seviyesinde profesyonel bir **AI Content Intelligence Platform**'una dönüştürür. Her servisin klasör yapısı, veri akışı, sequence diyagramları, event şemaları, database tabloları, API tasarımı, production senaryoları ve ölçeklenebilirlik stratejileri ayrıntılı olarak açıklanır.

---

## Reading Map

### Master Document (this file)

| Section | Coverage |
|---|---|
| Platform Vision | Neden Intelligence Platform? Mevcut sistemden farkı |
| High-Level Architecture | Tüm katmanların tek diyagramda görünümü |
| Technology Stack | Tam teknoloji yığını ve seçim gerekçeleri |
| Service Registry | 30+ servisin kısa başvuru tablosu |
| Data Topology | PostgreSQL + ClickHouse + Qdrant + Kafka + Redis birlikte kullanımı |

### Part Documents

| File | Coverage | Key Topics |
|---|---|---|
| `IP_PART1_ARCHITECTURE.md` | Sistem omurgası ve çok-ajanlı beyin | Event Driven Architecture, Real-time Stream Processing, Distributed AI Pipeline, Multi-Agent Architecture, AI Orchestrator, Model Router |
| `IP_PART2_AI_INTELLIGENCE.md` | AI zeka katmanı | Video Understanding, VLM, Multimodal AI, Long Context Memory, Knowledge Graph, Context Engine, Semantic Timeline, Retrieval Engine, Embedding Pipeline, LLM Decision Layer |
| `IP_PART3_STREAM_INTELLIGENCE.md` | Akış zekası ve öngörü motorları | Stream Intelligence, Viral Prediction Engine, Content Scoring Engine, Trend Detection, RL from Creator Feedback, Feature Store |
| `IP_PART4_DATA_INFRASTRUCTURE.md` | Veri altyapısı | Event Store, Time Series Database, Kafka Topics Design, Redis Streams, PostgreSQL + ClickHouse + Qdrant |
| `IP_PART5_GPU_ORCHESTRATION.md` | GPU ve orkestrasyon | AI Workflow Orchestration (Temporal/Airflow/Prefect), GPU Scheduling, TensorRT, ONNX Runtime, Triton Inference Server |
| `IP_PART6_PLATFORM_ENGINEERING.md` | Platform mühendisliği | API Gateway, Authentication, Observability, Distributed Tracing, Monitoring, Feature Flags, A/B Testing, Chaos Engineering, Auto Scaling, Kubernetes, GitOps, CI/CD, Production Deployment |

---

## Platform Vision

### Mevcut Sistem → Intelligence Platform

```
MEVCUT SİSTEM (v2.0)                    INTELLIGENCE PLATFORM (v3.0)
══════════════════════                  ════════════════════════════
Klip seçen AI                           İçerik zeka platformu
                                       
Rule-based scoring                      Multi-agent AI orchestration
Signal threshold → clip                 Context-aware decision making
                                       
Single GPU, single model                Distributed GPU cluster, model routing
Sequential inference                    Parallel inference, dynamic batching
                                       
PostgreSQL only                         PostgreSQL + ClickHouse + Qdrant
                                        + Event Store + Time Series DB
                                       
No memory                               Long Context Memory + Knowledge Graph
                                        
No prediction                           Viral Prediction Engine
                                        Trend Detection
                                        Content Scoring
                                       
No feedback loop                        Reinforcement Learning from
                                        Creator Feedback (RLCF)
                                        
Manual deployment                       GitOps + K8s auto-scaling
                                        Chaos engineering ready
```

### Core Principles

1. **Everything is an Event** — Event Sourcing + CQRS. Tüm state değişiklikleri immutable event'ler olarak kaydedilir.
2. **Multi-Agent by Design** — Tek bir monolitik AI yerine, uzmanlaşmış ajanlar koordineli çalışır.
3. **Multimodal Understanding** — Video + Audio + Chat + Metadata eşzamanlı analiz.
4. **Predictive, Not Just Reactive** — Geçmişe bakmakla kalmaz, geleceği öngörür (viral prediction, trend detection).
5. **Learning from Feedback** — Creator feedback'inden öğrenir, zamanla daha iyi clip'ler üretir.
6. **Production-Grade Operations** — Feature flags, A/B testing, chaos engineering, auto-scaling.
7. **Polyglot Persistence** — Her veri tipi için doğru araç: PostgreSQL (OLTP), ClickHouse (OLAP), Qdrant (vectors), Kafka (events), Redis (hot cache).

---

## High-Level Architecture

```
                           ┌─────────────────────────────────────────────┐
                           │              API GATEWAY                     │
                           │   (Kong / Traefik — Auth, Rate Limit, WAF)  │
                           └──────────────────────┬──────────────────────┘
                                                  │
                    ┌─────────────────────────────┼─────────────────────────────┐
                    │                             │                             │
              ┌─────▼─────┐              ┌────────▼────────┐          ┌────────▼────────┐
              │  Creator   │              │  Platform API   │          │  Webhook/API    │
              │  Dashboard │              │  (FastAPI)      │          │  Consumers      │
              │  (React)   │              │                 │          │                 │
              └─────┬──────┘              └────────┬────────┘          └────────┬────────┘
                    │                              │                            │
                    └──────────┬───────────────────┘                            │
                               │                                                 │
                    ┌──────────▼──────────────────────────────────────────────────▼─────┐
                    │                    EVENT BUS (Kafka)                            │
                    │  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐ │
                    │  │ stream  │ │ analysis │ │ decision │ │  clip   │ │ feedback │ │
                    │  │ events  │ │  events  │ │  events  │ │ events  │ │  events  │ │
                    │  └────┬────┘ └────┬─────┘ └────┬─────┘ └────┬────┘ └────┬─────┘ │
                    └───────┼───────────┼────────────┼────────────┼───────────┼───────┘
                            │           │            │            │           │
          ┌─────────────────┼───────────┼────────────┼────────────┼───────────┼──────────────┐
          │                 │           │            │            │           │              │
   ┌──────▼──────┐  ┌──────▼──────┐ ┌──▼─────────┐ ┌▼──────────┐ ┌▼─────────┐ ┌▼───────────┐ │
   │   STREAM    │  │   ANALYSIS  │ │ DECISION   │ │   CLIP    │ │ FEEDBACK │ │ INTELLI-  │ │
   │   LAYER     │  │   LAYER     │ │ LAYER      │ │  LAYER    │ │  LAYER   │ │ GENCE     │ │
   │             │  │             │ │            │ │           │ │          │ │ LAYER     │ │
   │ Stream Cap  │  │ Video Under │ │ AI Orch    │ │ Clip Gen  │ │ RLCF     │ │ Viral     │ │
   │ Audio Cap   │  │ VLM Agent   │ │ Model Route│ │ Subtitle  │ │ Creator  │ │ Predict   │ │
   │ Chat Source │  │ Audio Agent │ │ LLM Decisn │ │ Edit      │ │ Feedback │ │ Trend Det │ │
   │ Meta Poll   │  │ Chat Agent  │ │ Context Eng│ │ Thumbnail │ │ Reward   │ │ Content   │ │
   │             │  │ Multimodal  │ │ Retrieval  │ │ Upload    │ │ Model    │ │ Score     │ │
   └──────┬──────┘  └──────┬──────┘ └─────┬──────┘ └─────┬─────┘ └────┬─────┘ └─────┬────┘ │
          │                │              │              │            │             │       │
          │         ┌──────▼──────────────▼──────────────▼────────────▼─────────────▼────┐ │
          │         │                    GPU INFRASTRUCTURE                                │ │
          │         │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │ │
          │         │  │ Triton   │  │ TensorRT │  │ ONNX RT  │  │ GPU Scheduler    │   │ │
          │         │  │ Inference│  │ Optimizer│  │ Runtime  │  │ (K8s GPU Plugin) │   │ │
          │         │  │ Server   │  │          │  │          │  │                  │   │ │
          │         │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │ │
          │         └────────────────────────────────────────────────────────────────────┘ │
          │                                                                              │
   ┌──────▼──────────────────────────────────────────────────────────────────────────────────▼──┐
   │                        DATA INFRASTRUCTURE                                                   │
   │  ┌────────────┐  ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
   │  │ PostgreSQL │  │  ClickHouse  │  │ Qdrant   │  │  Redis   │  │   Event Store        │  │
   │  │  (OLTP)    │  │   (OLAP/TS)  │  │ (Vector) │  │ (Cache)  │  │ (Kafka + Schema      │  │
   │  │            │  │              │  │          │  │          │  │  Registry)           │  │
   │  │ Users      │  │ Metrics TS   │  │ Embeddings│ │ Hot data │  │ Event Replay         │  │
   │  │ Clips      │  │ Analytics    │  │ Semantic │  │ Sessions │  │ CQRS Read Models     │  │
   │  │ Streams    │  │ Aggregations │  │ Search   │  │ Streams  │  │                      │  │
   │  └────────────┘  └──────────────┘  └──────────┘  └──────────┘  └──────────────────────┘  │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Technology Stack — Complete

| Layer | Technology | Why |
|---|---|---|
| **Event Bus** | Apache Kafka 3.6+ | Persistent, replayable, partitioned, ordered, schema registry |
| **Fast Queue** | Redis Streams | Sub-ms latency pub/sub, consumer groups, hot cache |
| **OLTP Database** | PostgreSQL 16 | ACID, JSONB, logical replication, mature ecosystem |
| **OLAP / Time Series** | ClickHouse | Columnar, 100M+ rows/sec scan, real-time aggregations |
| **Vector Database** | Qdrant | High-recall ANN search, payload filtering, gRPC API |
| **Event Store** | Kafka + Schema Registry | Immutable event log, replay, CQRS projection |
| **Cache** | Redis 7 | Sessions, hot data, distributed locks, rate limiting |
| **Graph Database** | Neo4j (optional) / ArangoDB | Knowledge graph relationships |
| **API Gateway** | Kong / Traefik | Auth, rate limiting, WAF, request routing |
| **Service Framework** | FastAPI (Python 3.12) | Async native, Pydantic v2, OpenAPI |
| **ML Framework** | PyTorch 2.x + ONNX + TensorRT | Training + optimized inference |
| **Inference Server** | NVIDIA Triton | Multi-model serving, dynamic batching, GPU sharing |
| **Model Optimization** | TensorRT 8.6+ / ONNX Runtime | FP16/INT8 quantization, kernel fusion |
| **Workflow Orchestration** | Temporal | Durable execution, saga pattern, retry, compensation |
| **Container Orchestration** | Kubernetes 1.29+ | Auto-scaling, GPU scheduling, rolling updates |
| **GitOps** | ArgoCD | Declarative deployments, drift detection, rollbacks |
| **CI/CD** | GitHub Actions | Build, test, scan, sign, deploy pipeline |
| **Observability** | OpenTelemetry + Prometheus + Grafana + Loki | Traces, metrics, logs correlation |
| **Distributed Tracing** | Jaeger / Tempo | Request tracing across services |
| **Feature Flags** | LaunchDarkly / Unleash | Progressive delivery, instant rollback |
| **Secrets** | HashiCorp Vault | Dynamic secrets, rotation, audit |
| **Feature Store** | Feast / custom | Online/offline feature consistency |
| **Message Serialization** | Avro / Protobuf | Schema evolution, compact binary |
| **Object Storage** | S3 / MinIO | Clips, thumbnails, model artifacts |
| **CDN** | CloudFront / Cloudflare | Content delivery, edge caching |

---

## Service Registry

| # | Service | Layer | Responsibility | Tech |
|---|---|---|---|---|
| 1 | Stream Capture | Stream | HLS/RTMP ingest, frame extraction | FFmpeg, OpenCV |
| 2 | Audio Capture | Stream | Audio chunk extraction, resampling | FFmpeg, librosa |
| 3 | Chat Source | Stream | Platform chat WebSocket polling | websockets, Kick API |
| 4 | Metadata Poller | Stream | Viewer count, stream status polling | httpx |
| 5 | Video Understanding | Analysis | Scene detection, shot boundary, action recognition | PyTorch, TIMM |
| 6 | VLM Agent | Analysis | Vision-Language Model for scene description | LLaVA, Qwen-VL |
| 7 | Audio Analysis Agent | Analysis | SER, VAD, speaker diarization, audio features | Whisper, pyannote |
| 8 | Chat Analysis Agent | Analysis | Sentiment, toxicity, spike detection, donation | Transformers |
| 9 | Multimodal Fusion | Analysis | Cross-modal alignment, late/early fusion | PyTorch |
| 10 | AI Orchestrator | Decision | Multi-agent coordination, task dispatch | Custom + Temporal |
| 11 | Model Router | Decision | Route requests to optimal model/endpoint | Custom |
| 12 | LLM Decision Layer | Decision | Natural language reasoning for clip decisions | GPT-4o, Claude, Llama |
| 13 | Context Engine | Decision | Build context windows, manage memory | Custom + Qdrant |
| 14 | Retrieval Engine | Decision | Semantic search, RAG over past clips | Qdrant, sentence-transformers |
| 15 | Knowledge Graph | Decision | Entity relationships, streamer profiles | Neo4j |
| 16 | Event Detector | Decision | Multi-signal aggregation, composite scoring | Custom |
| 17 | Clip Generator | Clip | FFmpeg clip extraction, trimming | FFmpeg |
| 18 | Subtitle Service | Clip | Whisper transcription → SRT/ASS burn-in | Whisper, libass |
| 19 | Video Editor | Clip | Multi-platform export, effects, transitions | FFmpeg, MoviePy |
| 20 | Thumbnail Engine | Clip | AI-powered thumbnail generation | CLIP, OpenCV |
| 21 | Uploader | Clip | YouTube/TikTok/Instagram/Kick publish | Platform APIs |
| 22 | AI Metadata Generator | Clip | Title, description, tags, hashtags | LLM |
| 23 | Viral Prediction Engine | Intelligence | Predict clip virality before publish | XGBoost, LSTM |
| 24 | Content Scoring Engine | Intelligence | Multi-dimensional content quality scoring | Custom ML |
| 25 | Trend Detection | Intelligence | Detect trending topics, formats, keywords | NLP, time series |
| 26 | RLCF Service | Intelligence | Learn from creator feedback, reward model | RLHF techniques |
| 27 | Feature Store | Intelligence | Online/offline feature serving | Feast |
| 28 | Embedding Pipeline | Intelligence | Generate and index embeddings | sentence-transformers, CLIP |
| 29 | Semantic Timeline | Intelligence | Build semantic timeline of stream | Custom + Qdrant |
| 30 | Long Context Memory | Intelligence | Episodic + semantic memory management | Custom + Qdrant |

---

## Data Topology — Polyglot Persistence

```
                    ┌─────────────────────────────────────────────────────┐
                    │                WRITE PATH                            │
                    │                                                      │
                    │  Event → Kafka → ┌─→ PostgreSQL (current state)      │
                    │                  ├─→ ClickHouse (metrics/aggregates) │
                    │                  ├─→ Qdrant (embeddings)             │
                    │                  ├─→ Redis (hot cache update)        │
                    │                  └─→ Event Store (immutable log)     │
                    └─────────────────────────────────────────────────────┘

                    ┌─────────────────────────────────────────────────────┐
                    │                READ PATH                             │
                    │                                                      │
                    │  Query Type              →  Database                  │
                    │  ──────────────────────────────────────────────      │
                    │  User profile, clip meta  →  PostgreSQL               │
                    │  "How many clips today?"  →  ClickHouse               │
                    │  "Similar past clips?"     →  Qdrant                  │
                    │  "Current stream score?"   →  Redis                   │
                    │  "Replay stream events?"   →  Event Store (Kafka)     │
                    │  "Who is this streamer?"   →  Knowledge Graph (Neo4j)│
                    └─────────────────────────────────────────────────────┘
```

### Database Responsibility Matrix

| Database | Stores | Query Pattern | Retention | Scale |
|---|---|---|---|---|
| PostgreSQL | Users, streams, clips, preferences, API keys | CRUD, joins, transactions | Forever | TB |
| ClickHouse | Time-series metrics, analytics, aggregations | Columnar scans, GROUP BY | 90 days hot, 1yr cold | 10s of TB |
| Qdrant | Embeddings (video, audio, text, multimodal) | ANN search, payload filter | Forever (grows) | 100M+ vectors |
| Redis | Sessions, hot clips, stream state, rate limits | Sub-ms key-value | Eviction (hours) | GB |
| Kafka | All events (immutable log) | Replay, partitioned consume | 7-30 days | 10s of TB |
| Neo4j | Knowledge graph (entities, relationships) | Graph traversal | Forever | GB |
| S3/MinIO | Video files, thumbnails, model artifacts | Object storage | Lifecycle policy | 100s of TB |

---

## Platform-Wide Event Schema (Avro)

```json
{
  "type": "record",
  "name": "PlatformEvent",
  "namespace": "com.intelligence.platform",
  "fields": [
    {"name": "event_id", "type": "string", "doc": "UUID v7 — time-sortable"},
    {"name": "event_type", "type": "string", "doc": "Dot-separated: stream.started, analysis.vlm.complete"},
    {"name": "timestamp", "type": "long", "doc": "Epoch milliseconds UTC"},
    {"name": "source_service", "type": "string"},
    {"name": "stream_id", "type": ["null", "string"], "default": null},
    {"name": "correlation_id", "type": "string", "doc": "For distributed tracing"},
    {"name": "causation_id", ["null", "string"], "default": null, "doc": "Parent event ID"},
    {"name": "version", "type": "int", "doc": "Schema version"},
    {"name": "payload", "type": "bytes", "doc": "Avro-encoded payload, schema from registry"},
    {"name": "metadata", "type": {
      "type": "record", "name": "EventMetadata",
      "fields": [
        {"name": "retry_count", "type": "int", "default": 0},
        {"name": "priority", "type": "int", "default": 5},
        {"name": "ttl_ms", "type": ["null", "long"], "default": null},
        {"name": "trace_flags", "type": "int", "default": 0}
      ]
    }}
  ]
}
```

---

## Folder Structure — Target

```
intelligence-platform/
├── api/                         # API Gateway + REST/gRPC endpoints
│   ├── gateway/                 # Kong config, plugins, routes
│   ├── rest/                    # FastAPI routers
│   ├── grpc/                    # gRPC service definitions
│   └── websocket/               # Real-time WS endpoints
│
├── agents/                      # Multi-Agent system
│   ├── orchestrator/            # AI Orchestrator (agent coordinator)
│   ├── video_agent/             # Video understanding agent
│   ├── audio_agent/             # Audio analysis agent
│   ├── chat_agent/              # Chat analysis agent
│   ├── vlm_agent/               # Vision-Language Model agent
│   ├── multimodal_agent/        # Multimodal fusion agent
│   ├── decision_agent/          # LLM decision agent
│   ├── context_agent/           # Context engine agent
│   ├── retrieval_agent/         # Retrieval/RAG agent
│   └── shared/                  # Agent base classes, protocols
│
├── services/                    # Microservices
│   ├── stream_capture/
│   ├── audio_capture/
│   ├── chat_source/
│   ├── metadata_poller/
│   ├── event_detector/
│   ├── clip_generator/
│   ├── subtitle/
│   ├── video_editor/
│   ├── thumbnail/
│   ├── uploader/
│   ├── ai_metadata/
│   └── notification/
│
├── intelligence/                # Intelligence engines
│   ├── viral_prediction/
│   ├── content_scoring/
│   ├── trend_detection/
│   ├── rlcf/                    # Reinforcement Learning from Creator Feedback
│   ├── feature_store/
│   ├── embedding_pipeline/
│   ├── semantic_timeline/
│   └── long_context_memory/
│
├── inference/                   # GPU inference infrastructure
│   ├── triton/                  # Triton model repository + configs
│   ├── tensorrt/                # TensorRT engine builder
│   ├── onnx/                    # ONNX model zoo
│   ├── gpu_scheduler/           # GPU scheduling logic
│   └── model_router/            # Model routing service
│
├── data/                        # Data infrastructure
│   ├── migrations/              # Alembic (PostgreSQL)
│   ├── clickhouse/              # ClickHouse DDL + materialized views
│   ├── qdrant/                  # Qdrant collections + indexes
│   ├── neo4j/                   # Neo4j Cypher schemas
│   ├── kafka/                   # Kafka topic configs + schemas
│   └── redis/                   # Redis scripts + configs
│
├── shared/                      # Shared libraries
│   ├── event_bus/               # Event bus abstraction (Kafka + Redis)
│   ├── event_schemas/           # Avro/Protobuf schemas
│   ├── models/                  # Domain models (Pydantic)
│   ├── utils/                   # Common utilities
│   └── telemetry/               # OpenTelemetry instrumentation
│
├── platform/                    # Platform engineering
│   ├── observability/           # OTel, Prometheus, Grafana configs
│   ├── feature_flags/           # Feature flag definitions
│   ├── auth/                    # OAuth2, JWT, API key management
│   └── chaos/                   # Chaos engineering experiments
│
├── deploy/                      # Deployment
│   ├── k8s/                     # Kubernetes manifests (Helm)
│   ├── argocd/                  # GitOps application definitions
│   ├── terraform/               # Infrastructure as Code
│   └── docker/                  # Dockerfiles
│
├── .github/workflows/           # CI/CD pipelines
└── tests/                       # Test suites
    ├── unit/
    ├── integration/
    ├── contract/
    ├── chaos/
    ├── load/
    └── e2e/
```

---

## SLO Targets

| Metric | Target | Window |
|---|---|---|
| Frame analysis latency (p99) | < 500ms | Rolling 5 min |
| Clip generation time (p95) | < 30s | Rolling 1 hr |
| Event bus end-to-end latency (p99) | < 100ms | Rolling 5 min |
| API availability | 99.9% | Monthly |
| Inference uptime | 99.95% | Monthly |
| Event delivery guarantee | At-least-once + idempotency | Always |
| Kafka consumer lag (p99) | < 1000 messages | Rolling 5 min |
| GPU utilization (avg) | > 70% | Daily |
| ClickHouse query latency (p95) | < 200ms | Rolling 1 hr |
| Qdrant search latency (p99) | < 50ms | Rolling 5 min |

---

## What Each Part Document Contains

Every service documented in Parts 1–6 includes:

1. **Klasör Yapısı** — Complete folder/file layout
2. **Veri Akışı** — Data flow diagrams with ASCII art
3. **Sequence Diyagramları** — Mermaid sequence diagrams for key flows
4. **Event Şemaları** — Avro/Protobuf schemas for all events
5. **Database Tabloları** — SQL DDL for PostgreSQL, ClickHouse, Qdrant collections
6. **API Tasarımı** — REST/gRPC endpoint definitions with examples
7. **Production Senaryoları** — Failure modes, recovery, scaling events
8. **Ölçeklenebilirlik Stratejileri** — Horizontal/vertical scaling, sharding, partitioning

---

*Continue to `IP_PART1_ARCHITECTURE.md` for Architecture & Multi-Agent System.*
