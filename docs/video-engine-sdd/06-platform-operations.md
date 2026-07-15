# Video Engine SDD 06 - Platform ve Operasyonlar

**Belge durumu:** Tasarım temeli  
**Kapsam:** 58-70; API, veri, paketleme, gözlemlenebilirlik, performans, kaynak yönetimi, doğrulama, teslimat, üretim, hata kurtarma ve ölçeklenebilirlik  
**Normatif dil:** "MUST/ZORUNLU", "SHOULD/ÖNERİLİR" ve "MAY/OPSİYONEL" ifadeleri RFC 2119 anlamında kullanılır.  
**Ortak mimari:** FastAPI ve Pydantic v2, PostgreSQL, Temporal, S3 uyumlu nesne deposu, yalnız hot cache/ephemeral koordinasyon için Redis, FFmpeg/libav işçileri, GPU capability queue'ları, OpenTelemetry, Prometheus, Loki, Kubernetes ve Vault/KMS. Sistem multi-tenant, idempotent ve asenkron iş semantiğine sahiptir.

Bu belge, render motorunun platform sözleşmesini tanımlar. Medya algoritmalarının ayrıntıları ayrı render pipeline belgelerinde kalır; burada API'den kabul edilen bir işin doğrulanması, kalıcılaştırılması, planlanması, çalıştırılması, gözlemlenmesi, yayımlanması ve hata halinde kurtarılması ele alınır.

## Dağıtım ve Topoloji

```mermaid
flowchart TB
    Client[Web / SDK / Partner] -->|HTTPS REST, SSE, WebSocket| Edge[WAF + API Gateway]
    Edge --> API[FastAPI API Pods]
    Edge --> WH[Webhook Ingress]
    API --> PG[(PostgreSQL HA)]
    API --> Redis[(Redis Hot Cache)]
    API --> S3[(S3 Object Storage)]
    API --> Temporal[Temporal Frontend]
    Temporal --> TW[Temporal Workers]
    TW --> QC[CPU Capability Queue]
    TW --> QG[GPU Capability Queues]
    QC --> CPU[FFmpeg/libav CPU Workers]
    QG --> GPU[FFmpeg/libav GPU Workers]
    CPU --> S3
    GPU --> S3
    CPU --> PG
    GPU --> PG
    PG --> Outbox[Outbox Relay]
    Outbox --> Delivery[Signed Webhook Delivery]
    Vault[Vault + KMS] --> API
    Vault --> TW
    Vault --> CPU
    Vault --> GPU
    API --> OTEL[OpenTelemetry Collectors]
    TW --> OTEL
    CPU --> OTEL
    GPU --> OTEL
    OTEL --> Prom[(Prometheus)]
    OTEL --> Loki[(Loki)]
    OTEL --> Trace[(Trace Backend)]
```

### Topoloji kararları

- API, Temporal worker ve medya worker deployment'ları ayrı ölçeklenir; API pod'u FFmpeg çalıştırmaz.
- CPU ve GPU worker'ları ayrı Kubernetes node pool'larında çalışır. GPU pool'ları codec, GPU modeli, VRAM sınıfı ve driver capability etiketiyle ayrılır.
- PostgreSQL iş/tenant/audit için source of truth'tür. Redis hiçbir kalıcı iş durumu, lock sahibi veya sonuç kaydı için source of truth olamaz.
- S3, input, intermediate checkpoint ve immutable output nesnelerini tutar. İstemci yüklemeleri kısa ömürlü signed URL ile doğrudan S3'e gider.
- Temporal workflow, uzun süren orchestration ve retry zamanlamasının sahibidir; media activity idempotent checkpoint üretir.
- Secret'lar image, Git, ConfigMap veya log içine girmez. Vault dinamik credential üretir; envelope encryption anahtarları KMS tarafından korunur.
- Tenant kimliği API'den DB session context'e, Temporal search attribute'a, S3 key prefix'e, telemetry resource attribute'a ve webhook'a taşınır.
- Bölgesel deployment hücreleri bağımsız failure domain'dir. Bir iş, açık failover kararı ve checkpoint transferi olmadan bölgeler arasında koşarken taşınmaz.

### Önerilen klasör ağacı

```text
video-engine/
|-- apps/
|   |-- api/
|   |   |-- routes/
|   |   |-- schemas/
|   |   |-- dependencies/
|   |   `-- problem_details/
|   |-- webhook_dispatcher/
|   `-- outbox_relay/
|-- domain/
|   |-- jobs/
|   |-- assets/
|   |-- tenants/
|   |-- quotas/
|   `-- audit/
|-- orchestration/
|   |-- workflows/
|   |-- activities/
|   |-- task_queues/
|   `-- recovery/
|-- workers/
|   |-- common/
|   |-- ffmpeg_cpu/
|   |-- ffmpeg_gpu/
|   |-- probes/
|   `-- checkpoints/
|-- persistence/
|   |-- models/
|   |-- repositories/
|   |-- migrations/
|   |-- partitions/
|   `-- outbox/
|-- platform/
|   |-- storage/
|   |-- cache/
|   |-- telemetry/
|   |-- security/
|   `-- admission/
|-- deploy/
|   |-- docker/
|   |-- helm/video-engine/
|   |-- environments/
|   `-- dashboards/
|-- benchmarks/
|   |-- corpus-manifest/
|   |-- scenarios/
|   |-- baselines/
|   `-- reports/
|-- tests/
|   |-- unit/
|   |-- contract/
|   |-- integration/
|   |-- golden/
|   |-- fuzz/
|   |-- chaos/
|   `-- load/
`-- docs/video-engine-sdd/
```

### Uçtan uca invariantlar

1. Her mutating public request, tenant kapsamlı `Idempotency-Key` ile tekrar edilebilir olmalıdır.
2. Bir job state değişimi PostgreSQL'de monoton `version` artırır; API `ETag: "job-{id}-v{version}"` döndürür.
3. İşin terminal sonucu yalnız doğrulanmış S3 nesnesi ve transaction içinde yazılmış terminal DB durumu birlikte mevcutsa başarılıdır.
4. Bir workflow/activity retry'si aynı logical output'u ikinci kez yayımlayamaz; object key ve publish transaction deterministiktir.
5. Redis kaybı gecikmeyi artırabilir ancak doğruluk, yetkilendirme, quota muhasebesi veya recovery'yi bozamaz.
6. Her medya subprocess'i tenant, job, attempt ve trace kimliğiyle ilişkilidir; hassas signed URL'ler process argümanları ve loglardan maskelenir.
7. Kabul edilen iş miktarı, ölçülmüş kapasite ve quota ile sınırlanır; sınırsız kuyruk sistem davranışı değildir.

---

## 58. API Design

### Mekanizma, invariantlar ve gerekçe

Public API, `/v1` altında resource-oriented REST ve asenkron job semantiği kullanır. Render oluşturma çağrısı işi çalıştırmayı beklemez; doğrulama ve admission sonrasında `202 Accepted`, `Location`, `ETag` ve izleme bağlantıları döner. Pydantic v2 modellerinde `extra="forbid"`, strict tipler, açık discriminator ve normalize edilmiş zaman/UUID kullanılır.

- `Idempotency-Key`, tenant + HTTP method + canonical route kapsamında unique'dir. Aynı key ve aynı canonical body aynı cevabı; farklı body `409 idempotency_conflict` üretir.
- `POST /jobs` atomik olarak job, idempotency kaydı ve outbox `job.accepted` olayını oluşturur. Temporal start DB transaction içinde yapılmaz; outbox/dispatcher workflow'u başlatır.
- Optimistic concurrency için `If-Match` ZORUNLUDUR; iptal veya metadata güncellemesi stale ETag ile `412 Precondition Failed` döndürür.
- Hatalar `application/problem+json` RFC 7807 biçimindedir; `type`, `title`, `status`, `detail`, `instance`, `code`, `trace_id` ve güvenli `errors[]` taşır.
- Upload/download signed URL'leri dar method, content-type, content-length, checksum, tenant prefix ve en fazla 15 dakika TTL ile üretilir.
- Liste uçları cursor pagination kullanır; cursor tenant, stable sort tuple ve filter hash içeren imzalı opaque token'dır. Offset pagination yüksek cardinality tablolarda kullanılmaz.
- Webhook body, timestamp ve delivery id üzerinde HMAC-SHA256/Ed25519 ile imzalanır. Beş dakikalık tolerans, unique delivery id ve receiver replay store beklenir.
- Progress için SSE varsayılandır; çift yönlü kontrol gereken editör oturumlarında WebSocket kullanılabilir. Her event `id`, monoton `sequence`, `job_version` taşır; `Last-Event-ID` ile devam edilir.
- Quota; eşzamanlı job, bekleyen iş, input byte, output byte, GPU-saniye ve günlük medya-dakika boyutlarında uygulanır.

Neden: HTTP retry, mobil bağlantı kopması ve proxy timeout'ları kaçınılmazdır. Idempotency ve version sözleşmesi olmadan aynı render iki kez ücretlendirilebilir veya iptal edilmiş iş yayımlanabilir.

Alternatifler ve tradeoff'lar:

- Senkron render endpoint'i basittir ancak gateway timeout, kopmuş bağlantı ve kaynak rezervasyonu nedeniyle yalnız kısa probe işlemlerinde uygundur.
- GraphQL okuma esnekliği sağlar; upload, cache, async lifecycle ve HTTP conditional request semantiği için REST daha öngörülebilirdir.
- WebSocket daha düşük etkileşim gecikmesi sunar; proxy ve reconnect karmaşıklığı nedeniyle tek yönlü progress'te SSE tercih edilir.
- Broker'a doğrudan publish düşük gecikmelidir; transactional outbox olmadan DB/publish dual-write kaybı oluşur.

### Veri akışı ve public/internal API örneği

1. İstemci `POST /v1/uploads` ile checksum ve byte boyutunu bildirir; API quota kontrol edip signed PUT üretir.
2. İstemci S3'e doğrudan yükler ve `POST /v1/uploads/{id}:complete` çağrısıyla doğrulamayı başlatır.
3. API, `POST /v1/jobs` isteğini Pydantic ile doğrular, asset ownership ve quota kontrolü yapar, transaction içinde job/idempotency/outbox yazar.
4. Outbox relay Temporal workflow'u deterministic workflow id ile başlatır.
5. Progress DB projection ve ephemeral Redis fan-out üzerinden SSE'ye ulaşır; reconnect DB'deki son sequence'dan devam eder.
6. Terminal outbox olayı webhook dispatcher'a gider; delivery her denemede aynı event id, yeni attempt ve imza taşır.

```http
POST /v1/jobs HTTP/1.1
Authorization: Bearer <token>
Idempotency-Key: 01J2EXAMPLEA7Z6J
Content-Type: application/json

{
  "input_asset_id": "ast_01J2...",
  "timeline_id": "tml_01J2...",
  "output": {"container": "mp4", "video_codec": "h264", "width": 1920, "height": 1080},
  "callback": {"webhook_id": "wh_01J2..."},
  "client_reference": "campaign-42-v7"
}
```

```http
HTTP/1.1 202 Accepted
Location: /v1/jobs/job_01J2...
ETag: "job-job_01J2-v1"
Retry-After: 2
Content-Type: application/json

{"id":"job_01J2...","status":"accepted","version":1,"links":{"events":"/v1/jobs/job_01J2.../events"}}
```

```json
{
  "type": "https://errors.example.com/quota/gpu-seconds",
  "title": "GPU kotası aşıldı",
  "status": 429,
  "detail": "Yeni GPU işi şu anda kabul edilemiyor.",
  "instance": "/v1/jobs",
  "code": "quota_gpu_seconds_exceeded",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "retry_after_seconds": 60
}
```

Internal worker contract versioned protobuf/JSON payload olabilir, ancak yalnız kimlikleri ve immutable plan digest'ini taşır; büyük timeline veya signed media URL queue payload'ına gömülmez.

```python
from pydantic import BaseModel, ConfigDict, Field

class StartRenderActivity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tenant_id: str
    job_id: str
    attempt_id: str
    plan_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    capability: str
    traceparent: str
```

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
apps/api/routes/{jobs,uploads,events,webhooks}.py
apps/api/schemas/{requests,responses,problems}.py
apps/api/dependencies/{auth,tenant,etag,idempotency,quota}.py
domain/jobs/{entities,commands,policies}.py
orchestration/workflows/render.py
platform/admission/service.py
```

API codec ayrıntılarını doğrudan worker flag'lerine çevirmez. Validated request önce immutable `RenderIntent`, sonra capability-aware planner tarafından versioned `RenderPlan` olur. Plan digest'i workflow ve checkpoint boyunca sabit kalır; worker yalnız bu planı FFmpeg/libav graph'ına derler.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant C as Client
    participant A as FastAPI
    participant D as PostgreSQL
    participant O as Outbox Relay
    participant T as Temporal
    participant W as Media Worker
    C->>A: POST /v1/jobs + Idempotency-Key
    A->>D: quota + job + idempotency + outbox (TX)
    D-->>A: job v1
    A-->>C: 202 + Location + ETag
    O->>D: claim job.accepted
    O->>T: start workflow(job_id)
    T->>W: render activity(plan_digest)
    W-->>T: checkpoint/progress/result
    T->>D: terminal projection + outbox
    A-->>C: SSE progress / signed result URL
```

### Mermaid class

```mermaid
classDiagram
    class JobResource {+UUID id +JobStatus status +int version +string tenantId +ETag etag}
    class IdempotencyRecord {+string key +bytes requestHash +int responseStatus +UUID jobId}
    class UploadSession {+UUID assetId +long contentLength +string checksum +datetime expiresAt}
    class ProgressEvent {+long sequence +int jobVersion +string phase +float percent}
    class WebhookDelivery {+UUID eventId +int attempt +datetime timestamp +bytes signature}
    JobResource "1" --> "1" IdempotencyRecord
    JobResource "1" --> "0..*" ProgressEvent
    JobResource "1" --> "0..*" WebhookDelivery
    UploadSession "1" --> "0..*" JobResource
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Validating
    Validating --> Rejected: schema/auth/quota
    Validating --> Accepted: transaction committed
    Accepted --> Queued: workflow started
    Queued --> Running: worker lease
    Running --> Cancelling: If-Match cancel
    Running --> Succeeded: output verified
    Running --> Failed: terminal error
    Running --> Queued: retryable attempt
    Cancelling --> Cancelled: compensation complete
    Succeeded --> [*]
    Failed --> [*]
    Cancelled --> [*]
    Rejected --> [*]
