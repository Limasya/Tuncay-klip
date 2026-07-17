"""Public VOD archive tests for the fixed kick.com/thetuncay target."""
import json

import pytest

from services.kick_archive import (
    TARGET_CHANNEL_URL,
    KickArchiveService,
    is_target_channel_url,
    is_target_vod_url,
)


class FakeKickClient:
    def __init__(self, vods):
        self.vods = vods
        self.requested_limit = None

    async def list_public_vods(self, limit):
        self.requested_limit = limit
        return self.vods[:limit]


class FakePipeline:
    def __init__(self):
        self.calls = []

    async def process_url(self, url, max_clips, game, streamer, **kwargs):
        self.calls.append({
            "url": url,
            "max_clips": max_clips,
            "game": game,
            "streamer": streamer,
            "config": kwargs.get("config"),
        })
        return {"success": True, "total_clips": 2}


def test_target_url_validation_is_strict():
    assert is_target_channel_url(TARGET_CHANNEL_URL)
    assert is_target_channel_url(f"{TARGET_CHANNEL_URL}/")
    assert is_target_vod_url(f"{TARGET_CHANNEL_URL}/videos/abc-123")
    assert not is_target_vod_url("https://kick.com/other/videos/abc-123")
    assert not is_target_vod_url("https://youtube.com/watch?v=abc-123")
    assert not is_target_vod_url(TARGET_CHANNEL_URL)


@pytest.mark.asyncio
async def test_sync_processes_target_vod_once_and_persists_state(tmp_path):
    vod_url = f"{TARGET_CHANNEL_URL}/videos/vod-1"
    kick_client = FakeKickClient([
        {
            "vod_id": "vod-1",
            "url": vod_url,
            "title": "Public VOD",
            "category": "Just Chatting",
        },
        {
            "vod_id": "unexpected",
            "url": "https://kick.com/another-channel/videos/unexpected",
            "title": "Must not process",
        },
    ])
    pipeline = FakePipeline()
    state_path = tmp_path / "kick_archive_state.json"
    archive = KickArchiveService(
        kick_client=kick_client,
        pipeline=pipeline,
        state_path=state_path,
    )

    first = await archive.sync_archive(vod_limit=3, max_clips_per_vod=2)

    assert first["discovered"] == 1
    assert first["processed"] == 1
    assert first["clips_generated"] == 2
    assert len(pipeline.calls) == 1
    assert pipeline.calls[0]["url"] == vod_url
    assert pipeline.calls[0]["max_clips"] == 2
    assert pipeline.calls[0]["streamer"] == "Tuncay"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["channel"] == "thetuncay"
    assert state["vods"]["vod-1"]["status"] == "completed"
    assert state["vods"]["vod-1"]["clips_generated"] == 2

    second = await archive.sync_archive(vod_limit=3, max_clips_per_vod=2)
    assert second["processed"] == 0
    assert second["skipped"] == 1
    assert len(pipeline.calls) == 1


@pytest.mark.asyncio
async def test_sync_records_failed_vod_for_later_retry(tmp_path):
    class FailingPipeline:
        async def process_url(self, url, max_clips, game, streamer, **kwargs):
            return {"success": False, "error": "download failed"}

    state_path = tmp_path / "kick_archive_state.json"
    archive = KickArchiveService(
        kick_client=FakeKickClient([{
            "vod_id": "vod-failed",
            "url": f"{TARGET_CHANNEL_URL}/videos/vod-failed",
        }]),
        pipeline=FailingPipeline(),
        state_path=state_path,
    )

    report = await archive.sync_archive(vod_limit=1, max_clips_per_vod=1)

    assert report["failed"] == 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["vods"]["vod-failed"]["status"] == "failed"
    assert state["vods"]["vod-failed"]["error"] == "download failed"
