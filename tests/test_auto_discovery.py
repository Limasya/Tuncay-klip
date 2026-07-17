"""
Tests for auto-discovery, health monitor, auto-backup, and auto-boot.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


class TestAutoDiscovery:
    """Test LLM provider auto-discovery."""

    @pytest.mark.asyncio
    async def test_discover_all_returns_list(self):
        from services.auto_discovery import discover_all
        result = await discover_all()
        assert isinstance(result, list)
        assert len(result) >= 5

    @pytest.mark.asyncio
    async def test_discovered_provider_fields(self):
        from services.auto_discovery import discover_all
        providers = await discover_all()
        for p in providers:
            assert hasattr(p, "name")
            assert hasattr(p, "kind")
            assert hasattr(p, "available")
            assert hasattr(p, "model")
            assert hasattr(p, "setup_hint")
            assert p.kind in ("local", "cloud")

    @pytest.mark.asyncio
    async def test_auto_configure_env_returns_dict(self):
        from services.auto_discovery import discover_all, auto_configure_env
        providers = await discover_all()
        updates = auto_configure_env(providers)
        assert isinstance(updates, dict)

    def test_local_targets_have_env_vars(self):
        from services.auto_discovery import LOCAL_TARGETS
        for t in LOCAL_TARGETS:
            assert "env_var_host" in t
            assert "env_var_model" in t
            assert "default_host" in t
            assert "setup_hint" in t

    def test_cloud_targets_have_env_vars(self):
        from services.auto_discovery import CLOUD_TARGETS
        for t in CLOUD_TARGETS:
            assert "env_var_key" in t
            assert "setup_hint" in t

    @pytest.mark.asyncio
    async def test_ollama_model_check_returns_dict(self):
        from services.auto_discovery import ensure_ollama_model
        result = await ensure_ollama_model("llama3.1:8b")
        assert isinstance(result, bool)


class TestHealthMonitor:
    """Test health monitor service."""

    def test_register_service(self):
        from services.health_monitor import HealthMonitor
        monitor = HealthMonitor(interval=60)
        monitor.register("test_service")
        assert "test_service" in monitor._services

    def test_get_status_returns_dict(self):
        from services.health_monitor import HealthMonitor
        monitor = HealthMonitor(interval=60)
        monitor.register("test")
        status = monitor.get_status()
        assert "running" in status
        assert "services" in status
        assert "test" in status["services"]

    def test_service_states(self):
        from services.health_monitor import ServiceState
        assert ServiceState.HEALTHY.value == "healthy"
        assert ServiceState.FAILED.value == "failed"
        assert ServiceState.RECOVERING.value == "recovering"

    def test_health_to_dict(self):
        from services.health_monitor import ServiceHealth, ServiceState
        h = ServiceHealth(name="test", state=ServiceState.HEALTHY, consecutive_failures=0)
        d = h.to_dict()
        assert d["name"] == "test"
        assert d["state"] == "healthy"
        assert d["consecutive_failures"] == 0


class TestAutoBackup:
    """Test auto-backup system."""

    @pytest.mark.asyncio
    async def test_backup_status_returns_dict(self):
        from services.auto_backup import get_backup_status
        result = await get_backup_status()
        assert "total_backups" in result
        assert "total_size_mb" in result
        assert "latest" in result

    @pytest.mark.asyncio
    async def test_backup_database_returns_dict(self):
        from services.auto_backup import auto_backup_database
        result = await auto_backup_database()
        assert "status" in result
        assert result["status"] in ("created", "skipped", "failed")

    @pytest.mark.asyncio
    async def test_backup_clips_returns_dict(self):
        from services.auto_backup import auto_backup_clips
        result = await auto_backup_clips()
        assert "status" in result


class TestAutoBoot:
    """Test auto-boot orchestrator."""

    @pytest.mark.asyncio
    async def test_auto_boot_returns_report(self):
        from services.auto_boot import auto_boot
        report = await auto_boot()
        assert "boot_time_ms" in report
        assert "llm_providers" in report
        assert "health_monitor" in report
        assert "auto_backup" in report
        assert "event_bus_broadcast" in report
        assert "task_queue" in report
        assert "errors" in report
        assert isinstance(report["llm_providers"], list)

    @pytest.mark.asyncio
    async def test_auto_boot_completes_fast(self):
        from services.auto_boot import auto_boot
        report = await auto_boot()
        assert report["boot_time_ms"] < 20000

    @pytest.mark.asyncio
    async def test_auto_shutdown_completes(self):
        from services.auto_boot import auto_shutdown
        await auto_shutdown()