```

### Production sorunları, recovery ve performans

- İstemci timeout sonrası retry ederse idempotency kaydı aynı response snapshot/iş kimliğini döndürür. İlk transaction sonucu belirsizse key üzerinden GET yapılır.
- Outbox relay çökmesi job'u kaybetmez; `SKIP LOCKED`, lease expiry ve deterministic Temporal workflow id ile tekrar işler.
- SSE node değişimi event kaybettirmez; kısa hot replay Redis'ten, kalıcı gap PostgreSQL progress projection'dan doldurulur.
- Webhook endpoint yavaşsa jittered exponential backoff, per-destination circuit breaker ve dead-letter review uygulanır. Job başarısı webhook başarısına bağlı değildir.
- Signed URL sızması riskinde TTL kısa tutulur; token log redaction, object prefix policy ve KMS-backed tenant key ile blast radius sınırlandırılır.
- API latency için Pydantic schema cache, async DB pool, batched quota reads ve conditional GET kullanılır. Render payload'ları DB/API üzerinden kopyalanmaz.

### Benchmark, gerçek dünya, ölçek ve ownership

Yöntem: kayıtlı OpenAPI senaryoları ile k6/Locust; aynı tenant, çok tenant, idempotent retry fırtınası, pagination ve 100 bin SSE bağlantısı ayrı test edilir. Metrikler ve kabul eşikleri: cached GET p95 `< 100 ms`, job create p95 `< 250 ms`, p99 `< 750 ms`, API hata oranı `< %0,5`, duplicate logical job `0`, SSE event lag p99 `< 2 s`, webhook imzalama p99 `< 20 ms`. Eşikler üretim donanımı ve corpus manifest'iyle versionlanır.

Gerçek dünya senaryosu: bir mobil istemci upload tamamlandıktan sonra üç kez job create gönderir ve bağlantı değiştirir. Tek job oluşur; tüm cevaplar aynı `Location` değerini verir; progress yeni SSE bağlantısında `Last-Event-ID` ile devam eder.

Ölçeklenme: API stateless yatay ölçeklenir; tenant-rate shard edilmiş gateway limiter ve DB-backed authoritative quota kullanılır. Hot tenant için tenant concurrency cap ve weighted fair admission diğer tenant'ları korur.

Ownership: API Platform ekibi OpenAPI, auth, idempotency ve pagination; Workflow ekibi internal command; Media ekibi RenderIntent/RenderPlan sözleşmesi; SRE quota ve SLO sahibidir. Contract testleri OpenAPI breaking-change diff, idempotency race, ETag conflict, webhook signature/replay ve SSE resume senaryolarını ZORUNLU kapsar.

---

## 59. Database Schema

### Mekanizma, invariantlar ve gerekçe

PostgreSQL authoritative metadata store'dur. Her tenant-owned tabloda `tenant_id` bulunur; foreign key'ler mümkün olduğunda `(tenant_id, id)` composite key üzerinden tenant çapraz bağını fiziksel olarak engeller. Uygulama transaction başında `SET LOCAL app.tenant_id` uygular ve defense-in-depth Row Level Security kullanır. Kimlikler UUIDv7/ULID sıralanabilirliğiyle üretilir; dış kimlikler tahmin edilebilir sequence değildir.

Temel invariantlar:

- Bir job'ın state'i state machine dışında değişemez; `version` her mutasyonda tam bir artar.
- `jobs.output_asset_id`, yalnız `assets.status='verified'` olduğunda terminal success transaction'ına bağlanır.
- Aynı tenant/idempotency scope/key için tek canonical request hash vardır.
- Outbox olayı domain değişikliğiyle aynı transaction'da yazılır; relay teslimatı at-least-once, consumer etkisi idempotent'tir.
- Audit satırları append-only'dir; application role `UPDATE/DELETE` yetkisine sahip değildir.
- Monetary/usage counters float değil `bigint` tabanlı byte, frame, sample, millisecond veya micro-credit birimi kullanır.

Neden: render işlerinin dakika/saat sürmesi ve retry alması, transient queue durumunu yetersiz kılar. İlişkisel constraint'ler tenant izolasyonu, lifecycle ve faturalama doğruluğunu uygulama hatalarına karşı korur.

Alternatifler ve tradeoff'lar:

- Tam document store, değişken render spec için rahattır; lifecycle join, unique idempotency, audit ve quota transaction'larında daha zayıf/karmaşıktır.
- Event sourcing güçlü tarihçe sağlar; projection, GDPR silme ve operasyonel sorgu maliyeti yüksektir. Burada current-state + outbox + immutable audit seçilir.
- Redis job store düşük gecikmelidir ancak eviction/failover kalıcı doğruluğu bozacağından yalnız hot cache olarak kullanılır.
- Her tabloyu baştan partition etmek bakım maliyeti getirir; yalnız yüksek hacimli append tabloları partition edilir.

### Ayrıntılı schema ve indeksler

```sql
CREATE TABLE tenants (
  id uuid PRIMARY KEY,
  slug text NOT NULL UNIQUE,
  status text NOT NULL CHECK (status IN ('active','suspended','deleting')),
  home_region text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
  tenant_id uuid NOT NULL REFERENCES tenants(id),
  id uuid NOT NULL,
  status text NOT NULL CHECK (status IN
    ('accepted','queued','running','cancelling','cancelled','succeeded','failed')),
  version integer NOT NULL DEFAULT 1 CHECK (version > 0),
  priority smallint NOT NULL DEFAULT 50 CHECK (priority BETWEEN 0 AND 100),
  input_asset_id uuid NOT NULL,
  output_asset_id uuid,
  render_spec jsonb NOT NULL,
  plan_digest text,
  capability_key text,
  progress_sequence bigint NOT NULL DEFAULT 0,
  error_code text,
  client_reference text,
  accepted_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  deleted_at timestamptz,
  PRIMARY KEY (tenant_id, id),
  CHECK ((status = 'succeeded') = (output_asset_id IS NOT NULL)),
  CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX jobs_tenant_status_priority_idx
  ON jobs (tenant_id, status, priority DESC, accepted_at, id)
  WHERE deleted_at IS NULL;
CREATE INDEX jobs_active_capability_idx
  ON jobs (capability_key, priority DESC, accepted_at)
  WHERE status IN ('accepted','queued','running');
CREATE UNIQUE INDEX jobs_client_reference_uq
  ON jobs (tenant_id, client_reference) WHERE client_reference IS NOT NULL AND deleted_at IS NULL;

CREATE TABLE assets (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('input','intermediate','output','thumbnail','manifest')),
  status text NOT NULL CHECK (status IN ('pending','uploaded','verifying','verified','quarantined','deleted')),
  bucket text NOT NULL,
  object_key text NOT NULL,
  version_id text,
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  sha256 bytea NOT NULL,
  media_type text NOT NULL,
  probe jsonb,
  kms_key_ref text NOT NULL,
  retention_until timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, bucket, object_key, version_id),
  FOREIGN KEY (tenant_id) REFERENCES tenants(id)
);
ALTER TABLE jobs ADD CONSTRAINT jobs_input_asset_fk
  FOREIGN KEY (tenant_id, input_asset_id) REFERENCES assets(tenant_id, id);
ALTER TABLE jobs ADD CONSTRAINT jobs_output_asset_fk
  FOREIGN KEY (tenant_id, output_asset_id) REFERENCES assets(tenant_id, id);

CREATE TABLE idempotency_records (
  tenant_id uuid NOT NULL,
  scope text NOT NULL,
  key text NOT NULL,
  request_hash bytea NOT NULL,
  resource_id uuid,
  response_status smallint,
  response_body jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, scope, key),
  CHECK (expires_at > created_at)
);

CREATE TABLE job_attempts (
  tenant_id uuid NOT NULL,
  job_id uuid NOT NULL,
  attempt_no integer NOT NULL CHECK (attempt_no > 0),
  worker_id text,
  node_name text,
  capability_key text NOT NULL,
  checkpoint_asset_id uuid,
  status text NOT NULL CHECK (status IN ('leased','running','retryable_failed','terminal_failed','completed','lost')),
  error_class text,
  metrics jsonb,
  started_at timestamptz NOT NULL,
  heartbeat_at timestamptz,
  finished_at timestamptz,
  PRIMARY KEY (tenant_id, job_id, attempt_no),
  FOREIGN KEY (tenant_id, job_id) REFERENCES jobs(tenant_id, id)
);

CREATE TABLE outbox_events (
  shard smallint NOT NULL,
  id uuid NOT NULL,
  tenant_id uuid NOT NULL,
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  aggregate_version integer NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  trace_context jsonb NOT NULL,
  occurred_at timestamptz NOT NULL DEFAULT now(),
  available_at timestamptz NOT NULL DEFAULT now(),
  claimed_until timestamptz,
  published_at timestamptz,
  attempts integer NOT NULL DEFAULT 0,
  PRIMARY KEY (shard, occurred_at, id),
  UNIQUE (tenant_id, aggregate_type, aggregate_id, aggregate_version, event_type)
) PARTITION BY RANGE (occurred_at);

CREATE TABLE audit_log (
  occurred_at timestamptz NOT NULL,
  id uuid NOT NULL,
  tenant_id uuid NOT NULL,
  actor_type text NOT NULL,
  actor_id text NOT NULL,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text NOT NULL,
  request_id text,
  source_ip inet,
  before_hash bytea,
  after_hash bytea,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);
```

Ek tablolar: `webhook_endpoints`, `webhook_deliveries`, `quota_limits`, `usage_ledger`, `workflow_bindings`, `progress_events`, `schema_migrations`, `legal_holds`. `progress_events`, `audit_log`, `usage_ledger` ve `outbox_events` aylık/günlük hacme göre time partition; `jobs` ise ancak yüz milyonlar seviyesinde tenant hash partition'a geçirilir.

JSONB kullanımı:

- Kullanılır: versioned `render_spec`, ffprobe çıktısının sorgulanmayan/seyrek sorgulanan kısmı, attempt diagnostic metrics, event payload ve audit metadata.
- Kullanılmaz: tenant id, job status, timestamps, codec/capability routing alanları, quota counters, object key, lifecycle relation ve sık filtrelenen billing boyutları.
- Sık sorgulanan JSON alanı generated column veya normal kolona promote edilir. Geniş `GIN(render_spec)` varsayılan değildir; yazma amplifikasyonu ve bloat nedeniyle yalnız kanıtlanmış query için expression index eklenir.

### Veri akışı ve repository API örneği

1. API transaction, idempotency satırını conflict-safe insert eder.
2. Asset ownership ve quota ledger satırları tenant kapsamında kilitlenir/atomic update edilir.
3. Job ve `job.accepted` outbox satırı yazılır, commit edilir.
4. Relay partition/shard bazında `FOR UPDATE SKIP LOCKED` ile batch claim eder.
5. Worker heartbeat ve yüksek frekanslı progress'i her frame yazmaz; coalesced projection günceller, attempt terminal özeti kalıcılaştırır.
6. Success transaction asset'i verified, job'ı succeeded ve usage ledger/outbox'ı aynı atomik sınırda yazar.

```sql
UPDATE jobs
SET status = 'cancelling', version = version + 1
WHERE tenant_id = $1 AND id = $2 AND version = $3
  AND status IN ('accepted','queued','running')
RETURNING id, status, version;
-- Satır yoksa 404 değil önce existence kontrolüyle 404/412/409 ayrıştırılır.
```

Migration politikası expand/migrate/contract'tır. Önce nullable/yeni tablo ve geriye uyumlu kod; sonra chunked backfill ve doğrulama; en son `NOT NULL`, constraint validation ve eski kolon kaldırma yapılır. Büyük constraint `NOT VALID` eklenip ayrı deploy'da `VALIDATE CONSTRAINT` edilir. DDL lock bütçesi, statement timeout ve rollback/runbook migration dosyasına yazılır; app startup migration çalıştırmaz.

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
persistence/models/{job,asset,attempt,outbox,audit}.py
persistence/repositories/{jobs,assets,quotas}.py
persistence/migrations/versions/*.sql
persistence/partitions/{create,retain,archive}.py
persistence/outbox/{relay,consumer_dedup}.py
tests/integration/postgres/
```

Pipeline, büyük frame/audio verisini DB'ye yazmaz. DB yalnız plan digest, checkpoint pointer, media probe özeti, usage ve lifecycle tutar. Intermediate segmentler S3'te immutable'dır; schema bunların checksum ve retention bağını saklar.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant A as API
    participant P as PostgreSQL
    participant R as Outbox Relay
    participant T as Temporal
    A->>P: BEGIN + idempotency insert
    A->>P: quota reserve + job insert
    A->>P: outbox insert + COMMIT
    R->>P: claim batch SKIP LOCKED
    R->>T: start deterministic workflow
    T-->>R: already started / accepted
    R->>P: mark published
```

### Mermaid class

```mermaid
classDiagram
    class Tenant {+uuid id +string homeRegion +string status}
    class Job {+uuid id +string status +int version +jsonb renderSpec +string planDigest}
    class Asset {+uuid id +string kind +string objectKey +bytes sha256 +string status}
    class JobAttempt {+int attemptNo +string capability +string status +jsonb metrics}
    class OutboxEvent {+uuid id +int aggregateVersion +string eventType +datetime publishedAt}
    class AuditRecord {+uuid id +string action +bytes beforeHash +bytes afterHash}
    Tenant "1" --> "0..*" Job
    Tenant "1" --> "0..*" Asset
    Job "1" --> "1..*" JobAttempt
    Job --> Asset: input/output/checkpoint
    Job "1" --> "0..*" OutboxEvent
    Job "1" --> "0..*" AuditRecord
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Expand
    Expand --> DualReadWrite: compatible app deployed
    DualReadWrite --> Backfill: old and new schema active
    Backfill --> Validate: chunks complete
    Validate --> Contract: parity and constraints pass
    Contract --> [*]: old schema removed
    Backfill --> Paused: lag/lock budget exceeded
    Paused --> Backfill: capacity restored
    Validate --> RollbackCode: parity failed
```

### Production sorunları, recovery ve performans

- Connection storm için PgBouncer transaction pooling, sınırlı app pool ve admission uygulanır. Session-level tenant state yerine her transaction `SET LOCAL` kullanır.
- Replica lag nedeniyle job state read-after-write primary veya version-aware session route üzerinden okunur; stale replica terminal sonucu gizleyemez.
- Bloat/autovacuum geride kalırsa append partition rotate edilir, hot update index sayısı azaltılır ve vacuum per-table ayarlanır.
- Deadlock durumunda transaction kısa, lock order sabit ve serialization/deadlock retry bounded jitter ile yapılır.
- Partition oluşturma hatası yazmayı kesmemelidir; önceden N dönem yaratılır, default emergency partition alarm üretir.
- PITR; WAL archive, encrypted cross-region backup ve düzenli restore drill ile doğrulanır. Logical silme/retention ve legal hold ayrı policy'dir.
- Query performansı `pg_stat_statements`, `EXPLAIN (ANALYZE, BUFFERS)`, lock wait ve index hit ratio ile izlenir. N+1 ve geniş JSONB select engellenir.

### Benchmark, gerçek dünya, ölçek ve ownership

Yöntem: üretime benzer cardinality ile pgbench/custom replay; 10 milyon job, 1 milyar progress/audit satırı, hot tenant ve relay concurrency senaryoları. Eşikler: create transaction p95 `< 40 ms`, state transition p95 `< 25 ms`, job lookup p99 `< 50 ms`, outbox publish lag p99 `< 2 s`, lock wait p99 `< 20 ms`, duplicate aggregate event `0`, restore point objective doğrulaması RPO `<= 5 dk`.

Gerçek dünya: tek tenant bir kampanya anında 500 bin job yollar. Composite tenant/status index ve weighted admission taramayı sınırlarken outbox shard'ları paralel akar; tenant kota satırı global mutex olmaması için zaman kovalarına bölünür.

Ölçeklenme: önce vertical primary + read replicas + partitioning; write sınırında tenant-home-region/hücre bazlı PostgreSQL cluster shard'ı. Cross-shard join public request yolunda yapılmaz; global admin raporu async warehouse projection kullanır.

Ownership: Data Platform schema/migration/backup; domain ekipleri tablo semantiği; SRE capacity ve restore; Security audit/RLS politikasının sahibidir. Her migration CI'da boş DB, önceki release upgrade, downgrade/runbook, lock-budget ve veri parity testinden geçer.

---

## 60. Docker

### Mekanizma, invariantlar ve gerekçe

API, orchestration, CPU worker ve GPU worker için ayrı, multi-stage ve digest ile pinlenmiş image'lar üretilir. FFmpeg/libav binary'si build aşamasında belirli source revision, configure flags ve codec lisans manifest'iyle derlenir; runtime image'a yalnız gerekli shared library ve CA bundle taşınır.

- CPU image ve GPU image aynı `RenderPlan` contract version'ını uygular; capability farkı image label ve startup self-test ile ilan edilir.
- GPU image matrisi `CUDA major.minor + minimum driver + FFmpeg revision + codec SDK` olarak kilitlenir. Kubernetes node driver'ı image'ın minimum driver şartını sağlamıyorsa pod Ready olmaz.
- Container rootless, read-only root filesystem, dropped capabilities, `no-new-privileges`, seccomp/AppArmor ve explicit tmpfs ile çalışır.
- Image içinde secret, cloud credential, model lisans anahtarı veya writable cache bulunmaz.
- Her release OCI provenance, CycloneDX/SPDX SBOM, vulnerability scan ve cosign signature taşır.
- Floating tag (`latest`, unpinned distro/package) üretimde yasaktır; deployment image digest kullanır.

Neden: medya stack'i sistem library, codec patent/lisansı ve GPU driver ABI'sine hassastır. Aynı application commit'i farklı FFmpeg build'iyle farklı frame veya crash üretebilir; image supply-chain ve codec build'i birlikte reproducible olmalıdır.

Alternatifler ve tradeoff'lar:

- Tek universal image operasyonu basitleştirir fakat GPU kütüphaneleri CPU pod'larını büyütür, saldırı yüzeyi ve pull süresi artar.
- Distro FFmpeg güvenlik güncellemesini kolaylaştırır; configure flags/version kontrolü ve bit-exact baseline zorlaşır.
- Distroless küçüktür; FFmpeg shared library ve üretim debug araçları için sıkça zorlayıcıdır. Minimal Debian/Ubuntu runtime + ayrı debug image dengeli çözümdür.
- Static FFmpeg dependency drift'i azaltır; glibc, codec plugin ve lisans gereksinimleri doğrulanmadan varsayılan yapılmaz.

### Build/data flow ve image sözleşmesi örneği

1. BuildKit hermetic builder, lockfile ve checksum doğrulanmış kaynaklarla FFmpeg/libav üretir.
2. Unit test stage binary capability ve linked library manifest'ini kontrol eder.
3. Runtime stage non-root UID, worker binary, FFmpeg ve policy dosyalarını alır.
4. CI image'ı tarar, SBOM/provenance üretir, imzalar ve immutable registry'ye push eder.
5. Admission controller yalnız trusted issuer ve izinli digest'i cluster'a alır.
6. Worker başlangıçta `ffmpeg -buildconf`, encoder probe ve kısa encode/decode self-test sonucu capability registry'ye yazar.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM debian:bookworm@sha256:<builder-digest> AS ffmpeg-build
ARG FFMPEG_REF=n7.0.1
RUN --mount=type=cache,target=/var/cache/apt \
    ./build-ffmpeg.sh --ref "$FFMPEG_REF" --enable-libx264 --disable-debug

FROM python:3.12-slim-bookworm@sha256:<runtime-digest> AS app-build
RUN --mount=type=cache,target=/root/.cache/pip pip wheel --require-hashes -r requirements.lock -w /wheels

FROM python:3.12-slim-bookworm@sha256:<runtime-digest>
RUN groupadd -g 10001 engine && useradd -r -u 10001 -g engine engine
COPY --from=ffmpeg-build /opt/ffmpeg /opt/ffmpeg
COPY --from=app-build /wheels /wheels
COPY workers /app/workers
USER 10001:10001
ENV PATH="/opt/ffmpeg/bin:${PATH}" PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-m", "workers.ffmpeg_cpu"]
```

