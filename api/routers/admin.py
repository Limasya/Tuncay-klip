"""
Admin API Router
────────────────
System administration endpoints: config, services, metrics, health deep-dive.
"""
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from utils.auth_compat import Principal, Scope, require_scope

logger = logging.getLogger("admin_api")

router = APIRouter(prefix="/api/admin", tags=["admin"])

_start_time = time.time()


@router.get("/health/deep")
async def deep_health(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Deep health check — verifies DB, Redis, services."""
    checks = {}

    # Database
    try:
        from services.database import async_session
        async with async_session() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # Redis
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"), protocol=2)
        await r.ping()
        await r.aclose()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable (non-critical)"

    # Event bus
    try:
        from shared.event_bus import get_event_bus
        bus = get_event_bus()
        checks["event_bus"] = "ok" if bus._running else "stopped"
    except Exception:
        checks["event_bus"] = "error"

    # AI Pipeline
    try:
        from services.ai_pipeline import ai_pipeline
        checks["ai_pipeline"] = "ok" if ai_pipeline._started else "idle"
    except Exception:
        checks["ai_pipeline"] = "error"

    # Cloudflare health (Kick API erisimi)
    try:
        from services.zero_bandwidth_clipper import zero_bandwidth_clipper
        cf_health = zero_bandwidth_clipper.get_cf_health()
        if cf_health["is_healthy"]:
            checks["cloudflare"] = "ok"
        else:
            checks["cloudflare"] = f"warning: {cf_health['recommendation']}"
    except Exception:
        checks["cloudflare"] = "unknown"

    all_ok = all(v == "ok" for v in checks.values() if "unavailable" not in v and "idle" not in v)
    return {"status": "healthy" if all_ok else "degraded", "checks": checks}


@router.get("/metrics/summary")
async def metrics_summary(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """System metrics summary."""
    uptime = time.time() - _start_time

    from services.metrics import metrics
    from shared.event_bus import get_event_bus
    from services.ai_pipeline import ai_pipeline

    bus = get_event_bus()

    return {
        "uptime_seconds": round(uptime, 1),
        "uptime_human": _format_uptime(uptime),
        "http_requests": dict(metrics._counters),
        "event_bus": bus.metrics,
        "ai_pipeline": ai_pipeline.get_status(),
        "llm_stats": _get_llm_stats(),
    }


@router.get("/services")
async def list_services(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """List all registered services and their status."""
    services = []

    # Core services
    for name, module_path in [
        ("orchestrator", "microservices.orchestrator"),
        ("ai_pipeline", "services.ai_pipeline"),
        ("llm_engine", "services.llm_engine"),
        ("recommendation_engine", "services.recommendation_engine"),
        ("smart_editor", "services.smart_editor"),
    ]:
        try:
            mod = __import__(module_path, fromlist=[""])
            services.append({"name": name, "status": "loaded", "module": module_path})
        except Exception as e:
            services.append({"name": name, "status": f"error: {e}", "module": module_path})

    return {"services": services}


@router.get("/tasks")
async def task_queue_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Background task queue status — running tasks, queue depth, history."""
    from services.task_queue import task_queue
    return task_queue.get_status()


@router.get("/websocket")
async def websocket_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """WebSocket connection status — connected clients, subscriptions."""
    from services.ws_manager import ws_manager
    return ws_manager.get_status()


@router.get("/config")
async def get_safe_config(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Get non-sensitive configuration."""
    from config import get_settings
    s = get_settings()
    return {
        "kick_channel": s.kick_channel_slug,
        "database_backend": "postgresql" if "postgres" in s.database_url else "sqlite",
        "redis_enabled": bool(s.redis_url),
        "otel_enabled": s.otel_enabled,
        "deployment": s.deployment_environment,
        "feature_flags": s.feature_flags_file or "none",
        "analysis_fps": s.analysis_fps,
        "clip_pre_seconds": s.clip_pre_seconds,
        "clip_post_seconds": s.clip_post_seconds,
    }


@router.get("/llm/providers")
async def llm_providers(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """List all registered LLM providers and their configuration."""
    from services import llm_client
    return {
        "providers": [{"name": "facade", "type": "llm_client", "enabled": llm_client.is_router_active()}],
        "facade_status": llm_client.get_router_status(),
        "stats": llm_client.get_stats(),
    }


@router.get("/llm/health")
async def llm_health(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Quick LLM health check — probes the first available provider."""
    from services import llm_client
    return await llm_client.health_check()


@router.get("/discovery")
async def auto_discovery(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Auto-discover available LLM providers (local + cloud)."""
    from services.auto_discovery import discover_all
    providers = await discover_all()
    return {
        "providers": [
            {"name": p.name, "kind": p.kind, "available": p.available,
             "model": p.model, "latency_ms": p.latency_ms, "setup_hint": p.setup_hint}
            for p in providers
        ],
        "available_count": sum(1 for p in providers if p.available),
    }


@router.post("/discovery/configure")
async def auto_configure(
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Auto-discover and configure the best available LLM provider."""
    import os
    from services.auto_discovery import discover_all, auto_configure_env
    providers = await discover_all()
    env_updates = auto_configure_env(providers)
    applied = {}
    for key, value in env_updates.items():
        if not os.environ.get(key):
            os.environ[key] = value
            applied[key] = value
    return {
        "discovered": len(providers),
        "available": sum(1 for p in providers if p.available),
        "env_applied": applied,
    }


@router.get("/health-monitor")
async def health_monitor_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Service health monitor status — auto-restart info."""
    from services.health_monitor import health_monitor
    return health_monitor.get_status()


@router.get("/backups")
async def backup_status(
    _principal: Principal = Depends(require_scope(Scope.ANALYTICS_READ)),
):
    """Backup status — database backups, rotation, disk usage."""
    from services.auto_backup import get_backup_status
    return await get_backup_status()


@router.post("/backups/trigger")
async def trigger_backup(
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Trigger an immediate database backup."""
    from services.auto_backup import auto_backup_database
    return await auto_backup_database()


@router.post("/cache/clear")
async def clear_cache(
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Clear all caches (LLM response cache)."""
    from services import llm_client
    llm_client.clear_cache()
    return {"status": "cache_cleared"}


@router.post("/services/restart/{service_name}")
async def restart_service(
    service_name: str,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
):
    """Restart a specific service (AI Pipeline, etc.)."""
    if service_name == "ai_pipeline":
        from services.ai_pipeline import ai_pipeline
        await ai_pipeline.stop()
        await ai_pipeline.start()
        return {"status": "restarted", "service": "ai_pipeline"}
    raise HTTPException(status_code=404, detail=f"Service '{service_name}' not restartable")


def _format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _get_llm_stats() -> dict:
    try:
        from services import llm_client
        return llm_client.get_stats()
    except Exception as e:
        import logging
        logging.getLogger(__name__).debug("LLM stats unavailable: %s", e)
        return {}
