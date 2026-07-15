"""
Tests for Notification API Endpoints + Rate Limiter
─────────────────────────────────────────────────────
Covers /api/pipeline/notifications endpoints and RateLimiter utility.
"""
import time

import pytest
from fastapi.testclient import TestClient

from utils.rate_limiter import RateLimiter


# ── RateLimiter Unit Tests ─────────────────────────────────────


class TestRateLimiter:

    def test_initial_state(self):
        rl = RateLimiter(max_requests=10, window_seconds=60)
        stats = rl.get_stats()
        assert stats["max_requests"] == 10
        assert stats["window_seconds"] == 60
        assert stats["active_clients"] == 0
        assert stats["total_requests"] == 0
        assert stats["blocked_requests"] == 0

    def test_allow_within_limit(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        for i in range(5):
            allowed, headers = rl.check_rate_limit("client-1")
            assert allowed is True
            assert "X-RateLimit-Remaining" in headers

    def test_block_exceeding_limit(self):
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            allowed, _ = rl.check_rate_limit("client-2")
            assert allowed is True
        # 4th should be blocked
        allowed, headers = rl.check_rate_limit("client-2")
        assert allowed is False
        assert "Retry-After" in headers
        assert rl.get_stats()["blocked_requests"] == 1

    def test_different_clients_independent(self):
        rl = RateLimiter(max_requests=2, window_seconds=60)
        allowed_a, _ = rl.check_rate_limit("client-a")
        allowed_b, _ = rl.check_rate_limit("client-b")
        assert allowed_a is True
        assert allowed_b is True
        # Exhaust client-a
        rl.check_rate_limit("client-a")
        allowed_a2, _ = rl.check_rate_limit("client-a")
        allowed_b2, _ = rl.check_rate_limit("client-b")
        assert allowed_a2 is False  # client-a blocked
        assert allowed_b2 is True  # client-b still ok

    def test_remaining_decrements(self):
        rl = RateLimiter(max_requests=5, window_seconds=60)
        _, h1 = rl.check_rate_limit("c1")
        _, h2 = rl.check_rate_limit("c1")
        assert int(h1["X-RateLimit-Remaining"]) == 4
        assert int(h2["X-RateLimit-Remaining"]) == 3

    def test_cleanup_removes_expired(self):
        rl = RateLimiter(max_requests=5, window_seconds=1)
        rl.check_rate_limit("old-client")
        assert rl.get_stats()["active_clients"] == 1
        # Wait for window to expire
        time.sleep(1.1)
        rl.cleanup()
        assert rl.get_stats()["active_clients"] == 0

    def test_exclude_paths(self):
        rl = RateLimiter(exclude_paths=["/health", "/api/pipeline/ws"])
        assert rl._should_exclude("/health") is True
        assert rl._should_exclude("/api/pipeline/ws/events") is True
        assert rl._should_exclude("/api/clips") is False

    def test_rate_limit_headers_present(self):
        rl = RateLimiter(max_requests=10, window_seconds=60)
        _, headers = rl.check_rate_limit("test")
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers
        assert "X-RateLimit-Reset" in headers


# ── Notification API Integration Tests ─────────────────────────────


class TestNotificationAPI:

    @pytest.fixture
    def client(self):
        from main import app
        return TestClient(app)

    def test_get_notifications_empty(self, client):
        resp = client.get("/api/pipeline/notifications")
        assert resp.status_code == 200
        data = resp.json()
        # Either not_configured or has webhooks
        assert "webhooks" in data or "status" in data

    def test_add_webhook(self, client):
        resp = client.post("/api/pipeline/notifications/webhook", json={
            "url": "https://example.com/hook",
            "webhook_type": "generic",
            "label": "test-api-hook",
            "events": ["clip.created"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "added"
        assert data["label"] == "test-api-hook"

    def test_get_notifications_after_add(self, client):
        # Add webhook first
        client.post("/api/pipeline/notifications/webhook", json={
            "url": "https://example.com/hook2",
            "webhook_type": "discord",
            "label": "discord-test",
        })
        resp = client.get("/api/pipeline/notifications")
        assert resp.status_code == 200
        data = resp.json()
        assert data["webhooks_count"] >= 1

    def test_remove_webhook(self, client):
        # Add then remove
        client.post("/api/pipeline/notifications/webhook", json={
            "url": "https://example.com/hook3",
            "webhook_type": "generic",
            "label": "to-remove",
        })
        resp = client.delete("/api/pipeline/notifications/webhook/to-remove")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "removed"

    def test_remove_nonexistent_webhook(self, client):
        resp = client.delete("/api/pipeline/notifications/webhook/nonexistent-hook")
        assert resp.status_code == 404

    def test_add_discord_webhook(self, client):
        resp = client.post("/api/pipeline/notifications/webhook", json={
            "url": "https://discord.com/api/webhooks/123/abc",
            "webhook_type": "discord",
            "label": "discord-prod",
            "events": ["clip.created", "viewer.donation"],
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "discord"

    def test_add_telegram_webhook(self, client):
        resp = client.post("/api/pipeline/notifications/webhook", json={
            "url": "https://api.telegram.org/bot123/sendMessage?chat_id=456",
            "webhook_type": "telegram",
            "label": "telegram-prod",
        })
        assert resp.status_code == 200
        assert resp.json()["type"] == "telegram"
