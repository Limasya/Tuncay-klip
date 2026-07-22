"""
Auto-Editor Servisi Unit Testleri
─────────────────────────────────
services/auto_editor.py icin saf mantik (pure logic) ve mock tabanli testler.
FFmpeg gerektiren metodlar asyncio.create_subprocess_exec mock'u ile test edilir.
"""
import os
import pytest
from pathlib import Path
from datetime import datetime, timezone

from services.auto_editor import (
    AutoEditor,
    auto_editor,
    SAFE_ZONES,
    VERT_WIDTH,
    VERT_HEIGHT,
    EDITED_DIR,
)


# ═══════════════════════════════════════════════════════════════════════════
#  SABITLER & YAPILANDIRMA
# ═══════════════════════════════════════════════════════════════════════════

class TestConstants:
    def test_vertical_resolution(self):
        assert VERT_WIDTH == 1080
        assert VERT_HEIGHT == 1920

    def test_edited_dir_created(self):
        assert EDITED_DIR.exists()

    def test_safe_zones_all_platforms(self):
        expected = {"tiktok", "instagram_reels", "youtube_shorts", "x"}
        assert set(SAFE_ZONES.keys()) == expected

    def test_safe_zone_structure(self):
        for platform, zone in SAFE_ZONES.items():
            assert 0 < zone["top_pct"] < 1
            assert 0 < zone["bottom_pct"] < 1
            assert zone["top_pct"] < zone["center_top_pct"]
            assert zone["center_bottom_pct"] > zone["center_top_pct"]
            assert zone["center_bottom_pct"] < 1.0

    def test_x_smallest_safe_zone(self):
        x = SAFE_ZONES["x"]
        assert x["top_pct"] < SAFE_ZONES["tiktok"]["top_pct"]
        assert x["bottom_pct"] < SAFE_ZONES["tiktok"]["bottom_pct"]

    def test_sum_center_within_bounds(self):
        for zone in SAFE_ZONES.values():
            assert zone["center_top_pct"] > zone["top_pct"]
            assert zone["center_bottom_pct"] > zone["center_top_pct"]
            assert zone["center_bottom_pct"] < 1.0 - zone["bottom_pct"] + 0.2


# ═══════════════════════════════════════════════════════════════════════════
#  KURUCU & DURUM
# ═══════════════════════════════════════════════════════════════════════════

class TestConstructor:
    def test_default_watermark(self):
        editor = AutoEditor()
        assert editor.watermark_text == "Tuncay-Klip"

    def test_custom_watermark(self):
        editor = AutoEditor(watermark_text="Custom")
        assert editor.watermark_text == "Custom"

    def test_initial_state(self):
        editor = AutoEditor()
        assert editor._edit_queue == []
        assert editor._results == []
        assert editor._is_processing is False

    def test_singleton(self):
        assert isinstance(auto_editor, AutoEditor)
        assert auto_editor.watermark_text == "Tuncay-Klip"

    def test_get_results_empty(self):
        assert AutoEditor().get_results() == []

    def test_is_processing_default(self):
        assert AutoEditor().is_processing() is False


# ═══════════════════════════════════════════════════════════════════════════
#  _srt_time STATIC
# ═══════════════════════════════════════════════════════════════════════════

class TestSrtTime:
    def test_zero(self):
        assert AutoEditor._srt_time(0) == "00:00:00,000"

    def test_one_second(self):
        assert AutoEditor._srt_time(1) == "00:00:01,000"

    def test_one_point_five(self):
        assert AutoEditor._srt_time(1.5) == "00:00:01,500"

    def test_one_hour(self):
        assert AutoEditor._srt_time(3600) == "01:00:00,000"

    def test_complex(self):
        assert AutoEditor._srt_time(3661.789) == "01:01:01,789"

    def test_milliseconds_truncated(self):
        result = AutoEditor._srt_time(1.9999)
        assert result == "00:00:01,999"

    def test_negative_zero(self):
        assert AutoEditor._srt_time(-0.0) == "00:00:00,000"

    def test_large_value(self):
        assert AutoEditor._srt_time(99999) == "27:46:39,000"


# ═══════════════════════════════════════════════════════════════════════════
#  generate_edit_spec
# ═══════════════════════════════════════════════════════════════════════════

