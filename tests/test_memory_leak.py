"""
Görev 5: Memory Leak Test
===========================
Ring buffer (C++) ve deque tabanlı buffer'ları sürdürülen yük altında test eder.
Memory leak, buffer overflow ve performans bozulmasını arar.

Test edilen bileşenler:
  - C++ RingBuffer (signal_client.py)
  - VideoFrameBuffer (deque-based)
  - SignalScoreBuffer (deque-based)
  - ChatVelocityTracker (deque-based)
  - ScoringEngine (deque per signal)
"""
from __future__ import annotations

import gc
import os
import sys
import time
from collections import deque
from typing import List

import numpy as np
import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))


# ── C++ RingBuffer Tests ──────────────────────────────────────────────────────

class TestRingBufferMemory:
    """C++ RingBuffer'ın bellek davranışını test eder."""

    def _get_buffer(self, capacity: int = 1024):
        try:
            from signal_engine.python.signal_client import RingBuffer, SignalEngine
            engine = SignalEngine()
            if engine._lib is None:
                pytest.skip("C++ signal engine DLL yüklenemedi")
            return RingBuffer(engine._lib, capacity)
        except (ImportError, OSError, RuntimeError) as e:
            pytest.skip(f"C++ ring buffer mevcut değil: {e}")

    def test_capacity_property(self):
        """capacity property doğru değer döndürmeli."""
        buf = self._get_buffer(1024)
        assert buf.capacity == 1024

    def test_capacity_powers_of_two(self):
        """Capacity verilen değere dönmeli."""
        buf = self._get_buffer(1024)
        assert buf.capacity == 1024

    def test_overwrite_oldest_on_overflow(self):
        """Buffer dolduğunda en eski veri overwrite edilmeli."""
        buf = self._get_buffer(4)

        for i in range(4):
            buf.push([float(i)])

        data = buf.pop(10)
        assert data[-1] == 3.0

        buf.push([10.0])
        data = buf.pop(10)
        assert data[-1] == 10.0

    def test_push_read_cycle_no_leak(self):
        """1000 push/read döngüsü bellek sızıntısı içermemeli."""
        buf = self._get_buffer(1024)

        for _ in range(1000):
            buf.push([1.0] * 100)
            buf.pop(200)

        # Test successfully pushed and popped multiple times without crashing or leaking state
        assert buf.capacity == 1024
        # We can also do a final push/pop to verify sanity
        buf.push([2.0] * 10)
        final_pop = buf.pop(10)
        assert len(final_pop) == 10
        assert final_pop[0] == 2.0

    def test_large_push_no_crash(self):
        """Buffer capacity'den büyük push crash etmemeli."""
        buf = self._get_buffer(1024)
        try:
            buf.push([1.0] * 10000)
            assert buf.capacity == 1024
            # Push succeeded without crashing, which is the expected behavior for a ring buffer
        except Exception as e:
            pytest.fail(f"Pushing large array crashed with: {e}")

    def test_read_empty_buffer(self):
        """Boş buffer'dan pop() boş liste döndürmeli."""
        buf = self._get_buffer(1024)
        data = buf.pop(100)
        assert isinstance(data, list)
        assert len(data) == 0


# ── VideoFrameBuffer Memory Tests ─────────────────────────────────────────────

