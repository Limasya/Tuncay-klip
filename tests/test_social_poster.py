"""
Tests for services/social_poster.py — Postiz self-hosted social media poster.

Kapsam:
  - Config creation
  - Singleton creation
  - Status reporting when not initialized
  - Integration data class
  - Post data class
  - Mock Postiz API: initialize, list_integrations, create_post, post_now
  - Error handling: Postiz unavailable, upload failure
  - Cross-platform posting
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.social_poster import (
    SocialPoster,
    PostizConfig,
    PostizIntegration,
    ScheduledPost,
    social_poster,
)


class TestConfig:
    def test_default_config(self):
        cfg = PostizConfig()
        assert cfg.base_url == "http://localhost:5000"
        assert cfg.api_key == ""
        assert cfg.timeout == 30.0

    def test_custom_config(self):
        cfg = PostizConfig(base_url="http://my-postiz:5000", api_key="sk-test")
        assert cfg.base_url == "http://my-postiz:5000"
        assert cfg.api_key == "sk-test"


class TestDataClasses:
    def test_integration(self):
        integ = PostizIntegration(id="1", name="My TikTok", platform="tiktok", username="tuncay")
        assert integ.platform == "tiktok"
        assert integ.active is True

    def test_scheduled_post(self):
        post = ScheduledPost(id="p1", content="Hello", integration_ids=["1"], scheduled_at=1000.0)
        assert post.status == "pending"
        assert post.media_urls == []


class TestSingleton:
    def test_singleton_exists(self):
        assert social_poster is not None
        assert isinstance(social_poster, SocialPoster)


class TestStatusWhenNotInitialized:
    def test_status_not_init(self):
        poster = SocialPoster()
        status = poster.get_status()
        assert status["initialized"] is False
        assert status["integrations_count"] == 0

    @pytest.mark.asyncio
    async def test_list_integrations_not_init(self):
        poster = SocialPoster()
        result = await poster.list_integrations()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_integration_not_init(self):
        poster = SocialPoster()
        result = await poster.get_integration("tiktok")
        assert result is None

    @pytest.mark.asyncio
    async def test_post_now_not_init(self):
        poster = SocialPoster()
        result = await poster.post_now("hello", "tiktok")
        assert result is None


class TestInitialize:
    @pytest.mark.asyncio
    async def test_initialize_success(self):
        poster = SocialPoster(PostizConfig(base_url="http://fake:5000"))
        mock_client = AsyncMock()
        # Health check
        health_resp = MagicMock()
        health_resp.status_code = 200
        # Integrations
        integ_resp = MagicMock()
        integ_resp.status_code = 200
        integ_resp.json.return_value = [
            {"id": "integ-1", "name": "TikTok", "type": "tiktok", "username": "tuncay", "active": True}
        ]
        mock_client.get = AsyncMock(side_effect=[health_resp, integ_resp])

        with patch("services.social_poster.httpx.AsyncClient", return_value=mock_client):
            result = await poster.initialize()

        assert result is True
        assert poster._initialized is True
        assert len(poster._integrations) == 1
        assert poster._integrations[0].platform == "tiktok"
        await poster.close()

    @pytest.mark.asyncio
    async def test_initialize_health_fail(self):
        poster = SocialPoster(PostizConfig(base_url="http://fake:5000"))
        mock_client = AsyncMock()
        health_resp = MagicMock()
        health_resp.status_code = 500
        mock_client.get = AsyncMock(return_value=health_resp)

        with patch("services.social_poster.httpx.AsyncClient", return_value=mock_client):
            result = await poster.initialize()

        assert result is False
        assert poster._initialized is False

    @pytest.mark.asyncio
    async def test_initialize_connection_error(self):
        poster = SocialPoster(PostizConfig(base_url="http://fake:5000"))
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("refused"))

        with patch("services.social_poster.httpx.AsyncClient", return_value=mock_client):
            result = await poster.initialize()

        assert result is False


class TestCreatePost:
    @pytest.mark.asyncio
    async def test_create_post_now(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._integrations = [PostizIntegration(id="i1", name="TT", platform="tiktok")]
        mock_client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "post-1"}
        mock_client.post = AsyncMock(return_value=resp)
        poster._client = mock_client

        result = await poster.create_post(
            content="Efsane clutch!",
            integration_ids=["i1"],
        )
        assert result is not None
        assert result.id == "post-1"
        assert result.status == "published"

    @pytest.mark.asyncio
    async def test_create_post_scheduled(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "post-2"}
        poster._client.post = AsyncMock(return_value=resp)

        result = await poster.create_post(
            content="Scheduled post",
            integration_ids=["i1"],
            scheduled_at=1700000000.0,
        )
        assert result is not None
        assert result.status == "scheduled"

    @pytest.mark.asyncio
    async def test_create_post_api_error(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "bad request"
        poster._client.post = AsyncMock(return_value=resp)

        result = await poster.create_post(content="fail", integration_ids=["i1"])
        assert result is None


class TestPostNow:
    @pytest.mark.asyncio
    async def test_post_now_with_integration(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._integrations = [PostizIntegration(id="i1", name="YT", platform="youtube")]
        poster._client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "p3"}
        poster._client.post = AsyncMock(return_value=resp)

        result = await poster.post_now("Video title", "youtube")
        assert result is not None
        assert result.integration_ids == ["i1"]

    @pytest.mark.asyncio
    async def test_post_now_no_integration(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._integrations = []

        result = await poster.post_now("hello", "tiktok")
        assert result is None


class TestCrossPlatform:
    @pytest.mark.asyncio
    async def test_cross_platform(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._integrations = [
            PostizIntegration(id="i1", name="TT", platform="tiktok"),
            PostizIntegration(id="i2", name="IG", platform="instagram"),
        ]
        poster._client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"id": "cp-1"}
        poster._client.post = AsyncMock(return_value=resp)

        results = await poster.post_cross_platform(
            content="Cross post!",
            platforms=["tiktok", "instagram"],
        )
        assert "tiktok" in results
        assert "instagram" in results
        assert results["tiktok"] is not None


class TestUploadMedia:
    @pytest.mark.asyncio
    async def test_upload_not_initialized(self):
        poster = SocialPoster()
        result = await poster.upload_media("/tmp/video.mp4", "i1")
        assert result is None

    @pytest.mark.asyncio
    async def test_upload_success(self, tmp_path):
        poster = SocialPoster()
        poster._initialized = True
        poster._client = AsyncMock()
        resp = MagicMock()
        resp.status_code = 201
        resp.json.return_value = {"url": "https://cdn.postiz.com/video.mp4"}
        poster._client.post = AsyncMock(return_value=resp)

        # Create a temp file
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake video data")

        result = await poster.upload_media(str(video), "i1")
        assert result == "https://cdn.postiz.com/video.mp4"


class TestGetIntegration:
    @pytest.mark.asyncio
    async def test_get_integration_found(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._integrations = [
            PostizIntegration(id="i1", name="TT", platform="tiktok"),
            PostizIntegration(id="i2", name="IG", platform="instagram"),
        ]
        result = await poster.get_integration("instagram")
        assert result is not None
        assert result.id == "i2"

    @pytest.mark.asyncio
    async def test_get_integration_not_found(self):
        poster = SocialPoster()
        poster._initialized = True
        poster._integrations = []
        result = await poster.get_integration("tiktok")
        assert result is None
