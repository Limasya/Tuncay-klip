"""
Prometheus metrics (IP_PART6 Bölüm 36.2) + RED metodu middleware (34.3).

prometheus_client kuruluysa gerçek metrikler; değilse hiçbir şey yapmayan
no-op stub'lar kullanılır (PROMETHEUS_AVAILABLE=False). Böylece bağımlılık
opsiyonel kalır ama kuruluysa tam işlevsel olur.
"""
from __future__ import annotations

import time

try:
    from prometheus_client import (
        Counter,
        Histogram,
        Gauge,
        CONTENT_TYPE_LATEST,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except Exception:  # pragma: no cover - prometheus_client kurulu değilse
    PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"

    class _NoopMetric:
        """prometheus_client yoksa kullanılan zararsız yer tutucu."""

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def labels(self, *_args, **_kwargs) -> "_NoopMetric":
            return self

        def inc(self, *_args, **_kwargs) -> None:
            pass

        def dec(self, *_args, **_kwargs) -> None:
            pass

        def set(self, *_args, **_kwargs) -> None:
            pass

        def observe(self, *_args, **_kwargs) -> None:
            pass

    Counter = Histogram = Gauge = _NoopMetric  # type: ignore

    def generate_latest(*_args, **_kwargs) -> bytes:  # type: ignore
        return b""


# --- IP_PART6 36.2'deki metrik tanımları ------------------------------------
REQUESTS = Counter(
    "ip_requests_total",
    "Total requests",
    ["service", "method", "route", "status"],
)
LATENCY = Histogram(
    "ip_request_duration_seconds",
    "Request latency",
    ["service", "route"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
GPU_UTIL = Gauge("ip_gpu_utilization_ratio", "GPU utilization", ["gpu_id"])
KAFKA_LAG = Gauge("ip_kafka_consumer_lag", "Consumer lag", ["topic", "group"])
CLIP_JOBS = Counter("ip_clip_jobs_total", "Clip jobs", ["result"])  # ok|failed


def render_latest() -> tuple[bytes, str]:
    """/metrics endpoint için (payload, content_type) döndürür."""
    return generate_latest(), CONTENT_TYPE_LATEST


class PrometheusMiddleware:
    """
    ASGI middleware — her HTTP isteği için RED metrikleri toplar (34.3):
      R (Rate) + E (Errors): ip_requests_total{status}
      D (Duration):          ip_request_duration_seconds

    Route etiketi kardinalite patlamasını önlemek için template path kullanır
    (örn. /clips/{id}); mevcut değilse ham path'e düşer.
    """

    def __init__(self, app, service_name: str = "platform-api") -> None:
        self.app = app
        self.service_name = service_name

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        start = time.perf_counter()
        status_holder = {"code": 500}

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                status_holder["code"] = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = self._route_label(scope)
            elapsed = time.perf_counter() - start
            REQUESTS.labels(
                service=self.service_name,
                method=method,
                route=route,
                status=str(status_holder["code"]),
            ).inc()
            LATENCY.labels(service=self.service_name, route=route).observe(elapsed)

    @staticmethod
    def _route_label(scope) -> str:
        route = scope.get("route")
        if route is not None and getattr(route, "path", None):
            return route.path
        return scope.get("path", "unknown")


def set_gpu_utilization(gpu_id: str, ratio: float) -> None:
    GPU_UTIL.labels(gpu_id=gpu_id).set(ratio)


def set_kafka_lag(topic: str, group: str, lag: int) -> None:
    KAFKA_LAG.labels(topic=topic, group=group).set(lag)


def record_clip_job(success: bool) -> None:
    CLIP_JOBS.labels(result="ok" if success else "failed").inc()
