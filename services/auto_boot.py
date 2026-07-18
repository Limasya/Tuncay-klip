"""
Auto-Boot Orchestrator
─────────────────────
Single entry point that boots the entire system:
  1. Auto-discovers available LLM providers
  2. Auto-downloads missing models (Ollama, ML)
  3. Auto-configures environment variables
  4. Starts health monitor with auto-restart
  5. Starts auto-backup scheduler
  6. Starts WebSocket broadcast wiring
  7. Reports full system status
  8. Starts Kick Stream Monitor (canli yayin izleme)
  9. Starts Kick Clips Collector (公众clip toplama)

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
        "kick_stream_monitor": False,
        "kick_clips_collector": False,
        "intelligence_graph": False,
        "knowledge_base": False,
        "critic_analytics": False,
        "publisher": False,
        "ab_test": False,
        "quality_dashboard": False,
        "cost_tracker": False,
        "user_feedback": False,
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
                except Exception as e:
                    logger.debug("Dashboard broadcast hatası: %s", e)

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

# ── Step 8: Kick Stream Monitor — canli yayini izle, hafizada klip cikar ──
    with _maybe_span("boot.kick_stream_monitor"):
        try:
            from services.kick_stream_monitor import kick_stream_monitor
            report["kick_stream_monitor"] = await kick_stream_monitor.start()
            logger.info("Kick Stream Monitor basladi — canli yayin bekleniyor")
        except Exception as e:
            report["errors"].append(f"kick_stream_monitor: {e}")
            logger.warning("Kick Stream Monitor baslatilamadi: %s", e)

    # ── Step 9: Kick Clips Collector —公众clip'leri topla ──
    with _maybe_span("boot.kick_clips_collector"):
        try:
            from services.kick_clips_collector import kick_clips_collector
            report["kick_clips_collector"] = await kick_clips_collector.start()
            logger.info("Kick Clips Collector basladi —公众clip'ler toplaniyor")
        except Exception as e:
            report["errors"].append(f"kick_clips_collector: {e}")
            logger.warning("Kick Clips Collector baslatilamadi: %s", e)

    # ── Step 10: Content Intelligence Graph ──
    with _maybe_span("boot.intelligence_graph"):
        try:
            from services.intelligence_graph import graph_builder
            await graph_builder.start()
            report["intelligence_graph"] = True
            logger.info("Content Intelligence Graph basladi")
        except Exception as e:
            report["errors"].append(f"intelligence_graph: {e}")
            logger.warning("Intelligence Graph baslatilamadi: %s", e)

    # ── Step 11: Knowledge Base — tüm yayınların bilgi bankası ──
    with _maybe_span("boot.knowledge_base"):
        try:
            from services.knowledge_base import knowledge_base
            await knowledge_base.load()
            report["knowledge_base"] = True
            logger.info("Knowledge Base basladi — bilgi bankasi yuklendi")
        except Exception as e:
            report["errors"].append(f"knowledge_base: {e}")
            logger.warning("Knowledge Base baslatilamadi: %s", e)

    # ── Step 12: Critic Analytics — A/B ölçüm ve geri bildirim ──
    with _maybe_span("boot.critic_analytics"):
        try:
            from services.critic_analytics import critic_analytics
            await critic_analytics.load()
            report["critic_analytics"] = True
            logger.info("Critic Analytics basladi")
        except Exception as e:
            report["errors"].append(f"critic_analytics: {e}")
            logger.warning("Critic Analytics baslatilamadi: %s", e)

    # ── Step 13: Multi-Platform Publisher ──
    with _maybe_span("boot.publisher"):
        try:
            from services.multi_platform_publisher import multi_platform_publisher
            await multi_platform_publisher.load()
            report["publisher"] = True
            logger.info("Multi-Platform Publisher basladi")
        except Exception as e:
            report["errors"].append(f"publisher: {e}")
            logger.warning("Publisher baslatilamadi: %s", e)

    # ── Step 14: Thumbnail A/B Test ──
    with _maybe_span("boot.ab_test"):
        try:
            from services.thumbnail_ab_test import thumbnail_ab_test
            await thumbnail_ab_test.load()
            report["ab_test"] = True
            logger.info("Thumbnail A/B Test basladi")
        except Exception as e:
            report["errors"].append(f"ab_test: {e}")
            logger.warning("A/B Test baslatilamadi: %s", e)

    # ── Step 15: Quality Dashboard ──
    with _maybe_span("boot.quality_dashboard"):
        try:
            from services.quality_dashboard import quality_dashboard
            await quality_dashboard.load()
            report["quality_dashboard"] = True
            logger.info("Quality Dashboard basladi")
        except Exception as e:
            report["errors"].append(f"quality_dashboard: {e}")
            logger.warning("Quality Dashboard baslatilamadi: %s", e)

    # ── Step 16: Cost Tracker ──
    with _maybe_span("boot.cost_tracker"):
        try:
            from services.cost_tracker import cost_tracker
            await cost_tracker.load()
            report["cost_tracker"] = True
            logger.info("Cost Tracker basladi")
        except Exception as e:
            report["errors"].append(f"cost_tracker: {e}")
            logger.warning("Cost Tracker baslatilamadi: %s", e)

    # ── Step 17: User Feedback ──
    with _maybe_span("boot.user_feedback"):
        try:
            from services.user_feedback import user_feedback
            await user_feedback.load()
            report["user_feedback"] = True
            logger.info("User Feedback basladi")
        except Exception as e:
            report["errors"].append(f"user_feedback: {e}")
            logger.warning("User Feedback baslatilamadi: %s", e)

    elapsed = (time.time() - start) * 1000
    report["boot_time_ms"] = round(elapsed, 1)
    logger.info("Auto-boot completed in %.1fms (%d errors)", elapsed, len(report["errors"]))

    return report


async def auto_shutdown():
    """Graceful shutdown of all auto-booted services."""
    try:
        from services.health_monitor import health_monitor
        await health_monitor.stop()
    except Exception as e:
        logger.debug("health_monitor durdurulamadı: %s", e)
    try:
        from services.auto_backup import backup_scheduler
        await backup_scheduler.stop()
    except Exception as e:
        logger.debug("backup_scheduler durdurulamadı: %s", e)
    try:
        from services.task_queue import task_queue
        await task_queue.stop()
    except Exception as e:
        logger.debug("task_queue durdurulamadı: %s", e)
    try:
        from services.kick_stream_monitor import kick_stream_monitor
        await kick_stream_monitor.stop()
    except Exception as e:
        logger.debug("kick_stream_monitor durdurulamadı: %s", e)
    try:
        from services.kick_clips_collector import kick_clips_collector
        await kick_clips_collector.stop()
    except Exception as e:
        logger.debug("kick_clips_collector durdurulamadı: %s", e)
    try:
        from services.intelligence_graph import graph_builder
        from services.intelligence_graph import intelligence_graph
        await intelligence_graph.save()
    except Exception as e:
        logger.debug("intelligence_graph kaydedilemedi: %s", e)
    try:
        from services.knowledge_base import knowledge_base
        await knowledge_base.save()
    except Exception as e:
        logger.debug("knowledge_base kaydedilemedi: %s", e)
    try:
        from services.critic_analytics import critic_analytics
        await critic_analytics.save()
    except Exception as e:
        logger.debug("critic_analytics kaydedilemedi: %s", e)
    try:
        from services.multi_platform_publisher import multi_platform_publisher
        await multi_platform_publisher.save()
    except Exception as e:
        logger.debug("multi_platform_publisher kaydedilemedi: %s", e)
    try:
        from services.thumbnail_ab_test import thumbnail_ab_test
        await thumbnail_ab_test.save()
    except Exception as e:
        logger.debug("thumbnail_ab_test kaydedilemedi: %s", e)
    try:
        from services.quality_dashboard import quality_dashboard
        await quality_dashboard.save()
    except Exception as e:
        logger.debug("quality_dashboard kaydedilemedi: %s", e)
    try:
        from services.cost_tracker import cost_tracker
        await cost_tracker.save()
    except Exception as e:
        logger.debug("cost_tracker kaydedilemedi: %s", e)
    try:
        from services.user_feedback import user_feedback
        await user_feedback.save()
    except Exception as e:
        logger.debug("user_feedback kaydedilemedi: %s", e)
    try:
        from shared.event_bus import get_event_bus
        bus = get_event_bus()
        await bus.stop()
    except Exception as e:
        logger.debug("event_bus durdurulamadı: %s", e)
    logger.info("Auto-shutdown completed")
