"""
Cross-language integration tests — verifies Python ↔ C++ FFI, Python ↔ Rust subprocess,
and TypeScript AI Worker functional correctness.
"""
from __future__ import annotations

import math
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import pytest_asyncio
import httpx
from httpx import AsyncClient, ASGITransport


# ── C++ signal_engine (ctypes FFI) ──────────────────────────────────────────


class TestSignalEngineFFI:
    """Python → C++ signal_engine ctypes integration."""

    @pytest.fixture(autouse=True)
    def _load_engine(self):
        from signal_engine.python.signal_client import SignalEngine
        self.engine = SignalEngine()
        self.available = self.engine.available

    def test_singleton_loads(self):
        from signal_engine.python.signal_client import signal_engine
        assert signal_engine is not None

    def test_version_string(self):
        if not self.available:
            pytest.skip("signal_engine DLL not available")
        v = self.engine.version()
        assert isinstance(v, str)
        assert len(v) > 0

    def test_fft_magnitude_returns_json(self):
        if not self.available:
            pytest.skip("signal_engine DLL not available")
        # Generate a 1024-sample sine wave at 440 Hz
        sr = 44100.0
        n = 1024
        samples = [math.sin(2 * math.pi * 440 * i / sr) for i in range(n)]
        result = self.engine.fft_magnitude(samples)
        assert isinstance(result, dict)
        assert result.get("success") is True
        assert "magnitudes" in result
        assert len(result["magnitudes"]) > 0

    def test_detect_beats_returns_json(self):
        if not self.available:
            pytest.skip("signal_engine DLL not available")
        sr = 44100.0
        n = 44100  # 1 second of audio
        # Generate a low-frequency pulse train at ~120 BPM (2 Hz)
        samples = [0.8 * (1.0 if (i % (sr / 2)) < sr / 10 else 0.05) for i in range(n)]
        result = self.engine.detect_beats(samples, sample_rate=sr, threshold=0.3)
        assert isinstance(result, dict)
        assert result.get("success") is True

    def test_analyze_audio_full(self):
        if not self.available:
            pytest.skip("signal_engine DLL not available")
        sr = 44100.0
        n = 8820  # 0.2 seconds
        samples = [math.sin(2 * math.pi * 1000 * i / sr) for i in range(n)]
        result = self.engine.analyze_audio(samples, sample_rate=sr)
        assert isinstance(result, dict)
        assert "total_energy" in result
        assert result["total_energy"] > 0

    def test_ring_buffer_push_pop(self):
        if not self.available:
            pytest.skip("signal_engine DLL not available")
        rb = self.engine.create_ring_buffer(1024)
        data_in = [1.0, 2.0, 3.0, 4.0, 5.0]
        pushed = rb.push(data_in)
        assert pushed == len(data_in)
        assert rb.size == len(data_in)
        data_out = rb.pop(10)
        assert data_out == pytest.approx(data_in, abs=0.01)
        assert rb.empty

    def test_ring_buffer_overflow(self):
        if not self.available:
            pytest.skip("signal_engine DLL not available")
        rb = self.engine.create_ring_buffer(4)
        data_in = [1.0] * 10
        pushed = rb.push(data_in)
        assert pushed == 10
        # Pop returns only the last `capacity` items (ring overwrites)
        data_out = rb.pop(10)
        assert len(data_out) > 0


# ── Rust video-processor (subprocess) ────────────────────────────────────────