Image label sözleşmesi:

```text
org.opencontainers.image.revision=<git-sha>
video.example.com/ffmpeg.revision=n7.0.1
video.example.com/render-plan.version=6
video.example.com/capabilities=h264-sw,aac,scale-zimg
video.example.com/min-driver=550.54
video.example.com/sbom.digest=sha256:...
```

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
deploy/docker/{Dockerfile.api,Dockerfile.worker-cpu,Dockerfile.worker-gpu,Dockerfile.debug}
deploy/docker/scripts/{build-ffmpeg,verify-libs,self-test}.sh
deploy/docker/locks/{sources.lock,apt.snapshot,python.lock}
deploy/docker/policies/{seccomp.json,licenses.yaml}
tests/container/{capabilities,nonroot,readonly,sbom}.py
```

Render planner yalnız registry'de self-test geçmiş capability'lere plan yollar. FFmpeg configure flag veya encoder değişikliği render output baseline'ını etkilediğinden application değişikliği kadar versionlanır.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant CI as CI Builder
    participant B as BuildKit
    participant S as Security Scanner
    participant R as OCI Registry
    participant K as K8s Admission
    participant W as Worker
    CI->>B: build pinned CPU/GPU target
    B-->>CI: image + provenance + SBOM
    CI->>S: scan image/SBOM/licenses
    S-->>CI: policy result
    CI->>R: push digest + cosign signature
    K->>R: verify signature/attestation
    K->>W: schedule allowed digest
    W->>W: FFmpeg/GPU self-test
```

### Mermaid class

```mermaid
classDiagram
    class ImageManifest {+string digest +string revision +string planVersion +string sbomDigest}
    class FFmpegBuild {+string revision +string[] configureFlags +string licenseProfile}
    class GPUCompatibility {+string cudaVersion +string minDriver +string codecSdk}
    class CapabilityReport {+string imageDigest +string[] encoders +bool selfTestPassed}
    ImageManifest --> FFmpegBuild
    ImageManifest --> GPUCompatibility
    ImageManifest --> CapabilityReport
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Built
    Built --> Tested: container tests pass
    Tested --> Scanned: SBOM/CVE/license
    Scanned --> Signed: policy accepted
    Signed --> Published
    Published --> Admitted: signature verified
    Admitted --> Ready: runtime self-test
    Scanned --> Blocked: critical finding
    Ready --> Quarantined: capability drift/crash
```

### Production sorunları, recovery ve performans

- Driver mismatch pod crash-loop üretirse readiness capability probe başarısız olur, node taint edilir ve önceki signed digest'e rollout edilir.
- Registry kesintisine karşı node image cache tek recovery değildir; bölgesel registry replication ve pull-through mirror kullanılır.
- CVE bulunduğunda exploitability + reachable component değerlendirilir; critical reachable bulgu için rebuild/canary ve digest rollout, değişmeyen source revision ile yapılabilir.
- Read-only filesystem için FFmpeg temp path bounded `emptyDir`/tmpfs'tir; kapasite limiti aşılırsa job retryable resource error alır.
- Büyük image pull startup gecikmesini artırır; CPU/GPU katmanları ayrılır, gereksiz compiler/header silinir, node pre-pull DaemonSet canary öncesi çalışır.
- Core dump varsayılan kapalıdır; kontrollü debug image ve encrypted dump store yalnız incident policy ile açılır.

### Benchmark, gerçek dünya, ölçek ve ownership

Yöntem: cold/warm pull, startup self-test, image size, CVE count, encode throughput parity ve binary reproducibility karşılaştırılır. Eşikler: API image `< 300 MB`, CPU worker `< 800 MB`, GPU worker organization baseline'ına göre takip edilir; cold start readiness CPU `< 20 s`, pre-pulled GPU `< 30 s`; critical reachable CVE `0`; aynı source/build input için manifest dışı binary drift `0`; codec smoke corpus başarı `%100`.

Gerçek dünya: CUDA base image güncellenir ancak cluster driver eski kalır. Compatibility attestation ve startup probe rollout'u bloke eder; scheduler işleri eski healthy digest/capability pool'una yönlendirir.

Ölçeklenme: registry bölgesel mirror, layer dedup, pre-pull ve küçük specialization image'larıyla yüzlerce node aynı anda açılabilir. Capability image sayısı kontrolsüz kombinatoryal büyütülmez; desteklenen codec/GPU matrisi ürün SLO'suna göre sınırlanır.

Ownership: Developer Platform base image/BuildKit; Media Runtime FFmpeg flags ve codec lisansı; GPU Platform driver matrisi; Security SBOM/signing/CVE policy; SRE registry ve rollout sahibidir. Container contract testleri rootless, read-only, signal handling, graceful shutdown, capability truthfulness ve output parity içerir.

---

## 61. Monitoring

### Mekanizma, invariantlar ve gerekçe

OpenTelemetry trace/metric/log correlation katmanıdır. Prometheus sayısal zaman serilerini, Loki yapılandırılmış logları, trace backend span'leri tutar. API için RED (Rate, Errors, Duration), altyapı ve worker için USE (Utilization, Saturation, Errors), medya pipeline için frame/audio/codec özel sinyalleri birlikte kullanılır.

- Her request/job/workflow/activity/FFmpeg process `trace_id`, `tenant_hash`, `job_id`, `attempt_id`, `region`, `capability`, `image_digest` ile ilişkilidir.
- Raw tenant adı, signed URL, token, timeline içeriği ve kullanıcı dosya adı label/log olamaz.
- Prometheus label cardinality bounded'dır; `job_id` ve `asset_id` metric label değil trace/log field'dır.
- Workflow trace context, Temporal memo/search attribute'a minimum W3C `traceparent` olarak taşınır; retry yeni span, aynı logical trace linkage üretir.
- FFmpeg child process span'i komutun sanitize edilmiş template'ini, build revision'ı, progress parser sonuçlarını ve exit classification'ı taşır.
- Alert, tek düşük seviye metrikten değil kullanıcı etkisi/SLO burn-rate ve semptom-kapasite korelasyonundan üretilir.

Neden: yalnız CPU metriği, bozuk timestamp veya encoder stall'ını göstermez; yalnız log ise trend ve SLO üretmez. Correlated telemetry bir job'ın API kabulünden codec subprocess'ine kadar gecikme dağılımını görünür kılar.

Alternatifler ve tradeoff'lar:

- Her frame için log/metric kesin görünürlük sağlar ancak maliyet ve cardinality kabul edilemez; worker aggregation + sampled detail seçilir.
- Vendor agent hızlı kurulur; açık OTel semantic conventions taşınabilirliği ve merkezi redaction sağlar.
- Tail sampling hata/yavaş trace'leri korur fakat collector state maliyeti vardır; head sampling tek başına nadir codec hatalarını kaçırır.

### Veri akışı ve telemetry API örneği

1. Gateway W3C trace context'i doğrular veya yeni root trace oluşturur.
2. FastAPI span'i DB, S3 ve outbox child span'leri üretir.
3. Temporal interceptor context'i workflow/activity'ye taşır; replay sırasında nondeterministic telemetry workflow kararına etki etmez.
4. Worker sanitized FFmpeg process span'i açar; `-progress pipe:1` key/value akışını parser.
5. OTel Collector attribute processor hassas alanları siler, tail sampler hata/yavaş trace'i tutar.
6. Metrics Prometheus remote-write, logs Loki, traces backend'e gider; exemplars metric noktasını trace'e bağlar.

```text
http.server.request.duration{route="/v1/jobs",status_class="2xx"}
render.queue.wait.seconds{capability="nvenc-h264",priority_class="standard"}
render.realtime_factor{codec="h264",resolution="1080p",path="gpu"}
render.frames.total{result="encoded|dropped|duplicated"}
render.audio.samples.total{result="processed|clipped|silent"}
render.ffmpeg.exit.total{class="input|resource|codec|internal|cancelled"}
render.checkpoint.age.seconds{phase="encode"}
node.gpu.vram.utilization{gpu_model="..."}
```

```python
with tracer.start_as_current_span("ffmpeg.encode") as span:
    span.set_attributes({
        "media.ffmpeg.revision": FFMPEG_REVISION,
        "media.plan.digest": plan_digest,
        "media.codec": codec,
        "render.attempt_id": attempt_id,
    })
    result = await run_ffmpeg(progress_callback=record_aggregated_progress)
    span.set_attribute("process.exit.code", result.exit_code)
```

SLO örnekleri: API accepted-job availability `%99,95`; job dispatch latency p99 `< 30 s` standard queue; platform kaynaklı terminal failure `< %0,2`; progress freshness p99 `< 5 s`; webhook first-attempt dispatch p99 `< 10 s`. Render completion süresi input karmaşıklığına bağlı olduğundan resolution/codec/duration sınıfına göre SLO dilimlenir.

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
platform/telemetry/{bootstrap,attributes,redaction,sampling}.py
workers/common/{ffmpeg_progress,process_span,metric_aggregation}.py
deploy/dashboards/{api,workflow,worker,gpu,media-quality}.json
deploy/alerts/{slo,capacity,codec,storage}.yaml
deploy/otel-collector/{gateway,agent}.yaml
tests/contract/telemetry/
```

Pipeline phase'leri `probe`, `download`, `decode`, `filter`, `compose`, `encode`, `upload`, `verify`, `publish` ortak span/metric adlarını kullanır. Böylece plan değişse de kritik yol ve bottleneck karşılaştırılabilir.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant A as API
    participant T as Temporal
    participant W as Worker
    participant F as FFmpeg
    participant O as OTel Collector
    participant B as Backends
    A->>T: workflow + traceparent
    T->>W: activity + linked context
    W->>F: sanitized command + progress pipe
    F-->>W: frame/fps/out_time/speed
    W->>O: spans + aggregated metrics + logs
    A->>O: HTTP/DB/S3 spans
    O->>O: redact + sample + batch
    O->>B: Prometheus/Loki/trace export
```

### Mermaid class

```mermaid
classDiagram
    class TelemetryContext {+string traceId +string tenantHash +string jobId +string attemptId}
    class RenderSpan {+string phase +duration elapsed +string status}
    class FFmpegProgress {+long frame +duration outTime +float fps +float speed}
    class MediaMetrics {+counter frames +histogram realtimeFactor +counter exitClass}
    class RedactionPolicy {+string[] deniedKeys +sanitizeCommand()}
    TelemetryContext --> RenderSpan
    RenderSpan --> FFmpegProgress
    FFmpegProgress --> MediaMetrics
    RedactionPolicy --> RenderSpan
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Healthy
    Healthy --> Degraded: export errors/lag
    Degraded --> Buffered: local bounded queue
    Buffered --> Healthy: backend recovered
    Buffered --> SamplingIncreased: buffer pressure
    SamplingIncreased --> DroppingDebug: hard limit
    DroppingDebug --> Healthy: pressure cleared
    Healthy --> Alerting: SLO burn-rate exceeded
    Alerting --> Healthy: impact resolved
```

### Production sorunları, recovery ve performans

- Collector/back-end kesintisi render'ı durdurmaz; bounded memory/disk queue, priority sampling ve telemetry drop counters kullanılır. Telemetry backpressure media path'e aktarılmaz.
- Cardinality patlamasında offending label collector'da drop edilir, dashboard query sınırlandırılır ve recording rule ile aggregation yapılır.
- FFmpeg stderr burst'leri line/rate limit ve dedup fingerprint ile yönetilir; ilk/son bağlam korunur, signed URL maskelenir.
- Clock skew span sırasını bozarsa node NTP alarmı ve monotonic process duration kullanılır.
- Stuck job tespiti yalnız progress yüzdesine dayanmaz; heartbeat, CPU/GPU utilization, I/O bytes ve checkpoint age birlikte değerlendirilir.
- Telemetry overhead, worker CPU'nun `%2` ve job wall time'ın `%1` altında tutulur; high-frequency değerler process içinde aggregate edilir.

### Benchmark, gerçek dünya, ölçek ve ownership

Yöntem: telemetry açık/kapalı A/B, collector failure, cardinality bomb, log burst ve tail-sampling load testleri. Eşikler: span export success `> %99,9` normal durumda, metric scrape freshness `< 30 s`, log ingestion p99 `< 10 s`, trace-to-log correlation başarı `> %99`, worker CPU overhead `< %2`, dropped error traces `0`, page alert MTTD `< 5 dk`.

Gerçek dünya: belirli bir GPU driver sürümünde NVENC process'i exit vermeden ilerlemeyi keser. `ffmpeg_progress_age`, GPU utilization düşüşü ve checkpoint age alarmı aynı image/driver boyutunda kümelenir; worker watchdog process'i sonlandırıp retryable infrastructure hatası sınıflandırır.

Ölçeklenme: agent collector node-local batching, gateway collector tail sampling yapar. Metric recording rule ve tenant hash örneklemesi backend'i korur; yüksek hacimli debug log kısa retention, audit log ayrı immutable store/policy kullanır.

Ownership: Observability Platform collector/schema/backend; SRE SLO ve paging; Media Runtime media metric semantiği; Security redaction/audit; domain ekipleri dashboard/runbook sahibidir. Telemetry contract testleri zorunlu attribute, secret redaction, trace propagation, retry span linkage ve cardinality budget kontrolü yapar.

---

## 62. Performance Profiling

### Mekanizma, invariantlar ve gerekçe

Profiling, render süresini tek bir "FFmpeg yavaş" sonucuna indirgemek yerine wall-clock, CPU, GPU, disk/network I/O, queue wait ve scheduler throttling bileşenlerine ayırır. Her profil `image_digest`, FFmpeg revision/configuration, RenderPlan digest, corpus case, node tipi, GPU/driver, concurrency, warm/cold cache durumu ve profiler sürümü içeren immutable bir manifest ile saklanır.

- Profiling üretimde varsayılan olarak kapalı veya düşük oranlıdır; tenant/job hedefli açma yetkisi audit edilir, süre ve overhead bütçesiyle otomatik sona erer.
- Profiling sonucu iş davranışını değiştiremez. Profiler çökmesi render'ı başarısız yapmaz; yalnız profile artifact'i incomplete işaretlenir.
- Wall time her pipeline phase için monotonic clock ile ölçülür. CPU time, cgroup throttling ve runnable wait ayrı tutulur; `%CPU` tek başına bottleneck kanıtı değildir.
- GPU kernel/encoder/decode süreleri ile host-to-device/device-to-host transferleri ayrılır. GPU utilization yüksekliği tek başına verimli throughput anlamına gelmez.
- I/O ölçümü logical media byte, S3 transfer byte, local spill byte, read/write latency ve stall time olarak ayrılır.
- Profil artifact'lerinde signed URL, token, müşteri dosya adı, frame içeriği ve environment secret bulunamaz. Flamegraph sembolleri ve command line sanitize edilir.
- İki profil ancak aynı benchmark manifest'i ve toleranslı eşdeğer runtime sınıfında karşılaştırılır; farklı codec preset'i veya driver sonucu aynı baseline'a karıştırılmaz.

Neden: bir render'ın wall süresi; queue wait, input indirme, decode, filter graph, encode, upload ve throttling toplamıdır. Yalnız örnekleme profiler'ı CPU hot path'i bulabilir ama S3 stall'ını; yalnız GPU aracı kernel beklemesini bulabilir ama Python orchestration gecikmesini açıklamaz. Katmanlı profil, optimizasyonun doğru kaynağa uygulanmasını sağlar.

Alternatifler ve tradeoff'lar:

- Instrumentation profiler kesin phase süreleri verir ancak kod değişikliği ve ölçüm overhead'i getirir; sampling profiler daha düşük müdahaleyle hot stack bulur fakat kısa çağrıları kaçırabilir. İkisi birlikte kullanılır.
- `perf`/eBPF düşük seviyede güçlüdür; kernel capability ve sembol yönetimi ister. Üretimde ayrı privileged profiler DaemonSet'i, worker container'ına ek capability vermekten daha güvenlidir.
- Full GPU trace ayrıntılıdır ancak yüksek overhead ve büyük artifact üretir; CI/lab için, üretimde NVML/DCGM sayaçları ve hedefli kısa trace tercih edilir.
- FFmpeg `-benchmark_all` aşama bilgisi sağlar ancak log hacmini artırır ve tüm filtrelerde tutarlı ayrım sunmaz; `-progress pipe:1`, process rusage ve OTel phase span'leriyle korele edilir.
- Continuous profiling regresyonu erken yakalar; maliyet ve veri güvenliği nedeniyle symbol-only, düşük örneklemeli ve tenant-safe politika gerektirir.

### Veri akışı ve internal API/schema örneği

