"""
Tests for Post-Clip Microservices
──────────────────────────────────
Covers SubtitleMicroservice, VideoEditorMicroservice, AIGeneratorMicroservice,
ThumbnailMicroservice, and UploaderMicroservice (status + SRT generation).
"""
import asyncio
import os
import tempfile

import pytest

from shared.event_bus import EventBus
from shared.event_schemas import EventType, SystemEvent
from microservices.subtitle.service import SubtitleMicroservice
from microservices.video_editor.service import VideoEditorMicroservice, DEFAULT_PLATFORM_PROFILES
from microservices.ai_generator.service import AIGeneratorMicroservice
from microservices.thumbnail.service import ThumbnailMicroservice
from microservices.uploader.service import UploaderMicroservice


# ── SubtitleMicroservice ─────────────────────────────────────


class TestSubtitleMicroservice:

    def test_initial_status(self):
        bus = EventBus()
        svc = SubtitleMicroservice(event_bus=bus)
        status = svc.get_status()
        assert status["srt_generated"] == 0
        assert status["burn_in_count"] == 0
        assert status["failed"] == 0
        assert status["burn_in_enabled"] is False

    def test_status_with_burn_in(self):
        bus = EventBus()
        svc = SubtitleMicroservice(event_bus=bus, burn_in=True)
        status = svc.get_status()
        assert status["burn_in_enabled"] is True

    def test_format_srt_time(self):
        # 0 seconds
        assert SubtitleMicroservice._format_srt_time(0.0) == "00:00:00,000"
        # 1.5 seconds
        assert SubtitleMicroservice._format_srt_time(1.5) == "00:00:01,500"
        # 61.123 seconds (floating point precision → 122ms)
        assert SubtitleMicroservice._format_srt_time(61.123) == "00:01:01,122"
        # 1 hour
        assert SubtitleMicroservice._format_srt_time(3600.0) == "01:00:00,000"

    def test_format_srt_time_milliseconds(self):
        result = SubtitleMicroservice._format_srt_time(0.999)
        assert result == "00:00:00,999"

    @pytest.mark.asyncio
    async def test_generate_srt(self):
        bus = EventBus()
        svc = SubtitleMicroservice(event_bus=bus)

        segments = [
            {"start": 0.0, "end": 1.5, "text": "Hello world"},
            {"start": 1.5, "end": 3.0, "text": "Second line"},
        ]

        srt_path = await svc._generate_srt(segments, "test_clip_srt")
        assert srt_path is not None
        assert os.path.exists(srt_path)

        content = open(srt_path, encoding="utf-8").read()
        assert "Hello world" in content
        assert "Second line" in content
        assert "00:00:00,000 --> 00:00:01,500" in content
        assert "00:00:01,500 --> 00:00:03,000" in content

        # Cleanup
        os.remove(srt_path)

    @pytest.mark.asyncio
    async def test_on_transcript_no_segments(self):
        bus = EventBus()
        svc = SubtitleMicroservice(event_bus=bus)

        event = SystemEvent(
            event_type=EventType.TRANSCRIPT_READY.value,
            payload={"clip_path": "/fake/path.mp4", "segments": []},
            source_service="test",
        )
        await svc._on_transcript_ready(event)
        # Should not increment counters
        assert svc._srt_generated == 0

    @pytest.mark.asyncio
    async def test_on_transcript_generates_srt(self):
        bus = EventBus()
        received = []
        bus.subscribe(EventType.SUBTITLE_READY.value, lambda e: received.append(e))
        await bus.start()

        svc = SubtitleMicroservice(event_bus=bus)

        event = SystemEvent(
            event_type=EventType.TRANSCRIPT_READY.value,
            payload={
                "clip_path": "/fake/path.mp4",
                "clip_id": "test_sub",
                "segments": [
                    {"start": 0.0, "end": 2.0, "text": "Test subtitle"},
                ],
                "language": "en",
            },
            source_service="test",
        )
        await svc._on_transcript_ready(event)
        await asyncio.sleep(0.1)

        assert svc._srt_generated == 1
        assert len(received) >= 1

        # Cleanup SRT file
        srt_file = "data/subtitles/test_sub.srt"
        if os.path.exists(srt_file):
            os.remove(srt_file)


# ── VideoEditorMicroservice ─────────────────────────────────────


