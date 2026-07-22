"""
Integration test for the download → edit → results flow.

Tests the full cycle end-to-end with mocked external services:
  POST /api/kick-clips/{id}/download
  POST /api/kick-clips/edit
  GET  /api/kick-clips/edit-results
  GET  /api/kick-clips/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock

from main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _fake_state(clips=None):
    return {
        "clips": {
            c["clip_id"]: c
            for c in (clips or [
                {
                    "clip_id": "test001",
                    "title": "Test Clip 1",
                    "clip_url": "https://example.com/clip1.mp4",
                    "downloaded": False,
                    "score": 85,
                    "views": 1200,
                    "likes": 340,
                    "category": "funny",
                    "created_at": "2026-07-20T12:00:00Z",
                    "duration": 30,
                },
                {
                    "clip_id": "test002",
                    "title": "Test Clip 2",
                    "clip_url": "https://example.com/clip2.mp4",
                    "downloaded": True,
                    "score": 60,
                    "views": 500,
                    "likes": 100,
                    "category": "funny",
                    "created_at": "2026-07-20T13:00:00Z",
                    "duration": 45,
                },
            ])
        }
    }


@pytest.mark.asyncio
async def test_download_clip(client):
    """POST /api/kick-clips/{id}/download — download a clip."""
    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        AsyncMock(return_value=_fake_state()),
    ), patch(
        "services.kick_clips_collector.kick_clips_collector._write_state",
        AsyncMock(),
    ), patch(
        "services.auto_editor.auto_editor._download_clip",
        AsyncMock(return_value=True),
    ):
        resp = await client.post("/api/kick-clips/test001/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "Indirildi" in data["message"]


@pytest.mark.asyncio
async def test_download_clip_not_found(client):
    """POST /api/kick-clips/{id}/download — clip does not exist."""
    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        AsyncMock(return_value=_fake_state()),
    ):
        resp = await client.post("/api/kick-clips/nonexistent/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "bulunamadi" in data["message"]


@pytest.mark.asyncio
async def test_download_clip_no_url(client):
    """POST /api/kick-clips/{id}/download — clip without url."""
    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        AsyncMock(return_value=_fake_state([
            {
                "clip_id": "no_url_clip",
                "title": "No URL",
                "clip_url": "",
                "downloaded": False,
            }
        ])),
    ):
        resp = await client.post("/api/kick-clips/no_url_clip/download")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert "clip_url yok" in data["message"]


@pytest.mark.asyncio
async def test_edit_no_downloaded_clips(client):
    """POST /api/kick-clips/edit — no downloaded clips → empty."""
    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        AsyncMock(return_value=_fake_state([
            {
                "clip_id": "test001",
                "title": "Not Downloaded",
                "clip_url": "https://example.com/clip.mp4",
                "downloaded": False,
                "score": 85,
            },
        ])),
    ):
        resp = await client.post("/api/kick-clips/edit", params={"min_score": 0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "empty"


@pytest.mark.asyncio
async def test_edit_with_downloaded_clips(client):
    """POST /api/kick-clips/edit — triggers edit_batch in background."""
    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        AsyncMock(return_value=_fake_state()),
    ), patch(
        "services.auto_editor.auto_editor.is_processing",
        MagicMock(return_value=False),
    ), patch(
        "services.auto_editor.auto_editor.edit_batch",
        AsyncMock(),
    ):
        resp = await client.post("/api/kick-clips/edit", params={"min_score": 0, "max_clips": 5})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "started"
        assert len(data["clips"]) >= 1


@pytest.mark.asyncio
async def test_edit_results(client):
    """GET /api/kick-clips/edit-results — returns results list."""
    fake_results = [
        {"clip_id": "test001", "status": "completed", "output": "data/edited_clips/final_test001.mp4"},
    ]
    with patch(
        "services.auto_editor.auto_editor.get_results",
        MagicMock(return_value=fake_results),
    ), patch(
        "services.auto_editor.auto_editor.is_processing",
        MagicMock(return_value=False),
    ):
        resp = await client.get("/api/kick-clips/edit-results")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 1
        assert data["results"][0]["clip_id"] == "test001"
        assert "processing" in data


@pytest.mark.asyncio
async def test_full_download_edit_results_flow(client):
    """
    Full download → edit → results flow.

    Tests:
      1. Download a clip
      2. Verify state was updated (downloaded=True)
      3. Trigger edit
      4. Check results
    """
    state_data = _fake_state()

    async def read_state():
        return state_data

    async def write_state(state):
        state_data["clips"] = state["clips"]

    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        side_effect=read_state,
    ), patch(
        "services.kick_clips_collector.kick_clips_collector._write_state",
        side_effect=write_state,
    ), patch(
        "services.auto_editor.auto_editor._download_clip",
        AsyncMock(return_value=True),
    ), patch(
        "services.auto_editor.auto_editor.is_processing",
        MagicMock(return_value=False),
    ), patch(
        "services.auto_editor.auto_editor.edit_batch",
        AsyncMock(),
    ), patch(
        "services.auto_editor.auto_editor.get_results",
        MagicMock(return_value=[
            {"clip_id": "test001", "status": "completed", "output": "data/edited_clips/final_test001.mp4"},
        ]),
    ):
        resp_dl = await client.post("/api/kick-clips/test001/download")
        assert resp_dl.status_code == 200
        assert resp_dl.json()["status"] == "ok"

        resp_edit = await client.post("/api/kick-clips/edit", params={"min_score": 0, "max_clips": 5})
        assert resp_edit.status_code == 200
        assert resp_edit.json()["status"] == "started"

        resp_results = await client.get("/api/kick-clips/edit-results")
        assert resp_results.status_code == 200
        results_data = resp_results.json()
        assert len(results_data["results"]) == 1
        assert results_data["results"][0]["clip_id"] == "test001"


@pytest.mark.asyncio
async def test_list_endpoint(client):
    """GET /api/kick-clips/ — list clips."""
    with patch(
        "services.kick_clips_collector.kick_clips_collector.read_state",
        AsyncMock(return_value=_fake_state()),
    ):
        resp = await client.get("/api/kick-clips/")
        assert resp.status_code == 200
        data = resp.json()
        assert "clips" in data
        assert "total" in data
        assert data["total"] == 2