1. Benchmark runner veya yetkili operatör, job/corpus case için süreli bir `ProfileSession` oluşturur.
2. Policy service, ortam ve tenant politikasına göre izin verilen profiler'ları, maksimum süreyi ve overhead bütçesini belirler.
3. Worker render başlamadan manifest'e runtime fingerprint yazar; OTel span ve profiler session aynı `attempt_id` ile bağlanır.
4. FFmpeg `-benchmark`, gerektiğinde `-benchmark_all`, `-progress pipe:1` ve `-stats_period` ile çalışır. Wrapper process rusage, cgroup CPU/memory/I/O ve context-switch değerlerini toplar.
5. GPU agent NVML/DCGM; hedefli laboratuvar koşusunda Nsight Systems/Compute verisini toplar. Node agent disk/network eBPF özetini ilişkilendirir.
6. Artifact'ler sanitize edilip sıkıştırılır, checksum ile S3'e yazılır; PostgreSQL'e yalnız manifest, özet ve object pointer kaydedilir.
7. Analyzer kritik yol, flamegraph, phase breakdown ve baseline delta üretir; sonucu benchmark raporuna bağlar.

```python
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class ProfileSessionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    target_attempt_id: str
    mode: Literal["phase", "cpu-sample", "io", "gpu-sample", "gpu-trace"]
    duration_seconds: int = Field(ge=5, le=300)
    sample_hz: int = Field(default=49, ge=1, le=199)
    include_native_stacks: bool = True
    expires_at: datetime

class ProfileSummary(BaseModel):
    wall_ms: int
    cpu_user_ms: int
    cpu_system_ms: int
    cpu_throttled_ms: int
    io_wait_ms: int
    gpu_active_ms: int | None
    ffmpeg_utime_ms: int
    ffmpeg_stime_ms: int
    max_rss_bytes: int
    artifact_sha256: str
```

Internal uçlar public internete açılmaz: `POST /internal/v1/profile-sessions`, `GET /internal/v1/profile-sessions/{id}` ve `POST /internal/v1/profile-sessions/{id}:cancel`. Çağrılar mTLS workload identity, role, environment allowlist ve audit ile korunur. Profil DB kaydı örneği:

```sql
CREATE TABLE profile_runs (
  id uuid PRIMARY KEY,
  tenant_id uuid,
  job_id uuid,
  attempt_id text NOT NULL,
  mode text NOT NULL,
  runtime_fingerprint jsonb NOT NULL,
  summary jsonb,
  artifact_bucket text,
  artifact_key text,
  artifact_sha256 bytea,
  status text NOT NULL CHECK (status IN ('requested','collecting','analyzing','completed','incomplete','rejected')),
  expires_at timestamptz NOT NULL,
  created_by text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
```

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
platform/profiling/{policy,sessions,manifest,sanitizer}.py
workers/common/profiling/{phase_timer,rusage,ffmpeg_benchmark}.py
workers/probes/{cpu_sampler,io_sampler,gpu_sampler}.py
benchmarks/analyzers/{critical_path,flamegraph,baseline_delta}.py
deploy/profilers/{ebpf-daemonset,dcgm,nvidia-tools}.yaml
tests/performance/profiling/
```

Render pipeline'daki `probe`, `download`, `decode`, `filter`, `compose`, `encode`, `upload`, `verify` ve `publish` sınırları profil phase id'leriyle bire bir eşleşir. FFmpeg tek process içinde birden çok phase çalıştırsa bile filter graph node isimleri, progress zamanı ve libav instrumentation ile alt kırılım üretilir. Profil sonucu planner'ın maliyet modelini besleyebilir; ancak yeni model offline doğrulanıp versionlanmadan canlı admission kararını değiştiremez.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant O as Operator/Benchmark
    participant P as Profile Controller
    participant W as Media Worker
    participant F as FFmpeg/libav
    participant N as Node/GPU Agent
    participant S as S3
    participant A as Analyzer
    O->>P: create session(mode, attempt, budget)
    P->>P: authorize + audit + policy
    P->>W: attach bounded profile session
    W->>F: run with benchmark/progress
    W->>N: correlate cgroup/GPU/I/O samples
    F-->>W: progress + benchmark + exit
    N-->>W: sampled counters/stacks
    W->>S: sanitized artifact + checksum
    W->>A: immutable manifest + summary
    A-->>O: critical path + baseline delta
```

### Mermaid class

```mermaid
classDiagram
    class ProfileSession {+uuid id +string mode +int durationSeconds +string status}
    class RuntimeFingerprint {+string imageDigest +string ffmpegRevision +string nodeType +string driverVersion}
    class PhaseSample {+string phase +long wallNs +long cpuNs +long ioWaitNs}
    class GPUSample {+float utilization +long vramBytes +long encoderNs +long transferNs}
    class ProfileArtifact {+string objectKey +string sha256 +string format +bool sanitized}
    class BaselineComparison {+string baselineId +float wallDelta +float throughputDelta +string verdict}
    ProfileSession --> RuntimeFingerprint
    ProfileSession "1" --> "1..*" PhaseSample
    ProfileSession "1" --> "0..*" GPUSample
    ProfileSession --> ProfileArtifact
    ProfileArtifact --> BaselineComparison
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Requested
    Requested --> Rejected: policy/authorization
    Requested --> Armed: worker accepted
    Armed --> Collecting: target phase starts
    Collecting --> Uploading: duration/process ends
    Collecting --> Incomplete: profiler/node failure
    Collecting --> Cancelled: budget/operator
    Uploading --> Analyzing: checksum verified
    Uploading --> Incomplete: artifact failure
    Analyzing --> Completed: report stored
    Analyzing --> Incomplete: analyzer failure
    Completed --> Expired: retention elapsed
    Rejected --> [*]
    Cancelled --> [*]
    Expired --> [*]
```

### Production sorunları, recovery ve performans optimizasyonları

- Profiler overhead'i budget'ı aşarsa controller session'ı sonlandırır; render devam eder ve artifact `incomplete/overhead_guard` olur.
- Native stack sembolleri eksikse build-id üzerinden ayrı debug symbol image/store kullanılır; production image'a compiler/debug paketi eklenmez.
- PID namespace veya kısa ömürlü FFmpeg process'i attach yarışına yol açarsa worker process'i suspended başlatmak yerine profiler önceden cgroup'a bağlanır; başarısız attach render'ı geciktirmez.
- Node agent veri kaybında aynı kaynağın OTel/cgroup özetleri korunur; eksik eksen raporda açıkça belirtilir, sıfır kabul edilmez.
- Flamegraph'ta mutex contention görülürse yalnız fonksiyon mikro-optimizasyonu yapılmaz; queue depth, CPU affinity, NUMA remote access ve cgroup throttling birlikte kontrol edilir.
- I/O bottleneck için S3 multipart concurrency sınırlı artırılır, range read ve local spill düzeni optimize edilir; bandwidth saturation admission'a geri beslenir.
- CPU hot path için filter fusion, gereksiz pixel format/color conversion kaldırma, uygun SIMD build'i ve thread count/affinity denenir. GPU bottleneck için transfer azaltma ve kernel/encoder overlap ölçülmeden uygulanmaz.

Recovery, profil kontrol düzleminde idempotent session id ile yapılır. Controller restart sonrası `requested/collecting` kayıtları worker heartbeat ile reconcile eder; süresi geçmiş session'ı kapatır. Artifact upload multipart kaldıysa lifecycle rule temizler. Profiler kaynaklı worker crash'i `profiling_induced` olarak sınıflanır, aynı job profiling kapalı yeni attempt'te checkpoint'ten devam eder ve incident açılır.

### Benchmark yöntemi, metrikler, eşikler, gerçek dünya, ölçek ve ownership

Yöntem: aynı node'da pinlenmiş corpus ve en az 5 warm iteration; cold-cache ayrı seri; median, p95 ve güven aralığı raporlanır. Profil açık/kapalı A/B sırası randomize edilir. Metrikler: phase wall/CPU, CPU cycles/instructions/IPC, context switch, throttled time, page fault, disk/network throughput ve latency, GPU SM/encoder/decoder utilization, PCIe byte, VRAM, FPS ve realtime factor.

Kabul eşikleri: phase timer overhead `< %0,5`; normal CPU sampling overhead `< %2 wall`; hedefli GPU trace overhead raporlanır ve baseline performans sonucu olarak kullanılmaz; profile manifest alan tamlığı `%100`; secret redaction ihlali `0`; aynı build/corpus için üç tekrar coefficient of variation CPU serisinde `< %5`, GPU serisinde `< %7`; açıklanamayan wall-time payı `< %10`.

Gerçek dünya: 4K overlay işinde GPU utilization yalnız `%35`, wall time yüksektir. Profil, her frame'in GPU'dan host'a indirildiğini, CPU overlay sonrası tekrar upload edildiğini gösterir. Filter graph GPU-native overlay/scale zincirine çevrilir; PCIe byte/frame ve wall time düşüşü golden kalite testleriyle doğrulanır.

Ölçeklenme: continuous profile örneklemesi node ve capability sınıfı başına bütçelenir; aynı anda tüm pod'lar profile edilmez. Artifact retention tiered'dır, özetler uzun; ham stack/GPU trace kısa saklanır. Analyzer queue'su render queue'sundan bağımsızdır ve düşmesi üretimi etkilemez.

Ownership: Performance Engineering metodoloji/baseline; Media Runtime phase instrumentation ve FFmpeg sembolleri; GPU Platform GPU profiler; SRE production policy/incident; Security artifact redaction sahibidir. Test organizasyonu profiler unit parser testleri, container permission contract'ı, overhead benchmark'ı, secret canary redaction testi ve bilinen sentetik CPU/I/O/GPU bottleneck entegrasyon senaryolarını kapsar.

---

## 63. GPU Memory Optimization

### Mekanizma, invariantlar ve gerekçe

GPU memory yönetimi, işe başlamadan tahmin edilen ve runtime'da ölçülen bir `GpuMemoryEnvelope` sözleşmesine dayanır. Envelope; decoder surfaces, filter graph frame pool, compositor/intermediate surfaces, encoder lookahead/reference frames, model/workspace, upload/download staging, driver/runtime overhead ve fragmentation headroom toplamıdır.

Yaklaşık rezervasyon hesabı:

```text
surface_bytes = aligned_width * aligned_height * bytes_per_pixel(pixel_format)
pipeline_bytes = surface_bytes * (decode_surfaces + filter_inflight + compose_layers + encode_surfaces)
reserved_vram = pipeline_bytes + workspace_bytes + staging_bytes + driver_baseline + fragmentation_headroom
admit if reserved_vram <= allocatable_vram - node_safety_margin
```

- GPU worker, reservation alınmadan device allocation veya FFmpeg process başlatamaz.
- Scheduler'ın `allocatable_vram` değeri fiziksel toplam değil; driver baseline, sistem DaemonSet'leri, MIG partition ve güvenlik payı düşülmüş değerdir.
- Tüm frame/intermediate queue'ları bounded'dır. Producer, consumer'dan hızlıysa backpressure uygular; frame biriktirerek VRAM büyütmez.
- Aynı pixel format/device üzerindeki decode-filter-encode yolunda zero-copy hardware frame context korunur. CPU'ya download yalnız plan açıkça gerektiriyorsa yapılır.
- Pool allocation'ları shape/pixel format/device/capability ile key'lenir, kullanım sonrası temizlenir ve tenant verisi yeni işe görünmez.
- Peak VRAM tahmini admission'da kullanılır; ortalama VRAM ile concurrency açılmaz. Runtime hard watermark yeni frame admission'ını durdurur.
- OOM sonrasında aynı kaynak profiliyle kör retry yapılmaz. Retry, checkpoint + düşürülmüş inflight/tile/concurrency veya farklı capability/CPU fallback kararı taşır.
- Bitstream ve frame sonuç doğruluğu, memory optimizasyonundan bağımsızdır; tile/chunk sınırları timestamp, GOP, audio continuity ve filter halo kurallarını korur.

Neden: 4K/8K 10-bit frame, çok katmanlı compose ve encoder lookahead birkaç yüz yüzey oluşturabilir. GPU utilization düşük görünürken VRAM tükenebilir; bir işin plansız peak'i node'daki diğer tenant işlerini de OOM'a sürükler. Explicit reservation ve bounded surfaces failure domain'i iş seviyesine indirir.

Alternatifler ve tradeoff'lar:

- Bir GPU başına tek iş en güçlü izolasyondur fakat küçük 720p işleri için utilization düşüktür. VRAM reservation + encoder session limiti kontrollü bin-packing sağlar.
- MIG güçlü memory/compute izolasyonu sağlar; tüm GPU/codec modellerinde mevcut değildir ve video encoder engine paylaşımı GPU modeline göre değişir.
- CUDA MPS compute paylaşımını iyileştirebilir; NVENC/NVDEC ve tenant fault isolation semantiğini tek başına çözmez.
- Unified memory programlamayı kolaylaştırır ancak page migration ve beklenmeyen latency üretir; deterministic video path'te explicit device/host buffer tercih edilir.
- Full-frame pipeline basittir; 8K veya ağır modelde tile/chunk zorunlu olabilir. Tiling halo, seam ve temporal filter state karmaşıklığı getirir.
- Büyük kalıcı pool allocation overhead'ini azaltır; fragmentation ve idle VRAM tutma riski nedeniyle pool üst sınırı ve idle trim gerekir.

### Veri akışı ve internal API/schema örneği

1. Planner input probe, resolution, bit depth, pixel format, filter graph, layer count, encoder preset/lookahead ve model sürümünden peak envelope hesaplar.
2. Admission service capability queue seçmeden önce tenant GPU kotası, encoder session ve node sınıfı sınırını kontrol eder.
3. Scheduler `gpu_model`, `mig_profile`, `driver`, `codec`, `vram_class` label'lı node'a pod/activity yönlendirir.
4. Worker local arbiter'dan atomic reservation alır ve tahmin/gerçek kullanım telemetry'sini başlatır.
5. Decoder surface pool'a yazar; bounded graph queue'ları surface reference geçirir; encoder tamamlayınca reference count pool'a döner.
6. Soft watermark'ta producer concurrency azaltılır ve pool trim edilir; hard watermark/OOM'da process kesilir, son geçerli checkpoint doğrulanır.
7. Retry policy envelope'i `memory_profile=constrained` ile yeniden planlar veya daha büyük VRAM/MIG/CPU capability queue'suna taşır.

```python
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class GpuMemoryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    device_class: str
    pixel_format: str
    peak_bytes: int = Field(gt=0)
    decode_surfaces: int = Field(ge=2, le=64)
    filter_inflight: int = Field(ge=1, le=32)
    encode_surfaces: int = Field(ge=2, le=64)
    workspace_bytes: int = Field(ge=0)
    headroom_percent: int = Field(ge=10, le=40)
    strategy: Literal["full-frame", "tiled", "chunked", "cpu-fallback"]
    estimate_model_version: str

class GpuReservation(BaseModel):
    reservation_id: str
    attempt_id: str
    device_uuid: str
    bytes_reserved: int
    encoder_sessions: int
    expires_at_monotonic_ms: int
```

Local reservation socket/API yalnız aynı node workload identity'lerine açıktır: `Reserve(envelope, attempt_id)`, `Heartbeat(reservation_id, actual_peak)`, `Release(reservation_id)`. PostgreSQL attempt kaydına model version, estimated/actual peak ve OOM sınıfı yazılır; hızlı reservation Redis'e konmaz, node-local arbiter crash durumunda device process tablosundan reconcile eder.

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
platform/admission/{gpu_envelope,gpu_quota,capability_router}.py
workers/ffmpeg_gpu/{device_context,surface_pool,reservation}.py
workers/ffmpeg_gpu/strategies/{zero_copy,tiled,chunked,fallback}.py
workers/probes/{nvml,dcgm,encoder_sessions}.py
orchestration/recovery/gpu_oom.py
benchmarks/scenarios/gpu_memory/
tests/integration/gpu_memory/
```

Pipeline compiler, her graph edge için memory domain (`host`, `cuda`, `vaapi`), surface format, ownership ve maksimum inflight sayısı üretir. `hwupload`/`hwdownload` node'ları plan içinde görünürdür ve maliyetlendirilir. Tiled filter'lar spatial halo; temporal filter'lar önceki/sonraki frame context'i tanımlar. Encode checkpoint'leri bağımsız segment/GOP sınırlarında alınır.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant P as Render Planner
    participant A as Admission
    participant S as GPU Scheduler
    participant R as Node VRAM Arbiter
    participant W as GPU Worker
    participant F as FFmpeg/libav
    P->>A: plan + peak envelope
    A->>S: capability/vram class request
    S->>R: choose node with allocatable VRAM
    W->>R: atomic reserve(attempt, bytes)
    R-->>W: reservation lease
    W->>F: bounded zero-copy graph
    F-->>W: progress + actual VRAM
    W->>R: heartbeat(actual peak)
    alt OOM or hard watermark
        W->>F: terminate safely
        W->>R: release/reconcile
        W-->>A: retry with constrained envelope
    else completed
        W->>R: release
    end
```

### Mermaid class

