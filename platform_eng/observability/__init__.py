"""platform_eng.observability — metrics, logs, traces (IP_PART6 34-36)."""
from platform_eng.observability.logging import JsonFormatter, configure_logging
from platform_eng.observability.metrics import (
    REQUESTS,
    LATENCY,
    GPU_UTIL,
    KAFKA_LAG,
    CLIP_JOBS,
    render_latest,
    PrometheusMiddleware,
    PROMETHEUS_AVAILABLE,
)
from platform_eng.observability.tracing import (
    init_tracing,
    get_tracer,
    instrument_fastapi,
    OTEL_AVAILABLE,
)

__all__ = [
    "JsonFormatter",
    "configure_logging",
    "REQUESTS",
    "LATENCY",
    "GPU_UTIL",
    "KAFKA_LAG",
    "CLIP_JOBS",
    "render_latest",
    "PrometheusMiddleware",
    "PROMETHEUS_AVAILABLE",
    "init_tracing",
    "get_tracer",
    "instrument_fastapi",
    "OTEL_AVAILABLE",
]