class TestVideoEditorMicroservice:

    def test_initial_status(self):
        bus = EventBus()
        svc = VideoEditorMicroservice(event_bus=bus)
        status = svc.get_status()
        assert status["exports_done"] == 0
        assert status["exports_failed"] == 0
        assert status["auto_export"] is True
        assert "youtube" in status["platforms"]
        assert "tiktok" in status["platforms"]

    def test_custom_platforms(self):
        bus = EventBus()
        svc = VideoEditorMicroservice(event_bus=bus, platforms=["youtube", "shorts"])
        status = svc.get_status()
        assert "shorts" in status["platforms"]

    def test_auto_export_disabled(self):
        bus = EventBus()
        svc = VideoEditorMicroservice(event_bus=bus, auto_export=False)
        status = svc.get_status()
        assert status["auto_export"] is False

    def test_platform_profiles(self):
        assert DEFAULT_PLATFORM_PROFILES["youtube"] == "16:9"
        assert DEFAULT_PLATFORM_PROFILES["tiktok"] == "9:16"
        assert DEFAULT_PLATFORM_PROFILES["instagram_reels"] == "9:16"
        assert DEFAULT_PLATFORM_PROFILES["instagram_post"] == "1:1"
        assert DEFAULT_PLATFORM_PROFILES["shorts"] == "9:16"

    @pytest.mark.asyncio
    async def test_on_clip_created_no_file(self):
        bus = EventBus()
        svc = VideoEditorMicroservice(event_bus=bus)
        event = SystemEvent(
            event_type=EventType.CLIP_CREATED.value,
            payload={"file_path": "/nonexistent/clip.mp4", "clip_id": "test"},
            source_service="test",
        )
        await svc._on_clip_created(event)
        # Should not crash
        assert svc._exports_done == 0


# ── AIGeneratorMicroservice ─────────────────────────────────────


class TestAIGeneratorMicroservice:

    def test_initial_status(self):
        bus = EventBus()
        svc = AIGeneratorMicroservice(event_bus=bus)
        status = svc.get_status()
        assert status["generated"] == 0
        assert status["failed"] == 0
        assert status["streamer_name"] == "Tuncay"
        assert status["default_platform"] == "youtube"

    def test_custom_streamer(self):
        bus = EventBus()
        svc = AIGeneratorMicroservice(event_bus=bus, streamer_name="TestStreamer", default_platform="tiktok")
        status = svc.get_status()
        assert status["streamer_name"] == "TestStreamer"
        assert status["default_platform"] == "tiktok"


# ── ThumbnailMicroservice ─────────────────────────────────────


class TestThumbnailMicroservice:

    def test_initial_status(self):
        bus = EventBus()
        svc = ThumbnailMicroservice(event_bus=bus)
        status = svc.get_status()
        assert status["generated"] == 0
        assert status["failed"] == 0

    def test_custom_time_point(self):
        bus = EventBus()
        svc = ThumbnailMicroservice(event_bus=bus, time_point=2.0)
        assert svc.time_point == 2.0

    @pytest.mark.asyncio
    async def test_on_clip_created_no_file(self):
        bus = EventBus()
        svc = ThumbnailMicroservice(event_bus=bus)
        event = SystemEvent(
            event_type=EventType.CLIP_CREATED.value,
            payload={"file_path": "/nonexistent/clip.mp4", "clip_id": "test"},
            source_service="test",
        )
        await svc._on_clip_created(event)
        assert svc._generated == 0


# ── UploaderMicroservice ─────────────────────────────────────


