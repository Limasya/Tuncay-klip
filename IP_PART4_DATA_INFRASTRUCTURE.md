# INTELLIGENCE PLATFORM — PART 4
# Data Infrastructure

**Topics:** Event Store · Time Series Database · Kafka Topics Design · Redis Streams · PostgreSQL + ClickHouse + Qdrant

---

# 23. EVENT STORE

## 23.1 What is an Event Store?

Event Store, sistemdeki **tüm olayların değiştirilemez kaydıdır** (immutable log). Her state değişikliği, bir event olarak buraya yazılır ve asla silinmez veya değiştirilmez.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    EVENT STORE ARCHITECTURE                          │
│                                                                      │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐             │
│  │  Producers  │──→ │   Kafka     │──→ │  Consumers  │             │
│  │  (services) │    │  (log)      │    │  (services) │             │
│  └─────────────┘    └──────┬──────┘    └─────────────┘             │
│                            │                                         │
│                    ┌───────▼──────────────┐                         │
│                    │  SCHEMA REGISTRY     │                         │
│                    │  (Avro schemas)      │                         │
│                    └───────┬──────────────┘                         │
│                            │                                         │
│              ┌─────────────┼─────────────┐                          │
│              │             │             │                           │
│       ┌──────▼──────┐ ┌───▼──────┐ ┌───▼──────────┐                │
│       │ PostgreSQL  │ │ClickHouse│ │ Qdrant       │                │
│       │ (CQRS read  │ │(analytics│ │ (embeddings) │                │
│       │  model)     │ │  & TS)   │ │              │                │
│       └─────────────┘ └──────────┘ └──────────────┘                │
│                                                                      │
│  Properties:                                                         │
│  - APPEND-ONLY: events never modified or deleted                    │
│  - IMMUTABLE: historical record, audit trail                        │
│  - REPLAYABLE: can replay events to rebuild state                   │
│  - ORDERED: per-partition ordering guarantee                        │
│  - RETENTION: 7-30 days in Kafka, forever in projections            │
└──────────────────────────────────────────────────────────────────────┘
```

## 23.2 CQRS Pattern Implementation

```python
# data/event_store/cqrs_projection.py

import asyncio
import json
import logging
from typing import Callable, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Projection:
    """A CQRS read model projection."""
    name: str
    event_types: list[str]       # Which event types this projection handles
    handler: Callable             # Async function: (event) -> None
    last_processed_offset: int = 0


class EventStoreProjectionManager:
    """
    Manages CQRS projections from the event store.

    Flow:
    1. Events are written to Kafka (immutable log)
    2. Projection manager consumes events from Kafka
    3. Each projection updates its read model (PostgreSQL/ClickHouse/Qdrant)
    4. Read models are optimized for specific query patterns

    Projections:
    - clip_projection: maintains current state of all clips (PostgreSQL)
    - stream_projection: maintains stream metadata and status (PostgreSQL)
    - metrics_projection: maintains time-series metrics (ClickHouse)
    - embedding_projection: maintains vector embeddings (Qdrant)
    - timeline_projection: maintains semantic timeline (PostgreSQL + Qdrant)

    Idempotency:
    - Each projection tracks last processed offset
    - On restart, resumes from last offset (at-least-once delivery)
    - Handlers must be idempotent (safe to reprocess)
    - Use event_id for deduplication

    Consistency:
    - Eventually consistent (not immediate)
    - Projection lag: typically < 1 second
    - Monitored via Prometheus (projection_lag_seconds metric)
    """

    def __init__(self, kafka_consumer, postgres_pool, clickhouse_client, qdrant_client):
        self.kafka = kafka_consumer
        self.postgres = postgres_pool
        self.clickhouse = clickhouse_client
        self.qdrant = qdrant_client

        self._projections: dict[str, Projection] = {}
        self._running = False

    def register_projection(self, projection: Projection):
        """Register a CQRS projection."""
        self._projections[projection.name] = projection
        logger.info(f"Registered projection: {projection.name}")

    async def run(self):
        """Main projection loop — consume events and update read models."""
        self._running = True

        # Subscribe to all event topics
        topics = set()
        for proj in self._projections.values():
            for event_type in proj.event_types:
                topic = event_type.split(".")[0]  # "clip.created" → "clip"
                topics.add(f"{topic}.events")

        await self.kafka.subscribe(list(topics))

        while self._running:
            try:
                # Poll for events
                batch = await self.kafka.poll_batch(timeout_ms=1000, max_records=100)

                for record in batch:
                    event = json.loads(record.value)
                    event_type = event.get("event_type", "")

                    # Find matching projections
                    for proj in self._projections.values():
                        if self._matches(event_type, proj.event_types):
                            try:
                                await proj.handler(event)
                                proj.last_processed_offset = record.offset
                            except Exception as e:
                                logger.error(
                                    f"Projection {proj.name} failed for "
                                    f"{event_type}: {e}", exc_info=True
                                )

            except Exception as e:
                logger.error(f"Projection loop error: {e}", exc_info=True)
                await asyncio.sleep(1)

    def _matches(self, event_type: str, patterns: list[str]) -> bool:
        """Check if event type matches any pattern (supports wildcards)."""
        for pattern in patterns:
            if pattern == "*" or pattern == event_type:
                return True
            if pattern.endswith(".*"):
                prefix = pattern[:-2]
                if event_type.startswith(prefix + "."):
                    return True
        return False


# --- Projection Handlers ---