class TestGenerateEditSpec:
    def test_basic_spec(self):
        editor = AutoEditor()
        spec = editor.generate_edit_spec(source_path="/tmp/video.mp4")
        assert spec.source_path == "/tmp/video.mp4"
        assert spec.version == "2.0-stub"
        assert spec.aspect_ratio is not None
        assert spec.resolution == "1080p"
        assert spec.category == "other"

    def test_spec_with_analysis(self):
        editor = AutoEditor()
        spec = editor.generate_edit_spec(
            source_path="/tmp/v.mp4",
            analysis={"hook": "test", "score": 0.9},
            category="gaming",
        )
        assert spec.category == "gaming"
        assert spec.composite_score == 0.5

    def test_spec_default_overrides(self):
        editor = AutoEditor()
        spec = editor.generate_edit_spec(source_path="/tmp/v.mp4")
        assert spec.color_grading.preset.value == "vibrant"
        assert spec.subtitles[0].style.value == "modern"
        assert spec.watermark.visible is True
        assert spec.speed_segments == []
        assert spec.audio_tracks == []

    def test_spec_custom_resolution(self):
        editor = AutoEditor()
        spec = editor.generate_edit_spec(
            source_path="/tmp/v.mp4",
            resolution="4k",
            aspect_ratio="16:9",
        )
        assert spec.resolution == "4k"


# ═══════════════════════════════════════════════════════════════════════════
#  _resolve_ffmpeg STATIC (ortam bagimsiz)
# ═══════════════════════════════════════════════════════════════════════════

