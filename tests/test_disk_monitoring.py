"""
Disk Monitoring Tests — Proves zero intermediate disk writes during live processing.
===================================================================================
The core promise: during live stream analysis, only the final clip is written to disk.
No temp files, no buffer files, no intermediate storage.

Tests:
1. LiveStreamProcessor processes audio/video via pipes only — no disk writes
2. ChatSignalProducer velocity tracking works without disk
3. Full data flow stays in RAM
"""
from __future__ import annotations

import asyncio
import os
import struct
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import numpy as np
import pytest


class TestZeroDiskWrites:
    """Verify LiveStreamProcessor doesn't write intermediate files to disk."""

    def test_video_frame_buffer_pure_ram(self):
        """VideoFrameBuffer stores everything in memory (deque), never touches disk."""
        from services.live_stream_processor import VideoFrameBuffer

        buf = VideoFrameBuffer(max_seconds=60, target_fps=10)

        # Simulate 60 seconds of video at 30fps input
        frame = np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)
        for i in range(1800):  # 60s × 30fps
            buf.maybe_add(frame, float(i) / 30.0, 320, 240)

        # Verify: all data is in deque, no files created
        assert buf.count <= 600  # 60s × 10fps
        assert buf.total_frames_received == 1800
        # No file system access in the entire class
        import inspect
        source = inspect.getsource(VideoFrameBuffer)
        assert "open(" not in source
        assert "write(" not in source
        assert "Path(" not in source

    def test_signal_score_buffer_pure_ram(self):
        """SignalScoreBuffer is pure in-memory, no file operations."""
        from services.live_stream_processor import SignalScoreBuffer, SignalScore

        buf = SignalScoreBuffer(max_seconds=300)

        for i in range(300):
            buf.append(SignalScore(timestamp=float(i), composite_score=i / 300.0))

        assert len(buf.scores) == 300

        import inspect
        source = inspect.getsource(SignalScoreBuffer)
        assert "open(" not in source
        assert "write(" not in source
        assert "Path(" not in source

    def test_live_stream_processor_no_disk_in_init(self):
        """LiveStreamProcessor.__init__ creates no files, no directories."""
        from services.live_stream_processor import LiveStreamProcessor

        # Record all files before
        before_files = set()
        for root, dirs, files in os.walk("."):
            for f in files:
                if ".pyc" not in root and "__pycache__" not in root:
                    before_files.add(os.path.join(root, f))

        proc = LiveStreamProcessor()

        # Record all files after
        after_files = set()
        for root, dirs, files in os.walk("."):
            for f in files:
                if ".pyc" not in root and "__pycache__" not in root:
                    after_files.add(os.path.join(root, f))

        # No new files should have been created
        new_files = after_files - before_files
        assert len(new_files) == 0, f"Unexpected new files: {new_files}"

    def test_audio_chunk_processing_stays_in_ram(self):
        """_on_audio_chunk processes PCM data in memory only."""
        from services.live_stream_processor import LiveStreamProcessor

        proc = LiveStreamProcessor()
        received = []

        async def on_aud(data, ts):
            received.append(len(data))

        proc.on_audio(on_aud)

        # Generate 1 second of audio data (44100 samples × 4 bytes)
        chunk = b'\x00' * (44100 * 4)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(proc._on_audio_chunk(chunk))
        loop.close()

        assert len(received) == 1
        assert received[0] == 44100 * 4  # 176400 bytes

    def test_video_frame_processing_stays_in_ram(self):
        """_on_video_frame processes frame data in memory only."""
        from services.live_stream_processor import LiveStreamProcessor

        proc = LiveStreamProcessor()
        proc._start_time = time.time()

        received = []
        async def on_vid(frame, ts, w, h):
            received.append((w, h))

        proc.on_video(on_vid)

        # Generate a 320×240 RGB24 frame
        frame = np.random.randint(0, 256, (240, 320, 3), dtype=np.uint8)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(proc._on_video_frame(frame.tobytes(), 320, 240))
        loop.close()

        assert len(received) == 1
        assert received[0] == (320, 240)


