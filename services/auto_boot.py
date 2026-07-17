"""
Auto-Boot Orchestrator
──────────────────────
Single entry point that boots the entire system:
  1. Auto-discovers available LLM providers
  2. Auto-downloads missing models (Ollama, ML)
  3. Auto-configures environment variables
  4. Starts health monitor with auto-restart
  5. Starts auto-backup scheduler
  6. Starts WebSocket broadcast wiring
  7. Reports full system status

Usage from main.py lifespan:
    from services.auto_boot import auto_boot
    status = await auto_boot()
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager

try:
    from platform_eng.observability import start_span as _otel_span
    _OTEL_AVAILABLE = True
except Exception:
    _OTEL_AVAILABLE = False


@contextmanager
def _maybe_span(name: str, **attributes):
    if _OTEL_AVAILABLE:
        with _otel_span(name, **attributes) as span:
            yield span
    else:
        yield None


logger = logging.getLogger("auto_boot")


async def auto_boot() -> dict:
    """
    Full system auto-boot sequence.
    Returns a status report of everything that was configured.
    """
    start = time.time()
    report = {
        "boot_time_ms": 0,
        "llm_providers": [],
        "env_updates": {},
        "models": {},
        "health_monitor": False,
        "auto_backup": False,
        "event_bus_broadcast": False,
        "task_queue": False,
        "errors": [],
    }

    # ── Step 1: Auto-discover LLM providers ──
    with _maybe_span("boot.discover_providers"):
        try:
            from services.auto_discovery import discover_all, auto_configure_env
            providers = await discover_all()
            report["llm_providers"] = [
                {"name": p.name, "kind": p.kind, "available": p.available,
                 "model": p.model, "latency_ms": p.latency_ms}
                for p in providers
            ]
            # Auto-configure env for first available providers
            env_updates = auto_configure_env(providers)
            for key, value in env_updates.items():
                if not os.environ.get(key):
                    os.environ[key] = value
                    report["env_updates"][key] = value
            available = [p.name for p in providers if p.available]
            logger.info("LLM auto-discovery: %d available (%s)", len(available), ", ".join(available) or "none")
        except Exception as e:
            report["errors"].append(f"auto_discovery: {e}")
            logger.warning("LLM auto-discovery failed: %s", e)

    # ── Step 2: Auto-pull Ollama model if available ──
    with _maybe_span("boot.ollama_model"):
        try:
            from services.auto_discovery import ensure_ollama_model
            ollama_host = os.environ.get("OLLAMA_HOST", "")
            if ollama_host:
                ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
                pulled = await ensure_ollama_model(ollama_model)
                report["models"]["ollama"] = {"model": ollama_model, "pulled": pulled}
        except Exception as e:
            report["errors"].append(f"ollama_model: {e}")

    # ── Step 3: Ensure ML models ──
    with _maybe_span("boot.ml_models"):
        try:
            from services.auto_discovery import ensure_ml_models
            ml_status = await ensure_ml_models()
            report["models"]["ml_models"] = ml_status
        except Exception as e:
            report["errors"].append(f"ml_models: {e}")

    # ── Step 4: Start health monitor ──
    with _maybe_span("boot.health_monitor"):
        try:
            from services.health_monitor import health_monitor
            from services.llm_engine import llm_engine

            # Register LLM engine health check
            async def _check_llm():
                status = await llm_engine.health_check()
                if not status.get("healthy"):
                    raise RuntimeError(f"LLM unhealthy: {status}")

            async def _restart_llm():
                llm_engine.clear_cache()
                llm_engine._init_providers()

            health_monitor.register("llm_engine", check_fn=_check_llm, restart_fn=_restart_llm)

            # Register event bus health check
            async def _check_event_bus():
                from shared.event_bus import get_event_bus
                bus = get_event_bus()
                if not bus._running:
                    raise RuntimeError("Event bus not running")

            health_monitor.register("event_bus", check_fn=_check_event_bus)

            await health_monitor.start()
            report["health_monitor"] = True
        except Exception as e:
            report["errors"].append(f"health_monitor: {e}")

    # ── Step 5: Start auto-backup scheduler ──
    with _maybe_span("boot.backup_scheduler"):
        try:
            from services.auto_backup import backup_scheduler
            await backup_scheduler.start()
            report["auto_backup"] = True
        except Exception as e:
            report["errors"].append(f"auto_backup: {e}")

    # ── Step 6: Wire event bus → WebSocket ──
    with _maybe_span("boot.event_bus_broadcast"):
        try:
            from shared.event_bus import get_event_bus
            from services.ws_manager import ws_manager

            event_bus = get_event_bus()

            async def _broadcast_to_dashboard(event):
                try:
                    payload = {
                        "type": "event",
                        "event_type": getattr(event.event_type, "value", str(event.event_type)),
                        "timestamp": str(event.timestamp) if hasattr(event, "timestamp") else "",
                        "payload": event.payload if isinstance(event.payload, dict) else str(event.payload),
                    }
                    await ws_manager.broadcast(payload)
                except Exception:
                    pass

            event_bus.subscribe_wildcard("*", _broadcast_to_dashboard)
            report["event_bus_broadcast"] = True
        except Exception as e:
            report["errors"].append(f"event_bus_broadcast: {e}")

    # ── Step 7: Start background task queue ──
    with _maybe_span("boot.task_queue"):
        try:
            from services.task_queue import task_queue

            async def _handle_clip_analysis(payload: dict) -> dict:
                from services.ai_pipeline import ai_pipeline_hub
                return await ai_pipeline_hub.analyze_full_clip(payload.get("clip_id", ""))

            task_queue.register_handler("clip_analysis", _handle_clip_analysis)
            await task_queue.start()
            report["task_queue"] = True
        except Exception as e:
            report["errors"].append(f"task_queue: {e}")

    elapsed = (time.time() - start) * 1000
    report["boot_time_ms"] = round(elapsed, 1)
    logger.info("Auto-boot completed in %.1fms (%d errors)", elapsed, len(report["errors"]))

    return report


async def auto_shutdown():
    """Graceful shutdown of all auto-booted services."""
    try:
        from services.health_monitor import health_monitor
        await health_monitor.stop()
    except Exception:
        pass
    try:
        from services.auto_backup import backup_scheduler
        await backup_scheduler.stop()
    except Exception:
        pass
    try:
        from services.task_queue import task_queue
        await task_queue.stop()
    except Exception:
        pass
    try:
        from shared.event_bus import get_event_bus
        bus = get_event_bus()
        await bus.stop()
    except Exception:
        pass
    logger.info("Auto-shutdown completed")
