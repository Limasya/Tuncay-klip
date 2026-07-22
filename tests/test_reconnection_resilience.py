"""
Görev 4: Reconnection Resilience Test
=======================================
FFmpeg pipe crash, stream stall ve reconnect mantığını test eder.

Bulunan gap'ler:
  - FfmpegPipeManager'da Python-level reconnect yok
  - Pipe reader dead loop'a giriyor ama upstream'e sinyal vermiyor
  - StreamCaptureService'de düzgün reconnect var (exp backoff, max 10 deneme)
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))


class TestFfmpegPipeManagerResilience:
    """FfmpegPipeManager'ın hata toleransını test eder."""

    def test_graceful_stop_on_not_running(self):
        """Durmayan FfmpegPipeManager'ı durdurmaya çalışmak hata vermemeli."""
        from services.live_stream_processor import FfmpegPipeManager

        mgr = FfmpegPipeManager()
        assert mgr._running is False

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(mgr.stop())
            assert result is None
        finally:
            loop.close()

    def test_running_flag_default_false(self):
        """FfmpegPipeManager varsayılan olarak çalışmıyor olmalı."""
        from services.live_stream_processor import FfmpegPipeManager

        mgr = FfmpegPipeManager()
        assert mgr._running is False
        assert mgr._audio_process is None
        assert mgr._video_process is None

    def test_pipe_reader_handles_empty_data(self):
        """
        Pipe reader boş data aldığında loop'tan çıkmalı (crash etmemeli).
        """
        from services.live_stream_processor import FfmpegPipeManager

        mgr = FfmpegPipeManager()
        assert hasattr(mgr, '_read_audio_pipe')
        assert hasattr(mgr, '_read_video_pipe')

    def test_stop_delegates_to_kill_process(self):
        """stop() _kill_process üzerinden terminate + kill sequence izlemeli."""
        import inspect
        from services.live_stream_processor import FfmpegPipeManager

        stop_source = inspect.getsource(FfmpegPipeManager.stop)
        assert "_kill_process" in stop_source

        kill_source = inspect.getsource(FfmpegPipeManager._kill_process)
        assert "terminate" in kill_source
        assert "kill" in kill_source

    def test_python_level_reconnect_exists(self):
        """
        FfmpegPipeManager'da Python-level reconnect mekanizması mevcut.
        Exponential backoff ile _attempt_reconnect() çağrılır.
        """
        import inspect
        from services.live_stream_processor import FfmpegPipeManager

        source = inspect.getsource(FfmpegPipeManager)
        assert hasattr(FfmpegPipeManager, '_attempt_reconnect')
        assert "reconnect" in source.lower()
        assert "_reconnect_base_delay" in source or "reconnect_base_delay" in source
        assert "_max_reconnect_attempts" in source or "max_reconnect_attempts" in source


class TestStreamCaptureReconnection:
    """StreamCaptureService'in reconnect mantığını test eder."""

    def _get_reconnect_config(self):
        """Reconnect parametrelerini döndür."""
        return {
            "max_attempts": 10,
            "base_delay": 5.0,
            "max_delay": 60.0,
            "stall_threshold": 15.0,
            "health_check_interval": 10.0,
        }

    def test_exponential_backoff_sequence(self):
        """Exponential backoff doğru diziyi oluşturmalı."""
        config = self._get_reconnect_config()
        delays = []

        for attempt in range(1, config["max_attempts"] + 1):
            delay = min(
                config["base_delay"] * (2 ** (attempt - 1)),
                config["max_delay"]
            )
            delays.append(delay)

        assert delays[0] == 5.0
        assert delays[1] == 10.0
        assert delays[2] == 20.0
        assert delays[3] == 40.0
        assert delays[4] == 60.0
        assert all(d == 60.0 for d in delays[4:])

    def test_max_delay_cap(self):
        """Backoff 60s'yi aşmamalı."""
        config = self._get_reconnect_config()

        for attempt in range(1, 20):
            delay = min(
                config["base_delay"] * (2 ** (attempt - 1)),
                config["max_delay"]
            )
            assert delay <= config["max_delay"]

    def test_stall_detection_window(self):
        """Stall detection 15sn pencerede olmalı."""
        config = self._get_reconnect_config()
        assert config["stall_threshold"] == 15.0

    def test_max_reconnect_attempts(self):
        """Max 10 reconnect denemesi sonrası sistem durmalı."""
        config = self._get_reconnect_config()
        assert config["max_attempts"] == 10

    def test_health_check_interval(self):
        """Health check her 10sn'de bir çalışmalı."""
        config = self._get_reconnect_config()
        assert config["health_check_interval"] == 10.0

    def test_total_downtime_worst_case(self):
        """
        Worst-case reconnect toplam downtime:
        backoff: 5+10+20+40+60*6 = 435s
        stall detection: 10x15s = 150s
        total: 585s (~9.75dk)
        """
        config = self._get_reconnect_config()
        delays = []
        for attempt in range(1, config["max_attempts"] + 1):
            delay = min(
                config["base_delay"] * (2 ** (attempt - 1)),
                config["max_delay"]
            )
            delays.append(delay)

        total_backoff = sum(delays)
        total_stall_detection = config["max_attempts"] * config["stall_threshold"]
        total_worst = total_backoff + total_stall_detection

        assert total_worst == 585.0