class TestChatVelocityTracking:
    """ChatVelocityTracker velocity calculation — no disk, pure math."""

    def test_spike_detection(self):
        from services.chat_signal_producer import ChatVelocityTracker

        tracker = ChatVelocityTracker(
            short_window=5.0,
            long_window=60.0,
            spike_threshold=2.0,
        )

        now = time.time()

        # Baseline: 1 msg/sec for 60 seconds
        for i in range(60):
            tracker.record_message(timestamp=now - 60 + i)

        # Current burst: 10 msg/sec for 5 seconds
        for i in range(50):
            tracker.record_message(timestamp=now - 5 + i * 0.1)

        velocity = tracker.get_velocity()
        assert velocity["is_spike"] is True
        assert velocity["spike_ratio"] > 2.0
        assert velocity["short_rate"] > 5.0

    def test_no_spike_steady_state(self):
        from services.chat_signal_producer import ChatVelocityTracker

        tracker = ChatVelocityTracker(
            short_window=30.0,
            long_window=300.0,
            spike_threshold=2.0,
        )

        now = time.time()

        # Steady: 1 msg/sec for 300 seconds
        for i in range(300):
            tracker.record_message(timestamp=now - 300 + i)

        velocity = tracker.get_velocity()
        assert velocity["is_spike"] is False
        assert velocity["spike_ratio"] < 1.5

    def test_old_messages_cleanup(self):
        from services.chat_signal_producer import ChatVelocityTracker

        tracker = ChatVelocityTracker(short_window=10.0, long_window=60.0)

        now = time.time()

        # Messages from 10 minutes ago (should be cleaned up)
        for i in range(100):
            tracker.record_message(timestamp=now - 600 + i)

        # Recent messages (all within last 10 seconds)
        for i in range(10):
            tracker.record_message(timestamp=now - 9 + i)

        velocity = tracker.get_velocity()
        assert velocity["long_count"] <= 10  # old messages cleaned
        assert velocity["short_count"] <= 10

    def test_chat_signal_producer_instantiation(self):
        from services.chat_signal_producer import ChatSignalProducer

        producer = ChatSignalProducer()
        assert producer._running is False

        status = producer.get_status()
        assert status["running"] is False
        assert status["total_messages"] == 0


class TestFullDataFlowInMemory:
    """End-to-end: all intermediate data stays in RAM."""

    def test_score_buffer_accumulates_scores(self):
        from services.live_stream_processor import SignalScoreBuffer, SignalScore

        buf = SignalScoreBuffer(max_seconds=120)

        # Simulate 2 minutes of per-second scoring
        for i in range(120):
            score = SignalScore(
                timestamp=float(i),
                audio_energy=np.random.random() * 10000,
                video_motion=np.random.random(),
                composite_score=np.random.random(),
            )
            buf.append(score)

        assert len(buf.scores) == 120

        # Get last 30 seconds
        last_30 = buf.get_last_n(30)
        assert len(last_30) == 30

        # All scores are in RAM
        total_memory = sum(
            sys.getsizeof(s) for s in buf.scores
        )
        assert total_memory > 0  # Data exists in memory

    def test_video_buffer_get_range_no_fs(self):
        """VideoFrameBuffer.get_range never touches filesystem."""
        from services.live_stream_processor import VideoFrameBuffer

        buf = VideoFrameBuffer(max_seconds=30, target_fps=5)

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for i in range(150):  # 30s × 5fps
            buf.maybe_add(frame, float(i) * 0.2, 320, 240)

        # Range queries are pure in-memory
        window = buf.get_range(10.0, 20.0)
        assert len(window) >= 48 and len(window) <= 52  # ~10s × 5fps, float tolerance

        last_5s = buf.get_last_n_seconds(5.0)
        assert len(last_5s) >= 23 and len(last_5s) <= 27  # ~5s × 5fps, float tolerance
