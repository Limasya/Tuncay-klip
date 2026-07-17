"""
Service Health Monitor — auto-discovers, watches, and restarts failed services.
Runs as a background task inside the FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger("health_monitor")


class ServiceState(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


@dataclass
class ServiceHealth:
    name: str
    state: ServiceState = ServiceState.UNKNOWN
    last_check: float = 0.0
    last_healthy: float = 0.0
    consecutive_failures: int = 0
    total_restarts: int = 0
    error: str = ""
    check_fn: Optional[Callable[..., Coroutine]] = None
    restart_fn: Optional[Callable[..., Coroutine]] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "total_restarts": self.total_restarts,
            "last_check_ago_s": round(time.time() - self.last_check, 1) if self.last_check else 0,
            "last_healthy_ago_s": round(time.time() - self.last_healthy, 1) if self.last_healthy else None,
            "error": self.error,
        }


class HealthMonitor:
    """
    Background health checker that auto-discovers and auto-restarts services.
    - Polls every `interval` seconds
    - Marks service FAILED after `max_failures` consecutive failures
    - Calls `restart_fn` on failure
    - Backs off restarts with exponential delay
    """

    def __init__(self, interval: int = 30, max_failures: int = 3):
        self._services: dict[str, ServiceHealth] = {}
        self._interval = interval
        self._max_failures = max_failures
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._restart_cooldowns: dict[str, float] = {}

    def register(
        self,
        name: str,
        check_fn: Callable[..., Coroutine] | None = None,
        restart_fn: Callable[..., Coroutine] | None = None,
    ):
        """Register a service to monitor."""
        self._services[name] = ServiceHealth(
            name=name, check_fn=check_fn, restart_fn=restart_fn,
        )
        logger.debug("Registered health check: %s", name)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Health monitor started (interval=%ds)", self._interval)

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self._check_all()
            except Exception as e:
                logger.error("Health monitor loop error: %s", e)
            await asyncio.sleep(self._interval)

    async def _check_all(self):
        tasks = []
        for name, health in self._services.items():
            if health.check_fn:
                tasks.append(self._check_service(health))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_service(self, health: ServiceHealth):
        try:
            result = await health.check_fn()
            health.state = ServiceState.HEALTHY
            health.consecutive_failures = 0
            health.last_check = time.time()
            health.last_healthy = time.time()
            health.error = ""
        except Exception as e:
            health.consecutive_failures += 1
            health.last_check = time.time()
            health.error = str(e)[:200]

            if health.consecutive_failures >= self._max_failures:
                health.state = ServiceState.FAILED
                logger.error(
                    "Service %s FAILED after %d consecutive failures: %s",
                    health.name, health.consecutive_failures, e,
                )
                await self._try_restart(health)
            else:
                health.state = ServiceState.DEGRADED
                logger.warning(
                    "Service %s degraded (%d/%d failures): %s",
                    health.name, health.consecutive_failures, self._max_failures, e,
                )

    async def _try_restart(self, health: ServiceHealth):
        if not health.restart_fn:
            logger.warning("No restart function for %s, skipping auto-restart", health.name)
            return

        # Exponential backoff cooldown
        cooldown = min(60 * (2 ** min(health.total_restarts, 4)), 960)
        last_restart = self._restart_cooldowns.get(health.name, 0)
        if time.time() - last_restart < cooldown:
            remaining = cooldown - (time.time() - last_restart)
            logger.info("Restart cooldown for %s: %.0fs remaining", health.name, remaining)
            return

        health.state = ServiceState.RECOVERING
        health.total_restarts += 1
        self._restart_cooldowns[health.name] = time.time()

        logger.info("Attempting auto-restart of %s (attempt #%d)", health.name, health.total_restarts)
        try:
            await health.restart_fn()
            logger.info("Successfully restarted %s", health.name)
            health.state = ServiceState.HEALTHY
            health.consecutive_failures = 0
        except Exception as e:
            health.state = ServiceState.FAILED
            health.error = f"restart failed: {e}"
            logger.error("Failed to restart %s: %s", health.name, e)

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "interval": self._interval,
            "services": {name: h.to_dict() for name, h in self._services.items()},
        }


health_monitor = HealthMonitor(interval=30, max_failures=3)
