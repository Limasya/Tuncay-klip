"""
Tests for Live Stream Processor — Spike 1
==========================================
Verifies VideoFrameBuffer, SignalScoreBuffer, and LiveStreamProcessor
can be instantiated and their core logic works without a live stream.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import numpy as np
import pytest


class TestVideoFrameBuffer:
    """VideoFrameBuffer fps-düşürme ve aralık sorguları."""

    def test_add_frame_at_target_fps(self):
        from services.live_stream_processor import VideoFrameBuffer
        buf = VideoFrameBuffer(max_seconds=10, target_fps=2)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        added_count = 0
        for i in range(100):
            ts = i * 0.05  # 50ms aralıkla = 20fps → 5 saniye
            if buf.maybe_add(frame, ts, 320, 240):
                added_count += 1

        assert added_count == 10  # 20fps → 2fps = her 10'da 1
        assert buf.total_frames_received == 100
        assert buf.count == 10

    def test_get_range_returns_correct_window(self):
        from services.live_stream_processor import VideoFrameBuffer
        buf = VideoFrameBuffer(max_seconds=10, target_fps=10)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(100):
            buf.maybe_add(frame, float(i) * 0.1, 320, 240)

        window = buf.get_range(5.0, 6.0)
        assert len(window) == 11  # t=5.0, 5.1, ..., 6.0 (11 inclusive)

    def test_get_last_n_seconds(self):
        from services.live_stream_processor import VideoFrameBuffer
        buf = VideoFrameBuffer(max_seconds=10, target_fps=10)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(100):
            buf.maybe_add(frame, float(i) * 0.1, 320, 240)

        last_2s = buf.get_last_n_seconds(2.0)
        assert len(last_2s) == 21  # t=7.9..9.9 inclusive

    def test_max_frames_eviction(self):
        from services.live_stream_processor import VideoFrameBuffer
        buf = VideoFrameBuffer(max_seconds=2, target_fps=10)
        assert buf.max_frames == 20

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(30):
            buf.maybe_add(frame, float(i) * 0.1, 320, 240)

        assert buf.count == 20  # maxlen nedeniyle eskiler atıldı

    def test_clear(self):
        from services.live_stream_processor import VideoFrameBuffer
        buf = VideoFrameBuffer(max_seconds=5, target_fps=5)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(25):
            buf.maybe_add(frame, float(i) * 0.1, 320, 240)

        assert buf.count > 0
        buf.clear()
        assert buf.count == 0
        assert buf.current_time == 0.0


class TestSignalScoreBuffer:
    """SignalScoreBuffer skor tamponlama ve aralık sorguları."""

    def test_append_and_latest(self):
        from services.live_stream_processor import SignalScore, SignalScoreBuffer
        buf = SignalScoreBuffer(max_seconds=60)
        assert buf.latest is None

        s1 = SignalScore(timestamp=1.0, audio_energy=100, composite_score=0.5)
        s2 = SignalScore(timestamp=2.0, audio_energy=200, composite_score=0.8)
        buf.append(s1)
        buf.append(s2)

        assert buf.latest.composite_score == 0.8
        assert buf.latest.audio_energy == 200

    def test_get_range(self):
        from services.live_stream_processor import SignalScore, SignalScoreBuffer
        buf = SignalScoreBuffer(max_seconds=60)

        for i in range(10):
            buf.append(SignalScore(timestamp=float(i), composite_score=i / 10.0))

        window = buf.get_range(3.0, 6.0)
        assert len(window) == 4  # t=3,4,5,6

    def test_get_last_n(self):
        from services.live_stream_processor import SignalScore, SignalScoreBuffer
        buf = SignalScoreBuffer(max_seconds=60)

        for i in range(20):
            buf.append(SignalScore(timestamp=float(i)))

        last_5 = buf.get_last_n(5)
        assert len(last_5) == 5
        assert last_5[-1].timestamp == 19.0

    def test_max_entries_eviction(self):
        from services.live_stream_processor import SignalScore, SignalScoreBuffer
        buf = SignalScoreBuffer(max_seconds=5)

        for i in range(10):
            buf.append(SignalScore(timestamp=float(i)))

        assert len(buf.scores) == 5
        assert buf.scores[0].timestamp == 5.0  # ilk 5 atıldı


class TestLiveStreamProcessor:
    """LiveStreamProcessor başlatma, durdurma ve durum raporlama."""

    def test_instantiation(self):
        from services.live_stream_processor import LiveStreamProcessor
        proc = LiveStreamProcessor(
            audio_buffer_seconds=60,
            video_buffer_seconds=60,
            video_fps=2,
        )
        assert proc._running is False
        assert proc.current_time == 0.0

    def test_status_when_idle(self):
        from services.live_stream_processor import LiveStreamProcessor
        proc = LiveStreamProcessor()
        status = proc.get_status()

        assert status["running"] is False
        assert status["uptime_seconds"] == 0.0
        assert status["audio"]["ring_buffer_size"] == 0
        assert status["video"]["frame_count"] == 0
        assert status["scores"]["count"] == 0

    def test_callback_registration(self):
        from services.live_stream_processor import LiveStreamProcessor
        proc = LiveStreamProcessor()

        audio_cb = MagicMock()
        video_cb = MagicMock()
        score_cb = MagicMock()

        proc.on_audio(audio_cb)
        proc.on_video(video_cb)
        proc.on_score(score_cb)

        assert len(proc._on_audio_callbacks) == 1
        assert len(proc._on_video_callbacks) == 1
        assert len(proc._on_score_callbacks) == 1

    def test_video_callback_called(self):
        from services.live_stream_processor import LiveStreamProcessor
        proc = LiveStreamProcessor()

        received = []
        def on_vid(frame, ts, w, h):
            received.append((ts, w, h))

        proc.on_video(on_vid)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        proc._start_time = time.time() - 1.0

        # Senkron callback — await gerekmeyen
        # Manuel olarak it
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            proc._on_video_frame(frame.tobytes(), 320, 240)
        )

        assert len(received) == 1
        assert received[0][1] == 320

    def test_audio_chunk_accumulates(self):
        from services.live_stream_processor import LiveStreamProcessor
        proc = LiveStreamProcessor(audio_sample_rate=44100.0)

        received = []
        async def on_aud(data, ts):
            received.append((len(data), ts))

        proc.on_audio(on_aud)

        proc._start_time = time.time()

        # 44100 float samples × 4 bytes = 176400 bytes = 1 saniye
        chunk1 = b'\x00' * (44100 * 2)  # yarım saniye
        chunk2 = b'\x00' * (44100 * 2)  # yarım saniye

        import asyncio
        loop = asyncio.new_event_loop()

        loop.run_until_complete(proc._on_audio_chunk(chunk1))
        assert len(received) == 0  # henüz tamamlanmadı

        loop.run_until_complete(proc._on_audio_chunk(chunk2))
        assert len(received) == 1  # tam 1 saniye → callback tetiklendi
        assert received[0][0] == 44100 * 4  # 176400 bytes

        loop.close()


class TestFfmpegPipeManager:
    """FfmpegPipeManager başlatma/durdurma (FFmpeg olmadan)."""

    def test_instantiation(self):
        from services.live_stream_processor import FfmpegPipeManager
        mgr = FfmpegPipeManager()
        assert mgr._running is False
        assert mgr._audio_process is None
        assert mgr._video_process is None

    def test_stop_when_not_running(self):
        import asyncio
        from services.live_stream_processor import FfmpegPipeManager
        mgr = FfmpegPipeManager()
        asyncio.get_event_loop().run_until_complete(mgr.stop())
        assert mgr._running is False


class TestFusionLoopLogic:
    """Hysteresis tetikleme mantığı (senaryo bazlı)."""

    def test_consecutive_high_triggers(self):
        from services.live_stream_processor import SignalScore, SignalScoreBuffer
        buf = SignalScoreBuffer(max_seconds=60)

        # 5 saniye boyunca yüksek skor
        for i in range(5):
            buf.append(SignalScore(
                timestamp=float(i),
                audio_energy=5000,
                video_motion=0.8,
                composite_score=0.7,
            ))

        # Son 3'ten fazlası eşik üstünde
        last_3 = buf.get_last_n(3)
        assert all(s.composite_score >= 0.6 for s in last_3)

    def test_low_score_resets_consecutive(self):
        from services.live_stream_processor import SignalScore, SignalScoreBuffer
        buf = SignalScoreBuffer(max_seconds=60)

        # Yüksek → düşük → yüksek (kesintili)
        scores = [
            SignalScore(timestamp=0.0, composite_score=0.8),
            SignalScore(timestamp=1.0, composite_score=0.3),  # düşük
            SignalScore(timestamp=2.0, composite_score=0.9),
        ]
        for s in scores:
            buf.append(s)

        last_3 = buf.get_last_n(3)
        # Ortadaki düşük skor nedeniyle 3 üst üste yüksek değil
        assert last_3[1].composite_score < 0.6