```mermaid
classDiagram
    class GpuMemoryEnvelope {+long peakBytes +int headroomPercent +string strategy +string modelVersion}
    class GpuReservation {+string id +string deviceUuid +long bytesReserved +datetime leaseExpiry}
    class SurfacePool {+string pixelFormat +string shape +int capacity +trim()}
    class FrameSurface {+long bytes +int refCount +string memoryDomain}
    class WatermarkPolicy {+long softBytes +long hardBytes +applyBackpressure()}
    class OomRecoveryPlan {+string checkpointId +int reducedInflight +string fallbackCapability}
    GpuMemoryEnvelope --> GpuReservation
    GpuReservation --> SurfacePool
    SurfacePool "1" o-- "1..*" FrameSurface
    WatermarkPolicy --> SurfacePool
    GpuReservation --> OomRecoveryPlan: on failure
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Estimated
    Estimated --> Rejected: envelope exceeds all classes
    Estimated --> Reserved: node capacity available
    Reserved --> Allocating: worker starts
    Allocating --> Running: pools initialized
    Running --> Throttled: soft watermark
    Throttled --> Running: pressure reduced
    Running --> Checkpointing: hard watermark predicted
    Throttled --> OOM: allocation failed
    Checkpointing --> RetryingConstrained: resources released
    OOM --> RetryingConstrained: checkpoint valid
    OOM --> Failed: no checkpoint/fallback
    RetryingConstrained --> Reserved: new envelope/node
    Running --> Released: completed/cancelled
    Released --> [*]
```

### Production sorunları, recovery ve performans optimizasyonları

- Estimate drift, yeni FFmpeg/driver sürümünde artarsa actual/estimated oranı capability ve plan feature'larına göre alarm üretir; model düzeltilene kadar safety margin otomatik policy ile yükseltilir.
- Fragmentation nedeniyle free byte yeterli görünürken allocation başarısız olabilir. Uzun yaşayan context/pool trim edilir, iş concurrency'si düşürülür; worker process recycle drain ile yapılır.
- Leaked surface, refcount ve pool outstanding metric'iyle tespit edilir. Attempt sonu tüm reservation/surface'lerin sıfırlanması invariant testi başarısızsa worker quarantine edilir.
- GPU reset/Xid, tek job OOM'undan ayrılır. Device health agent node'u cordon/taint eder, tüm affected attempt'ler checkpoint'ten başka node'da retry edilir.
- Encoder session limiti VRAM'den bağımsız admission boyutudur; reservation hem byte hem session token alır.
- Zero-copy optimizasyonu için aynı hardware frame context'i paylaşılır, gereksiz renk uzayı ve bit-depth dönüşümleri kaldırılır. Bounded pipeline decode/filter/encode overlap sağlar ancak queue derinliği ölçülmeden büyütülmez.
- Tiled processing, filter halo kadar overlap ve deterministic crop ile seam'i önler. Temporal denoise/interpolation gibi global state isteyen filter'lar destek matrisi yoksa tile edilmez; daha büyük GPU veya CPU path seçilir.

Recovery sırası: allocation durdur, process'i bounded grace ile sonlandır, device context ve IPC handle'ları serbest bırak, node sağlık sınıfını kontrol et, son checksum doğrulanmış segment checkpoint'ini seç, envelope'i yeni observed peak ile büyüt veya constrained stratejiye indir, yeni attempt id ile retry et. Partial output publish edilmez; aynı deterministic object key'e yalnız verify sonrası atomic manifest pointer güncellenir.

### Benchmark yöntemi, metrikler, eşikler, gerçek dünya, ölçek ve ownership

Yöntem: çözünürlük (`720p`-`8K`), 8/10/12-bit, chroma formatı, layer sayısı, codec/preset/lookahead, full/tile/chunk ve concurrency matrisi; NVML/DCGM high-water mark ile process allocator değerleri karşılaştırılır. Soak test fragmentation ve pool reuse için en az 8 saat sürer.

Metrikler ve eşikler: estimate/actual peak oranı p99 `>= 1,10` ve `< 1,35`; steady-state allocatable VRAM kullanımı `< %85`, geçici peak `< %90`; safety reserve `>= max(2 GiB, %10)` capability policy'sine göre; beklenmeyen GPU OOM `0/10.000 job`; reservation leak `0`; constrained retry success `> %95`; zero-copy path host-device transfer byte'ını baseline'a göre en az `%50` azaltmalı ve kalite testini geçmelidir; throughput optimizasyonu VRAM/job'ı `%10` artırıyorsa açık kapasite onayı ister.

Gerçek dünya: iki 4K 10-bit HEVC işi aynı 24 GiB GPU'ya yerleştirilir; ikisinin encode lookahead peak'i aynı anda oluşur. Ortalama bazlı scheduler OOM üretirken peak reservation ikinci işi bekletir. Birinci tamamlandığında lease serbest kalır ve ikinci başlar; tenant fairness korunur.

Ölçeklenme: queue'lar `codec + gpu_arch + vram_class + driver_generation + strategy` capability anahtarlarıyla sınırlı sayıda tutulur. Fragmentasyonu önlemek için small-job bin packing ve large-job reserved pool ayrılır. Çok büyük işler tile/chunk ile yatay parçalansa da final mux ve temporal boundary koordinasyonu workflow tarafından bounded fan-out/fan-in ile yapılır.

Ownership: GPU Platform driver/device plugin/MIG ve health; Media Runtime surface graph, pool ve FFmpeg hardware context; Capacity Engineering envelope modeli; Workflow ekibi checkpoint retry; SRE alarm/runbook sahibidir. Testler allocator unit/property testleri, reservation race, forced CUDA OOM, GPU reset chaos, cross-tenant zeroization, long soak leak ve golden seam/timestamp doğrulamasını kapsar.

---

## 64. RAM Optimization

### Mekanizma, invariantlar ve gerekçe

RAM yönetimi pod cgroup limiti, işe özgü `MemoryEnvelope`, bounded queue ve streaming I/O üzerine kuruludur. Python heap, FFmpeg/libav native heap, decoded frame/audio buffers, multipart network buffers, page cache, subprocess overhead ve safety margin ayrı tahmin edilir.

```text
frame_bytes = stride_bytes * aligned_height
audio_bytes = channels * bytes_per_sample * samples_per_chunk
working_set = process_baseline + frame_bytes * max_inflight_frames
            + audio_bytes * max_inflight_audio_chunks
            + network_buffers + filter_workspace + page_cache_budget
pod_limit >= working_set + fragmentation_headroom + recovery_margin
```

- Input/output nesnesi RAM'e bütünüyle alınmaz; S3 range/multipart streaming ve bounded chunks kullanılır.
- Queue capacity byte bazlıdır; yalnız item sayısı kullanmak değişken 8K frame ile bellek taşmasına izin vermez.
- Pydantic request/RenderPlan içinde base64 medya, dev timeline blob'u veya ffprobe raw output kopyaları taşınmaz; S3 pointer/digest kullanılır.
- Worker pod'un toplam limitinin tamamı işlere dağıtılmaz. Runtime, telemetry, TLS, allocator fragmentation ve graceful checkpoint için rezerv bırakılır.
- Backpressure zinciri sink'ten source'a yayılır. Upload yavaşsa encoder output queue sınırsız büyümez; encoder/read cadence sınırlandırılır veya local bounded spill kullanılır.
- Shared pool buffer'ı tenant geçişinde sıfırlanır; reference ownership açık ve use-after-free/double-return engellenir.
- OOMKilled attempt terminal media failure sayılmaz. Checkpoint varsa daha düşük queue/chunk veya daha büyük memory class ile sınırlı retry edilir.
- Memory optimization output frame/audio/timestamp semantiğini değiştiremez; chunk sınırları filter state ve resampler delay'ini taşır.

Neden: decoded 8K RGBA tek frame yüzlerce MB olabilir; birkaç queue ve Python/native kopya pod limitini hızla aşar. Kernel OOM killer process'e cleanup fırsatı vermediğinden yalnız exception yakalamak yeterli değildir. Admission ve bounded working set, OOM'u oluşmadan önlemelidir.

Alternatifler ve tradeoff'lar:

- Yüksek pod memory limiti operasyonu kolaylaştırır fakat bin-packing'i bozar ve leak'i gizler. Ölçülmüş envelope sınıfları tercih edilir.
- Local disk spill RAM'i azaltır; disk kapasitesi, encryption, cleanup ve I/O latency maliyeti getirir. Yalnız rewind/intermediate zorunluysa kullanılır.
- `mmap` kopyayı azaltabilir fakat page cache yine cgroup memory'ye sayılır ve random access I/O fault üretir; resident memory olarak ölçülür.
- Genel amaçlı object pool allocation maliyetini düşürür; farklı shape ve ömürlerde fragmentation/retention yaratır. Pool'lar boyut sınıflı ve bounded olmalıdır.
- Forked worker process izolasyon ve tam heap reclaim sağlar; startup ve model warm-up maliyeti vardır. Uzun yaşayan supervisor + iş başına subprocess, native leak failure domain'ini sınırlar.
- Çok küçük chunks peak RAM'i azaltır ancak syscall, S3 part ve codec overhead'ini artırır; ölçülmüş optimum kullanılır.

### Veri akışı ve internal API/schema örneği

1. Planner probe ve graph'tan frame/audio/network çalışma setini tahmin eder; memory class (`small`, `medium`, `large`, `xlarge`) seçer.
2. Admission tenant concurrency ve cluster allocatable RAM'i kontrol eder; Temporal capability queue memory class içerir.
3. Worker cgroup limitini okur, envelope ile uyuşmazsa başlamadan `resource_mismatch` döndürür.
4. S3 reader bounded chunk pool'a okur; demux/decode/filter/encode stage'leri byte-weighted semaphore üzerinden buffer devreder.
5. Upload multipart sink tüketim hızını yayınlar; backpressure upstream inflight sınırını düşürür.
6. Worker RSS/PSS, cgroup `memory.current`, `memory.events`, major fault, allocator ve queue byte değerlerini izler.
7. Soft watermark'ta cache/pool trim, chunk küçültme ve prefetch kapatma; hard watermark'ta checkpoint + kontrollü process sonlandırma uygulanır.

```python
from pydantic import BaseModel, ConfigDict, Field

class MemoryEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    class_name: str
    pod_limit_bytes: int = Field(gt=0)
    process_baseline_bytes: int = Field(ge=0)
    max_frame_queue_bytes: int = Field(gt=0)
    max_audio_queue_bytes: int = Field(gt=0)
    max_network_buffer_bytes: int = Field(gt=0)
    max_spill_bytes: int = Field(ge=0)
    soft_watermark_percent: int = Field(default=75, ge=50, le=85)
    hard_watermark_percent: int = Field(default=90, ge=80, le=95)
    estimate_model_version: str
```

Checkpoint schema'sı process belleğini serialize etmez; yeniden üretilebilir sınırı tanımlar:

```json
{
  "checkpoint_version": 3,
  "job_id": "job_01J2...",
  "plan_digest": "sha256:...",
  "completed_segment": 17,
  "next_input_pts": 1843200,
  "audio_sample_cursor": 882000,
  "filter_state_asset_id": "ast_01J2...",
  "output_parts": [{"part": 17, "sha256": "...", "size_bytes": 42881920}]
}
```

### Dosya/klasör organizasyonu ve render pipeline bağı

```text
platform/admission/{memory_envelope,memory_classes}.py
workers/common/memory/{byte_semaphore,buffer_pool,watermarks}.py
workers/common/io/{s3_stream,multipart_sink,spill_manager}.py
workers/common/checkpoints/{manifest,segment_boundary}.py
workers/probes/{cgroup_memory,allocator_stats}.py
orchestration/recovery/oom.py
tests/integration/memory/
```

Pipeline graph edge'leri `max_inflight_bytes`, buffer ownership ve spill policy taşır. Decode frame pool'u, audio chunk pool'u ve mux output chunk'ı bağımsız bütçelenir. Timeline compositor yalnız görünür/halo gereken tile ve frame'leri açar; tüm asset'leri preload etmez. Segment checkpoint, encoder flush ve audio sample cursor tutarlılığı sağlandıktan sonra durable olur.

### Mermaid sequence

```mermaid
sequenceDiagram
    participant P as Planner
    participant A as Admission
    participant W as Worker
    participant R as S3 Reader
    participant F as FFmpeg/libav Graph
    participant U as Multipart Upload
    participant C as Checkpoint Store
    P->>A: working-set envelope
    A->>W: route to memory-class queue
    W->>W: verify cgroup + reserve headroom
    R->>F: bounded input chunks
    F->>U: bounded encoded parts
    U-->>F: sink pressure/credits
    F-->>R: upstream backpressure
    alt hard watermark
        W->>C: durable segment checkpoint
        W->>F: graceful stop
        W-->>A: retry with constrained envelope
    else complete
        U-->>W: checksum + multipart complete
    end
```

### Mermaid class

```mermaid
classDiagram
    class MemoryEnvelope {+long podLimit +long queueBudget +int softWatermark +int hardWatermark}
    class ByteSemaphore {+long capacity +long inUse +acquire(bytes) +release(bytes)}
    class BufferPool {+string sizeClass +int maxBuffers +trim() +zeroize()}
    class MediaBuffer {+long size +string owner +int references}
    class SpillManager {+long maxBytes +string encryptedPath +cleanup()}
    class MemoryCheckpoint {+long nextPts +long audioCursor +string[] partHashes}
    MemoryEnvelope --> ByteSemaphore
    ByteSemaphore --> BufferPool
    BufferPool "1" o-- "0..*" MediaBuffer
    MemoryEnvelope --> SpillManager
    SpillManager --> MemoryCheckpoint
```

### Mermaid state

```mermaid
stateDiagram-v2
    [*] --> Estimated
    Estimated --> Admitted: class capacity available
    Estimated --> Rejected: exceeds maximum class
    Admitted --> Running
    Running --> Backpressured: queue byte limit
    Backpressured --> Running: sink catches up
    Running --> Trimming: soft watermark
    Trimming --> Running: memory released
    Trimming --> Checkpointing: hard watermark
    Checkpointing --> RetryingConstrained: checkpoint durable
    Running --> OOMKilled: unexpected peak/leak
    OOMKilled --> RetryingConstrained: checkpoint exists
    OOMKilled --> Failed: retry exhausted/no safe checkpoint
    RetryingConstrained --> Admitted
    Running --> Released: completed/cancelled
    Released --> [*]
```

### Production sorunları, recovery ve performans optimizasyonları

- Python RSS düşmüyorsa bunun live object, allocator arena veya page cache olduğu heap/PSS/cgroup değerleriyle ayrılır. Kör `gc.collect()` hot loop'a eklenmez; object lifetime ve native ownership düzeltilir.
- Native FFmpeg filter leak'i joblar arasında birikiyorsa worker subprocess her iş/iş grubu sonunda recycle edilir; supervisor Ready kalırken yeni iş alımı drain edilir.
- Slow S3 upload queue şişmesi byte semaphore ile engellenir; bölgesel storage sorunu circuit breaker/admission'ı düşürür, RAM limitini artırmaz.
- `emptyDir` spill dolarsa input okumaları durur, tamamlanmış checkpoint upload edilir ve retry başka node/storage class'a taşınır. Partial spill lifecycle cleanup ve pod UID ownership ile silinir.
- OOMKilled sonrası Kubernetes exit `137`, cgroup `oom_kill` counter ve son watermark telemetry'si birleştirilir. Aynı plan için ilk retry queue/chunk'u küçültür, ikinci retry daha büyük class'a gider; bounded deneme sonrası terminal resource error döner.
- Kopyaları azaltmak için `memoryview`/zero-copy pipe, pooled aligned buffer, streaming JSON parser yerine küçük pointer payload ve FFmpeg pipe/socket buffer tuning uygulanabilir. Her zero-copy değişikliği ownership ve lifetime sanitizer testinden geçer.
- NUMA node ile CPU/memory locality yüksek throughput worker'da pinlenir; remote memory artışı profille kanıtlanmadan affinity uygulanmaz.

Recovery'de job state, kernel process memory'sine dayanmaz. Son durable segment ve filter-state checkpoint'i doğrulanır; tamamlanmamış multipart upload abort edilir; yeni attempt deterministic segment numarasından devam eder. Stateful filter checkpoint desteklemiyorsa son güvenli GOP/segment başından yeniden render edilir ve eski parçalar content hash ile deduplicate edilir.

### Benchmark yöntemi, metrikler, eşikler, gerçek dünya, ölçek ve ownership

Yöntem: 720p-8K, layer/filter sayısı, VFR, yüksek kanal audio, uzun duration, yavaş S3 sink, memory pressure ve 24 saat soak corpus'u. `memory.current`, `memory.peak`, RSS/PSS, page cache, major faults, allocation rate, GC pause, queue bytes, spill bytes ve throughput birlikte ölçülür.

Eşikler: observed peak / pod limit p99 `< %85` normal profile, hard watermark'e ulaşan normal job `< %0,1`; tahmin actual peak'i en az `%10` headroom ile kapsamalı ve overestimate p95 `< %35`; beklenmeyen OOMKill `0/10.000 job`; iş sonrası retained memory artışı 1.000 iterasyonda `< %2`; backpressure altında queue byte hard limit aşımı `0`; streaming input için object boyutuyla RSS korelasyon eğimi yaklaşık `0`; constrained retry başarı `> %95`.

Gerçek dünya: iki saatlik ProRes input önce geçici `bytes` nesnesine indirilip sonra FFmpeg'e verildiğinde pod 12 GiB'da OOM olur. Range streaming ve 16 MiB bounded chunks ile peak RSS duration'dan bağımsız hale gelir; network sink yavaşladığında reader credit bekler.

