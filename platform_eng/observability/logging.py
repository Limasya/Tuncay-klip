"""
Yapılandırılmış JSON logging (IP_PART6 Bölüm 34.2).

Her log satırı ts/level/service/msg alanları taşır ve OpenTelemetry aktif ise
trace_id/span_id ekler — böylece loglar trace'lerle ilişkilendirilebilir (34.1).
OpenTelemetry kurulu değilse trace alanları None olur (graceful degradation).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


def _current_trace_context() -> tuple[str | None, str | None]:
    """Aktif span'in (trace_id, span_id) hex değerlerini döndürür; yoksa (None, None)."""
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        ctx = span.get_span_context() if span else None
        if ctx and getattr(ctx, "trace_id", 0):
            return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")
    except Exception:
        pass
    return None, None


class JsonFormatter(logging.Formatter):
    """Log kayıtlarını tek satırlık JSON'a çevirir."""

    def format(self, record: logging.LogRecord) -> str:
        trace_id, span_id = _current_trace_context()
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": record.name,
            "msg": record.getMessage(),
            "trace_id": trace_id,
            "span_id": span_id,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # yapılandırılmış ek alanlar: logger.info(..., extra={"extra_fields": {...}})
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(service_name: str, level: str = "INFO", json_format: bool = True) -> None:
    """
    Kök logger'ı yapılandırır.

    Args:
        service_name: logger.name olarak da kullanılabilecek servis adı (bilgi amaçlı).
        level: log seviyesi ("DEBUG", "INFO", ...).
        json_format: True ise JSON formatter, aksi halde düz metin.
    """
    handler = logging.StreamHandler(sys.stdout)
    if json_format:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    logging.getLogger(service_name).setLevel(level.upper())
