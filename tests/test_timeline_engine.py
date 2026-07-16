"""Unit and API tests for the first professional timeline vertical slice."""
from fractions import Fraction

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from api.routers import projects as projects_router
from main import app
from services.project_store import ProjectStore
from services.timeline_engine import (
    EditMode,
    RationalTime,
    TimeRange,
    TimelineClip,
    Track,
    TrackType,
)


def rt(seconds: int) -> RationalTime:
    return RationalTime(seconds, 1)


def clip(path: str, source_start: int, duration: int, record_start: int) -> TimelineClip:
    return TimelineClip.create(
        asset_path=path,
        source_range=TimeRange(rt(source_start), rt(duration)),
        record_start=rt(record_start),
    )


def test_rational_time_normalizes_and_adds_exactly():
    assert RationalTime(2, 4) == RationalTime(1, 2)
    assert RationalTime(1, 3) + RationalTime(1, 6) == RationalTime(1, 2)
    assert RationalTime.from_seconds(0.1).to_dict() == {
        "numerator": 1,
        "denominator": 10,
    }


def test_insert_splits_current_clip_and_ripples_following_content():
    track = Track("v1", "V1", TrackType.VIDEO, 0, clips=[clip("a.mp4", 0, 10, 0)])
    inserted = clip("b.mp4", 0, 2, 0)

    track.insert_clip(inserted, rt(5), EditMode.INSERT)

    assert [item.asset_path for item in track.clips] == ["a.mp4", "b.mp4", "a.mp4"]
    assert [item.record_range.start for item in track.clips] == [rt(0), rt(5), rt(7)]
    assert [item.record_range.duration for item in track.clips] == [rt(5), rt(2), rt(5)]
    assert track.clips[2].source_range.start == rt(5)


def test_overwrite_preserves_non_overwritten_source_fragments():
    track = Track("v1", "V1", TrackType.VIDEO, 0, clips=[clip("a.mp4", 0, 10, 0)])
    replacement = clip("b.mp4", 0, 4, 0)

    track.insert_clip(replacement, rt(3), EditMode.OVERWRITE)

    assert [item.asset_path for item in track.clips] == ["a.mp4", "b.mp4", "a.mp4"]
    assert [item.record_range.start for item in track.clips] == [rt(0), rt(3), rt(7)]
    assert track.clips[2].source_range.start == rt(7)


def test_extract_closes_removed_range():
    track = Track(
        "v1",
        "V1",
        TrackType.VIDEO,
        0,
        clips=[clip("a.mp4", 0, 5, 0), clip("b.mp4", 0, 5, 5)],
    )

    track.remove(TimeRange(rt(2), rt(4)), EditMode.EXTRACT)

    assert [item.record_range.start for item in track.clips] == [rt(0), rt(2)]
    assert [item.record_range.duration for item in track.clips] == [rt(2), rt(4)]
    assert track.clips[1].source_range.start == rt(1)


def test_ripple_trim_moves_following_clips():
    first = clip("a.mp4", 0, 5, 0)
    second = clip("b.mp4", 0, 5, 5)
    track = Track("v1", "V1", TrackType.VIDEO, 0, clips=[first, second])

    track.ripple_trim(first.clip_id, rt(3))

    assert first.record_range.duration == rt(3)
    assert second.record_range.start == rt(3)


@pytest_asyncio.fixture
async def project_client(tmp_path, monkeypatch):
    monkeypatch.setattr(projects_router, "project_store", ProjectStore(tmp_path / "projects"))
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_project_api_persists_timeline_and_checks_revision(project_client):
    created = await project_client.post("/api/v1/projects", json={"name": "API Project"})
    assert created.status_code == 201
    project = created.json()
    project_id = project["project_id"]
    video_track = next(
        track for track in project["timeline"]["tracks"] if track["track_type"] == "video"
    )

    added = await project_client.post(
        f"/api/v1/projects/{project_id}/tracks/{video_track['track_id']}/clips",
        json={
            "expected_revision": 1,
            "asset_path": "source.mp4",
            "source_range": {
                "start": {"numerator": 0, "denominator": 1},
                "duration": {"numerator": 5, "denominator": 1},
            },
            "record_start": {"numerator": 0, "denominator": 1},
            "mode": "insert",
        },
    )
    assert added.status_code == 200
    assert added.json()["project"]["revision"] == 2

    conflict = await project_client.post(
        f"/api/v1/projects/{project_id}/tracks",
        json={"expected_revision": 1, "track_type": "title", "name": "T1"},
    )
    assert conflict.status_code == 409

    fetched = await project_client.get(f"/api/v1/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json()["timeline"]["duration"] == {
        "numerator": 5,
        "denominator": 1,
    }