Ölçeklenme: memory class'ları scheduler request/limit ve queue capability ile eşleşir. Küçük işler aynı node'da bin-pack edilir; xlarge işler taint/toleration ile ayrılır. Admission, `sum(reserved_working_set) <= node_allocatable - daemon_and_safety` invariantını uygular; overcommit yalnız ölçülmüş düşük korelasyonlu phase'lerde kontrollü ve kill-cost aware olabilir.

Ownership: Media Runtime buffer lifecycle/streaming; Capacity Engineering envelope modeli ve class sizing; Kubernetes Platform cgroup/NUMA/eviction; Storage Platform multipart/spill; Workflow ekibi checkpoint; SRE OOM runbook sahibidir. Testler byte semaphore property/race, buffer zeroization, forced slow sink, cgroup pressure, OOM chaos, checkpoint resume, long soak leak ve golden chunk-boundary audio/video testlerini içerir.

---

## 65. Benchmark

### Mekanizma, invariantlar ve gerekçe

Benchmark sistemi, render motorunun kalite, hız ve kaynak tüketimini tekrarlanabilir biçimde ölçen kontrollü deney altyapısıdır. Her benchmark çalışması sabit bir environment fingerprint (image digest, driver, FFmpeg/libav/build revision, model/font hashes) ile ilişkilidir; böylece sonuçlar zaman içinde karşılaştırılabilir.

Invariant'lar:

- Benchmark sonucu yalnızca environment fingerprint ile birlikte anlamlıdır. Fingerprint olmadan sonuç geçersizdir.
- Benchmark çalışması production workload'una etki etmez; ayrı worker pool veya time-window kullanılır.
- Warm-up frame'leri ölçüm havuzuna dahil edilmez.
- En az 3 warm-up ve 10 ölçüm; p50/p95/p99, peak RSS/VRAM, CPU/GPU seconds, output fps ve cache hit oranı kaydedilir.
- Golden corpus lisanslı, privacy onaylı ve content hash ile sabittir.
- Lossless veya intra-only referans profile ile kalite ölçümü yapılır; codec kaynaklı fark benchmark amacı dışında tutulur.
- Regresyon eşiği: p95 latency/RTF'de `%10` kötüleşme merge'i bloklar; `%5-10` arası owner waiver gerektirir.

Neden: Performans ölçümleri environment'a bağlıdır; fingerprint olmazsa regresyon tespiti imkansızdır. Golden corpus olmadan kalite karşılaştırması subjektif kalır.

### Alternatifler ve tradeoff'lar

- **Manuel benchmark (ffmpeg -benchmark):** Basit, tek seferlik. Otomasyon ve historical tracking yok. Opsiyonel quick-check olarak kalabilir.
- **Benchmark.framework (pytest-benchmark):** Python-native, CI entegrasyonu kolay. Ancak media workload için custom harness gerekir.
- **Custom benchmark harness:** Tam kontrol, domain-specific metric. Bakım maliyeti yüksek. Seçilen yol: framework + custom extension.

### Veri akışı

1. CI/CD veya scheduled trigger benchmark suite'i başlatır.
2. Harness environment fingerprint'i hesaplar (image digest, binary versions, hardware identifiers).
3. Golden corpus S3'ten indirilir (cold/warm cache senaryosu ayrı).
4. Workload'lar parametrize edilir: resolution, codec, duration, filter count, parallelism level.
5. Her workload warm-up çalıştırır (sonuçlar atılır).
6. Ölçüm çalıştırılır; FFmpeg `-progress pipe:1` ile frame/fps/speed, cgroup ile memory/CPU, nvidia-smi ile GPU metrics toplanır.
7. Sonuçlar environment fingerprint ile birlikte PostgreSQL'e yazılır.
8. Regression kontrolü: önceki benchmark run ile p95 karşılaştırması.
9. CI'da regresyon varsa pipeline block edilir.

### API / Interface / Model

```python
class BenchmarkConfig(BaseModel):
    env_fingerprint: str  # SHA-256 of environment
    corpus_id: str
    workloads: List[WorkloadSpec]
    warmup_runs: int = 3
    measure_runs: int = 10
    regression_threshold_pct: float = 10.0

class WorkloadSpec(BaseModel):
    name: str
    resolution: str  # "1080p", "4K"
    codec: str  # "h264", "h265", "vp9"
    duration_sec: float
    filter_count: int
    parallelism: int

class BenchmarkResult(BaseModel):
    run_id: str
    env_fingerprint: str
    workload: WorkloadSpec
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    realtime_factor: float
    peak_rss_bytes: int
    peak_vram_bytes: Optional[int]
    cpu_seconds: float
    gpu_seconds: Optional[float]
    output_fps: float
    cache_hit_ratio: float
    quality_psnr: Optional[float]
    quality_ssim: Optional[float]
    timestamp: datetime

class RegressionReport(BaseModel):
    baseline_run_id: str
    current_run_id: str
    regressions: List[RegressionItem]
    improvements: List[RegressionItem]
    verdict: Literal["pass", "warning", "fail"]
```

### Dosya / klasör organizasyonu ve render pipeline bağı

```
tests/benchmark/
    harness.py              # BenchmarkRunner
    workloads/              # Parametrized workload specs
    golden_corpus/          # Content hash → S3 mapping
    reports/                # Historical results
    regression.py           # Regression detector
deploy/benchmark/
    cronjob.yaml            # Scheduled benchmark
    config/                 # Corpus, workload definitions
```

Benchmark sonuçları release pipeline'ın bir gate'idir. Yeni FFmpeg/model/font güncellemesi benchmark'tan geçmeden production'a alınmaz.

### Sequence diyagramı

```mermaid
sequenceDiagram
    participant CI as CI/CD
    participant BH as BenchmarkHarness
    participant W as Worker
    participant F as FFmpeg
    participant S3 as S3 Corpus
    participant DB as PostgreSQL
    CI->>BH: trigger_benchmark(config)
    BH->>BH: compute_env_fingerprint()
    BH->>S3: download_golden_corpus(corpus_id)
    S3-->>BH: corpus files
    loop workload
        BH->>W: run_workload(warmup=true)
        W->>F: ffmpeg -benchmark
        F-->>W: progress + metrics
        BH->>W: run_workload(measure=true)
        W->>F: ffmpeg -benchmark
        F-->>W: frame/fps/speed/memory
        BH->>BH: aggregate_stats()
    end
    BH->>DB: save_results(benchmark_result)
    BH->>BH: check_regression(baseline)
    BH->>CI: verdict(pass/warning/fail)
```

### Class diyagramı

```mermaid
classDiagram
    class BenchmarkHarness {
        +run_suite(config) List~BenchmarkResult~
        +check_regression(baseline, current) RegressionReport
    }
    class EnvironmentFingerprint {
        +compute() str
        +image_digest: str
        +ffmpeg_revision: str
        +driver_version: str
    }
    class GoldenCorpus {
        +download(corpus_id) Path
        +verify_hash(files) bool
    }
    class WorkloadRunner {
        +run(workload, warmup) MetricSet
    }
    class RegressionDetector {
        +compare(baseline, current) RegressionReport
    }
    BenchmarkHarness --> EnvironmentFingerprint
    BenchmarkHarness --> GoldenCorpus
    BenchmarkHarness --> WorkloadRunner
    BenchmarkHarness --> RegressionDetector
```

### State diyagramı

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Preparing: trigger received
    Preparing --> CorpusReady: corpus downloaded
    CorpusReady --> WarmingUp: workload started
    WarmingUp --> Measuring: warmup done
    Measuring --> Aggregating: measurements done
    Aggregating --> Reporting: stats computed
    Reporting --> Pass: no regression
    Reporting --> Warning: within threshold
    Reporting --> Fail: regression detected
    Pass --> Idle
    Warning --> Idle
    Fail --> Blocked: CI gate blocked
```

### Production sorunları ve recovery

- Benchmark worker crash: Temporal retry ile yeniden çalıştırılır; warm-up tekrarlanır.
- Golden corpus corrupted: hash mismatch; S3'ten yeniden indirilir.
- Non-deterministic sonuçlar: environment drift, thermal throttling, noisy neighbor; benchmark cluster izole ve dedicated.
- GPU VRAM measurement yanlışlığı: nvidia-smi sampling rate ayarı; cross-validation.
- Benchmark süre aşımı: workload timeout, Partial result kaydedilir.

### Performans optimizasyonları

Benchmark harness'ı kendisi production'a equivalent performans gerektirmez fakat sonuçların güvenilirliği için determinism kritiktir. Cold cache ve warm cache benchmark'ları ayrı run olarak çalıştırılır. CI'da benchmark paralel çalıştırılabilir fakat her run ayrı resource group'a sahip olmalıdır.

### Gerçek dünya uygulaması

FFmpeg 7.1'e yükseltme sonrası benchmark: p95 latency %8 artmış, quality metric'ler değişmemiş. Investigasyon: yeni libx264 preset davranışı. Fix: encoder config ayarı. Benchmark regression'ı CI'da yakaladı ve merge'i engelledi.

### Ölçeklenebilirlik

Benchmark workload'ları horizontal scale edilebilir; her workload bağımsız worker'da çalışır. Historical results PostgreSQL'de partition edilir; long-term trend analysis için time-series DB entegrasyonu. Multi-region benchmark identical corpus ile karşılaştırma sağlar.

### Ownership ve test

**Ownership:** Release Engineering (harness/CI), Media Runtime (metric definitions), ML Platform (model benchmarks), GPU Platform (hardware fingerprint). **Testler:** harness self-test (fingerprint determinism, metric collection), regression detector (true positive/negative), corpus integrity, concurrent benchmark isolation, metric accuracy vs manual measurement.

---

## 66. Testing

### Mekanizma, invariantlar ve gerekçe

Test stratejisi çok katmanlıdır: unit → contract → integration → golden → property → fuzz → chaos → load. Her katman farklı riski hedefler. Render motoru için testler yalnız "code works" değil, "output is deterministic, quality is acceptable, and failure is recoverable" doğrular.

Invariant'lar:

- Her PR unit + contract + integration testlerini geçmek zorundadır.
- Golden testler her release'de çalıştırılır; golden corpus update owner approval gerektirir.
- Property testler invariant ihlalini rastgele girdilerle tespit eder.
- Fuzz testler malformed input ve edge case'leri hedefler.
- Chaos testler infrastructure failure (pod kill, network partition, disk full) senaryolarını simüle eder.
- Testler production code path'ini kullanır; mock yalnız external boundary'dedir (S3, YouTube API, TikTok API).
- Her test environment fingerprint raporlar.
- Test coverage metric'i release gate değildir; risk-based coverage hedeflenir.

### Alternatifler ve tradeoff'lar

- **Golden-only testing:** Kalite garantisi güçlü fakat regression detection zayıf. Property/fuzz ile desteklenir.
- **Full mock testing:** Hızlı fakat integration bug'larını kaçırır. External boundary'de sınırlı kullanılır.
- **Manual QA:** Yaratıcı edge case tespit eder fakat tekrarlanabilirliği düşük. Automation-first, manual validation limited.

### Test tipleri ve kapsamı

**Unit tests:** Her modül için bağımsız. Time normalization, color math, coordinate transform, audio gain staging, Bezier evaluation, keyframe interpolation. Mock yalnız native subprocess (FFmpeg) için.

**Contract tests:** API endpoint, Pydantic schema, database migration, FFmpeg CLI contract, plugin ABI, cache key format. Her contract değişikliğinde çalıştırılır.

**Integration tests:** End-to-end pipeline (ClipSpec → RenderPlan → FFmpeg → output). Real FFmpeg subprocess, real database (test container), mock S3 (localstack veya minio).

**Golden tests:** Referans output ile karşılaştırma. Frame-level pixel tolerance (SSIM > 0.999 lossless, > 0.995 lossy). Audio sample-level comparison. SRT/ASS subtitle byte-level comparison. Thumbnail exact PTS extraction.

**Property tests:** Hypothesis ile random ClipSpec generated. Invariant'lar: timeline duration == output duration (±1 frame), rational time roundtrip, all tracks rendered, no orphan frames. Fuzz corpus'u regression suite'e eklenir.

**Fuzz tests:** Malformed JSON, extreme values (duration = 0, duration = MAX), missing required fields, circular references, oversized assets, binary-in-text. AFL/libFuzzer edge case detection.

**Chaos tests:** Pod kill during render, network partition during upload, disk full during encode, Redis failure during cache, PostgreSQL failover during job creation. Temporal recovery correctness doğrulanır.

**Load tests:** Concurrent 100/500/1000 render job submission. Queue backpressure, worker saturation, database connection pool. Latency degradation curve.

### API / Interface / Model

```python
class TestSuiteConfig(BaseModel):
    environment_fingerprint: str
    suites: List[str]  # ["unit", "contract", "integration", "golden", "property", "fuzz", "chaos"]
    golden_corpus_version: str
    fuzz_duration_sec: int = 300
    chaos_scenarios: List[str]
    load_concurrency: int = 100

class TestResult(BaseModel):
    suite: str
    passed: int
    failed: int
    skipped: int
    duration_sec: float
    env_fingerprint: str
    coverage_percent: Optional[float]
    failures: List[TestFailure]

class GoldenTestResult(BaseModel):
    test_name: str
    reference_hash: str
    output_hash: str
    ssim: Optional[float]
    psnr: Optional[float]
    audio_lufs_diff: Optional[float]
    passed: bool
    tolerance_exceeded_by: Optional[float]
```

### Dosya / klasör organizasyonu ve render pipeline bağı

```
tests/
    unit/                   # Unit tests per module
    contract/               # API, schema, CLI contracts
    integration/            # Pipeline integration
    golden/                 # Golden reference comparison
    property/               # Hypothesis property tests
    fuzz/                   # Fuzz corpus and harness
    chaos/                  # Chaos test scenarios
    load/                   # Load test scripts
    fixtures/               # Test data, mock assets
    conftest.py             # Shared fixtures
tests/benchmark/            # Separate benchmark (§65)
deploy/test/
    ci-pipeline.yaml        # GitHub Actions / GitLab CI
    test-containers/        # PostgreSQL, Redis, MinIO
    gpu-test-runner/        # NVIDIA GPU CI runner
```

### Sequence diyagramı

```mermaid
sequenceDiagram
    participant CI as CI Pipeline
    participant TU as Test Unit Runner
    participant IR as Integration Runner
    participant GR as Golden Runner
    participant PR as Property Runner
    participant CH as Chaos Runner
    participant DB as Test DB
    participant S3 as Test S3
    CI->>TU: run_unit_tests()
    TU-->>CI: pass/fail
    CI->>IR: run_integration_tests()
    IR->>DB: setup test database
    IR->>S3: upload test assets
    IR->>IR: run_full_pipeline()
    IR-->>CI: pass/fail
    CI->>GR: run_golden_tests()
    GR->>S3: load golden corpus
    GR->>GR: render_and_compare()
    GR-->>CI: ssim/psnr results
    CI->>PR: run_property_tests()
    PR->>PR: hypothesis generate/render
    PR-->>CI: invariant violations
    CI->>CH: run_chaos_tests()
    CH->>CH: inject_failures()
    CH-->>CI: recovery verification
```

### Class diyagramı

```mermaid
classDiagram
    class TestOrchestrator {
        +run_suite(config) List~TestResult~
        +generate_report() TestReport
    }
    class GoldenComparator {
        +compare(reference, output) GoldenTestResult
        +compute_ssim(ref, out) float
        +compute_psnr(ref, out) float
    }
    class PropertyValidator {
        +validate_invariants(spec, output) bool
        +generate_random_spec() ClipSpec
    }
    class ChaosInjector {
        +inject(scenario) ChaosResult
        +verify_recovery() bool
    }
    class FuzzHarness {
        +run(corpus, duration) List~FuzzResult~
    }
    TestOrchestrator --> GoldenComparator
    TestOrchestrator --> PropertyValidator
    TestOrchestrator --> ChaosInjector
    TestOrchestrator --> FuzzHarness
```

### State diyagramı

```mermaid
stateDiagram-v2
    [*] --> UnitTests
    UnitTests --> ContractTests: unit pass
    UnitTests --> Failed: unit fail
    ContractTests --> IntegrationTests: contract pass
    ContractTests --> Failed: contract fail
    IntegrationTests --> GoldenTests: integration pass
    IntegrationTests --> Failed: integration fail
    GoldenTests --> PropertyTests: golden pass
    GoldenTests --> Failed: golden fail
    PropertyTests --> FuzzTests: property pass
    PropertyTests --> Failed: property fail
    FuzzTests --> ChaosTests: fuzz pass
    FuzzTests --> Failed: fuzz fail
    ChaosTests --> LoadTests: chaos pass
    ChaosTests --> Failed: chaos fail
    LoadTests --> Passed: load pass
    LoadTests --> Failed: load fail
    Failed --> Blocked: CI blocked
