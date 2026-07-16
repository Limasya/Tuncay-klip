"""
OpenTelemetry distributed tracing (IP_PART6 Bölüm 35).

opentelemetry-sdk kuruluysa gerçek tracing; değilse no-op (OTEL_AVAILABLE=False).
Kafka context propagation (35.3) için inject/extract yardımcıları da sağlanır.
"""
from __future__ import annotations

import contextlib
from typing import Iterator, Optional

try:
    from opentelemetry import trace, context as otel_context
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
    from opentelemetry.propagate import inject, extract

    OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - opentelemetry kurulu değilse
    OTEL_AVAILABLE = False
    trace = None  # type: ignore
    otel_context = None  # type: ignore


_tracer = None


def init_tracing(
    service_name: str,
    otlp_endpoint: Optional[str] = None,
    sample_ratio: float = 0.1,
    environment: str = "production",
):
    """
    Tracer provider'ı kurar (IP_PART6 35.2). OTLP endpoint verilirse span'ler
    oraya BatchSpanProcessor ile aktarılır. OTel yoksa None döner.
    """
    global _tracer
    if not OTEL_AVAILABLE:
        return None

    resource = Resource.create({
        "service.name": service_name,
        "service.version": "3.0.0",
        "deployment.environment": environment,
    })
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBasedTraceIdRatio(sample_ratio),  # head sampling
    )

    if otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
            )
        except Exception:
            # exporter eklentisi yoksa yalnızca in-process provider kalır
            pass

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer(service_name)
    return _tracer


def get_tracer(service_name: str = "platform"):
    """Mevcut tracer'ı döndürür; init edilmemişse global provider'dan alır."""
    global _tracer
    if not OTEL_AVAILABLE:
        return None
    if _tracer is None:
        _tracer = trace.get_tracer(service_name)
    return _tracer


def instrument_fastapi(app, service_name: str = "platform-api") -> bool:
    """FastAPI otomatik enstrümantasyonunu etkinleştirir. Başarılıysa True."""
    if not OTEL_AVAILABLE:
        return False
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        return True
    except Exception:
        return False


@contextlib.contextmanager
def start_span(name: str, **attributes) -> Iterator[object]:
    """
    Manuel span context manager (IP_PART6 35.2). OTel yoksa hiçbir şey yapmaz.

    Kullanım:
        with start_span("clip.extract", clip_id=cid) as span:
            ...
    """
    tracer = get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:  # span'i hata olarak işaretle
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise


# --- Kafka / event bus context propagation (IP_PART6 35.3) ------------------
def inject_context() -> dict[str, str]:
    """Aktif trace context'i header sözlüğüne enjekte eder (producer tarafı)."""
    if not OTEL_AVAILABLE:
        return {}
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


@contextlib.contextmanager
def extracted_context(carrier: dict[str, str]) -> Iterator[None]:
    """Header sözlüğünden parent context'i geri yükler (consumer tarafı)."""
    if not OTEL_AVAILABLE or not carrier:
        yield
        return
    ctx = extract(carrier)
    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)