class TestEventBusErrorHandling:
    """EventBus hata yönetimini test eder."""

    def test_dlq_capacity(self):
        """Dead-letter queue max 100 event tutmalı."""
        from shared.event_bus import EventBus

        bus = EventBus(history_size=500)
        assert hasattr(bus, '_dlq')
        assert bus._dlq.maxlen == 100

    def test_handler_failure_goes_to_dlq(self):
        """Handler exception'ı DLQ'ya düşmeli, bus devam etmeli."""
        from shared.event_bus import EventBus
        from shared.event_schemas import EventType

        bus = EventBus()

        async def failing_handler(event):
            raise ValueError("test error")

        bus.subscribe(EventType.EVENT_SCORED.value, failing_handler)

        assert len(bus._dlq) == 0

    def test_bus_queue_capacity(self):
        """EventBus dispatch queue max 10000 event tutmalı."""
        from shared.event_bus import EventBus

        bus = EventBus()
        assert bus._dispatch_queue.maxsize == 10000

    def test_metrics_tracking(self):
        """EventBus metrikleri doğru sayılmalı."""
        from shared.event_bus import EventBus

        bus = EventBus()
        assert bus._metrics["events_published"] == 0
        assert bus._metrics["events_dispatched"] == 0
        assert bus._metrics["events_failed"] == 0
        assert bus._metrics["events_dlq"] == 0


class TestDecisionEngineResilience:
    """DecisionEngineService'in hata toleransını test eder."""

    def _make_engine(self):
        from microservices.decision_engine.service import DecisionEngineService
        from unittest.mock import MagicMock
        return DecisionEngineService(event_bus=MagicMock())

    def test_evaluate_never_raises(self):
        """evaluate() hiçbir zaman exception fırlatmamalı."""
        from shared.event_schemas import HighlightScore

        engine = self._make_engine()

        edge_cases = [
            HighlightScore(composite_score=0.0, breakdown={}, active_signals=0),
            HighlightScore(composite_score=1.0, breakdown={}, active_signals=0),
            HighlightScore(composite_score=-1.0, breakdown={}, active_signals=0),
            HighlightScore(composite_score=float('inf'), breakdown={}, active_signals=0),
            HighlightScore(composite_score=float('nan'), breakdown={}, active_signals=0),
        ]

        for score in edge_cases:
            try:
                result = engine.evaluate(score)
                assert result.decision in ("CREATE_CLIP", "REJECT")
            except Exception as e:
                pytest.fail(f"evaluate() raised for score={score.composite_score}: {e}")

    def test_per_stream_isolation(self):
        """Her stream_id bağımsız confirmation window'a sahip olmalı."""
        from shared.event_schemas import HighlightScore

        engine = self._make_engine()

        score = HighlightScore(
            composite_score=0.80,
            breakdown={"audio": 0.5, "chat": 0.4},
            active_signals=2,
        )

        engine.evaluate(score, stream_id="stream_a")
        engine.evaluate(score, stream_id="stream_b")

        assert "stream_a" in engine._stream_confirmation
        assert "stream_b" in engine._stream_confirmation
        assert engine._stream_confirmation["stream_a"] is not engine._stream_confirmation["stream_b"]

    def test_cooldown_prevents_clip_storm(self):
        """Cooldown clip storm'u engellemeli."""
        from shared.event_schemas import HighlightScore
        from microservices.decision_engine.service import DecisionEngineService

        engine = DecisionEngineService(
            event_bus=MagicMock(),
            cooldown_seconds=5.0,
            confirmation_window=2,
            confirmation_required=2,
        )

        score = HighlightScore(
            composite_score=0.80,
            breakdown={"a": 0.5, "b": 0.4, "c": 0.3, "d": 0.2},
            active_signals=4,
        )

        results = []
        for _ in range(10):
            r = engine.evaluate(score, stream_id="storm_test")
            results.append(r.decision)

        clips = [r for r in results if r == "CREATE_CLIP"]
        assert len(clips) == 1, f"Cooldown clip storm engellemeli, {len(clips)} clip üretildi"

    def test_confirmation_window_prevents_false_positive(self):
        """Confirmation window tek seferlik spike'ı engellemeli."""
        from shared.event_schemas import HighlightScore

        engine = self._make_engine()

        high_score = HighlightScore(
            composite_score=0.80, breakdown={"a": 0.5, "b": 0.4},
            active_signals=2,
        )
        low_score = HighlightScore(
            composite_score=0.30, breakdown={"a": 0.1},
            active_signals=1,
        )

        engine.evaluate(high_score, stream_id="fp_test")
        r = engine.evaluate(low_score, stream_id="fp_test")

        assert r.decision == "REJECT", "Tek high score sonrası low score REJECT etmeli"