```

### Production sorunları ve recovery

- Test DB/Redis cleanup: her test sonrası transaction rollback veya container recreate.
- Golden corpus drift: hash-based versioning; update require owner approval + semantic diff review.
- GPU test non-determinism:同一 input tolerance ile karşılaştırma; RTF thresholdları relaxed.
- Chaos test produção etkisi: izole namespace, ayrı cluster veya time-window.
- Flaky test: retry policy, quarantine, root cause investigation.
- Fuzz crash: crash reproducer kaydedilir; fuzzing durdurulur ve fix önceliklendirilir.

### Performans optimizasyonları

Unit testler paralel çalıştırılır (pytest-xdist). Integration testleri test container ile parallelize edilir. Golden testler lazy corpus loading ile memory-efficient. Property testler max example ile sınırlandırılır. Chaos testler time-budget ile çalışır.

### Gerçek dünya uygulaması

FFmpeg upgrade sonrası golden test: SSIM 0.9998 → 0.9995. Tolerance 0.999 altında fail. Investigation: encoder internal dithering değişikliği. Tolerance update approved.

### Ölçeklenebilirlik

Test parallelism CI runner sayısı ile orantılı. GPU testleri ayrı runner pool'a sahip. Test results historical PostgreSQL'de tutulur; trend analysis ve flaky test detection.

### Ownership ve test

**Ownership:** Quality Engineering (test framework), Media Runtime (golden corpus), Security (fuzz/chaos), Platform (integration containers). **Testlerin testi:** Test harness self-test, golden comparator accuracy, property invariant soundness, chaos scenario coverage, fuzz corpus effectiveness.

---

## 67. CI/CD

### Mekanizma, invariantlar ve gerekçe

CI/CD pipeline'ı, kod değişikliklerinden production deploy'a kadar tüm süreci otomatikleştiren kontrollü teslimat hattıdır. Her commit test, build, scan, sign, publish ve deploy adımlarından geçer.

Invariant'lar:

- Production'a yalnız signed ve scanlenmiş image yayınlanır.
- Image digest immutable'dır; aynı digest ile her deploy tekrarlanabilir.
- Build reproducibility: aynı source + aynı build input = aynı binary (deterministic build).
- CVE vulnerability scanning critical ise build block edilir; high için waiver süreci vardır.
- Artifact signing key Vault/KMS'te saklanır; CI runner'da plaintext bulunmaz.
- Canary deploy %1 trafik ile başlar; SLO burn-rate alarm yoksa kademeli artırılır.
- Rollback tek komutla yapılabilir; database migration backward-compatible olmalıdır.
- Branch protection: main branch'e doğrudan push yasak; PR + review + CI pass zorunlu.
- Secret'lar CI environment'ta inject edilir; repo veya log'da plaintext saklanmaz.

### Alternatifler ve tradeoff'lar

- **GitHub Actions:** Kolay setup, marketplace actions. Self-hosted runner gerektirir (GPU). Opsiyon: Kubernetes runner.
- **GitLab CI:** Built-in container registry, self-hosted runners. Daha ağır setup.
- **ArgoCD + GitHub Actions:** GitOps deployment. ArgoCD progressive delivery (canary/rolling). Kubernetes native.
- **Tek CD tool (Spinnaker/Flux):** Ek bağımlılık, öğrenme eğrisi. Gerek yok: ArgoCD yeterli.

Tradeoff: GitHub Actions + ArgoCD kombinasyonu build/test'i CI'da, deploy'u GitOps ile yönetir. Self-hosted GPU runner maliyetli fakat gerekli.

### Pipeline stages

```
1. Lint & Type Check (ruff, mypy)
2. Unit Tests (pytest parallel)
3. Contract Tests (API, schema, CLI)
4. Build Docker Image (multi-stage, GPU variants)
5. SBOM Generation (syft)
6. CVE Scan (grype/trivy) → block on critical
7. Container Test (capability smoke, codec parity)
8. Artifact Signing (cosign, key in Vault)
9. Push to Registry (GCR/ECR, digest-labeled)
10. Integration Tests (test containers)
11. Golden Tests (if golden corpus changed)
12. Benchmark (if codec/filter/runtime changed)
13. Canary Deploy (ArgoCD, %1 traffic)
14. SLO Verification (30 min observation)
15. Progressive Rollout (10% → 50% → 100%)
16. Post-deploy Smoke Tests
```

### API / Interface / Model

```python
class PipelineConfig(BaseModel):
    trigger: Literal["push", "pr", "scheduled", "manual"]
    branch: str
    commit_sha: str
    stages: List[PipelineStage]
    gpu_required: bool = False
    golden_test_required: bool = False
    benchmark_required: bool = False

class PipelineStage(BaseModel):
    name: str
    status: Literal["pending", "running", "passed", "failed", "skipped", "blocked"]
    duration_sec: Optional[float]
    artifacts: List[str]
    logs_url: str

class DeployManifest(BaseModel):
    image_digest: str
    environment: str  # "staging", "production"
    canary_percent: int
    rollback_digest: Optional[str]
    slo_burn_rate: Optional[float]
```

### Dosya / klasör organizasyonu ve render pipeline bağı

```
.github/workflows/
    ci.yaml                 # Main CI pipeline
    benchmark.yaml          # Scheduled benchmark
    deploy.yaml             # Deploy pipeline
    chaos-test.yaml         # Weekly chaos tests
deploy/
    argocd/
        application.yaml    # ArgoCD app definition
        rollout.yaml        # Canary config
    k8s/
        base/               # Base manifests
        overlays/           # Per-environment
tests/ci/
    container-test/         # Image smoke tests
    capability-test/        # FFmpeg/GPU capability
    deploy-test/            # Post-deploy smoke
scripts/
    sign-image.sh           # Cosign signing
    rollback.sh             # Emergency rollback
    sbom-generate.sh        # SBOM creation
```

### Sequence diyagramı

```mermaid
sequenceDiagram
    participant DEV as Developer
    participant GH as GitHub
    participant CI as CI Pipeline
    participant REG as Container Registry
    participant AR as ArgoCD
    participant K8 as Kubernetes
    participant MON as Monitoring
    DEV->>GH: PR + commit
    GH->>CI: trigger pipeline
    CI->>CI: lint + type check
    CI->>CI: unit + contract tests
    CI->>CI: build + scan + sign
    CI->>REG: push image (digest-labeled)
    CI->>CI: integration + golden tests
    CI->>GH: PR status check
    DEV->>GH: merge after approval
    GH->>CI: trigger deploy pipeline
    CI->>REG: verify image signature
    CI->>AR: update manifest (canary %1)
    AR->>K8: rollout canary
    MON->>MON: observe SLO (30 min)
    alt SLO healthy
        AR->>K8: progressive rollout 10→50→100
    else SLO degraded
        AR->>K8: rollback to previous digest
    end
    MON->>GH: deploy status
```

### Class diyagramı

```mermaid
classDiagram
    class CIPipeline {
        +run(config) PipelineResult
        +block_on_critical(finding) bool
    }
    class ImageBuilder {
        +build(dockerfile, context) ImageDigest
        +scan(image) ScanReport
        +sign(image, key) SignedImage
    }
    class DeployController {
        +canary(deploy_manifest)
        +progressive_rollout()
        +rollback(digest)
    }
    class SLOVerifier {
        +observe(window_sec) SLOReport
        +should_progress() bool
        +should_rollback() bool
    }
    CIPipeline --> ImageBuilder
    DeployController --> SLOVerifier
```

### State diyagramı

```mermaid
stateDiagram-v2
    [*] --> Linting
    Linting --> Testing: lint pass
    Linting --> Failed: lint fail
    Testing --> Building: tests pass
    Testing --> Failed: tests fail
    Building --> Scanning: image built
    Scanning --> Signed: no critical CVE
    Scanning --> Blocked: critical CVE
    Signed --> Integrating: pushed to registry
    Integrating --> GoldenTesting: integration pass
    GoldenTesting --> Benchmarking: golden pass / skipped
    Benchmarking --> Deploying: benchmark pass / skipped
    Deploying --> Canary: %1 traffic
    Canary --> Progressive: SLO healthy 30 min
    Canary --> RolledBack: SLO degraded
    Progressive --> Deployed: 100% traffic
    RolledBack --> [*]
    Deployed --> [*]
    Failed --> [*]
```

### Production sorunları ve recovery

- GPU runner unavailable: CPU-only tests çalışır; GPU-dependent tests skip edilir; alert tetiklenir.
- Registry outage: image push retry; fallback olarak manuel image pull + deploy.
- ArgoCD sync failure: manual kubectl rollout;事后 ArgoCD reconciliation.
- Canary SLO alarm: automatic rollback; incident ticket açılır.
- SBOM generation failure: build block; SBOM tool upgrade.
- Signing key rotation: dual-key transition; old key retain for in-flight deploys.
- Database migration backward-incompatibility: expand/contract pattern; old version tolerance window.

### Performans optimizasyonları

Build cache (BuildKit layer cache) ile incremental build. Test parallelism (pytest-xdist). Image scan parallel. Canary observation window minimum 30 dk fakat SLO-based adaptive. Post-deploy smoke tests quick (< 2 dk).

### Gerçek dünya uygulaması

FFmpeg 7.1 upgrade: PR opened → CI green → merge → canary %1 deploy → 30 dk SLO observation → no regression → progressive 10% → 50% → 100% → deployed. Total: ~45 dakika.

### Ölçeklenebilirlik

Multi-region deploy: her region ayrı ArgoCD application. Image replication cross-region. Feature flags ile gradual feature rollout. Multi-tenant deploy: per-tenant canary. Disaster recovery: cross-region failover with DNS.

### Ownership ve test

**Ownership:** Developer Platform (CI/CD pipeline), Security (signing, CVE), Media Runtime (golden tests), SRE (deploy, rollback, monitoring). **Testler:** pipeline self-test, container smoke test, signing verification, rollback drill, SBOM accuracy, canary behavior, multi-region sync.

---

## 68. Production Deployment

### Mekanizma, invariantlar ve gerekçe

Production deployment, Kubernetes cluster'ına kademeli ve kontrollü biçimde yeni versiyon yayımlama sürecidir. Deployment strategy rolling update + canary ile yapılır. Her deployment backward-compatible, rollback mümkün ve SLO-correlated olmalıdır.

Invariant'lar:

- Deployment yalnızca signed image ile yapılır; unsigned image deploy edilemez.
- Database migration backward-compatible (expand/contract pattern); eski ve yeni version aynı anda çalışabilir.
- PodDisruptionBudget (PDB) minimum availability'yi korur.
- Resource requests/limits job planından gelir; limitsiz pod deploy edilemez.
- Canary %1 ile başlar; SLO burn-rate alarm yoksa kademeli (10→50→100%).
- Rollback tek komutla yapılabilir; database migration rollback separately managed.
- Secret rotation deployment sırasında graceful; old secret retain window.
- Health checks (liveness, readiness, startup) zorunlu.
- Graceful shutdown: in-flight jobs drain edilir; SIGTERM → drain → SIGKILL timeout.

### Alternatifler ve tradeoff'lar

- **Rolling update:** Kubernetes native, basit. Canary kontrolü sınırlı.
- **ArgoCD Rollout:** Canary, blue-green, A/B destekler. Progressive delivery.
- **Spinnaker:** Multi-cloud, advanced strategies. Ek bağımlılık, heavyweight.
- **Helm/Kustomize + manual:** Basit, scriptable. Automation eksik.

Seçilen: ArgoCD Rollout ile Kubernetes-native progressive delivery.

### Cluster topolojisi

```
production-cluster/
  control-plane/          # API server, etcd, scheduler
  node-pools/
    general/              # FastAPI API pods, stateless
    cpu-render/           # FFmpeg CPU workers
    nvidia-render/        # NVIDIA GPU workers (T4/A10G)
    vaapi-render/         # Intel/AMD VAAPI workers
    windows-render/       # Windows D3D11VA workers (ayrı cluster)
    temporal/             # Temporal workers
    monitoring/           # Prometheus, Loki, collectors
  storage/
    nvme-local/           # Scratch per-node
    shared-filesystem/    # Optional NFS/EFS for shared scratch
  networking/
    service-mesh/         # Optional: Istio/Linkerd
    network-policy/       # Pod-to-pod restrictions
    egress-gateway/       # Controlled external access
```

### API / Interface / Model

```python
class DeploymentManifest(BaseModel):
    image_digest: str
    version: str
    environment: str
    canary_percent: int = 1
    rollback_to_digest: Optional[str]
    migration_mode: Literal["expand", "contract", "none"]
    resource_requests: Dict[str, str]
    resource_limits: Dict[str, str]
    node_pool: str
    pdb_min_available: int

class DeploymentStatus(BaseModel):
    deployment_id: str
    version: str
    phase: Literal["pending", "migrating", "canary", "progressing", "deployed", "rolled_back"]
    canary_percent: int
    slo_burn_rate: Optional[float]
    pods_ready: int
    pods_total: int
    started_at: datetime
    completed_at: Optional[datetime]
```

### Dosya / klasör organizasyonu ve render pipeline bağı

```
deploy/
    argocd/
        application.yaml
        rollout-strategy.yaml
    k8s/
        base/
            api-deployment.yaml
            worker-deployment.yaml
            hpa.yaml
            pdb.yaml
            network-policy.yaml
            service-account.yaml
        overlays/
            staging/
            production/
            canary/
    helm/
        chart.yaml
        values.yaml
        values-production.yaml
    migration/
        alembic/            # Database migrations
        expand-contract.md  # Migration guide
scripts/
    deploy.sh               # Deploy automation
    rollback.sh             # Emergency rollback
    health-check.sh         # Post-deploy verification
    drain.sh                # Graceful shutdown
```

### Sequence diyagramı

```mermaid
sequenceDiagram
    participant REL as Release Manager
    participant AR as ArgoCD
    participant K8 as Kubernetes
    participant PG as PostgreSQL
    participant MON as Monitoring
    participant SRE as SRE On-Call
    REL->>AR: update_manifest(digest, canary=1%)
    AR->>K8: rollout canary pods
    K8->>K8: liveness/readiness checks
    MON->>MON: observe SLO (30 min)
    alt SLO healthy
        REL->>AR: increase canary (1→10%)
        MON->>MON: observe SLO (15 min)
        REL->>AR: increase canary (10→50%)
        MON->>MON: observe SLO (15 min)
        REL->>AR: full rollout (100%)
    else SLO degraded
        SRE->>AR: rollback(previous_digest)
        AR->>K8: restore previous version
    end
    Note over PG: expand migration (old+new compatible)
    REL->>PG: run expand migration
    REL->>AR: mark deployed
    Note over PG: contract migration (after drain)
```

### State diyagramı

```mermaid
stateDiagram-v2
    [*] --> Pending: release triggered
    Pending --> MigratingExpand: migration needed
    MigratingExpand --> Canary: expand complete
    Pending --> Canary: no migration
    Canary --> Progressive: SLO healthy
    Canary --> RollingBack: SLO degraded
    Progressive --> Progressive: canary increased
    Progressive --> Deployed: 100% + stable
    Deployed --> ContractingExpand: expand cleanup
    ContractingExpand --> Done: contract complete
    RollingBack --> Done: previous version restored
    Done --> [*]
