"""
Tests for Analytics API + ClipAnalytics Model
──────────────────────────────────────────────
Covers ClipAnalytics model and /api/analytics endpoints.
"""
import pytest
from fastapi.testclient import TestClient

from models.database import ClipAnalytics


# ── ClipAnalytics Model Tests ─────────────────────────────────────


class TestClipAnalyticsModel:

    def test_compute_engagement_rate_with_views(self):
        a = ClipAnalytics(
            clip_id=1, platform="youtube",
            views=100, likes=10, comments=5, shares=3,
        )
        rate = a.compute_engagement_rate()
        assert rate == pytest.approx(18.0)  # (10+5+3)/100 * 100

    def test_compute_engagement_rate_zero_views(self):
        a = ClipAnalytics(clip_id=1, platform="youtube", views=0, likes=10)
        assert a.compute_engagement_rate() == 0.0

    def test_compute_engagement_rate_no_interactions(self):
        a = ClipAnalytics(clip_id=1, platform="youtube", views=500, likes=0, comments=0, shares=0)
        assert a.compute_engagement_rate() == 0.0

    def test_to_dict(self):
        a = ClipAnalytics(
            clip_id=42, platform="tiktok",
            views=1000, likes=200, shares=50,
            comments=30, impressions=5000,
            watch_time_seconds=120.5,
            avg_watch_percentage=75.0,
            engagement_rate=28.0,
        )
        d = a.to_dict()
        assert d["clip_id"] == 42
        assert d["platform"] == "tiktok"
        assert d["views"] == 1000
        assert d["impressions"] == 5000
        assert d["engagement_rate"] == 28.0

    def test_defaults(self):
        a = ClipAnalytics(clip_id=1, platform="youtube")
        # SQLAlchemy defaults apply on insert, not instantiation
        assert a.clip_id == 1
        assert a.platform == "youtube"


# ── Analytics API Integration Tests ─────────────────────────────


class TestAnalyticsAPI:

    @pytest.fixture
    def client(self):
        from main import app
        return TestClient(app)

    def test_summary_empty(self, client):
        resp = client.get("/api/analytics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_views" in data
        assert "top_clips" in data

    def test_summary_with_platform_filter(self, client):
        resp = client.get("/api/analytics/summary?platform=youtube")
        assert resp.status_code == 200
        assert resp.json()["platform_filter"] == "youtube"

    def test_clip_analytics_empty(self, client):
        resp = client.get("/api/analytics/clip/999")
        assert resp.status_code == 200
        data = resp.json()
        assert data["clip_id"] == 999
        assert data["analytics"] == []
        assert data["summary"] is None

    def test_update_analytics(self, client):
        # Need a clip to exist first
        resp = client.post("/api/analytics/update", json={
            "clip_id": 1,
            "platform": "youtube",
            "views": 500,
            "likes": 50,
            "comments": 10,
            "shares": 5,
            "impressions": 2000,
            "watch_time_seconds": 60.0,
            "avg_watch_percentage": 80.0,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "recorded"
        assert data["engagement_rate"] > 0

    def test_platform_analytics(self, client):
        resp = client.get("/api/analytics/platform/youtube")
        assert resp.status_code == 200
        data = resp.json()
        assert data["platform"] == "youtube"
        assert "total_views" in data
