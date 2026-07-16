"""
platform_eng.observability testleri (IP_PART6 Bölüm 34-36).

Kapsam:
  - JsonFormatter: geçerli JSON + zorunlu alanlar + extra_fields
  - metrics: render_latest, yardımcı setter'lar, PrometheusMiddleware (ASGI)
  - graceful degradation bayrakları import edilebilir
"""
import json
import logging

import pytest

from platform_eng.observability import (
    JsonFormatter,
    configure_logging,
    render_latest,
    PrometheusMiddleware,
    PROMETHEUS_AVAILABLE,
    OTEL_AVAILABLE,
)
from platform_eng.observability.metrics import (
    set_gpu_utilization,
    set_kafka_lag,
    record_clip_job,
)


# ── logging ───────────────────────────────────────────────────────────
def _record(msg: str, **extra) -> logging.LogRecord:
    rec = logging.LogRecord("svc", logging.INFO, __file__, 1, msg, None, None)
    if extra:
        rec.extra_fields = extra
    return rec


def test_json_formatter_emits_valid_json():
    out = JsonFormatter().format(_record("hello"))
    parsed = json.loads(out)
    assert parsed["msg"] == "hello"
    assert parsed["level"] == "INFO"
    assert parsed["service"] == "svc"
    assert "ts" in parsed
    # OTel yoksa trace alanları None (graceful)
    assert "trace_id" in parsed


def test_json_formatter_includes_extra_fields():
    out = JsonFormatter().format(_record("with-extra", clip_id="abc", n=3))
    parsed = json.loads(out)
    assert parsed["clip_id"] == "abc"
    assert parsed["n"] == 3


def test_configure_logging_sets_handler():
    configure_logging("test-svc", level="DEBUG")
    root = logging.getLogger()
    assert len(root.handlers) == 1
    assert root.level == logging.DEBUG


# ── metrics ───────────────────────────────────────────────────────────
def test_render_latest_returns_bytes_and_content_type():
    payload, content_type = render_latest()
    assert isinstance(payload, (bytes, bytearray))
    assert "text/plain" in content_type


def test_metric_helpers_do_not_raise():
    # prometheus_client kurulu olsun ya da olmasın hata vermemeli
    set_gpu_utilization("gpu-0", 0.5)
    set_kafka_lag("clip.requested", "clip-generator", 42)
    record_clip_job(True)
    record_clip_job(False)


def test_availability_flags_are_bool():
    assert isinstance(PROMETHEUS_AVAILABLE, bool)
    assert isinstance(OTEL_AVAILABLE, bool)


# ── PrometheusMiddleware (ASGI) ───────────────────────────────────────
@pytest.mark.asyncio
async def test_prometheus_middleware_passes_through():
    seen = {}

    async def app(scope, receive, send):
        seen["type"] = scope["type"]
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = PrometheusMiddleware(app, service_name="test")
    sent = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "path": "/health"}
    await mw(scope, receive, send)

    assert seen["type"] == "http"
    assert sent[0]["status"] == 200


@pytest.mark.asyncio
async def test_prometheus_middleware_ignores_non_http():
    called = {"n": 0}

    async def app(scope, receive, send):
        called["n"] += 1

    mw = PrometheusMiddleware(app)
    await mw({"type": "lifespan"}, None, None)
    assert called["n"] == 1
