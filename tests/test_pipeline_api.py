"""
Integration tests for Pipeline API endpoints.
Tests the full request → response cycle through FastAPI.
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


# ─── Health & Readiness ──────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "phase" in data


@pytest.mark.asyncio
async def test_readiness_endpoint(client):
    resp = await client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "ready" in data
    assert "checks" in data


# ─── Pipeline Status & Metrics ───────────────────────────

@pytest.mark.asyncio
async def test_pipeline_status(client):
    resp = await client.get("/api/pipeline/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "pipeline" in data
    assert "event_bus" in data


@pytest.mark.asyncio
async def test_pipeline_metrics(client):
    resp = await client.get("/api/pipeline/metrics")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)


@pytest.mark.asyncio
async def test_pipeline_events(client):
    resp = await client.get("/api/pipeline/events")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_pipeline_events_by_type(client):
    resp = await client.get("/api/pipeline/events/chat.message")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# ─── Chat Injection ──────────────────────────────────────

@pytest.mark.asyncio
async def test_chat_injection(client):
    resp = await client.post("/api/pipeline/chat", json={
        "text": "pogchamp amazing play!",
        "user": "test_viewer",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "label" in data
    assert data["label"] in ("POSITIVE", "NEGATIVE", "NEUTRAL")


@pytest.mark.asyncio
async def test_chat_injection_empty(client):
    resp = await client.post("/api/pipeline/chat", json={
        "text": "just a normal message",
        "user": "viewer",
    })
    assert resp.status_code == 200


# ─── Score Endpoint ──────────────────────────────────────

@pytest.mark.asyncio
async def test_score_endpoint(client):
    resp = await client.get("/api/pipeline/score")
    assert resp.status_code == 200
    data = resp.json()
    assert "composite_score" in data
    assert "breakdown" in data
    assert "active_signals" in data


# ─── Metadata Generation ─────────────────────────────────

@pytest.mark.asyncio
async def test_generate_metadata(client):
    resp = await client.post(
        "/api/pipeline/generate-metadata?category=exciting&platform=youtube"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "title" in data
    assert "description" in data
    assert "hashtags" in data
    assert isinstance(data["hashtags"], list)
    assert len(data["title"]) > 0


@pytest.mark.asyncio
async def test_generate_metadata_tiktok(client):
    resp = await client.post(
        "/api/pipeline/generate-metadata?category=funny&platform=tiktok"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["hashtags"]) <= 5  # TikTok limit


# ─── System Endpoints ────────────────────────────────────

@pytest.mark.asyncio
async def test_system_status(client):
    resp = await client.get("/api/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "cpu_usage" in data


@pytest.mark.asyncio
async def test_analysis_stats(client):
    resp = await client.get("/api/system/analysis-stats")
    assert resp.status_code == 200


# ─── Clip Endpoints ──────────────────────────────────────

@pytest.mark.asyncio
async def test_clips_list(client):
    resp = await client.get("/api/clips/")
    assert resp.status_code == 200
    data = resp.json()
    assert "clips" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_clips_with_filters(client):
    resp = await client.get("/api/clips/?category=funny&sort_by=created_at")
    assert resp.status_code == 200


# ─── Preferences ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_preferences_get(client):
    resp = await client.get("/api/preferences/")
    assert resp.status_code == 200
    data = resp.json()
    assert "emotion_sensitivity" in data


# ─── Error Handling ──────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_stop_when_not_running(client):
    resp = await client.post("/api/pipeline/stop")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_export_missing_file(client):
    resp = await client.post("/api/pipeline/export", json={
        "clip_path": "/nonexistent/path.mp4",
        "platforms": ["youtube"],
    })
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_subtitle_missing_file(client):
    resp = await client.post("/api/pipeline/generate-subtitles", json={
        "clip_path": "/nonexistent/path.mp4",
    })
    assert resp.status_code == 404
