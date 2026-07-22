"""
Zero-Bandwidth -- Community Clips Pure Function Unit Tests
──────────────────────────────────────────────────────────
Direct module-level function tests for services/zero_bandwidth/community_clips.py
"""
import pytest
from datetime import datetime, timezone
from services.zero_bandwidth.community_clips import (
    _parse_ts,
    _normalize_clip,
    format_clips_for_llm,
    calculate_community_confidence,
    estimate_clip_position,
    detect_clip_clusters,
    validate_clip_timing,
    filter_clips_by_timing,
)


class TestParseTs:
    def test_iso_z_suffix(self):
        dt = _parse_ts("2026-07-18T15:15:05Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2026 and dt.month == 7 and dt.day == 18

    def test_iso_offset(self):
        dt = _parse_ts("2026-07-18T15:15:05+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_space_separated(self):
        dt = _parse_ts("2026-07-18 15:03:51")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.hour == 15

    def test_empty_string(self):
        assert _parse_ts("") is None

    def test_none(self):
        assert _parse_ts(None) is None

    def test_invalid_string(self):
        assert _parse_ts("not-a-date") is None


class TestNormalizeClip:
    def test_basic_clip(self):
        raw = {
            "id": 12345,
            "title": "test clip",
            "views": 100,
            "likes": 10,
            "duration": 30.0,
        }
        result = _normalize_clip(raw)
        assert result is not None
        assert result["clip_id"] == "12345"
        assert result["title"] == "test clip"
        assert result["views"] == 100
        assert result["likes"] == 10
        assert result["duration"] == 30.0

    def test_no_id_returns_none(self):
        assert _normalize_clip({"title": "no id"}) is None

    def test_empty_dict_returns_none(self):
        assert _normalize_clip({}) is None

    def test_creator_dict(self):
        raw = {"clip_id": "1", "creator": {"username": "testuser"}}
        result = _normalize_clip(raw)
        assert result["creator"] == "testuser"

    def test_creator_string(self):
        raw = {"clip_id": "1", "creator": "testuser"}
        result = _normalize_clip(raw)
        assert result["creator"] == "testuser"

    def test_missing_fields_defaults(self):
        raw = {"clip_id": "1"}
        result = _normalize_clip(raw)
        assert result["title"] == ""
        assert result["views"] == 0
        assert result["likes"] == 0
        assert result["duration"] == 0.0

    def test_clip_id_from_id_field(self):
        raw = {"id": "abc", "title": "test"}
        result = _normalize_clip(raw)
        assert result["clip_id"] == "abc"
        assert result["title"] == "test"


class TestCalculateCommunityConfidence:
    def test_base_score(self):
        conf = calculate_community_confidence(views=0, likes=0, max_views=0, cluster_size=1)
        assert conf == pytest.approx(0.50)

    def test_max_views_high_score(self):
        conf = calculate_community_confidence(views=34, likes=0, max_views=34, cluster_size=1)
        assert 0.70 <= conf <= 0.95

    def test_likes_add_bonus(self):
        no_likes = calculate_community_confidence(views=10, likes=0, max_views=34, cluster_size=1)
        with_likes = calculate_community_confidence(views=10, likes=5, max_views=34, cluster_size=1)
        assert with_likes > no_likes

    def test_cluster_bonus(self):
        single = calculate_community_confidence(views=10, likes=0, max_views=34, cluster_size=1)
        clustered = calculate_community_confidence(views=10, likes=0, max_views=34, cluster_size=5)
        assert clustered > single

    def test_cap_at_095(self):
        conf = calculate_community_confidence(views=1000, likes=100, max_views=1000, cluster_size=10)
        assert conf <= 0.95

    def test_zero_max_views_no_bonus(self):
        conf = calculate_community_confidence(views=100, likes=0, max_views=0, cluster_size=1)
        assert conf == pytest.approx(0.50)


class TestEstimateClipPosition:
    def test_basic_position(self):
        pos = estimate_clip_position(
            {"created_at": "2026-07-18T15:15:05Z"},
            "2026-07-18 15:03:51",
        )
        assert pos is not None
        assert pos == pytest.approx(674, abs=5)

    def test_no_created_at(self):
        pos = estimate_clip_position({"title": "test"}, "2026-07-18 15:03:51")
        assert pos is None

    def test_no_vod_start(self):
        pos = estimate_clip_position({"created_at": "2026-07-18T15:15:05Z"}, "")
        assert pos is None

    def test_empty_clip(self):
        pos = estimate_clip_position({}, "2026-07-18 15:03:51")
        assert pos is None

    def test_negative_diff_returns_negative(self):
        pos = estimate_clip_position(
            {"created_at": "2026-07-18T14:00:00Z"},
            "2026-07-18 15:03:51",
        )
        assert pos is not None
        assert pos < 0


class TestFormatClipsForLlm:
    def test_empty_list(self):
        result = format_clips_for_llm([])
        assert result == ""

    def test_single_clip(self):
        clips = [{"title": "Test Clip", "views": 50, "likes": 5, "duration": 30}]
        result = format_clips_for_llm(clips)
        assert "Test Clip" in result
        assert "izlenme: 50" in result
        assert "begeni: 5" in result

    def test_with_position(self):
        clips = [{"created_at": "2026-07-18T15:15:05Z", "title": "Pos Clip", "views": 10, "likes": 1, "duration": 30}]
        result = format_clips_for_llm(clips, vod_start_time="2026-07-18 15:03:51", vod_duration=14996)
        assert "[~" in result
        assert "%" in result

    def test_max_10_clips(self):
        clips = [{"title": f"Clip {i}", "views": i, "likes": 0, "duration": 30} for i in range(20)]
        result = format_clips_for_llm(clips)
        assert len([l for l in result.split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10."))]) == 10

    def test_clip_without_title(self):
        clips = [{"views": 0, "likes": 0, "duration": 15}]
        result = format_clips_for_llm(clips)
        assert "Baslik yok" in result


class TestDetectClipClusters:
    def test_no_clips(self):
        assert detect_clip_clusters([], "") == []

    def test_single_clip(self):
        clips = [{"created_at": "2026-07-18T15:15:05Z"}]
        clusters = detect_clip_clusters(clips, "2026-07-18 15:03:51")
        assert clusters == [1]

    def test_two_close_clips(self):
        clips = [
            {"created_at": "2026-07-18T15:15:05Z"},
            {"created_at": "2026-07-18T15:16:05Z"},
        ]
        clusters = detect_clip_clusters(clips, "2026-07-18 15:03:51")
        assert clusters[0] == 2
        assert clusters[1] == 2

    def test_two_distant_clips(self):
        clips = [
            {"created_at": "2026-07-18T15:15:05Z"},
            {"created_at": "2026-07-18T16:15:05Z"},
        ]
        clusters = detect_clip_clusters(clips, "2026-07-18 15:03:51")
        assert clusters[0] == 1
        assert clusters[1] == 1

    def test_three_clips_two_in_cluster(self):
        clips = [
            {"created_at": "2026-07-18T15:15:05Z"},
            {"created_at": "2026-07-18T15:16:05Z"},
            {"created_at": "2026-07-18T17:00:00Z"},
        ]
        clusters = detect_clip_clusters(clips, "2026-07-18 15:03:51")
        assert clusters[0] == 2
        assert clusters[1] == 2
        assert clusters[2] == 1

    def test_missing_created_at_uses_zero(self):
        clips = [
            {"title": "no date"},
            {"created_at": "2026-07-18T15:15:05Z"},
        ]
        clusters = detect_clip_clusters(clips, "2026-07-18 15:03:51")
        assert len(clusters) == 2


class TestValidateClipTiming:
    def test_clip_in_range(self):
        valid, reason = validate_clip_timing(
            {"created_at": "2026-07-18T15:15:05Z"}, "2026-07-18 15:03:51", 14996,
        )
        assert valid

    def test_clip_before_vod(self):
        valid, reason = validate_clip_timing(
            {"created_at": "2026-07-18T14:53:51Z"}, "2026-07-18 15:03:51", 14996,
        )
        assert not valid

    def test_clip_after_vod(self):
        valid, reason = validate_clip_timing(
            {"created_at": "2026-07-18T19:19:00Z"}, "2026-07-18 15:03:51", 14996,
        )
        assert not valid

    def test_tolerance_accepts_boundary(self):
        valid, reason = validate_clip_timing(
            {"created_at": "2026-07-18T15:01:51Z"}, "2026-07-18 15:03:51", 14996, tolerance_sec=120,
        )
        assert valid

    def test_tolerance_rejects_outside(self):
        valid, reason = validate_clip_timing(
            {"created_at": "2026-07-18T14:59:00Z"}, "2026-07-18 15:03:51", 14996, tolerance_sec=120,
        )
        assert not valid

    def test_no_created_at_passes(self):
        valid, reason = validate_clip_timing({"title": "test"}, "2026-07-18 15:03:51", 14996)
        assert valid

    def test_no_vod_start_passes(self):
        valid, reason = validate_clip_timing({"created_at": "2026-07-18T15:15:05Z"}, "", 14996)
        assert valid


class TestFilterClipsByTiming:
    def test_mixed_clips(self):
        clips = [
            {"created_at": "2026-07-18T15:15:05Z", "title": "good"},
            {"created_at": "2026-07-18T14:50:00Z", "title": "bad"},
            {"created_at": "2026-07-18T20:00:00Z", "title": "bad2"},
        ]
        valid = filter_clips_by_timing(clips, "2026-07-18 15:03:51", 14996)
        assert len(valid) == 1
        assert valid[0]["title"] == "good"

    def test_all_good(self):
        clips = [
            {"created_at": "2026-07-18T15:15:05Z", "title": "a"},
            {"created_at": "2026-07-18T15:20:00Z", "title": "b"},
        ]
        valid = filter_clips_by_timing(clips, "2026-07-18 15:03:51", 14996)
        assert len(valid) == 2

    def test_all_bad(self):
        clips = [
            {"created_at": "2026-07-18T10:00:00Z", "title": "a"},
            {"created_at": "2026-07-19T10:00:00Z", "title": "b"},
        ]
        valid = filter_clips_by_timing(clips, "2026-07-18 15:03:51", 14996)
        assert len(valid) == 0

    def test_empty_list(self):
        assert filter_clips_by_timing([], "2026-07-18 15:03:51", 14996) == []

    def test_no_date_clips_always_pass(self):
        clips = [
            {"title": "no date 1"},
            {"title": "no date 2"},
        ]
        valid = filter_clips_by_timing(clips, "2026-07-18 15:03:51", 14996)
        assert len(valid) == 2