class TestRustVideoProcessor:
    """Python → Rust video_processor subprocess integration."""

    @pytest.fixture(autouse=True)
    def _find_binary(self):
        if sys.platform == "win32":
            self.binary = Path("tools/video-processor/target/release/tuncay-video-processor.exe")
        else:
            self.binary = Path("tools/video-processor/target/release/tuncay-video-processor")
        self.available = self.binary.exists()

    def test_binary_exists(self):
        if not self.available:
            pytest.skip("Rust binary not built")
        assert self.binary.stat().st_size > 0

    def test_version_command(self):
        if not self.available:
            pytest.skip("Rust binary not built")
        proc = subprocess.run(
            [str(self.binary), "--version"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 0
        assert len(proc.stdout.strip()) > 0

    def test_probe_command_nonexistent_file(self):
        if not self.available:
            pytest.skip("Rust binary not built")
        proc = subprocess.run(
            [str(self.binary), "probe", "nonexistent_vod.mp4"],
            capture_output=True, text=True, timeout=10,
        )
        # Should return error (non-zero exit or error JSON)
        assert proc.returncode != 0 or "error" in proc.stdout.lower()

    def test_validate_command_nonexistent_file(self):
        if not self.available:
            pytest.skip("Rust binary not built")
        proc = subprocess.run(
            [str(self.binary), "validate", "nonexistent_vod.mp4"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode != 0 or "error" in proc.stdout.lower()

    def test_checksum_command_nonexistent_file(self):
        if not self.available:
            pytest.skip("Rust binary not built")
        proc = subprocess.run(
            [str(self.binary), "checksum", "nonexistent_vod.mp4"],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode != 0 or "error" in proc.stdout.lower()


# ── Unified /health endpoint (Python FastAPI) ────────────────────────────────


class TestUnifiedHealthEndpoint:
    """Verify the /health endpoint reports engine statuses."""

    @pytest_asyncio.fixture
    async def client(self):
        try:
            from main import app
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
        except Exception:
            yield None

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_200(self, client):
        if client is None:
            pytest.skip("FastAPI app not importable")
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_health_returns_engines_dict(self, client):
        if client is None:
            pytest.skip("FastAPI app not importable")
        data = (await client.get("/health")).json()
        assert "engines" in data
        assert isinstance(data["engines"], dict)

    @pytest.mark.asyncio
    async def test_health_reports_cpp_signal_engine(self, client):
        if client is None:
            pytest.skip("FastAPI app not importable")
        data = (await client.get("/health")).json()
        engines = data["engines"]
        assert "cpp_signal_engine" in engines
        assert "status" in engines["cpp_signal_engine"]

    @pytest.mark.asyncio
    async def test_health_reports_rust_video_processor(self, client):
        if client is None:
            pytest.skip("FastAPI app not importable")
        data = (await client.get("/health")).json()
        engines = data["engines"]
        assert "rust_video_processor" in engines
        assert "status" in engines["rust_video_processor"]

    @pytest.mark.asyncio
    async def test_health_reports_analysis_engines(self, client):
        if client is None:
            pytest.skip("FastAPI app not importable")
        data = (await client.get("/health")).json()
        engines = data["engines"]
        assert "analysis_engines" in engines
        assert "available" in engines["analysis_engines"]


# ── TypeScript AI Worker functional test ──────────────────────────────────────

SAMPLE_TRANSCRIPT = """
[00:00:00] Welcome back to the stream guys, today we're playing Valorant
[00:00:05] Let me check the settings real quick
[00:00:10] OK guys we're in the game now, let's go
[00:00:15] Oh wait I hear someone coming from mid
[00:00:20] HE'S RIGHT THERE OH MY GOD
[00:00:25] I can't believe I hit that shot, that was insane
[00:00:30] Chat are you seeing this? That was a headshot from 50 meters
[00:00:35] Let me clip that, that's going on TikTok for sure
[00:00:40] Wait wait wait, another one coming
[00:00:45] NO WAY I GOT A DOUBLE KILL
[00:00:50] Chat is going crazy right now, W's in the chat
[00:00:55] OK guys calm down, it's just a game
[00:01:00] But seriously that was the best play I've ever made
[00:01:05] Let me check the clip, yeah that's perfect for a short
[00:01:10] We should make this the highlight of the stream
[00:01:15] Anyway let's continue, we have 3 more rounds to win
[00:01:20] I'm feeling confident now, let's gooooo
[00:01:25] *music plays* we're vibing now chat
[00:01:30] That double kill was absolutely nuts, I need to rewatch it
""".strip()

AI_WORKER_URL = "http://localhost:3001"


class TestAIWorkerFunctional:
    """Functional test: ai_worker 3-agent CoT pipeline end-to-end."""

    @pytest.fixture(autouse=True)
    def _check_worker(self):
        try:
            r = httpx.get(f"{AI_WORKER_URL}/health", timeout=3.0)
            self.available = r.status_code == 200
        except Exception:
            self.available = False

    @pytest.mark.asyncio
    async def test_analyze_returns_valid_schema(self):
        if not self.available:
            pytest.skip("AI Worker not running on :3001")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{AI_WORKER_URL}/analyze",
                json={"transcript": SAMPLE_TRANSCRIPT, "language": "en", "max_clips": 2},
            )

        assert resp.status_code == 200
        data = resp.json()

        # Top-level structure
        assert "clips" in data, "Response must contain 'clips' key"
        assert "agent_log" in data, "Response must contain 'agent_log' key"
        assert isinstance(data["clips"], list)
        assert isinstance(data["agent_log"], dict)

        # Agent log
        log = data["agent_log"]
        assert "analyzed" in log
        assert "reviewed" in log
        assert "finalized" in log

    @pytest.mark.asyncio
    async def test_clips_have_valid_timestamps(self):
        if not self.available:
            pytest.skip("AI Worker not running on :3001")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{AI_WORKER_URL}/analyze",
                json={"transcript": SAMPLE_TRANSCRIPT, "language": "en", "max_clips": 2},
            )

        data = resp.json()
        clips = data["clips"]

        if len(clips) == 0:
            pytest.skip("AI Worker returned 0 clips (LLM may be unavailable)")

        for clip in clips:
            # Required fields
            assert "start" in clip, f"Clip missing 'start': {clip}"
            assert "end" in clip, f"Clip missing 'end': {clip}"
            assert "reason" in clip, f"Clip missing 'reason': {clip}"
            assert "score" in clip, f"Clip missing 'score': {clip}"

            # Timestamp sanity
            assert isinstance(clip["start"], (int, float))
            assert isinstance(clip["end"], (int, float))
            assert clip["start"] >= 0, f"start must be >= 0: {clip['start']}"
            assert clip["end"] > clip["start"], f"end must be > start: {clip}"
            assert clip["end"] - clip["start"] <= 120, f"clip too long (>120s): {clip}"

            # Score sanity
            assert 0.0 <= clip["score"] <= 1.0, f"score must be 0-1: {clip['score']}"

            # Reason is non-empty string
            assert isinstance(clip["reason"], str)
            assert len(clip["reason"]) > 5, f"reason too short: {clip['reason']}"

    @pytest.mark.asyncio
    async def test_analyze_rejects_empty_transcript(self):
        if not self.available:
            pytest.skip("AI Worker not running on :3001")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{AI_WORKER_URL}/analyze",
                json={"transcript": ""},
            )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_analyze_rejects_missing_transcript(self):
        if not self.available:
            pytest.skip("AI Worker not running on :3001")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{AI_WORKER_URL}/analyze",
                json={},
            )

        assert resp.status_code == 400
