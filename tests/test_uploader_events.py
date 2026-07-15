"""
Tests for AutoPublisher: Event Bus integration + Retry/Backoff.

Covers:
- CLIP_PUBLISHED event emission on success
- STREAM_ERROR event emission on permanent failure
- Exponential backoff retry for transient errors
- No retry for permanent errors (401/403)
- Parallel publish_multi
- Error classification
- Metrics tracking
"""
import asyncio
import math
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared.event_bus import EventBus
from shared.event_schemas import EventType, SystemEvent
from src.uploader import (
    AutoPublisher,
    PublishError,
    PermanentPublishError,
    TransientPublishError,
    classify_http_error,
)


# ─── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
async def event_bus():
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
async def publisher(event_bus):
    return AutoPublisher(event_bus=event_bus)


@pytest.fixture
def video_file():
    """Create a temp video file for testing."""
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.write(fd, b"\x00" * 1024)  # 1KB dummy
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
async def published_events(event_bus):
    """Collect CLIP_PUBLISHED events."""
    events = []

    async def handler(event: SystemEvent):
        events.append(event)

    event_bus.subscribe(EventType.CLIP_PUBLISHED.value, handler)
    return events


@pytest.fixture
async def error_events(event_bus):
    """Collect STREAM_ERROR events."""
    events = []

    async def handler(event: SystemEvent):
        events.append(event)

    event_bus.subscribe(EventType.STREAM_ERROR.value, handler)
    return events


# ─── Error Classification Tests ────────────────────────────────

class TestErrorClassification:
    def test_401_is_permanent(self):
        err = classify_http_error(401, "youtube")
        assert isinstance(err, PermanentPublishError)
        assert err.permanent is True

    def test_403_is_permanent(self):
        err = classify_http_error(403, "tiktok")
        assert isinstance(err, PermanentPublishError)

    def test_400_is_permanent(self):
        err = classify_http_error(400, "instagram")
        assert isinstance(err, PermanentPublishError)

    def test_422_is_permanent(self):
        err = classify_http_error(422, "twitter")
        assert isinstance(err, PermanentPublishError)

    def test_429_is_transient(self):
        err = classify_http_error(429, "youtube")
        assert isinstance(err, TransientPublishError)
        assert err.permanent is False

    def test_500_is_transient(self):
        err = classify_http_error(500, "tiktok")
        assert isinstance(err, TransientPublishError)

    def test_502_is_transient(self):
        err = classify_http_error(502, "instagram")
        assert isinstance(err, TransientPublishError)

    def test_503_is_transient(self):
        err = classify_http_error(503, "twitter")
        assert isinstance(err, TransientPublishError)

    def test_0_is_transient(self):
        err = classify_http_error(0, "kick")
        assert isinstance(err, TransientPublishError)

    def test_418_is_permanent(self):
        err = classify_http_error(418, "youtube")
        assert isinstance(err, PermanentPublishError)

    def test_error_has_platform(self):
        err = classify_http_error(500, "tiktok")
        assert err.platform == "tiktok"
        assert err.http_status == 500


# ─── AutoPublisher Basic Tests ─────────────────────────────────

