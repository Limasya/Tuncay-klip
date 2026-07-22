"""
Zero-Bandwidth -- VOD Metadata Pure Function Unit Tests
─────────────────────────────────────────────────────────
Direct module-level function tests for services/zero_bandwidth/vod_metadata.py
"""
import pytest
from services.zero_bandwidth.vod_metadata import extract_vod_id, _normalize_vod_metadata


class TestExtractVodId:
    def test_standard_kick_url(self):
        vod_id = extract_vod_id("https://kick.com/thetuncay/videos/12345")
        assert vod_id == "12345"

    def test_any_channel_url(self):
        vod_id = extract_vod_id("https://kick.com/anychannel/videos/99999")
        assert vod_id == "99999"

    def test_direct_video_endpoint(self):
        vod_id = extract_vod_id("https://kick.com/video/55555")
        assert vod_id == "55555"

    def test_no_match_returns_none(self):
        assert extract_vod_id("https://kick.com/") is None

    def test_random_url_returns_none(self):
        assert extract_vod_id("https://example.com/random/path") is None

    def test_empty_string_returns_none(self):
        assert extract_vod_id("") is None

    def test_trailing_slash(self):
        vod_id = extract_vod_id("https://kick.com/thetuncay/videos/12345/")
        assert vod_id == "12345"


class TestNormalizeVodMetadata:
    def test_basic_metadata(self):
        raw = {
            "id": 12345,
            "session_title": "Test Stream | !dc",
            "duration": 14996000,
            "categories": [{"id": 15, "name": "Just Chatting"}],
            "start_time": "2026-07-18 15:03:51",
            "created_at": "2026-07-18 15:03:53",
        }
        result = _normalize_vod_metadata(raw, "https://kick.com/thetuncay/videos/12345")
        assert result["id"] == 12345
        assert result["session_title"] == "Test Stream | !dc"
        assert result["title"] == "Test Stream | !dc"
        assert result["category"] == "Just Chatting"
        assert result["vod_url"] == "https://kick.com/thetuncay/videos/12345"

    def test_duration_ms_conversion(self):
        raw = {"id": 1, "duration": 14996000}
        result = _normalize_vod_metadata(raw, "")
        assert result["duration"] == pytest.approx(14996.0)

    def test_duration_sec_preserved(self):
        raw = {"id": 1, "duration": 5196}
        result = _normalize_vod_metadata(raw, "")
        assert result["duration"] == pytest.approx(5196.0)

    def test_duration_zero_defaults_to_3600(self):
        raw = {"id": 1, "duration": 0}
        result = _normalize_vod_metadata(raw, "")
        assert result["duration"] == pytest.approx(3600.0)

    def test_no_duration_defaults_to_3600(self):
        raw = {"id": 1}
        result = _normalize_vod_metadata(raw, "")
        assert result["duration"] == pytest.approx(3600.0)

    def test_title_fallback_to_session_title(self):
        raw = {"id": 1, "session_title": "Live Now!"}
        result = _normalize_vod_metadata(raw, "")
        assert result["title"] == "Live Now!"

    def test_title_fallback_to_title(self):
        raw = {"id": 1, "title": "VOD Title"}
        result = _normalize_vod_metadata(raw, "")
        assert result["title"] == "VOD Title"

    def test_categories_string(self):
        raw = {"id": 1, "categories": "Just Chatting"}
        result = _normalize_vod_metadata(raw, "")
        assert result["category"] == "Just Chatting"

    def test_categories_empty(self):
        raw = {"id": 1}
        result = _normalize_vod_metadata(raw, "")
        assert result["category"] == ""

    def test_start_time_preferred(self):
        raw = {"id": 1, "start_time": "2026-07-18 15:00:00", "created_at": "2026-07-18 15:01:00"}
        result = _normalize_vod_metadata(raw, "")
        assert result["start_time"] == "2026-07-18 15:00:00"

    def test_fallback_to_created_at(self):
        raw = {"id": 1, "created_at": "2026-07-18 15:01:00"}
        result = _normalize_vod_metadata(raw, "")
        assert result["start_time"] == "2026-07-18 15:01:00"
