"""
Prometheus Metrics Middleware
────────────────────────────
Exposes /metrics endpoint for Prometheus scraping.
Tracks request count, latency, errors, and custom business metrics.
"""
from __future__ import annotations

import time
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


# ── Metric Counters ─────────────────────────────────────────────

class MetricsCollector:
    """In-memory metrics collector that exposes Prometheus-compatible text."""

    def __init__(self):
        self._counters: dict[str, float] = defaultdict(float)
        self._histograms: dict[str, list[float]] = defaultdict(list)
        self._gauges: dict[str, float] = {}
        self._labels: dict[str, dict[str, str]] = {}

    def inc(self, name: str, value: float = 1.0, labels: dict[str, str] | None = None):
        key = self._label_key(name, labels)
        self._counters[key] += value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None):
        key = self._label_key(name, labels)
        self._histograms[key].append(value)

    def gauge(self, name: str, value: float, labels: dict[str, str] | None = None):
        key = self._label_key(name, labels)
        self._gauges[key] = value

    def _label_key(self, name: str, labels: dict[str, str] | None) -> str:
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
            return f'{name}{{{label_str}}}'
        return name

    def render(self) -> str:
        """Render all metrics in Prometheus text exposition format."""
        lines = []

        for key, value in sorted(self._counters.items()):
            metric_name = key.split("{")[0]
            lines.append(f"# HELP {metric_name} Counter")
            lines.append(f"# TYPE {metric_name} counter")
            lines.append(f"{key} {value}")

        for key, values in sorted(self._histograms.items()):
            metric_name = key.split("{")[0]
            lines.append(f"# HELP {metric_name} Histogram")
            lines.append(f"# TYPE {metric_name} histogram")
            if values:
                p50 = sorted(values)[len(values) // 2]
                p99 = sorted(values)[int(len(values) * 0.99)]
                lines.append(f'{key}_sum {sum(values)}')
                lines.append(f'{key}_count {len(values)}')
                lines.append(f'{key}{{quantile="0.5"}} {p50}')
                lines.append(f'{key}{{quantile="0.99"}} {p99}')

        for key, value in sorted(self._gauges.items()):
            metric_name = key.split("{")[0]
            lines.append(f"# HELP {metric_name} Gauge")
            lines.append(f"# TYPE {metric_name} gauge")
            lines.append(f"{key} {value}")

        return "\n".join(lines) + "\n"


# ── Singleton ───────────────────────────────────────────────────

metrics = MetricsCollector()


# ── Middleware ───────────────────────────────────────────────────

class PrometheusMiddleware(BaseHTTPMiddleware):
    """Middleware that tracks HTTP request metrics."""

    SKIP_PATHS = {"/metrics", "/health", "/ready", "/docs", "/openapi.json"}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self.SKIP_PATHS:
            return await call_next(request)

        method = request.method
        start = time.time()

        try:
            response = await call_next(request)
            elapsed = time.time() - start
            status = str(response.status_code)

            metrics.inc("http_requests_total", labels={"method": method, "status": status})
            metrics.observe("http_request_duration_seconds", elapsed, labels={"method": method, "path": path})

            return response
        except Exception:
            metrics.inc("http_requests_total", labels={"method": method, "status": "500"})
            metrics.inc("http_request_errors_total", labels={"method": method})
            raise


# ── Setup ───────────────────────────────────────────────────────

def setup_metrics(app: FastAPI):
    """Attach metrics middleware and /metrics/internal endpoint."""
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics/internal", include_in_schema=False)
    async def prometheus_metrics_internal():
        return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")
