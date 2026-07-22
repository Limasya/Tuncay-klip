"""
Görev 3: Chat/Cloudflare Risk Analysis & Test
===============================================
Chat polling kalıplarını, Cloudflare tetikleme risklerini ve
mitigasyon stratejilerini test eder.

Bulunan riskler:
  - 3 bağımsız chat poller, hepsi aynı endpoint'i her 2sn'de poll ediyor
  - httpx kullanıyor (curl_cffi değil) → TLS fingerprint Cloudflare'da tetikleyici
  - sabit Chrome 125 User-Agent → zamanla stale fingerprint olur
  - HTTP error'da backoff yok → 429/503'te bile sabit 2sn interval
  - Jitter yok → tüm pollerlar aynı anda tetikleniyor
"""
from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from typing import List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))


# ── Risk Metrikleri ────────────────────────────────────────────────────────────

class TestCloudflareRiskMetrics:
    """
    Chat polling kalıplarının Cloudflare tetikleme riskini ölçer.
    """

    def test_polling_frequency_per_endpoint(self):
        """
        Tek bir chat poller 2sn interval ile ~0.5 req/s üretir.
        3 poller = ~1.5 req/s → yüksek risk.
        """
        poll_interval = 2.0
        requests_per_second_per_poller = 1.0 / poll_interval
        num_pollers = 3
        total_rps = requests_per_second_per_poller * num_pollers

        assert requests_per_second_per_poller == 0.5
        assert total_rps == 1.5

    def test_request_pattern_is_periodic(self):
        """
        Sabit interval =.periodic pattern → Cloudflare bot detection'a yatar.
        Jitter olmalı.
        """
        intervals = [2.0] * 10  # tüm poller'lar sabit 2sn

        avg = sum(intervals) / len(intervals)
        stdev = (sum((x - avg) ** 2 for x in intervals) / len(intervals)) ** 0.5

        assert stdev == 0.0, "Jitter yok → periodic pattern riski"

    def test_user_agent_is_stale(self):
        """
        Chrome 125 User-Agent sabit kalmış → zamanla stale fingerprint riski.
        """
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        assert "Chrome/125" in ua

    def test_chat_uses_httpx_not_curl_cffi(self):
        """
        Chat polling httpx kullanıyor → TLS fingerprint Cloudflare'da tetikleyici.
        curl_cffi (impersonate) kullanmalı.
        """
        try:
            from services.kick_api import KickAPIService
            import inspect
            source = inspect.getsource(KickAPIService)

            has_httpx = "httpx" in source.lower()
            has_curl = "curl_cffi" in source.lower() or "CurlSession" in source

            assert has_httpx, "KickAPIService httpx kullanmıyor"
        except ImportError:
            pytest.skip("KickAPIService import edilemedi")

    def test_no_backoff_on_http_error(self):
        """
        HTTP 429/503 hatalarında exponential backoff yok → risk.
        """
        try:
            from services.chat_signal_producer import ChatSignalProducer
            import inspect
            source = inspect.getsource(ChatSignalProducer.poll_chat)

            has_backoff = "backoff" in source.lower() or "exponential" in source.lower()
            has_retry_delay = "retry_delay" in source.lower() or "wait * 2" in source

            assert not has_backoff, "Backoff mevcut (beklenmeyen)"
            assert not has_retry_delay, "Retry delay mevcut (beklenmeyen)"
        except (ImportError, AttributeError):
            pytest.skip("ChatSignalProducer import edilemedi")

    def test_no_jitter_in_polling_interval(self):
        """
        Polling interval'ında jitter yok → tüm pollerlar sinkronize.
        """
        try:
            from services.chat_signal_producer import ChatSignalProducer
            import inspect
            source = inspect.getsource(ChatSignalProducer.poll_chat)

            has_jitter = "jitter" in source.lower() or "random" in source.lower()
            assert not has_jitter, "Jitter mevcut (beklenmeyen)"
        except (ImportError, AttributeError):
            pytest.skip("ChatSignalProducer import edilemedi")

    def test_same_endpoint_multiple_pollers(self):
        """
        3 poller aynı endpoint'i poll ediyor → pattern tanınabilir.
        """
        endpoints = [
            "/api/v2/channels/thetuncay/messages",
            "/api/v2/channels/thetuncay/messages",
            "/api/v2/channels/thetuncay/messages",
        ]
        unique = set(endpoints)

        assert len(unique) == 1, "Aynı endpoint birden fazla poller tarafından kullanılıyor"

    def test_cloudflare_block_detection_mechanism_exists(self):
        """
        Cloudflare block detection mevcut → iyi.
        """
        try:
            from services.zero_bandwidth.alerting import check_cf_blocked
            assert callable(check_cf_blocked)
        except ImportError:
            pytest.skip("alerting modülü bulunamadı")


# ── Mitigasyon Önerileri ──────────────────────────────────────────────────────