class TestUploaderMicroservice:

    def test_initial_status(self):
        bus = EventBus()
        svc = UploaderMicroservice(event_bus=bus)
        status = svc.get_status()
        assert status["uploaded"] == 0
        assert status["failed"] == 0
        assert status["pending"] == 0
        assert status["auto_upload"] is False
        assert status["metadata_cached"] == 0

    def test_auto_upload_enabled(self):
        bus = EventBus()
        svc = UploaderMicroservice(event_bus=bus, auto_upload=True)
        status = svc.get_status()
        assert status["auto_upload"] is True

    @pytest.mark.asyncio
    async def test_ai_metadata_caching(self):
        bus = EventBus()
        svc = UploaderMicroservice(event_bus=bus)

        event = SystemEvent(
            event_type=EventType.AI_METADATA_READY.value,
            payload={
                "clip_id": "clip_123",
                "title": "Epic Moment",
                "description": "Amazing clip",
                "hashtags": ["#epic", "#gaming"],
            },
            source_service="ai_generator",
        )
        await svc._on_ai_metadata(event)
        assert svc.get_status()["metadata_cached"] == 1
        assert "clip_123" in svc._metadata_cache

    @pytest.mark.asyncio
    async def test_edit_ready_no_auto_upload(self):
        bus = EventBus()
        svc = UploaderMicroservice(event_bus=bus, auto_upload=False)

        event = SystemEvent(
            event_type=EventType.EDIT_READY.value,
            payload={
                "clip_id": "clip_456",
                "exports": {"youtube": "/fake/path.mp4"},
            },
            source_service="video_editor",
        )
        await svc._on_edit_ready(event)
        # Should not upload when auto_upload is disabled
        assert svc._uploaded == 0

    @pytest.mark.asyncio
    async def test_edit_ready_missing_export_file(self):
        bus = EventBus()
        svc = UploaderMicroservice(event_bus=bus, auto_upload=True)

        event = SystemEvent(
            event_type=EventType.EDIT_READY.value,
            payload={
                "clip_id": "clip_789",
                "exports": {"youtube": "/nonexistent/path.mp4"},
            },
            source_service="video_editor",
        )
        await svc._on_edit_ready(event)
        # File doesn't exist, should skip
        assert svc._uploaded == 0


# ── Cross-Service Event Flow ─────────────────────────────────────


class TestPostClipEventFlow:
    """Tests that all post-clip services subscribe to correct events."""

    def test_all_services_subscribe_correctly(self):
        bus = EventBus()

        sub = SubtitleMicroservice(event_bus=bus)
        vid = VideoEditorMicroservice(event_bus=bus)
        ai = AIGeneratorMicroservice(event_bus=bus)
        thumb = ThumbnailMicroservice(event_bus=bus)
        upload = UploaderMicroservice(event_bus=bus)

        # Check that subscriptions exist (no error on construction)
        assert sub._srt_generated == 0
        assert vid._exports_done == 0
        assert ai._generated == 0
        assert thumb._generated == 0
        assert upload._uploaded == 0

    @pytest.mark.asyncio
    async def test_metadata_cache_pop_on_edit(self):
        bus = EventBus()
        svc = UploaderMicroservice(event_bus=bus, auto_upload=True)

        # Cache metadata
        meta_event = SystemEvent(
            event_type=EventType.AI_METADATA_READY.value,
            payload={"clip_id": "c1", "title": "Test Title", "hashtags": ["#test"]},
            source_service="ai_generator",
        )
        await svc._on_ai_metadata(meta_event)
        assert len(svc._metadata_cache) == 1

        # Process edit (missing file → won't upload but should pop cache)
        edit_event = SystemEvent(
            event_type=EventType.EDIT_READY.value,
            payload={"clip_id": "c1", "exports": {"youtube": "/fake.mp4"}},
            source_service="video_editor",
        )
        await svc._on_edit_ready(edit_event)
        # Cache should be popped even if file missing
        assert len(svc._metadata_cache) == 0


# ── Quality Control regression (post-render QC bug) ──────────────

class TestQualityControlWiring:
    """Regression guard for the QC method-name bug.

    social_video_generator önceden `_qc.check(...)` çağırıyordu ama
    QualityControl'da böyle bir metod yok; AttributeError sessizce
    yutuluyordu ve QC hiç çalışmıyordu. Doğru metod adı `run_qc`.
    """

    def test_quality_control_exposes_run_qc_not_check(self):
        from services.quality_control import QualityControl
        assert hasattr(QualityControl, "run_qc"), "run_qc metodu bulunmalı"
        assert not hasattr(QualityControl, "check"), (
            "QualityControl.check yok — generator run_qc kullanmalı"
        )

    def test_social_generator_calls_run_qc(self):
        import inspect
        from services.social_video_generator import SocialVideoGenerator
        # Sınıftaki QC çağrısını yapan metodu bul ve kaynağını incele.
        src = inspect.getsource(SocialVideoGenerator)
        assert "_qc.run_qc(" in src, "generator _qc.run_qc çağırmalı"
        assert "_qc.check(" not in src, "eski _qc.check çağrısı geri gelmiş!"

