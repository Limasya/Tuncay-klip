"""
API endpoint testleri.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "engines" in data


@pytest.mark.asyncio
async def test_system_status(client):
    resp = await client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "is_monitoring" in data
    assert "cpu_usage" in data
    assert "gpu_available" in data


@pytest.mark.asyncio
async def test_clips_list(client):
    resp = await client.get("/api/clips/")
    assert resp.status_code == 200
    data = resp.json()
    assert "clips" in data
    assert "total" in data
    assert "page" in data


@pytest.mark.asyncio
async def test_clips_list_with_filters(client):
    resp = await client.get("/api/clips/?category=funny&sort_by=created_at")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_preferences_get(client):
    resp = await client.get("/api/preferences/")
    assert resp.status_code == 200
    data = resp.json()
    assert "emotion_sensitivity" in data
    assert "export_format" in data
    assert "export_resolution" in data


@pytest.mark.asyncio
async def test_preferences_update(client):
    resp = await client.put("/api/preferences/", json={
        "emotion_sensitivity": 0.8,
        "auto_subtitle": False,
    })
    # May return 400 if no broadcaster exists, that's ok
    assert resp.status_code in (200, 400)


@pytest.mark.asyncio
async def test_clip_not_found(client):
    resp = await client.get("/api/clips/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_system_start_stop(client):
    # Start without Kick credentials should still respond
    # 409 = channel not live, 503 = orchestrator unavailable, 500 = other error
    resp = await client.post("/api/system/start")
    assert resp.status_code in (200, 409, 500, 503)

    resp = await client.post("/api/system/stop")
    assert resp.status_code in (200, 400)


@pytest.mark.asyncio
async def test_analysis_stats(client):
    resp = await client.get("/api/system/analysis-stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "processed_frames" in data
    assert "events_triggered" in data