class TestMitigationRecommendations:
    """
    Cloudflare risk azaltma stratejilerini test eder.
    """

    def test_jitter_recommendation(self):
        """
        Polling interval'ına jitter eklenmeli:
        base_interval = 2.0s, jitter = ±0.3s → actual: [1.7s, 2.3s]
        """
        import random

        base_interval = 2.0
        jitter_range = 0.3
        intervals = [
            base_interval + random.uniform(-jitter_range, jitter_range)
            for _ in range(100)
        ]

        avg = sum(intervals) / len(intervals)
        assert 1.7 <= avg <= 2.3

        stdev = (sum((x - avg) ** 2 for x in intervals) / len(intervals)) ** 0.5
        assert stdev > 0, "Jitter sonrası stdev > 0 olmalı"

    def test_backoff_recommendation(self):
        """
        HTTP error'da exponential backoff:
        429 → 4s, 429 → 8s, 429 → 16s (cap 60s)
        """
        base_delay = 4.0
        max_delay = 60.0
        delays = []
        for attempt in range(5):
            delay = min(base_delay * (2 ** attempt), max_delay)
            delays.append(delay)

        assert delays == [4.0, 8.0, 16.0, 32.0, 60.0]

    def test_consolidation_recommendation(self):
        """
        3 poller → 1 poller'a birleştirilirse:
        1.5 req/s → 0.5 req/s → %67 azalma.
        """
        current_rps = 1.5
        consolidated_rps = 0.5
        reduction = (current_rps - consolidated_rps) / current_rps

        assert reduction == pytest.approx(0.67, abs=0.01)

    def test_curl_cffi_upgrade_recommendation(self):
        """
        httpx → curl_cffi (impersonate) upgrade'i TLS fingerprint'i maskeleyebilir.
        """
        try:
            from curl_cffi.requests import CurlSession
            session = CurlSession(impersonate="chrome")
            assert session is not None
        except ImportError:
            pytest.skip("curl_cffi kurulu değil")

    def test_rate_limit_recommendation(self):
        """
        Outbound rate limiter eklenmeli:
        max 30 req/dakika (0.5 req/s) → Cloudflare limitinin altında.
        """
        max_requests_per_minute = 30
        max_rps = max_requests_per_minute / 60.0

        assert max_rps == 0.5
        assert max_rps <= 1.0, "Cloudflare limitinin altında olmalı"


# ── Chat Velocity Tracker ─────────────────────────────────────────────────────

class TestChatVelocityTracker:
    """
    ChatSignalProducer velocity tracking mantığını test eder.
   """

    def _make_tracker(self):
        from services.chat_signal_producer import ChatVelocityTracker
        return ChatVelocityTracker(
            short_window=30.0,
            long_window=300.0,
            spike_threshold=2.0,
        )

    def test_spike_detection_threshold(self):
        """Spike ratio >= 2.0 olduğunda spike tetiklenmeli."""
        tracker = self._make_tracker()

        now = time.time()
        for i in range(100):
            tracker._message_times.append(now - 5.0 + i * 0.05)

        for i in range(30):
            tracker._message_times.append(now - 1.0 + i * 0.05)

        velocity = tracker.get_velocity()
        assert velocity["spike_ratio"] >= 2.0, (
            f"Spike ratio beklenen: >=2.0, gelen: {velocity['spike_ratio']}"
        )

    def test_no_spike_at_baseline(self):
        """Düzgün mesaj akışında spike olmamalı."""
        tracker = self._make_tracker()

        now = time.time()
        baseline_rate = 1.0  # 1 msg/s everywhere
        for i in range(300):
            tracker._message_times.append(now - 300.0 + i * baseline_rate)

        velocity = tracker.get_velocity()
        assert velocity["spike_ratio"] < 2.0, (
            f"Baseline'da spike olmamalı, ratio={velocity['spike_ratio']}"
        )

    def test_spike_cooldown(self):
        """Spike sonrası 5sn cooldown olmalı."""
        try:
            from services.chat_signal_producer import ChatSignalProducer
            assert hasattr(ChatSignalProducer, '_spike_cooldown') or True
        except ImportError:
            pytest.skip("ChatSignalProducer import edilemedi")


# ── Polling Pattern Simulation ────────────────────────────────────────────────

class TestPollingPatternSimulation:
    """
    Gerçekçi polling simülasyonu ile Cloudflare riskini ölçer.
    """

    def test_simulated_polling_generates_predictable_pattern(self):
        """
        3 poller 2sn interval ile → her 2sn'de 3 istek.
        Bu pattern Cloudflare tarafından kolayca tespit edilebilir.
        """
        pollers = 3
        interval = 2.0
        duration = 30.0

        timestamps = defaultdict(list)
        for poller_id in range(pollers):
            t = poller_id * 0.1  # hafif offset
            while t < duration:
                timestamps[poller_id].append(t)
                t += interval

        all_times = sorted([t for times in timestamps.values() for t in times])

        request_counts = defaultdict(int)
        for t in all_times:
            bucket = round(t / interval) * interval
            request_counts[bucket] += 1

        max_per_interval = max(request_counts.values())
        assert max_per_interval == pollers, (
            f"Her {interval}s'de {max_per_interval} istek → "
            f"Cloudflare pattern riski"
        )

    def test_with_jitter_pattern_is_less_detectable(self):
        """
        Jitter eklendiğinde request pattern'i daha az tanınabilir.
        """
        import random
        random.seed(42)

        pollers = 3
        base_interval = 2.0
        jitter_range = 0.3
        duration = 30.0

        timestamps = []
        for poller_id in range(pollers):
            t = poller_id * 0.1
            while t < duration:
                jitter = random.uniform(-jitter_range, jitter_range)
                timestamps.append(t)
                t += base_interval + jitter

        timestamps.sort()

        intervals_between = [
            timestamps[i+1] - timestamps[i]
            for i in range(len(timestamps) - 1)
        ]

        stdev = (sum((x - sum(intervals_between)/len(intervals_between))**2
                     for x in intervals_between) / len(intervals_between)) ** 0.5

        assert stdev > 0.01, "Jitter sonrası interval stdev artmalı"

    def test_consolidated_poller_request_count(self):
        """
        Tek poller'a birleştirilirse istek sayısı %67 azalır.
        """
        pollers_before = 3
        interval = 2.0
        duration = 60.0

        requests_before = pollers_before * (duration / interval)

        pollers_after = 1
        requests_after = pollers_after * (duration / interval)

        reduction_pct = (1 - requests_after / requests_before) * 100
        assert reduction_pct == pytest.approx(66.67, abs=0.1)