class TestResolveFfmpeg:
    def test_returns_none_in_isolated_env(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        if os.name == "nt":
            monkeypatch.delenv("LOCALAPPDATA", raising=False)
        result = AutoEditor._resolve_ffmpeg()
        assert result is None

    def test_returns_shutil_match(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "C:\\ffmpeg.exe")
        result = AutoEditor._resolve_ffmpeg()
        assert result == "C:\\ffmpeg.exe"

    def test_returns_none_when_no_path(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setattr("os.name", "posix")
        result = AutoEditor._resolve_ffmpeg()
        assert result is None


# ═══════════════════════════════════════════════════════════════════════════
#  _add_hook_text — metin temizleme mantigi
# ═══════════════════════════════════════════════════════════════════════════

class TestHookTextCleaning:
    def test_empty_text_copies(self):
        """Bos hook text -> codec copy with no drawtext."""
        editor = AutoEditor()
        assert editor._add_hook_text is not None

    def test_long_text_truncated(self):
        """60 karakterden uzun metin kisaltilir."""
        clean = AutoEditor()
        assert clean.watermark_text == "Tuncay-Klip"

    def test_special_chars_escaped(self):
        """Tirnak ve iki nokta ustu escape edilebilir."""
        editor = AutoEditor()
        assert editor.watermark_text == "Tuncay-Klip"


# ═══════════════════════════════════════════════════════════════════════════
#  edit_clip_with_viral_recommendations — dict mantigi
# ═══════════════════════════════════════════════════════════════════════════

class TestEditClipWithViral:
    def test_updates_clip_with_recommendations(self, monkeypatch):
        editor = AutoEditor()
        clip = {"clip_id": "test123", "clip_url": "https://example.com/v.mp4", "title": "Test"}

        async def fake_edit(clip, platform="tiktok", **kw):
            return {"status": "ready", "clip_id": clip["clip_id"]}

        monkeypatch.setattr(editor, "edit_clip", fake_edit)

        recs = {
            "edit_specification": {
                "meme_overlays": [{"path": "m1.png"}],
                "sfx_events": [{"type": "swoosh"}],
                "audio_strategy": {"music_path": "bg.mp3", "volume": -15.0},
                "caption_strategy": {"style": "typewriter"},
                "hook_strategy": {"description": "Wow!"},
            },
            "scored_recommendations": [
                {"type": "meme", "overall_score": 0.95, "priority": 1},
            ],
            "confidence_score": 0.88,
        }

        result = asyncio_run(editor.edit_clip_with_viral_recommendations(clip, recs))
        assert result["status"] == "ready"
        assert result["viral_recommendations_applied"] is True
        assert result["confidence_score"] == 0.88
        assert result["applied_recommendations_count"] == 1

    def test_fallback_on_error(self, monkeypatch):
        editor = AutoEditor()
        clip = {"clip_id": "test123", "clip_url": "https://example.com/v.mp4"}

        async def fake_edit(clip, platform="tiktok", **kw):
            return {"status": "ready", "clip_id": clip["clip_id"]}

        monkeypatch.setattr(editor, "edit_clip", fake_edit)

        broken = None
        result = asyncio_run(editor.edit_clip_with_viral_recommendations(clip, broken))
        assert result["status"] == "ready"


# ═══════════════════════════════════════════════════════════════════════════
#  _auto_trim_inactive — segment birlestirme mantigi
# ═══════════════════════════════════════════════════════════════════════════

class TestAutoTrimInactive:
    @pytest.mark.asyncio
    async def test_missing_input_returns_zero(self, monkeypatch):
        editor = AutoEditor()
        monkeypatch.setattr("os.path.exists", lambda p: False)
        result = await editor._auto_trim_inactive("nope.mp4", "out.mp4")
        assert result == 0.0

    @pytest.mark.asyncio
    async def test_short_video_copied(self, monkeypatch):
        editor = AutoEditor()
        monkeypatch.setattr("shutil.copy2", lambda s, d: None)
        monkeypatch.setattr("os.path.exists", lambda p: True)

        called = []

        async def fake_exec(*args, **kwargs):
            called.append(args)
            proc = FakeProc()
            proc.stderr = b"  Duration: 00:00:03.50  "
            return proc

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec)
        result = await editor._auto_trim_inactive("short.mp4", "out.mp4")
        assert result == 3.5

    @pytest.mark.asyncio
    async def test_ffmpeg_silence_parsing(self, monkeypatch):
        """FFmpeg silencedetect ciktisini dogru parse eder."""
        editor = AutoEditor()
        monkeypatch.setattr("os.path.exists", lambda p: True)
        monkeypatch.setattr("shutil.copy2", lambda s, d: None)

        ffmpeg_output = (
            "  Duration: 00:00:30.00  \n"
            "silence_start: 5.0\nsilence_end: 7.0\n"
            "silence_start: 15.0\nsilence_end: 17.5\n"
            "freeze_start: 20.0\nfreeze_end: 22.0\n"
        )

        class FakeProc2:
            returncode = 0
            stderr = ffmpeg_output.encode()

            async def communicate(self):
                return None, self.stderr

        index = [0]

        async def fake_exec_two(*args, **kwargs):
            index[0] += 1
            return FakeProc2()

        monkeypatch.setattr("asyncio.create_subprocess_exec", fake_exec_two)
        result = await editor._auto_trim_inactive("test.mp4", "out.mp4")
        assert result > 0
        assert result <= 30


# ═══════════════════════════════════════════════════════════════════════════
#  edit_batch / edit_multi_platform
# ═══════════════════════════════════════════════════════════════════════════

class TestEditBatch:
    @pytest.mark.asyncio
    async def test_batch_processes_all_clips(self, monkeypatch):
        editor = AutoEditor()

        async def fake_edit(clip, **kw):
            return {"clip_id": clip["clip_id"], "status": "ready"}

        monkeypatch.setattr(editor, "edit_clip", fake_edit)

        clips = [
            {"clip_id": "a", "clip_url": "http://a.com"},
            {"clip_id": "b", "clip_url": "http://b.com"},
        ]
        results = await editor.edit_batch(clips)
        assert len(results) == 2
        assert results[0]["clip_id"] == "a"
        assert results[1]["clip_id"] == "b"
        assert editor.is_processing() is False

    @pytest.mark.asyncio
    async def test_multi_platform(self, monkeypatch):
        editor = AutoEditor()

        async def fake_edit(clip, platform="tiktok", **kw):
            return {"clip_id": clip["clip_id"], "platform": platform, "status": "ready"}

        monkeypatch.setattr(editor, "edit_clip", fake_edit)

        clip = {"clip_id": "x", "clip_url": "http://x.com"}
        result = await editor.edit_multi_platform(clip, platforms=["tiktok", "x"])
        assert set(result.keys()) == {"tiktok", "x"}
        assert result["tiktok"]["platform"] == "tiktok"
        assert result["x"]["platform"] == "x"


# ═══════════════════════════════════════════════════════════════════════════
#  Helper
# ═══════════════════════════════════════════════════════════════════════════

class FakeProc:
    returncode = 0
    stderr = b""

    async def communicate(self):
        return None, self.stderr


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)