async def clip_projection_handler(event: dict, postgres_pool):
    """Handle clip-related events → update clip read model."""
    event_type = event["event_type"]
    payload = event["payload"]

    if event_type == "clip.created":
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO clips_read_model
                   (clip_id, stream_id, file_path, duration_s, created_at,
                    status, composite_score, clip_type)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                   ON CONFLICT (clip_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    composite_score = EXCLUDED.composite_score""",
                payload["clip_id"], payload["stream_id"],
                payload["file_path"], payload["duration_s"],
                payload["timestamp_ms"], "created",
                payload.get("composite_score", 0),
                payload.get("clip_type", "unknown"),
            )

    elif event_type == "clip.published":
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """UPDATE clips_read_model
                   SET status = 'published', 
                       platform = $2, platform_url = $3,
                       published_at = $4
                   WHERE clip_id = $1""",
                payload["clip_id"], payload.get("platform"),
                payload.get("url"), payload["timestamp_ms"],
            )

    elif event_type == "clip.rejected":
        async with postgres_pool.acquire() as conn:
            await conn.execute(
                """UPDATE clips_read_model
                   SET status = 'rejected', rejection_reason = $2
                   WHERE clip_id = $1""",
                payload["clip_id"], payload.get("reason"),
            )
```

## 23.3 Event Store Database Schema

```sql
-- Event Store: append-only event log (Kafka is primary, this is CQRS read model)
CREATE TABLE event_log (
    event_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type         VARCHAR(100) NOT NULL,
    stream_id          VARCHAR(100),
    timestamp_ms       BIGINT NOT NULL,
    source_service     VARCHAR(50) NOT NULL,
    correlation_id     UUID NOT NULL,
    causation_id       UUID,
    payload            JSONB NOT NULL,
    schema_version     INT DEFAULT 1,
    kafka_topic        VARCHAR(100),
    kafka_partition    INT,
    kafka_offset       BIGINT,
    processed_at       TIMESTAMPTZ DEFAULT now(),
    
    INDEX idx_type_ts (event_type, timestamp_ms DESC),
    INDEX idx_stream_ts (stream_id, timestamp_ms DESC),
    INDEX idx_correlation (correlation_id),
    INDEX idx_payload_gin (payload JSONB_PATH_OPS)
) PARTITION BY RANGE (timestamp_ms);

-- Monthly partitions
CREATE TABLE event_log_2026_07 PARTITION OF event_log
    FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
CREATE TABLE event_log_2026_08 PARTITION OF event_log
    FOR VALUES FROM ('2026-08-01') TO ('2026-09-01');

-- Clips read model (CQRS projection)
CREATE TABLE clips_read_model (
    clip_id            VARCHAR(100) PRIMARY KEY,
    stream_id          VARCHAR(100) NOT NULL,
    streamer_id        VARCHAR(100),
    file_path          TEXT,
    duration_s         INT,
    composite_score    FLOAT DEFAULT 0,
    clip_type          VARCHAR(50) DEFAULT 'unknown',
    status             VARCHAR(20) DEFAULT 'created',
    platform           VARCHAR(50),
    platform_url       TEXT,
    rejection_reason   TEXT,
    viral_score        FLOAT,
    content_score      FLOAT,
    view_count         INT DEFAULT 0,
    like_count         INT DEFAULT 0,
    created_at         BIGINT NOT NULL,
    published_at       BIGINT,
    updated_at         TIMESTAMPTZ DEFAULT now(),
    
    INDEX idx_stream_status (stream_id, status),
    INDEX idx_streamer_status (streamer_id, status),
    INDEX idx_created (created_at DESC),
    INDEX idx_viral (viral_score DESC)
);
```

## 23.4 Event Replay

```python
# data/event_store/replay_service.py

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EventReplayService:
    """
    Replays events from the Event Store to rebuild state or reprocess.

    Use Cases:
    1. BUG FIX: Found a bug in event handler → fix code → replay affected events
    2. NEW PROJECTION: Added a new read model → replay all historical events
    3. DATA MIGRATION: Changed schema → replay events with new projection logic
    4. DISASTER RECOVERY: Lost a database → replay events to rebuild state

    Replay Process:
    1. Specify: stream_id, time range, event types, target projection
    2. Seek Kafka consumer to start offset (based on timestamp)
    3. Read events sequentially
    4. For each event: call projection handler (idempotent)
    5. Track progress (events replayed, errors, ETA)
    6. On completion: verify state consistency

    Safety:
    - Replay is IDEMPOTENT (safe to replay same event multiple times)
    - Replay does NOT produce new events (read-only)
    - Replay can be paused/resumed
    - Rate limited to avoid overwhelming databases
    """

    def __init__(self, kafka_admin, projection_manager):
        self.kafka_admin = kafka_admin
        self.projection_manager = projection_manager

    async def replay(
        self,
        stream_id: str,
        start_timestamp_ms: int,
        end_timestamp_ms: int,
        event_types: Optional[list[str]] = None,
        target_projection: Optional[str] = None,
        rate_limit_per_sec: int = 100,
    ):
        """Replay events for a specific stream and time range."""
        logger.info(
            f"Starting replay: stream={stream_id}, "
            f"range={start_timestamp_ms}-{end_timestamp_ms}, "
            f"types={event_types}, projection={target_projection}"
        )

        # Find Kafka offsets for time range
        topics = self._get_topics_for_event_types(event_types)
        partitions = await self.kafka_admin.get_partitions(topics)

        # Seek to start timestamp
        consumer = await self.kafka_admin.create_consumer(
            group_id=f"replay_{stream_id}_{start_timestamp_ms}"
        )

        for topic, partition_list in partitions.items():
            for partition in partition_list:
                offset = await self.kafka_admin.find_offset_by_timestamp(
                    topic, partition, start_timestamp_ms
                )
                await consumer.seek(topic, partition, offset)

        # Replay loop
        replayed = 0
        errors = 0
        rate_limiter = asyncio.Semaphore(rate_limit_per_sec)

        async for record in consumer:
            event_timestamp = record.timestamp

            # Check end condition
            if event_timestamp > end_timestamp_ms:
                break

            event = record.value
            event_type = event.get("event_type", "")

            # Filter by event types
            if event_types and event_type not in event_types:
                continue

            # Filter by stream
            if event.get("stream_id") != stream_id:
                continue

            # Process event
            async with rate_limiter:
                try:
                    if target_projection:
                        proj = self.projection_manager._projections.get(target_projection)
                        if proj and self.projection_manager._matches(event_type, proj.event_types):
                            await proj.handler(event)
                    else:
                        # Replay to all matching projections
                        for proj in self.projection_manager._projections.values():
                            if self.projection_manager._matches(event_type, proj.event_types):
                                await proj.handler(event)

                    replayed += 1
                    if replayed % 100 == 0:
                        logger.info(f"Replay progress: {replayed} events, {errors} errors")

                except Exception as e:
                    errors += 1
                    logger.error(f"Replay error for {event_type}: {e}")

        logger.info(f"Replay complete: {replayed} events replayed, {errors} errors")
        return {"replayed": replayed, "errors": errors}

    def _get_topics_for_event_types(self, event_types: Optional[list[str]]) -> list[str]:
        """Map event types to Kafka topics."""
        if not event_types:
            return ["stream.events", "analysis.events", "decision.events",
                    "clip.events", "intelligence.events"]
        # Map event type prefixes to topics
        topic_map = {
            "stream": "stream.events",
            "analysis": "analysis.events",
            "decision": "decision.events",
            "clip": "clip.events",
            "intelligence": "intelligence.events",
        }
        topics = set()
        for et in event_types:
            prefix = et.split(".")[0]
            if prefix in topic_map:
                topics.add(topic_map[prefix])
        return list(topics) if topics else ["stream.events"]
```

---

# 24. TIME SERIES DATABASE (ClickHouse)

## 24.1 Why ClickHouse?

ClickHouse, **saniyede yüz milyonlarca satır** tarayabilen columnar OLAP veritabanıdır. Zaman serisi verisi için idealdir.

```
POSTGRESQL vs CLICKHOUSE for Time Series:
                                          
  PostgreSQL (OLTP):                       ClickHouse (OLAP):
  ─────────────────                        ──────────────────
  Row-based storage                        Columnar storage
  Good for: CRUD, transactions             Good for: Aggregations, scans
  Insert: 50K rows/sec                     Insert: 1M+ rows/sec
  Query "avg score last 5 min":            Query "avg score last 5 min":
    → Index lookup, read rows                → Column scan, vectorized
    → ~50ms for 1M rows                      → ~5ms for 100M rows
  Storage: 100GB for 100M rows             Storage: 10GB for 100M rows
    (10x compression vs PG)                  (10x better compression)

  WHEN TO USE EACH:
  PostgreSQL: User data, clip metadata, preferences (CRUD, joins)
  ClickHouse: Metrics, analytics, time series, aggregations (scans, GROUP BY)
```

## 24.2 ClickHouse Schema Design

```sql
-- ============================================================
-- CLICKHOUSE SCHEMA — INTELLIGENCE PLATFORM
-- ============================================================

-- 1. Real-time stream metrics (high frequency, 5s granularity)
CREATE TABLE stream_metrics (
    stream_id        String,
    timestamp_ms     UInt64,
    metric_name      LowCardinality(String),
    metric_value     Float64,
    signal_source    LowCardinality(String),  -- 'fast_path', 'deep_path'
    
    -- Materialized for fast aggregation
    PROJECTION proj_hourly_agg (
        SELECT stream_id, metric_name,
               toStartOfHour(fromUnixTimestamp64Milli(timestamp_ms)) as hour,
               avg(metric_value), max(metric_value), count()
        GROUP BY stream_id, metric_name, hour
    )
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(fromUnixTimestamp64Milli(timestamp_ms))
ORDER BY (stream_id, timestamp_ms, metric_name)
TTL toDateTime(timestamp_ms / 1000) + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

-- 2. Inference performance metrics
CREATE TABLE inference_metrics (
    endpoint_id      String,
    model_name       LowCardinality(String),
    timestamp_ms     UInt64,
    latency_ms       Float64,
    batch_size       UInt32,
    gpu_utilization  Float64,
    gpu_memory_used  Float64,
    status           LowCardinality(String),  -- 'success', 'failed', 'timeout'
    
    INDEX idx_model_ts (model_name, timestamp_ms)
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(fromUnixTimestamp64Milli(timestamp_ms))
ORDER BY (endpoint_id, timestamp_ms)
TTL toDateTime(timestamp_ms / 1000) + INTERVAL 30 DAY;

-- 3. Agent performance metrics
CREATE TABLE agent_metrics (
    agent_name       LowCardinality(String),
    timestamp_ms     UInt64,
    messages_received UInt64,
    messages_processed UInt64,
    messages_failed  UInt64,
    avg_processing_ms Float64,
    state            LowCardinality(String),
    
    INDEX idx_agent_ts (agent_name, timestamp_ms)
) ENGINE = MergeTree
PARTITION BY toYYYYMMDD(fromUnixTimestamp64Milli(timestamp_ms))
ORDER BY (agent_name, timestamp_ms)
TTL toDateTime(timestamp_ms / 1000) + INTERVAL 30 DAY;

-- 4. Clip performance tracking (post-publish analytics)
CREATE TABLE clip_performance (
    clip_id          String,
    streamer_id      String,
    platform         LowCardinality(String),
    timestamp_ms     UInt64,
    views            UInt64,
    likes            UInt64,
    comments         UInt64,
    shares           UInt64,
    watch_time_sec   Float64,
    engagement_rate  Float64,  -- (likes + comments + shares) / views
    
    INDEX idx_streamer_ts (streamer_id, timestamp_ms),
    INDEX idx_clip (clip_id)
) ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMM(fromUnixTimestamp64Milli(timestamp_ms))
ORDER BY (clip_id, timestamp_ms)
TTL toDateTime(timestamp_ms / 1000) + INTERVAL 365 DAY;

-- 5. Materialized view: 1-minute stream metric aggregations
CREATE MATERIALIZED VIEW stream_metrics_1min
ENGINE = SummingMergeTree
PARTITION BY toYYYYMMDD(fromUnixTimestamp64Milli(window_start))
ORDER BY (stream_id, window_start, metric_name)
AS SELECT
    stream_id,
    toStartOfMinute(fromUnixTimestamp64Milli(timestamp_ms)) AS window_start,
    metric_name,
    count() AS sample_count,
    sum(metric_value) AS sum_value,
    max(metric_value) AS max_value,
    min(metric_value) AS min_value,
    avg(metric_value) AS avg_value
FROM stream_metrics
GROUP BY stream_id, window_start, metric_name;

-- 6. Materialized view: Hourly clip performance
CREATE MATERIALIZED VIEW clip_performance_hourly
ENGINE = ReplacingMergeTree
PARTITION BY toYYYYMMDD(fromUnixTimestamp64Milli(hour_ts))
ORDER BY (streamer_id, hour_ts, platform)
AS SELECT
    streamer_id,
    platform,
    toStartOfHour(fromUnixTimestamp64Milli(timestamp_ms)) AS hour_ts,
    count(DISTINCT clip_id) AS clip_count,
    sum(views) AS total_views,
    avg(engagement_rate) AS avg_engagement,
    max(views) AS max_clip_views
FROM clip_performance
GROUP BY streamer_id, platform, hour_ts;

-- ============================================================
-- COMMON QUERIES
-- ============================================================

-- "What was the energy level trend for stream X in last 30 minutes?"
SELECT
    window_start,
    avg_value AS energy_level,
    max_value AS peak_energy
FROM stream_metrics_1min
WHERE stream_id = 'stream_123'
  AND metric_name = 'energy_level'
  AND window_start > now() - INTERVAL 30 MINUTE
ORDER BY window_start;

-- "What's the average inference latency per model in last hour?"
SELECT
    model_name,
    avg(latency_ms) AS avg_latency,
    max(latency_ms) AS p99_latency,
    countIf(status = 'success') * 100.0 / count() AS success_rate
FROM inference_metrics
WHERE timestamp_ms > toUnixTimestamp(now() - INTERVAL 1 HOUR) * 1000
GROUP BY model_name
ORDER BY avg_latency;

-- "Which streamer had the best clip performance this week?"
SELECT
    streamer_id,
    sum(total_views) AS weekly_views,
    avg(avg_engagement) AS avg_engagement,
    max(max_clip_views) AS best_clip_views
FROM clip_performance_hourly
WHERE hour_ts > toStartOfWeek(now())
GROUP BY streamer_id
ORDER BY weekly_views DESC
LIMIT 10;
```

## 24.3 ClickHouse Production Configuration

```yaml
# deploy/clickhouse/config.yaml
logger:
  level: information
  log: /var/log/clickhouse-server/clickhouse-server.log

# Memory limits (adjust per server)
max_memory_usage: 10000000000  # 10GB per query
max_memory_usage_for_user: 20000000000  # 20GB per user
max_server_memory_usage_to_ram_ratio: 0.8

# Merge settings
background_pool_size: 16
merge_tree:
  max_suspicious_broken_parts: 5
  parts_to_delay_insert: 150
  parts_to_throw_insert: 300

# Compression
compression:
  - case:
      min_part_size: 10000000000  # 10GB
      min_part_size_ratio: 0.01
    method: zstd
    level: 3

# Distributed table settings (for cluster)
distributed_ddl:
  path: '/clickhouse/task_queue/ddl'

# TLS (production)
openSSL:
  server:
    certificateFile: /etc/clickhouse-server/ssl/server.crt
    privateKeyFile: /etc/clickhouse-server/ssl/server.key

# Users
users:
  readonly:
    profile: readonly
    networks:
      ip: "::/0"  # All IPs (restrict in production)
  analyst:
    profile: analyst
    password_hash: "..."  # bcrypt hash
```

---

# 25. KAFKA TOPICS DESIGN

## 25.1 Complete Topic Catalog

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        KAFKA TOPIC CATALOG                                  │
│                                                                             │
│  TIER 1: INGESTION (high throughput, 7-day retention)                      │
│  ┌────────────────────────────┬──────────┬─────────┬─────────────────────┐ │
│  │ Topic                      │ Partitions│ RF │ Description            │ │
│  ├────────────────────────────┼──────────┼─────┼─────────────────────┤ │
│  │ stream.raw.frames          │    12    │  3  │ Raw video frames (2fps)│ │
│  │ stream.raw.audio           │     6    │  3  │ Audio chunks (1s)     │ │
│  │ stream.raw.chat            │     6    │  3  │ Raw chat messages      │ │
│  │ stream.raw.metadata        │     3    │  3  │ Viewer count, status   │ │
│  └────────────────────────────┴──────────┴─────┴─────────────────────┘ │
│                                                                             │
│  TIER 2: ANALYSIS (medium throughput, 14-day retention)                    │
│  ┌────────────────────────────┬──────────┬─────────┐                       │
│  │ analysis.video.complete    │     6    │   3     │                       │
│  │ analysis.audio.complete    │     6    │   3     │                       │
│  │ analysis.chat.complete     │     6    │   3     │                       │
│  │ analysis.vlm.complete      │     3    │   3     │                       │
│  │ analysis.multimodal.fused  │     3    │   3     │                       │
│  │ analysis.ocr.complete      │     3    │   3     │                       │
│  └────────────────────────────┴──────────┴─────────┘                       │
│                                                                             │
│  TIER 3: DECISION (low throughput, 30-day retention)                      │
│  ┌────────────────────────────┬──────────┬─────────┐                       │
│  │ decision.event.detected    │     3    │   3     │                       │
│  │ decision.clip.candidate    │     3    │   3     │                       │
│  │ decision.clip.confirmed    │     3    │   3     │                       │
│  │ decision.clip.rejected     │     3    │   3     │                       │
│  │ decision.llm.reasoning     │     3    │   3     │                       │
│  └────────────────────────────┴──────────┴─────────┘                       │
│                                                                             │
│  TIER 4: EXECUTION (low throughput, 30-day retention)                     │
│  ┌────────────────────────────┬──────────┬─────────┐                       │
│  │ clip.created               │     3    │   3     │                       │
│  │ clip.subtitle.ready        │     3    │   3     │                       │
│  │ clip.thumbnail.ready       │     3    │   3     │                       │
│  │ clip.edited                │     3    │   3     │                       │
│  │ clip.published             │     3    │   3     │                       │
│  │ clip.metadata.generated    │     3    │   3     │                       │
│  └────────────────────────────┴──────────┴─────────┘                       │
│                                                                             │
│  TIER 5: INTELLIGENCE (low throughput, 90-day retention)                  │
│  ┌────────────────────────────┬──────────┬─────────┐                       │
│  │ intelligence.viral.predicted│    3    │   3     │                       │
│  │ intelligence.trend.detected │    3    │   3     │                       │
│  │ intelligence.score.updated  │    3    │   3     │                       │
│  │ intelligence.feedback.received│  3    │   3     │                       │
│  │ intelligence.embedding.indexed│  3    │   3     │                       │
│  └────────────────────────────┴──────────┴─────────┘                       │
│                                                                             │
│  TIER 6: SYSTEM (internal, 30-day retention)                              │
│  ┌────────────────────────────┬──────────┬─────────┐                       │
│  │ system.lifecycle           │     3    │   3     │                       │
│  │ system.health              │     3    │   3     │                       │
│  │ system.scale               │     3    │   3     │                       │
│  │ system.dlq                 │     3    │   3     │ Dead letter queue     │
│  └────────────────────────────┴──────────┴─────────┘                       │
└─────────────────────────────────────────────────────────────────────────────┘

RF = Replication Factor
```

## 25.2 Topic Configuration

```python
# data/kafka/topic_manager.py

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class TopicConfig:
    """Kafka topic configuration."""
    name: str
    partitions: int
    replication_factor: int
    retention_ms: int            # Message retention
    max_message_bytes: int       # Max message size
    compression: str             # "none", "gzip", "snappy", "lz4", "zstd"
    cleanup_policy: str          # "delete", "compact", "delete,compact"
    min_insync_replicas: int     # Minimum in-sync replicas for acks=all


class KafkaTopicManager:
    """
    Manages Kafka topic lifecycle.

    Topic Naming Convention:
    <tier>.<domain>.<action>

    Examples:
    - stream.raw.frames (tier 1, stream domain, raw frames)
    - analysis.video.complete (tier 2, analysis domain, video complete)
    - decision.clip.confirmed (tier 3, decision domain, clip confirmed)
    - clip.created (tier 4, clip domain, created)
    - intelligence.viral.predicted (tier 5, intelligence domain, viral predicted)

    Partition Key Strategy:
    - All topics use stream_id as partition key
    - Ensures all events for a stream are in the same partition
    - Guarantees ordering within a stream

    Retention Strategy:
    - Tier 1 (ingestion): 7 days (high volume, transient)
    - Tier 2 (analysis): 14 days (medium volume, may need replay)
    - Tier 3 (decision): 30 days (low volume, audit trail)
    - Tier 4 (execution): 30 days (low volume, audit trail)
    - Tier 5 (intelligence): 90 days (low volume, long-term analytics)
    - Tier 6 (system): 30 days (internal, debugging)

    Compaction:
    - system.health: compact (keep latest per key)
    - All others: delete (time-based expiration)
    """

    TOPIC_CONFIGS = {
        # Tier 1: Ingestion
        "stream.raw.frames": TopicConfig(
            "stream.raw.frames", 12, 3,
            retention_ms=7 * 24 * 3600 * 1000,
            max_message_bytes=10 * 1024 * 1024,  # 10MB (frame data)
            compression="lz4",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        "stream.raw.audio": TopicConfig(
            "stream.raw.audio", 6, 3,
            retention_ms=7 * 24 * 3600 * 1000,
            max_message_bytes=2 * 1024 * 1024,
            compression="lz4",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        "stream.raw.chat": TopicConfig(
            "stream.raw.chat", 6, 3,
            retention_ms=7 * 24 * 3600 * 1000,
            max_message_bytes=64 * 1024,  # 64KB
            compression="snappy",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        # Tier 2: Analysis
        "analysis.video.complete": TopicConfig(
            "analysis.video.complete", 6, 3,
            retention_ms=14 * 24 * 3600 * 1000,
            max_message_bytes=1 * 1024 * 1024,
            compression="zstd",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        "analysis.vlm.complete": TopicConfig(
            "analysis.vlm.complete", 3, 3,
            retention_ms=14 * 24 * 3600 * 1000,
            max_message_bytes=512 * 1024,
            compression="zstd",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        # Tier 3: Decision
        "decision.clip.confirmed": TopicConfig(
            "decision.clip.confirmed", 3, 3,
            retention_ms=30 * 24 * 3600 * 1000,
            max_message_bytes=256 * 1024,
            compression="zstd",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        # Tier 5: Intelligence
        "intelligence.viral.predicted": TopicConfig(
            "intelligence.viral.predicted", 3, 3,
            retention_ms=90 * 24 * 3600 * 1000,
            max_message_bytes=256 * 1024,
            compression="zstd",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        # Tier 6: System
        "system.dlq": TopicConfig(
            "system.dlq", 3, 3,
            retention_ms=30 * 24 * 3600 * 1000,
            max_message_bytes=1 * 1024 * 1024,
            compression="zstd",
            cleanup_policy="delete",
            min_insync_replicas=2,
        ),
        "system.health": TopicConfig(
            "system.health", 3, 3,
            retention_ms=30 * 24 * 3600 * 1000,
            max_message_bytes=64 * 1024,
            compression="snappy",
            cleanup_policy="compact",  # Keep latest per key
            min_insync_replicas=2,
        ),
    }

    async def create_all_topics(self, admin_client):
        """Create all configured topics."""
        for topic_name, config in self.TOPIC_CONFIGS.items():
            await self._create_topic(admin_client, topic_name, config)

    async def _create_topic(self, admin_client, name: str, config: TopicConfig):
        """Create a single Kafka topic."""
        from kafka.admin import NewTopic

        topic = NewTopic(
            name=name,
            num_partitions=config.partitions,
            replication_factor=config.replication_factor,
            topic_configs={
                "retention.ms": str(config.retention_ms),
                "max.message.bytes": str(config.max_message_bytes),
                "compression.type": config.compression,
                "cleanup.policy": config.cleanup_policy,
                "min.insync.replicas": str(config.min_insync_replicas),
            },
        )

        try:
            await admin_client.create_topics([topic])
            logger.info(f"Created topic: {name} ({config.partitions}p, rf={config.replication_factor})")
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.debug(f"Topic {name} already exists")
            else:
                logger.error(f"Failed to create topic {name}: {e}")
                raise
```

## 25.3 Consumer Group Strategy

```
CONSUMER GROUPS:
                                          
  ┌──────────────────────────────────────────────────────────────────┐
  │ Group: video-analysis-workers                                    │
  │ Members: 3-12 (auto-scaled)                                     │
  │ Topics: stream.raw.frames                                       │
  │ Partition assignment: 4 partitions per member                   │
  │ Commit: manual (after processing)                              │
  │ Offset reset: latest (newest only)                             │
  └──────────────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────────────┐
  │ Group: audio-analysis-workers                                    │
  │ Members: 2-6 (auto-scaled)                                      │
  │ Topics: stream.raw.audio                                        │
  └──────────────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────────────┐
  │ Group: event-detector                                            │
  │ Members: 1-3                                                    │
  │ Topics: analysis.*.complete                                     │
  │ Note: Fan-in consumer (reads from multiple topics)             │
  └──────────────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────────────┐
  │ Group: clip-generator                                            │
  │ Members: 1-5                                                    │
  │ Topics: decision.clip.confirmed                                 │
  └──────────────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────────────┐
  │ Group: intelligence-engines                                      │
  │ Members: 1-3                                                    │
  │ Topics: clip.created, intelligence.feedback.received            │
  │ Runs: Viral Prediction, Trend Detection, RLCF                  │
  └──────────────────────────────────────────────────────────────────┘
  ┌──────────────────────────────────────────────────────────────────┐
  │ Group: cqrs-projections                                          │
  │ Members: 1 (singleton — ordering critical)                      │
  │ Topics: All tiers                                                │
  │ Purpose: Maintain CQRS read models                              │
  └──────────────────────────────────────────────────────────────────┘
```

---

# 26. REDIS STREAMS

## 26.1 Role in the Architecture

Redis Streams, Kafka'nın yanında **düşük latency'li, geçici** iletişim için kullanılır:

```
KAFKA vs REDIS STREAMS:
                                          
  Kafka:                                   Redis Streams:
  ──────                                   ──────────────
  Persistent (disk)                        Volatile (memory, optionally AOF)
  High throughput (100K+ msg/s)            Medium throughput (10K+ msg/s)
  Consumer groups, partitions              Consumer groups, pending lists
  Retention: days                          Retention: minutes to hours
  Latency: 5-20ms                          Latency: < 1ms
  Use: Event bus (durable, replay)         Use: Fast path, real-time signaling

WHEN TO USE REDIS STREAMS:
  ✓ Fast path signals (audio spike → trigger deep analysis NOW)
  ✓ Agent-to-agent real-time messaging (< 1ms latency)
  ✓ Session state, hot cache
  ✓ Rate limiting, distributed locks
  ✓ Pub/Sub for dashboard updates

WHEN TO USE KAFKA:
  ✓ All persistent events (audit trail)
  ✓ Event sourcing (replay capability)
  ✓ Cross-service communication
  ✓ High-volume data ingestion
  ✓ CQRS projections
```

## 26.2 Redis Streams Implementation

```python
# data/redis/streams_manager.py

import asyncio
import json
import time
from typing import Optional, Callable
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


class RedisStreamsManager:
    """
    Manages Redis Streams for fast-path communication.

    Streams:
    - fast_path:signals — Quick signals (audio spike, chat burst, viewer delta)
    - agent:messages — Inter-agent real-time messaging
    - dashboard:updates — Real-time dashboard push updates
    - system:notifications — System alerts and notifications

    Consumer Groups:
    - fast_path:signals → "deep-path-workers" group
    - agent:messages → per-agent consumer groups
    - dashboard:updates → per-dashboard-session groups

    Stream Properties:
    - MAXLEN: 10000 (trim old entries, keep memory bounded)
    - ID: time-ordered (ms-sequence format)
    - Pending entries list (PEL): track unacked messages
    - Claim: stalled messages can be claimed by other consumers
    """

    STREAM_MAXLEN = 10000
    CLAIM_TIMEOUT_MS = 30000  # 30 seconds before message can be claimed

    # Stream names
    STREAM_FAST_PATH = "fast_path:signals"
    STREAM_AGENT_MESSAGES = "agent:messages"
    STREAM_DASHBOARD = "dashboard:updates"
    STREAM_NOTIFICATIONS = "system:notifications"

    def __init__(self, redis_client):
        self.redis = redis_client
        self._consumers: dict[str, asyncio.Task] = {}

    async def publish(
        self,
        stream: str,
        message: dict,
        maxlen: Optional[int] = None,
    ) -> str:
        """Publish a message to a Redis Stream."""
        if maxlen is None:
            maxlen = self.STREAM_MAXLEN

        # XADD with automatic trimming
        message_id = await self.redis.xadd(
            stream,
            {"data": json.dumps(message), "ts": str(int(time.time() * 1000))},
            maxlen=maxlen,
            approximate=True,  # ~ maxlen (faster trimming)
        )
        return message_id

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable,
        count: int = 10,
        block_ms: int = 5000,
    ):
        """Consume messages from a stream as part of a consumer group."""
        # Ensure consumer group exists
        try:
            await self.redis.xgroup_create(stream, group, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise  # Group already exists is OK

        while True:
            try:
                # Read new messages
                messages = await self.redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={stream: ">"},  # ">" = never delivered messages
                    count=count,
                    block=block_ms,
                )

                for stream_name, msg_list in messages:
                    for msg_id, fields in msg_list:
                        try:
                            data = json.loads(fields.get("data", "{}"))
                            await handler(data)
                            # Acknowledge
                            await self.redis.xack(stream, group, msg_id)
                        except Exception as e:
                            logger.error(f"Stream handler error: {e}", exc_info=True)
                            # Don't ack — message stays in PEL for retry/claim

                # Check for stalled messages (claim them)
                await self._claim_stalled_messages(stream, group, consumer, handler)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Stream consume error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def _claim_stalled_messages(
        self, stream: str, group: str, consumer: str, handler: Callable
    ):
        """Claim and process stalled messages (consumer died without acking)."""
        # Get pending messages older than CLAIM_TIMEOUT_MS
        pending = await self.redis.xpending_range(
            stream, group,
            min="-", max="+",
            count=10,
            idle=self.CLAIM_TIMEOUT_MS,
        )

        for entry in pending:
            msg_id = entry["message_id"]
            # Claim the message
            claimed = await self.redis.xclaim(
                stream, group, consumer,
                min_idle_time=self.CLAIM_TIMEOUT_MS,
                message_ids=[msg_id],
            )

            if claimed:
                for _, fields in claimed:
                    try:
                        data = json.loads(fields.get("data", "{}"))
                        await handler(data)
                        await self.redis.xack(stream, group, msg_id)
                        logger.info(f"Claimed and processed stalled message: {msg_id}")
                    except Exception as e:
                        logger.error(f"Error processing claimed message: {e}")

    async def start_consumer(
        self,
        stream: str,
        group: str,
        consumer: str,
        handler: Callable,
    ) -> str:
        """Start a background consumer task."""
        task = asyncio.create_task(
            self.consume(stream, group, consumer, handler)
        )
        consumer_key = f"{stream}:{group}:{consumer}"
        self._consumers[consumer_key] = task
        return consumer_key

    async def stop_consumer(self, consumer_key: str):
        """Stop a background consumer."""
        task = self._consumers.get(consumer_key)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self._consumers[consumer_key]

    async def stop_all(self):
        """Stop all consumers."""
        for key in list(self._consumers.keys()):
            await self.stop_consumer(key)
```

## 26.3 Fast Path Signal Flow

```python
# Example: Fast path signal from audio spike to deep analysis trigger

# In Stream Capture Service (producer):
async def on_audio_spike(stream_id: str, magnitude: float, timestamp_ms: int):
    """Called when audio spike is detected (fast path)."""
    await redis_streams.publish(
        stream=RedisStreamsManager.STREAM_FAST_PATH,
        message={
            "type": "audio_spike",
            "stream_id": stream_id,
            "magnitude": magnitude,
            "timestamp_ms": timestamp_ms,
        },
    )

# In Deep Path Worker (consumer):
async def handle_fast_path_signal(signal: dict):
    """Handle fast path signal — trigger deep analysis."""
    if signal["type"] == "audio_spike":
        # Immediately trigger deep analysis for the current frame
        await orchestrator.trigger_deep_analysis(
            stream_id=signal["stream_id"],
            reason="audio_spike",
            magnitude=signal["magnitude"],
            timestamp_ms=signal["timestamp_ms"],
        )

# Start consumer:
await redis_streams.start_consumer(
    stream=RedisStreamsManager.STREAM_FAST_PATH,
    group="deep-path-workers",
    consumer=f"worker-{worker_id}",
    handler=handle_fast_path_signal,
)
```

---

# 27. POSTGRESQL + CLICKHOUSE + QDRANT — TOGETHER

## 27.1 Polyglot Persistence Strategy

```
┌──────────────────────────────────────────────────────────────────────┐
│                POLYGLOT PERSISTENCE ARCHITECTURE                     │
│                                                                      │
│                     ┌──────────────────┐                            │
│                     │   EVENT BUS      │                            │
│                     │   (Kafka)        │                            │
│                     └────────┬─────────┘                            │
│                              │                                       │
│              ┌───────────────┼───────────────┐                      │
│              │               │               │                      │
│       ┌──────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐               │
│       │ PostgreSQL  │ │ ClickHouse │ │  Qdrant    │               │
│       │             │ │            │ │            │               │
│       │ OLTP        │ │ OLAP       │ │ Vector     │               │
│       │ CRUD        │ │ Analytics  │ │ ANN Search │               │
│       │ Joins       │ │ Time Series│ │ Similarity │               │
│       │ ACID        │ │ Aggregates │ │ Semantic   │               │
│       │             │ │            │ │            │               │
│       │ ┌─────────┐ │ │ ┌────────┐ │ │ ┌────────┐│               │
│       │ │ Users   │ │ │ │Metrics │ │ │ │Embed-  ││               │
│       │ │ Clips   │ │ │ │Trends  │ │ │ │dings   ││               │
│       │ │ Streams │ │ │ │Stats   │ │ │ │Search  ││               │
│       │ │ Prefs   │ │ │ │TS Data │ │ │ │RAG     ││               │
│       │ └─────────┘ │ │ └────────┘ │ │ └────────┘│               │
│       └─────────────┘ └────────────┘ └────────────┘               │
│                                                                      │
│  WRITE PATH: Event → Kafka → CQRS Projection → All three DBs       │
│  READ PATH: Query type determines which DB to query                 │
│                                                                      │
│  CONSISTENCY: Eventually consistent (CQRS projections lag < 1s)    │
│  CONSISTENCY GUARANTEE: Read-your-writes via Redis cache           │
└──────────────────────────────────────────────────────────────────────┘
```

## 27.2 Query Routing

```python
# data/query_router.py

from enum import Enum
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


class QueryTarget(Enum):
    """Which database to route a query to."""
    POSTGRESQL = "postgresql"     # OLTP: CRUD, joins, transactions
    CLICKHOUSE = "clickhouse"     # OLAP: aggregations, time series, analytics
    QDRANT = "qdrant"             # Vector: semantic search, similarity
    REDIS = "redis"               # Cache: hot data, sessions
    NEO4J = "neo4j"               # Graph: entity relationships


class QueryRouter:
    """
    Routes queries to the appropriate database based on query type.

    Routing Rules:
    1. CRUD operations (INSERT, UPDATE, DELETE, SELECT by ID) → PostgreSQL
    2. Aggregations (SUM, AVG, COUNT, GROUP BY) → ClickHouse
    3. Time range queries → ClickHouse
    4. Semantic similarity → Qdrant
    5. Graph traversal → Neo4j
    6. Hot data lookup → Redis (with PostgreSQL fallback)
    7. Complex joins → PostgreSQL (ClickHouse doesn't support all join types)

    Read-Your-Writes Consistency:
    - After write to PostgreSQL, invalidate Redis cache
    - Next read goes to PostgreSQL (not stale cache)
    - CQRS projections update asynchronously (< 1s lag)
    """

    # Query pattern → target database
    ROUTING_RULES = {
        # PostgreSQL patterns
        "get_clip_by_id": QueryTarget.POSTGRESQL,
        "update_clip_status": QueryTarget.POSTGRESQL,
        "get_streamer_profile": QueryTarget.POSTGRESQL,
        "create_clip": QueryTarget.POSTGRESQL,
        "get_user_preferences": QueryTarget.POSTGRESQL,

        # ClickHouse patterns
        "get_stream_metrics": QueryTarget.CLICKHOUSE,
        "get_clip_analytics": QueryTarget.CLICKHOUSE,
        "get_trend_data": QueryTarget.CLICKHOUSE,
        "get_inference_stats": QueryTarget.CLICKHOUSE,
        "get_time_range_data": QueryTarget.CLICKHOUSE,
        "get_aggregation": QueryTarget.CLICKHOUSE,

        # Qdrant patterns
        "search_similar_clips": QueryTarget.QDRANT,
        "search_episodes": QueryTarget.QDRANT,
        "search_timeline": QueryTarget.QDRANT,
        "semantic_search": QueryTarget.QDRANT,

        # Redis patterns
        "get_current_stream_score": QueryTarget.REDIS,
        "get_session_data": QueryTarget.REDIS,
        "get_hot_clip": QueryTarget.REDIS,

        # Neo4j patterns
        "get_streamer_graph": QueryTarget.NEO4J,
        "find_similar_streamers": QueryTarget.NEO4J,
        "get_trending_for_game": QueryTarget.NEO4J,
    }

    def __init__(
        self,
        postgres_pool,
        clickhouse_client,
        qdrant_client,
        redis_client,
        neo4j_driver=None,
    ):
        self.postgres = postgres_pool
        self.clickhouse = clickhouse_client
        self.qdrant = qdrant_client
        self.redis = redis_client
        self.neo4j = neo4j_driver

    async def execute(
        self, query_type: str, **kwargs
    ) -> Any:
        """Route and execute a query to the appropriate database."""
        target = self.ROUTING_RULES.get(query_type)

        if target is None:
            logger.warning(f"Unknown query type: {query_type}, defaulting to PostgreSQL")
            target = QueryTarget.POSTGRESQL

        if target == QueryTarget.POSTGRESQL:
            return await self._query_postgres(query_type, **kwargs)
        elif target == QueryTarget.CLICKHOUSE:
            return await self._query_clickhouse(query_type, **kwargs)
        elif target == QueryTarget.QDRANT:
            return await self._query_qdrant(query_type, **kwargs)
        elif target == QueryTarget.REDIS:
            return await self._query_redis(query_type, **kwargs)
        elif target == QueryTarget.NEO4J:
            return await self._query_neo4j(query_type, **kwargs)

    async def _query_postgres(self, query_type: str, **kwargs):
        """Execute PostgreSQL query."""
        async with self.postgres.acquire() as conn:
            if query_type == "get_clip_by_id":
                return await conn.fetchrow(
                    "SELECT * FROM clips_read_model WHERE clip_id = $1",
                    kwargs["clip_id"],
                )
            elif query_type == "get_streamer_profile":
                return await conn.fetchrow(
                    "SELECT * FROM streamer_profiles WHERE stream_id = $1",
                    kwargs["stream_id"],
                )
            # ... more query handlers

    async def _query_clickhouse(self, query_type: str, **kwargs):
        """Execute ClickHouse query."""
        if query_type == "get_stream_metrics":
            return await self.clickhouse.query(
                """SELECT timestamp_ms, metric_name, metric_value
                   FROM stream_metrics
                   WHERE stream_id = %(stream_id)s
                     AND timestamp_ms >= %(start_ms)s
                   ORDER BY timestamp_ms""",
                params=kwargs,
            )
        elif query_type == "get_aggregation":
            return await self.clickhouse.query(
                """SELECT %(agg_fn)s(metric_value) as result
                   FROM stream_metrics
                   WHERE stream_id = %(stream_id)s
                     AND metric_name = %(metric_name)s
                     AND timestamp_ms >= %(start_ms)s""",
                params=kwargs,
            )

    async def _query_qdrant(self, query_type: str, **kwargs):
        """Execute Qdrant query."""
        if query_type == "search_similar_clips":
            return await self.qdrant.search(
                collection_name="clips",
                query_vector=kwargs["query_vector"],
                query_filter=kwargs.get("filter"),
                limit=kwargs.get("limit", 5),
            )

    async def _query_redis(self, query_type: str, **kwargs):
        """Execute Redis query."""
        if query_type == "get_current_stream_score":
            return await self.redis.hgetall(
                f"stream:current:{kwargs['stream_id']}"
            )

    async def _query_neo4j(self, query_type: str, **kwargs):
        """Execute Neo4j query."""
        if self.neo4j is None:
            logger.warning("Neo4j not configured")
            return None
        # ... Neo4j query handlers
```

## 27.3 Data Consistency Strategy

```python
# data/consistency/consistency_manager.py

import asyncio
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ConsistencyManager:
    """
    Manages cross-database consistency.

    Challenge: When an event updates PostgreSQL, ClickHouse, and Qdrant
    asynchronously, there's a brief inconsistency window.

    Strategies:
    1. READ-YOUR-WRITES: After write, write to Redis cache too
       Next read hits Redis (fresh data), not stale CQRS projection
       Redis TTL: 5 seconds (enough for CQRS to catch up)

    2. VERSIONED WRITES: Each write includes a version number
       Read checks if version is stale → triggers refresh

    3. COMPENSATING TRANSACTIONS: If a projection fails, log it
       Background job retries failed projections

    4. ANTI-CORRUPTION LAYER: Each DB has its own data format
       Translation layer prevents format coupling

    5. SNAPSHOT ISOLATION: ClickHouse queries use snapshot
       Consistent read even while projections are updating
    """

    def __init__(self, redis_client, postgres_pool):
        self.redis = redis_client
        self.postgres = postgres_pool

    async def write_with_cache(
        self,
        entity_type: str,
        entity_id: str,
        data: dict,
        cache_ttl: int = 5,
    ):
        """Write to PostgreSQL and update Redis cache for read-your-writes."""
        # Write to PostgreSQL
        async with self.postgres.acquire() as conn:
            # ... actual write logic
            pass

        # Update Redis cache (read-your-writes consistency)
        cache_key = f"{entity_type}:{entity_id}"
        await self.redis.setex(
            cache_key,
            cache_ttl,
            json.dumps(data),
        )

    async def read_with_cache(
        self,
        entity_type: str,
        entity_id: str,
        fallback_query: callable,
    ) -> Optional[dict]:
        """Read from Redis cache first, fallback to database."""
        cache_key = f"{entity_type}:{entity_id}"

        # Try cache first
        cached = await self.redis.get(cache_key)
        if cached:
            return json.loads(cached)

        # Cache miss → query database
        result = await fallback_query(entity_id)

        # Populate cache
        if result:
            await self.redis.setex(cache_key, 5, json.dumps(result))

        return result

    async def invalidate_cache(self, entity_type: str, entity_id: str):
        """Invalidate cache entry (on update)."""
        await self.redis.delete(f"{entity_type}:{entity_id}")
```

## 27.4 Complete Database Schema Summary

```sql
-- ============================================================
-- POSTGRESQL SCHEMA (OLTP — CRUD, joins, transactions)
-- ============================================================

-- Users & Auth
CREATE TABLE users (
    user_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username         VARCHAR(100) UNIQUE NOT NULL,
    email            VARCHAR(200) UNIQUE NOT NULL,
    password_hash    VARCHAR(200),
    role             VARCHAR(20) DEFAULT 'viewer',  -- viewer, creator, admin
    created_at       TIMESTAMPTZ DEFAULT now(),
    last_login       TIMESTAMPTZ
);

CREATE TABLE api_keys (
    key_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES users(user_id),
    key_hash         VARCHAR(200) NOT NULL,
    name             VARCHAR(100),
    scopes           TEXT[] DEFAULT '{}',
    expires_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now(),
    last_used        TIMESTAMPTZ
);

-- Streams
CREATE TABLE streams (
    stream_id        VARCHAR(100) PRIMARY KEY,
    streamer_id      UUID REFERENCES users(user_id),
    platform         VARCHAR(50),  -- twitch, youtube, kick
    platform_stream_id VARCHAR(200),
    title            TEXT,
    started_at       TIMESTAMPTZ,
    ended_at         TIMESTAMPTZ,
    status           VARCHAR(20) DEFAULT 'active',
    peak_viewers     INT DEFAULT 0,
    total_clips      INT DEFAULT 0
);

-- Clips (CQRS read model — see section 23.3 for full schema)

-- Streamer profiles (see section 10.4)

-- Semantic timeline (see section 13.3)

-- Episodic memory (see section 10.4)

-- Creator feedback (see section 21.3)

-- Streamer preferences (see section 21.3)

-- Agent registry (see section 4.5)

-- Model endpoints (see section 6.6)

-- ============================================================
-- CLICKHOUSE SCHEMA (OLAP — analytics, time series)
-- ============================================================

-- stream_metrics (see section 2.4)
-- stream_intelligence (see section 17.4)
-- inference_metrics (see section 24.2)
-- agent_metrics (see section 24.2)
-- clip_performance (see section 24.2)
-- keyword_frequency (see section 20.3)
-- trends (see section 20.3)
-- feature_store_* (see section 22.3)

-- ============================================================
-- QDRANT COLLECTIONS (Vector search)
-- ============================================================

-- clips: clip description embeddings (384d, cosine)
-- episodic_memory: stream episode summaries (384d, cosine)
-- semantic_timeline: timeline segment embeddings (384d, cosine)
-- chat_topics: chat topic embeddings (384d, cosine)
-- vlm_descriptions: VLM scene description embeddings (384d, cosine)

-- ============================================================
-- NEO4J SCHEMA (Knowledge graph)
-- ============================================================

-- Nodes: Streamer, Game, GameAgent, Clip, Trend, Demographic
-- Relationships: PLAYS, MAIN_AGENT, CREATED, FEATURES, MATCHES, HAS_DEMOGRAPHIC
```

---

## Part 4 Summary

| Component | Technology | Role | Retention |
|---|---|---|---|
| Event Store | Kafka + PostgreSQL (CQRS) | Immutable event log, replay, audit | Kafka: 7-90d, PG: forever |
| Time Series DB | ClickHouse | Real-time metrics, analytics, aggregations | 30-365 days |
| Kafka Topics | Apache Kafka 3.6+ | Event bus, 6 tiers, 30+ topics | 7-90 days |
| Redis Streams | Redis 7 | Fast path signals, <1ms latency | Minutes |
| PostgreSQL | PostgreSQL 16 | OLTP, CRUD, joins, transactions | Forever |
| Qdrant | Qdrant | Vector search, semantic retrieval | Forever |
| Neo4j | Neo4j (optional) | Knowledge graph, entity relationships | Forever |

---

*Continue to `IP_PART5_GPU_ORCHESTRATION.md` for GPU & Orchestration Infrastructure.*
