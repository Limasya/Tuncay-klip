"""HTTP contract tests for the fixed public Kick archive endpoints."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.routers import social as social_router
from main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_kick_archive_sync_accepts_bounded_job(monkeypatch, client):
    def fake_start_sync(vod_limit=None, max_clips_per_vod=None):
        assert vod_limit == 2
        assert max_clips_per_vod == 3
        return {
            "status": "accepted",
            "channel": "thetuncay",
            "channel_url": "https://kick.com/thetuncay",
        }

    monkeypatch.setattr(social_router.kick_archive, "start_sync", fake_start_sync)

    response = await client.post(
        "/api/v1/social/kick-archive/sync",
        json={"vod_limit": 2, "max_clips_per_vod": 3},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["channel"] == "thetuncay"


@pytest.mark.asyncio
async def test_kick_archive_status_returns_state(monkeypatch, client):
    async def fake_get_status():
        return {
            "channel": "thetuncay",
            "running": False,
            "vod_counts": {"completed": 3, "processing": 0, "failed": 1},
        }

    monkeypatch.setattr(social_router.kick_archive, "get_status", fake_get_status)

    response = await client.get("/api/v1/social/kick-archive/status")
    assert response.status_code == 200, response.text
    assert response.json()["vod_counts"]["completed"] == 3


@pytest.mark.asyncio
async def test_master_pipeline_rejects_other_channels(client):
    response = await client.post(
        "/api/v1/social/generate-master-pipeline",
        json={"url": "https://kick.com/someone-else/videos/abc"},
    )
    assert response.status_code == 400
    assert "thetuncay" in response.json()["detail"]
