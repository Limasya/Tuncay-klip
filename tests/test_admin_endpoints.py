"""
Test HTTP Admin endpoints after launching app with lifespans auto-boot.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

class TestAdminEndpoints:
    def test_discovery_endpoint(self):
        resp = client.get("/api/admin/discovery")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert "available_count" in data

    def test_auto_configure(self):
        resp = client.post("/api/admin/discovery/configure")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert isinstance(data["env_applied"], dict)

    def test_health_monitor(self):
        resp = client.get("/api/admin/health-monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert data["running"] is True
        assert "services" in data

    def test_backups(self):
        resp = client.get("/api/admin/backups")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_backups" in data
        assert "latest" in data

    def test_backup_trigger(self):
        # Ensure we can trigger an immediate db backup
        resp = client.post("/api/admin/backups/trigger")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("created", "skipped")

    def test_llm_providers(self):
        resp = client.get("/api/admin/llm/providers")
        assert resp.status_code == 200
        data = resp.json()
        assert "providers" in data
        assert isinstance(data["providers"], list)
        # Also check health route
        resp = client.get("/api/admin/llm/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "healthy" in data