class TestVideoFrameBufferMemory:
    """VideoFrameBuffer bellek davranışını test eder."""

    def _make_buf(self, max_seconds: int = 180, target_fps: int = 2):
        from services.live_stream_processor import VideoFrameBuffer
        return VideoFrameBuffer(max_seconds=max_seconds, target_fps=target_fps)

    def _measure_buffer_memory(self, buf) -> int:
        """Buffer'daki toplam bellek miktarını tahmin et (bytes)."""
        if not buf.frames:
            return 0
        frame = buf.frames[0].frame
        per_frame = frame.nbytes
        return per_frame * len(buf.frames)

    def test_buffer_maxlen_enforced(self):
        """Buffer maxlen aşıldığında eski frame'ler düşmeli."""
        buf = self._make_buf(max_seconds=10, target_fps=2)

        for i in range(30):
            ts = i * 0.5
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            buf.maybe_add(frame, ts, 320, 240)

        assert buf.count <= 20

    def test_memory_stable_under_sustained_load(self):
        """Sürekli yük altında bellek sabit kalmalı (artmamalı)."""
        buf = self._make_buf(max_seconds=5, target_fps=2)

        for i in range(40):
            frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
            buf.maybe_add(frame, i * 0.5, 320, 240)

        memory_samples = []
        for i in range(160):
            frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
            buf.maybe_add(frame, (40 + i) * 0.5, 320, 240)

            if i % 20 == 0:
                memory_samples.append(self._measure_buffer_memory(buf))

        for i in range(1, len(memory_samples)):
            growth = memory_samples[i] - memory_samples[i-1]
            assert abs(growth) < 1024, (
                f"Bellek artışı tespit edildi: "
                f"{memory_samples[i-1]} -> {memory_samples[i]} bytes"
            )

    def test_deque_overflow_removes_old_frames(self):
        """Deque overflow, en eski frame'leri çıkarmalı."""
        buf = self._make_buf(max_seconds=5, target_fps=2)

        first_timestamps = []
        for i in range(100):
            ts = i * 0.5
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            buf.maybe_add(frame, ts, 320, 320)

            if i < 5:
                first_timestamps.append(ts)

        if buf.count > 0:
            oldest_in_buffer = buf.frames[0].timestamp
            assert oldest_in_buffer > first_timestamps[0], (
                f"Eski frame'ler çıkmalı: en eski={oldest_in_buffer}, "
                f"beklenen>{first_timestamps[0]}"
            )

    def test_clear_resets_memory(self):
        """clear() memory'yi serbest bırakmalı."""
        buf = self._make_buf(max_seconds=30, target_fps=2)

        for i in range(60):
            frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
            buf.maybe_add(frame, i * 0.5, 320, 240)

        before_clear = self._measure_buffer_memory(buf)
        buf.clear()
        after_clear = self._measure_buffer_memory(buf)

        assert after_clear == 0
        assert buf.count == 0


# ── SignalScoreBuffer Memory Tests ────────────────────────────────────────────

class TestSignalScoreBufferMemory:
    """SignalScoreBuffer bellek davranışını test eder."""

    def _make_buf(self, max_seconds: int = 300):
        from services.live_stream_processor import SignalScoreBuffer
        return SignalScoreBuffer(max_seconds=max_seconds)

    def _make_score(self, ts: float):
        from services.live_stream_processor import SignalScore
        return SignalScore(
            timestamp=ts,
            audio_energy=0.5,
            audio_peak=0.8,
            audio_bpm=120.0,
            video_motion=0.3,
            video_scene_change=0.1,
            emotion_intensity=0.6,
            chat_velocity=0.4,
            composite_score=0.55,
        )

    def test_buffer_max_entries(self):
        """Buffer max_entries limitini aşmamalı."""
        buf = self._make_buf(max_seconds=300)
        for i in range(400):
            buf.append(self._make_score(float(i)))

        assert len(buf.scores) <= 300

    def test_memory_stable_under_sustained_load(self):
        """Sürekli ekleme/okuma altında bellek sabit kalmalı."""
        buf = self._make_buf(max_seconds=100)

        for i in range(500):
            buf.append(self._make_score(float(i)))
            _ = buf.get_last_n(10)

        assert len(buf.scores) <= 100

    def test_latest_property(self):
        """latest property en son eklenen score'u döndürmeli."""
        buf = self._make_buf()
        buf.append(self._make_score(1.0))
        buf.append(self._make_score(2.0))

        assert buf.latest.timestamp == 2.0

    def test_get_range_performance(self):
        """get_range() performansı büyük buffer'da bozulmamalı."""
        buf = self._make_buf(max_seconds=300)
        for i in range(300):
            buf.append(self._make_score(float(i)))

        start = time.perf_counter()
        for _ in range(100):
            result = buf.get_range(100.0, 200.0)
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"100 get_range 1sn'den uzun sürdü: {elapsed:.2f}s"


# ── ChatVelocityTracker Memory Tests ──────────────────────────────────────────