```

### Production sorunları ve recovery

- Pod crash loop: liveness probe restart; escalation alert.
- Resource exhaustion: HPA scaled up; capacity planning review.
- Database connection pool exhaustion: connection pool tuning; read replica offload.
- Graceful shutdown timeout: SIGKILL after drain window; job checkpoint ile recovery.
- Secret rotation during deployment: dual-secret window; old secret retained.
- Network policy blocking new pods: policy audit; pre-deploy validation.
- Node pool capacity insufficient: cluster autoscaler; pre-provisioning for large deploys.
- Cross-region DNS failover: health check TTL; manual override option.

### Performans optimizasyonları

Node pre-provisioning: canary öncesi yeni node pool hazırlanır. Image pre-pull: DaemonSet ile yeni image tüm node'lara indirilir. Startup probe optimization: FFmpeg binary warm cache. Readiness gate: traffic yalnızca ready pod'lara yönlendirilir.

### Gerçek dünya uygulaması

Yeni versiyon deployment: expand migration (3 dk) → canary %1 (30 dk SLO) → %10 (15 dk) → %50 (15 dk) → %100. Toplam: ~65 dakika. Rollback: tek komut, ~3 dk (previous pods ready).

### Ölçeklenebilirlik

Multi-cluster: active-active veya active-passive. Cluster autoscaler ile dynamic node provisioning. Regional deployment: her region bağımsız canary cycle. Feature flags: gradual feature activation independent of deploy.

### Ownership ve test

**Ownership:** SRE (deployment orchestration, rollback), Platform Engineering (cluster, node pools), Media Runtime (worker config), Security (secret rotation, network policy). **Testler:** deploy drill (quarterly), rollback drill (monthly), PDB verification, resource limit enforcement, health check validation, graceful shutdown verification, migration backward-compatibility test.

---

## 69. Error Recovery

### Mekanizma, invariantlar ve gerekçe

Hata kurtarma sistemi, render motorunun her katmanında meydana gelen hataları sınıflandıran, izole eden ve kurtaran kontrollü mekanizmadır. Her hata sınıfı için tanımlı bir recovery politikası vardır; retry-blind değil, hata-sınıfına-bağlı retry uygulanır.

Invariant'lar:

- Her hata bir `ErrorClass`'e atanır: `transient`, `resource`, `input`, `policy`, `determinism`.
- `transient` hatalar exponential backoff ile retry edilir; deadline sınırlıdır.
- `resource` hatalar farklı worker/node/storage class ile retry edilebilir.
- `input` hataları retry edilmez; kullanıcıya alanlı hata mesajı döner.
- `policy` hataları retry edilmez; policy update veya manual intervention gerektirir.
- `determinism` hataları en yüksek şiddettir: cache quarantine, alert, incident.
- Dead letter queue (DLQ) terminal failure'ları tutar; periyodik audit ve cleanup yapılır.
- Compensation/saga pattern: dış dünyadaki etkiler (upload, publish) geri alınamıyorsa orphan resource GC yapılır.
- Checkpoint-based recovery: her render phase'inin checkpoint'i kalıcıdır; crash sonrası son checkpoint'ten devam edilir.
- Her hata detayı trace_id, job_id, attempt_id ile ilişkilidir.

### Alternatifler ve tradeoff'lar

- **Blind retry (max_retries=3):** Basit fakat pahalı hatalarda gereksiz tekrar, Determinism hatalarında tehlikeli. Kullanılmaz.
- **Circuit breaker:** External service hatalarında faydalı; fakat kendi internal hatalarını kapsamaz. API adapter'larında kullanılır.
- **Saga/compensation:** Multi-step operasyonlarda partial failure recovery. Render pipeline için checkpoint-based approach tercih edilir.
- **Dead letter queue:** Terminal hatalar için audit trail ve retry queue'dan ayrıştırma. Gerekli.

### Hata sınıflandırması tablosu

| Sınıf | Örnek | Retry | Compensation | Escalation |
|---|---|---|---|---|
| transient | S3 503, network timeout, pod eviction | exp backoff + jitter | Yok (idempotent) | Yok (otomatik) |
| resource | OOM, GPU OOM, disk full, connection pool exhausted | farklı worker/node/class | Checkpoint-based resume | Alert |
| input | Bozuk video, bilinmeyen codec, invalid ClipSpec | Yok | Yok | Kullanıcıya hata |
| policy | License revoke, TOS violation, quota exceeded | Yok | Delivery abort | Manual intervention |
| determinism | Cache fingerprint mismatch, same input different output | Yok | Cache quarantine | P0 incident |

### API / Interface / Model

```python
class ErrorClassification(BaseModel):
    error_class: Literal["transient", "resource", "input", "policy", "determinism"]
    error_code: str
    message: str
    retryable: bool
    requires_compensation: bool
    escalation_level: Literal["none", "alert", "page", "incident"]
    checkpoint_resumable: bool
    suggested_action: str

class RetryPolicy(BaseModel):
    max_attempts: int
    backoff_base_sec: float
    backoff_max_sec: float
    jitter: bool
    deadline_sec: float
    different_worker_required: bool

class CompensationAction(BaseModel):
    action_type: Literal["checkpoint_resume", "asset_cleanup", "delivery_abort", "cache_quarantine"]
    target: str
    details: Dict[str, Any]

class DeadLetterEntry(BaseModel):
    job_id: str
    error_classification: ErrorClassification
    attempts: int
    last_error: str
    created_at: datetime
    compensation_actions: List[CompensationAction]
    audit_metadata: Dict[str, Any]
```

### Dosya / klasör organizasyonu ve render pipeline bağı

```
video_engine/recovery/
    error_classifier.py     # Error classification
    retry_manager.py        # Per-class retry logic
    checkpoint_manager.py   # Phase checkpoint/restore
    compensation.py         # Saga/compensation actions
    dead_letter.py          # DLQ management
    alert_classifier.py     # Escalation routing
    runbook_index.py        # Runbook lookup
deploy/
    alerts/
        error-classification.yaml
        escalation-policies.yaml
    runbooks/
        transient-error.md
        resource-exhaustion.md
        determinism-incident.md
        input-validation.md
```

### Sequence diyagramı

```mermaid
sequenceDiagram
    participant W as Worker
    participant EC as ErrorClassifier
    participant RM as RetryManager
    participant CM as CheckpointManager
    participant DLQ as DeadLetterQueue
    participant ALT as AlertManager
    participant PG as PostgreSQL
    W->>EC: classify(error)
    EC-->>W: ErrorClassification
    alt transient
        W->>RM: schedule_retry(policy)
        RM-->>W: retry_token
        W->>W: wait + retry
    else resource
        W->>CM: save_checkpoint()
        CM->>PG: persist checkpoint
        W->>RM: schedule_retry(different_worker=true)
    else input
        W->>PG: update_job_status(failed, user_message)
    else policy
        W->>DLQ: enqueue(entry)
        W->>ALT: escalate(alert)
    else determinism
        W->>DLQ: enqueue(entry, severity=critical)
        W->>ALT: escalate(incident)
        W->>PG: quarantine_cache(fingerprint)
    end
```

### Class diyagramı

```mermaid
classDiagram
    class ErrorClassifier {
        +classify(error) ErrorClassification
    }
    class RetryManager {
        +should_retry(classification) bool
        +schedule_retry(policy) RetryToken
    }
    class CheckpointManager {
        +save_checkpoint(phase, state) CheckpointId
        +restore_checkpoint(id) PhaseState
    }
    class CompensationEngine {
        +execute(actions) CompensationResult
        +rollback_if_possible(actions) bool
    }
    class DeadLetterQueue {
        +enqueue(entry) void
        +audit_entries() List~DeadLetterEntry~
        +cleanup(retention_days) int
    }
    ErrorClassifier --> RetryManager
    ErrorClassifier --> CompensationEngine
    ErrorClassifier --> DeadLetterQueue
    CheckpointManager --> CompensationEngine
```

### State diyagramı

```mermaid
stateDiagram-v2
    [*] --> Running
    Running --> ErrorDetected: error occurs
    ErrorDetected --> RetryingTransient: transient
    ErrorDetected --> RetryingResource: resource
    ErrorDetected --> FailedInput: input
    ErrorDetected --> EscalatingPolicy: policy
    ErrorDetected --> EscalatingDeterminism: determinism
    RetryingTransient --> Running: retry success
    RetryingTransient --> FailedRetryExhausted: deadline exceeded
    RetryingResource --> Running: retry success (new worker)
    RetryingResource --> FailedRetryExhausted: exhausted
    FailedInput --> DeadLetter
    EscalatingPolicy --> DeadLetter
    EscalatingDeterminism --> IncidentCreated: P0
    DeadLetter --> [*]
    IncidentCreated --> [*]
    FailedRetryExhausted --> DeadLetter
```

### Production sorunları ve recovery

- Retry storm: exponential backoff + jitter ile engellenir; global rate limit.
- Checkpoint corruption: checksum doğrulama; corrupt ise son safe GOP başından yeniden render.
- Dead letter queue growth: retention policy (30 gün); periyodik audit ve cleanup.
- Escalation fatigue: alarm grouping, severity-based threshold tuning.
- Compensation partial failure: orphan resource GC; manual cleanup runbook.
- OOM during checkpoint save: micro-checkpoint (minimal state) ile kurtarma.
- Network partition recovery: Temporal activity timeout + heartbeat ile detection.

### Performans optimizasyonları

Checkpoint frequency tuning: çok sık overhead yaratır, çok seyrek data loss artırır. Optimal: her GOP sınırında veya 30 sn aralıkla. Error classification fast-path: known error codes için classification < 1 ms. DLQ async: error handling path'i render path'i bloklamaz.

### Gerçek dünya uygulaması

Render worker GPU OOM: error classified as `resource`. Checkpoint kaydedilir. Retry farklı worker'da (daha büyük GPU class). Başarılı. Dead letter'a düşen YouTube upload (TOS violation): audit, manual review, user notification.

### Ölçeklenebilirlik

Error classification service horizontal scale. DLQ partition by error_class ve tenant. Checkpoint store PostgreSQL partitioned by job. Alert routing multi-region; escalation per region's on-call.

### Ownership ve test

**Ownership:** Media Runtime (error classification, checkpoint), SRE (escalation, runbook), Security (determinism incidents), Platform (DLQ infrastructure). **Testler:** error injection (per class), retry behavior, checkpoint save/restore, dead letter lifecycle, compensation correctness, escalation routing, determinism quarantine drill, chaos-based end-to-end recovery.

---

## 70. Scalability

### Mekanizma, invariantlar ve gerekçe

Ölçeklenebilirlik, render motorunun talep artışını yatay resource expansion ile karşılayabilme kapasitesidir. Ölçekleme yalnız worker sayısı değil, queue routing, admission control, cache hit ratio ve storage tiering'i de kapsar.

Invariant'lar:

- Horizontal scaling stateless worker'larla yapılır; stateful bileşenler (PostgreSQL, Redis) için replication/cluster.
- Admission control: yeni job kabulü `sum(reserved_working_set) <= node_allocatable - safety_margin` invariantını korur.
- Backpressure: queue byte limit, tenant quota ve global capacity signal ile yukarı doğru yayılır.
- Hot tenant isolation: tek bir yoğun tenant diğerlerini etkilemez; separate queue veya dedicated worker pool.
- Cache hit ratio scaling ile orantılı artmalıdır; cache miss oranı太高 ise capacity plan wrong.
- Storage tiering: hot (NVMe) → warm (S3 Standard) → cold (S3 Glacier) lifecycle.
- Auto-scaling: HPA (CPU/memory), KEDA (queue depth), cluster autoscaler (node).
- Capacity forecasting: historical workload pattern ile gelecek kapasite ihtiyacı tahmini.

### Alternatifler ve tradeoff'lar

- **Vertical scaling (daha büyük makine):** Basit fakat ceiling var; single point of failure. GPU worker için bounding box.
- **Horizontal scaling (daha fazla makine):** Stateless worker ile kolay; orchestration overhead. Seçilen yol.
- **Serverless (Lambda/Cloud Run):** Cold start sorunları, GPU desteksiz, timeout limits. Media processing için uygun değil.
- **Hybrid (cloud burst):** On-prem base + cloud peak. Cost/complexity tradeoff. Large event için faydalı.

### Kapasite denklemleri

```
worker_count = ceil(peak_concurrent_jobs * avg_rt_factor * target_sla / worker_capacity)

worker_capacity = min(
    cpu_throughput * cpu_cores,
    gpu_throughput * gpu_count,
    network_throughput * nic_bandwidth,
    storage_iops * disk_bandwidth
)

cache_hit_ratio > 0.8 threshold: capacity plan doğru
cache_hit_ratio < 0.6 threshold: capacity veya cache strategy yanlış
```

### Scale sinyalleri

| Sinyal | Metrik | Eşik | Aksiyon |
|---|---|---|---|
| CPU utilization | node CPU avg | > %70 | Scale out worker |
| Memory pressure | cgroup P95 | > %80 | Scale up class |
| Queue depth | job queue length | > 2x worker | Add workers |
| GPU utilization | GPU compute % | > %85 | Add GPU workers |
| Cache miss rate | L1+L2 miss ratio | > %40 | Review cache strategy |
| S3 egress | bytes/day per tenant | > budget | Throttle/defer |
| NIC saturation | network util | > %80 | Scale egress capacity |
| DB connection pool | active/total | > %80 | Add replicas |
| Latency P95 | render duration | > SLO | Capacity review |

### API / Interface / Model

```python
class CapacityPlan(BaseModel):
    region: str
    node_pools: List[NodePoolConfig]
    total_cpu_workers: int
    total_gpu_workers: int
    storage_tier_distribution: Dict[str, float]
    cache_hit_target: float
    monthly_cost_estimate: float

class ScalingPolicy(BaseModel):
    metric: str
    scale_up_threshold: float
    scale_down_threshold: float
    min_replicas: int
    max_replicas: int
    cooldown_sec: int
    scaling_factor: float  # 1.5 = 50% increase

class TenantQuota(BaseModel):
    tenant_id: str
    max_concurrent_jobs: int
    max_daily_jobs: int
    max_egress_bytes: int
    priority_class: Literal["standard", "high", "critical"]
    dedicated_worker_pool: Optional[str]

class AdmissionDecision(BaseModel):
    accepted: bool
    reason: Optional[str]
    estimated_wait_sec: Optional[float]
    suggested_queue: str
```

### Dosya / klasör organizasyonu ve render pipeline bağı

```
platform/scaling/
    capacity_planner.py     # Capacity forecasting
    admission_controller.py # Job admission
    auto_scaler.py          # HPA/KEDA integration
    backpressure.py         # Queue-based backpressure
    tenant_isolation.py     # Hot tenant management
    storage_tier.py         # NVMe/S3/Glacier lifecycle
    cost_tracker.py         # Per-tenant cost tracking
deploy/
    autoscaling/
        hpa.yaml            # CPU/memory HPA
        keda.yaml           # Queue depth scaler
        cluster-autoscaler.yaml
    capacity/
        node-pool-config.yaml
        tenant-quotas.yaml
        storage-tier-policy.yaml
tests/scaling/
    test_admission.py
    test_backpressure.py
    test_tenant_isolation.py
```

### Sequence diyagramı

```mermaid
sequenceDiagram
    participant API as API
    participant AC as AdmissionController
    participant Q as Task Queue
    participant SC as Scaler
    participant K8 as Kubernetes
    participant S3 as S3 Storage
    participant MON as Monitoring
    API->>AC: submit_job(job_spec)
    AC->>AC: check_capacity()
    AC->>AC: check_tenant_quota()
    alt capacity available
        AC->>Q: enqueue(job)
        AC-->>API: accepted
    else capacity insufficient
        AC->>SC: request_scale_out()
        SC->>K8: hpa_scale()
        AC-->>API: queued (wait est.)
    end
    Q->>Q: dispatch to worker
    MON->>SC: scale_signal(metric)
    SC->>K8: adjust_replicas()
    MON->>S3: tier_migration(aging_artifacts)
```

### Class diyagramı

```mermaid
classDiagram
    class AdmissionController {
        +check_capacity() bool
        +check_tenant_quota(tenant_id) bool
        +admit(job_spec) AdmissionDecision
    }
    class CapacityPlanner {
        +forecast(workload_pattern) CapacityPlan
        +current_utilization() UtilizationReport
    }
    class AutoScaler {
        +scale_up(pool, factor)
        +scale_down(pool, factor)
        +get_replica_count() int
    }
    class BackpressureManager {
        +check_pressure() PressureLevel
        +apply_throttle(action)
    }
    class TenantIsolation {
        +assign_queue(tenant_id) str
        +isolate_hot_tenant(tenant_id)
    }
    class StorageTierManager {
        +migrate_aging_artifacts()
        +get_tier_distribution() Dict
    }
    AdmissionController --> CapacityPlanner
    AdmissionController --> TenantIsolation
    AutoScaler --> BackpressureManager
    StorageTierManager --> AutoScaler
```

### State diyagramı

```mermaid
stateDiagram-v2
    [*] --> Normal: baseline capacity
    Normal --> ScalingUp: load increasing
    ScalingUp --> Normal: capacity adequate
    ScalingUp --> Saturated: scaling limit reached
    Saturated --> Backpressured: queue growing
    Backpressured --> Throttled: tenant quota exceeded
    Throttled --> Normal: load decreasing
    Saturated --> Degraded: SLO at risk
    Degraded --> EmergencyScaling: auto-scale burst
    EmergencyScaling --> Normal: burst capacity ready
    Normal --> ScalingDown: load decreasing
    ScalingDown --> Normal: right-sized
```

### Production sorunları ve recovery

- Scale-out storm: rapid scaling → cost spike; cooldown + max_replicas limit.
- Hot tenant: tek tenant tüm kuyruğu doldurur; admission throttle ve dedicated queue.
- Cache stampede: cold start'ta binlerce miss; cache warming strategy.
- Storage tiering latency: cold→warm migration gecikmesi; hot tier retention policy.
- Kubernetes HPA flapping: metric smoothing, stable window, cooldown tuning.
- Cluster autoscaler slow: node provisioning 3-5 dk; pre-provisioning for predicted peaks.
- Cross-region capacity imbalance: weighted DNS routing, regional quota.

### Performans optimizasyonları

HPA custom metrics (queue depth, GPU utilization) ile daha hassas scale. KEDA ScaledObject ile event-driven scaling. Predictive scaling: historical pattern ile peak öncesi scale. Bin-packing optimization: small jobs packed, large jobs isolated.

### Gerçek dünya uygulaması

Black Friday: 3x normal load. Predictive scaling 1 saat öncesinden node pool prepare. Admission controller tenant throttle uygular. Cache warming cold assets. Sonuç: SLO korundu, maliyet %40 arttı (budget içinde).

### Ölçeklenebilirlik

Multi-region: active-active with weighted routing. Cross-region cache: global L2 S3, regional L1 NVMe. Database: read replicas per region, write primary. Storage: lifecycle policies auto-tier. Cost: per-tenant billing, reserved capacity.

### Ownership ve test

**Ownership:** Capacity Engineering (planning, forecasting), Platform (autoscaling, HPA/KEDA), Media Runtime (admission, backpressure), Storage (tiering), FinOps (cost tracking). **Testler:** admission under load, backpressure behavior, tenant isolation, scaling accuracy, cost tracking accuracy, cold start performance, tier migration correctness, disaster recovery drill.