class TestAutoPublisherBasic:
    def test_init_with_event_bus(self, event_bus):
        pub = AutoPublisher(event_bus=event_bus)
        assert pub.event_bus is event_bus

    def test_init_default_event_bus(self):
        pub = AutoPublisher()
        assert pub.event_bus is not None

    def test_supported_platforms(self, publisher):
        assert "youtube" in publisher.SUPPORTED_PLATFORMS
        assert "tiktok" in publisher.SUPPORTED_PLATFORMS
        assert "instagram" in publisher.SUPPORTED_PLATFORMS
        assert "twitter" in publisher.SUPPORTED_PLATFORMS
        assert "kick" in publisher.SUPPORTED_PLATFORMS

    def test_set_credentials(self, publisher):
        publisher.set_credentials("youtube", {"client_secrets": "abc"})
        assert "youtube" in publisher._credentials
        assert publisher._credentials["youtube"]["client_secrets"] == "abc"

    def test_get_status(self, publisher):
        status = publisher.get_status()
        assert "supported_platforms" in status
        assert "configured_platforms" in status
        assert "metrics" in status
        assert isinstance(status["metrics"]["published"], int)

    @pytest.mark.asyncio
    async def test_publish_nonexistent_file(self, publisher):
        result = await publisher.publish(
            video_path="/nonexistent/path.mp4",
            title="Test",
            platform="youtube",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_publish_unsupported_platform(self, publisher, video_file):
        result = await publisher.publish(
            video_path=video_file,
            title="Test",
            platform="myspace",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_publish_no_credentials(self, publisher, video_file):
        """Platform with no credentials returns None (no retry)."""
        result = await publisher.publish(
            video_path=video_file,
            title="Test",
            platform="youtube",
        )
        assert result is None


# ─── Event Bus Integration Tests ───────────────────────────────

class TestEventBusIntegration:
    @pytest.mark.asyncio
    async def test_success_emits_clip_published(
        self, event_bus, publisher, video_file, published_events,
    ):
        """Successful publish emits CLIP_PUBLISHED event."""
        async def fake_youtube(*args, **kwargs):
            return {
                "platform": "youtube",
                "video_id": "abc123",
                "url": "https://youtube.com/watch?v=abc123",
            }

        publisher._publish_youtube = fake_youtube
        publisher.set_credentials("youtube", {"client_secrets": "test"})

        result = await publisher.publish(
            video_path=video_file,
            title="Test Clip",
            platform="youtube",
            clip_id="clip-001",
            stream_id="stream-001",
        )

        # Wait for event dispatch
        await asyncio.sleep(0.1)

        assert result is not None
        assert result["video_id"] == "abc123"
        assert len(published_events) == 1
        evt = published_events[0]
        assert evt.event_type == EventType.CLIP_PUBLISHED
        assert evt.payload["clip_id"] == "clip-001"
        assert evt.payload["platform"] == "youtube"
        assert evt.payload["video_id"] == "abc123"
        assert evt.payload["url"] == "https://youtube.com/watch?v=abc123"

    @pytest.mark.asyncio
    async def test_permanent_error_emits_stream_error(
        self, event_bus, publisher, video_file, error_events,
    ):
        """Permanent publish error emits STREAM_ERROR."""
        async def fake_youtube(*args, **kwargs):
            raise PermanentPublishError("Auth denied", "youtube", 401)

        publisher._publish_youtube = fake_youtube
        publisher.set_credentials("youtube", {"client_secrets": "bad"})

        result = await publisher.publish(
            video_path=video_file,
            title="Test",
            platform="youtube",
        )

        await asyncio.sleep(0.1)

        assert result is None
        assert len(error_events) == 1
        evt = error_events[0]
        assert evt.event_type == EventType.STREAM_ERROR
        assert "Auth denied" in evt.payload["error"]

    @pytest.mark.asyncio
    async def test_transient_error_retries_then_fails(
        self, event_bus, publisher, video_file, error_events,
    ):
        """Transient error retries MAX_RETRIES times, then emits error."""
        call_count = 0

        async def fake_youtube(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise TransientPublishError("Server down", "youtube", 500)

        publisher._publish_youtube = fake_youtube
        publisher.set_credentials("youtube", {"client_secrets": "test"})
        publisher.MAX_RETRIES = 2
        publisher.RETRY_BASE_SECONDS = 0.01  # Fast for tests

        result = await publisher.publish(
            video_path=video_file,
            title="Test",
            platform="youtube",
        )

        await asyncio.sleep(0.1)

        assert result is None
        # 1 initial + 2 retries = 3 calls
        assert call_count == 3
        assert publisher._metrics["retries"] >= 2
        assert len(error_events) == 1

    @pytest.mark.asyncio
    async def test_transient_then_success(
        self, event_bus, publisher, video_file, published_events,
    ):
        """Retry succeeds after transient failure."""
        call_count = 0

        async def fake_youtube(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise TransientPublishError("Temporary", "youtube", 503)
            return {
                "platform": "youtube",
                "video_id": "retry-success",
                "url": "https://youtube.com/watch?v=retry-success",
            }

        publisher._publish_youtube = fake_youtube
        publisher.set_credentials("youtube", {"client_secrets": "test"})
        publisher.MAX_RETRIES = 3
        publisher.RETRY_BASE_SECONDS = 0.01

        result = await publisher.publish(
            video_path=video_file,
            title="Test",
            platform="youtube",
        )

        await asyncio.sleep(0.1)

        assert result is not None
        assert result["video_id"] == "retry-success"
        assert call_count == 3
        assert len(published_events) == 1


# ─── Retry/Backoff Tests ──────────────────────────────────────

class TestRetryBackoff:
    def test_backoff_delay_increases(self, publisher):
        delays = [publisher._backoff_delay(i) for i in range(5)]
        # Each delay should be >= previous (with small jitter tolerance)
        for i in range(1, len(delays)):
            assert delays[i] >= delays[i - 1] * 0.7  # jitter tolerance

    def test_backoff_max_cap(self, publisher):
        delay = publisher._backoff_delay(100)  # Very large attempt
        assert delay <= publisher.RETRY_MAX_SECONDS + 5  # with jitter

    def test_backoff_min_floor(self, publisher):
        delay = publisher._backoff_delay(0)
        assert delay >= 0.5

    def test_publish_error_classes(self):
        perm = PermanentPublishError("auth", "youtube", 401)
        assert perm.permanent is True
        assert perm.platform == "youtube"
        assert perm.http_status == 401

        trans = TransientPublishError("timeout", "tiktok", 504)
        assert trans.permanent is False
        assert trans.platform == "tiktok"


# ─── publish_multi Tests ───────────────────────────────────────

class TestPublishMulti:
    @pytest.mark.asyncio
    async def test_publish_multi_parallel(
        self, event_bus, publisher, video_file, published_events,
    ):
        """publish_multi uploads to multiple platforms in parallel."""
        call_order = []

        async def fake_platform(platform_name):
            async def _publish(self, *args, **kwargs):
                call_order.append(platform_name)
                await asyncio.sleep(0.05)  # Simulate work
                return {
                    "platform": platform_name,
                    "video_id": f"{platform_name}-123",
                    "url": f"https://{platform_name}.com/v/{platform_name}-123",
                }
            return _publish

        for p in ["youtube", "tiktok", "instagram"]:
            publisher._credentials[p] = {"test": True}
            fn = await fake_platform(p)
            setattr(publisher, f"_publish_{p}", fn)

        results = await publisher.publish_multi(
            video_path=video_file,
            title="Multi Test",
            platforms=["youtube", "tiktok", "instagram"],
            clip_id="multi-001",
        )

        await asyncio.sleep(0.1)

        assert len(results) == 3
        platforms = {r["platform"] for r in results}
        assert platforms == {"youtube", "tiktok", "instagram"}

    @pytest.mark.asyncio
    async def test_publish_multi_partial_failure(
        self, event_bus, publisher, video_file,
    ):
        """publish_multi returns only successful results."""
        async def fake_success(self, *args, **kwargs):
            return {"platform": "youtube", "video_id": "yt-1", "url": ""}

        async def fake_fail(self, *args, **kwargs):
            raise PermanentPublishError("No auth", "tiktok", 401)

        publisher._credentials["youtube"] = {"test": True}
        publisher._credentials["tiktok"] = {"test": True}
        publisher._publish_youtube = fake_success
        publisher._publish_tiktok = fake_fail

        results = await publisher.publish_multi(
            video_path=video_file,
            title="Partial",
            platforms=["youtube", "tiktok"],
        )

        assert len(results) == 1
        assert results[0]["platform"] == "youtube"

    @pytest.mark.asyncio
    async def test_publish_multi_defaults_all_platforms(
        self, event_bus, publisher, video_file,
    ):
        """publish_multi with no platforms list uses SUPPORTED_PLATFORMS."""
        async def fake_ok(self, *args, **kwargs):
            return {"platform": "any", "video_id": "x", "url": ""}

        for p in publisher.SUPPORTED_PLATFORMS:
            publisher._credentials[p] = {"test": True}
            setattr(publisher, f"_publish_{p}", fake_ok)

        results = await publisher.publish_multi(
            video_path=video_file,
            title="All Platforms",
        )

        assert len(results) == len(publisher.SUPPORTED_PLATFORMS)


# ─── Metrics Tests ─────────────────────────────────────────────

class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_published_count(
        self, event_bus, publisher, video_file,
    ):
        async def fake_ok(self, *args, **kwargs):
            return {"platform": "youtube", "video_id": "v1", "url": ""}

        publisher._credentials["youtube"] = {"test": True}
        publisher._publish_youtube = fake_ok

        await publisher.publish(video_file, "T", platform="youtube")
        await publisher.publish(video_file, "T", platform="youtube")

        assert publisher._metrics["published"] == 2
        assert publisher._metrics["by_platform"]["youtube"]["published"] == 2

    @pytest.mark.asyncio
    async def test_metrics_failed_count(
        self, event_bus, publisher, video_file,
    ):
        async def fake_fail(self, *args, **kwargs):
            raise PermanentPublishError("No", "youtube", 401)

        publisher._credentials["youtube"] = {"test": True}
        publisher._publish_youtube = fake_fail

        await publisher.publish(video_file, "T", platform="youtube")

        assert publisher._metrics["failed"] >= 1

    @pytest.mark.asyncio
    async def test_get_status_reflects_configured(self, publisher):
        publisher.set_credentials("youtube", {"key": "x"})
        publisher.set_credentials("tiktok", {"key": "y"})
        status = publisher.get_status()
        assert "youtube" in status["configured_platforms"]
        assert "tiktok" in status["configured_platforms"]


# ─── UploaderMicroservice Integration ──────────────────────────

class TestUploaderMicroserviceIntegration:
    def test_init_shares_event_bus(self, event_bus):
        from microservices.uploader.service import UploaderMicroservice
        ms = UploaderMicroservice(event_bus=event_bus)
        assert ms.event_bus is event_bus

    def test_lazy_publisher_init(self, event_bus):
        from microservices.uploader.service import UploaderMicroservice
        ms = UploaderMicroservice(event_bus=event_bus)
        assert ms._publisher is None

        publisher = ms._get_publisher()
        assert publisher is not None
        assert publisher.event_bus is event_bus

    @pytest.mark.asyncio
    async def test_manual_upload_uses_publisher(self, event_bus, video_file):
        from microservices.uploader.service import UploaderMicroservice
        ms = UploaderMicroservice(event_bus=event_bus)

        # Mock the publisher
        mock_pub = AsyncMock(return_value={
            "platform": "youtube", "video_id": "m1", "url": "http://test",
        })
        mock_publisher = MagicMock()
        mock_publisher.publish = mock_pub
        ms._publisher = mock_publisher

        result = await ms.manual_upload(
            clip_path=video_file,
            platform="youtube",
            title="Manual",
        )

        assert result["video_id"] == "m1"
        mock_pub.assert_called_once()

    def test_status(self, event_bus):
        from microservices.uploader.service import UploaderMicroservice
        ms = UploaderMicroservice(event_bus=event_bus, auto_upload=True)
        status = ms.get_status()
        assert status["auto_upload"] is True
        assert status["uploaded"] == 0
        assert status["failed"] == 0