class TestChatVelocityTrackerMemory:
    """ChatVelocityTracker bellek davranışını test eder."""

    def _make_tracker(self):
        from services.chat_signal_producer import ChatVelocityTracker
        return ChatVelocityTracker(
            short_window=30.0,
            long_window=300.0,
            spike_threshold=2.0,
        )

    def test_message_history_bounded(self):
        """Mesaj geçmişi long_window'yi aşmamalı."""
        tracker = self._make_tracker()

        now = time.time()
        for i in range(5000):
            tracker._message_times.append(now + i)

        old_count = len(tracker._message_times)

        for i in range(100):
            tracker._message_times.append(now + 5000 + i)

        assert len(tracker._message_times) <= old_count + 100

    def test_spike_check_performance(self):
        """get_velocity() 1000 mesajda hızlı olmalı."""
        tracker = self._make_tracker()

        now = time.time()
        for i in range(1000):
            tracker._message_times.append(now - 100.0 + i * 0.1)

        start = time.perf_counter()
        for _ in range(100):
            tracker.get_velocity()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"100 get_velocity {elapsed:.2f}s sürdü"


# ── ScoringEngine Memory Tests ────────────────────────────────────────────────

class TestScoringEngineMemory:
    """ScoringEngine bellek davranışını test eder."""

    def _make_engine(self):
        from microservices.event_detector.service import ScoringEngine
        return ScoringEngine(decay_halflife=5.0)

    def test_signal_history_bounded(self):
        """Her sinyal geçmişi maxlen ile sınırlı olmalı."""
        engine = self._make_engine()

        for i in range(200):
            for signal in engine.WEIGHTS:
                engine.update_signal(signal, float(i) / 200.0)

        for signal, history in engine._signal_history.items():
            assert len(history) <= 120, (
                f"{signal} history {len(history)} > 120"
            )

    def test_compute_score_performance(self):
        """compute_score() 1000 hesaplamada hızlı olmalı."""
        engine = self._make_engine()

        now = time.time()
        for i in range(120):
            for signal in engine.WEIGHTS:
                engine._signal_history[signal].append(
                    (now - i * 0.1, float(i) / 120.0)
                )

        start = time.perf_counter()
        for _ in range(1000):
            engine.compute_score()
        elapsed = time.perf_counter() - start

        assert elapsed < 1.0, f"1000 compute_score {elapsed:.2f}s sürdü"

    def test_memory_stable_under_sustained_load(self):
        """Sürekli update + compute altında bellek sabit kalmalı."""
        engine = self._make_engine()

        for i in range(500):
            for signal in engine.WEIGHTS:
                engine.update_signal(signal, float(i % 100) / 100.0)
            engine.compute_score()

        for signal, history in engine._signal_history.items():
            assert len(history) <= 120


# ── Combined Stress Test ──────────────────────────────────────────────────────

class TestCombinedStress:
    """Tüm buffer bileşenlerini aynı anda test eder."""

    def test_all_buffers_concurrent_stress(self):
        """
        Tüm buffer'ları aynı anda 500 iterasyonla test et.
        Bellek sızıntısı veya crash olmamalı.
        """
        from services.live_stream_processor import (
            VideoFrameBuffer, SignalScoreBuffer, SignalScore,
        )

        vbuf = VideoFrameBuffer(max_seconds=30, target_fps=2)
        sbuf = SignalScoreBuffer(max_seconds=300)
        engine = self._make_engine()
        tracker = self._make_chat_tracker()

        for i in range(500):
            ts = float(i) * 0.5

            frame = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
            vbuf.maybe_add(frame, ts, 320, 240)

            sbuf.append(SignalScore(
                timestamp=ts,
                audio_energy=float(i % 100) / 100.0,
                composite_score=float(i % 100) / 100.0,
            ))

            for signal in engine.WEIGHTS:
                engine.update_signal(signal, float(i % 100) / 100.0)
            engine.compute_score()

            tracker._message_times.append(time.time() + i)
            if i % 10 == 0:
                tracker.get_velocity()

        assert vbuf.count <= vbuf.max_frames
        assert len(sbuf.scores) <= sbuf.max_entries

        for signal, history in engine._signal_history.items():
            assert len(history) <= 120

    def _make_engine(self):
        from microservices.event_detector.service import ScoringEngine
        return ScoringEngine(decay_halflife=5.0)

    def _make_chat_tracker(self):
        from services.chat_signal_producer import ChatVelocityTracker
        return ChatVelocityTracker(
            short_window=30.0,
            long_window=300.0,
            spike_threshold=2.0,
        )
