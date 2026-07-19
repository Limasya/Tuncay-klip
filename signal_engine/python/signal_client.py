"""
Signal Engine — Python Ctypes Wrapper
======================================
High-performance C++ signal processing engine for the Tuncay-Klip pipeline.
Exposes audio FFT, beat detection, video motion analysis, and scene detection.

Usage:
    from signal_engine.signal_client import signal_engine

    # Analyze audio
    result = signal_engine.analyze_audio(samples, sample_rate=44100.0)
    print(f"Beats: {result['beat_count']}, BPM: {result['beats'][0]['bpm']}")

    # Detect beats only (fast)
    beats = signal_engine.detect_beats(samples, sample_rate=44100.0)

    # Analyze video frames (RGB24)
    result = signal_engine.analyze_video(frames, width=1920, height=1080, fps=30.0)

    # Correlate audio + video for viral moments
    moments = signal_engine.correlate_signals(audio_samples, video_frames, ...)
"""
from __future__ import annotations

import ctypes
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Find shared library ───────────────────────────────────────────────────────

_SEARCH_PATHS = [
    Path(__file__).resolve().parent.parent.parent / "signal_engine" / "build" / "bin" / "Release",
    Path(__file__).resolve().parent.parent.parent / "signal_engine" / "build" / "bin" / "Debug",
    Path(__file__).resolve().parent.parent.parent / "signal_engine" / "build" / "Release",
    Path(__file__).resolve().parent.parent.parent / "signal_engine" / "build",
    Path(__file__).resolve().parent.parent.parent / "signal_engine" / "build" / "lib",
]

if sys.platform == "win32":
    _LIB_NAMES = ["signal_engine.dll"]
else:
    _LIB_NAMES = ["libsignal_engine.so", "libsignal_engine.dylib"]


def _find_library() -> Optional[Path]:
    for search in _SEARCH_PATHS:
        for name in _LIB_NAMES:
            lib_path = search / name
            if lib_path.exists():
                return lib_path
    # Also try system path (LD_LIBRARY_PATH, PATH)
    for name in _LIB_NAMES:
        try:
            ctypes.CDLL(name)
            return Path(name)
        except OSError:
            continue
    return None


# ── Signal Engine Client ──────────────────────────────────────────────────────

class SignalEngine:
    """Python wrapper for the C++ signal processing engine."""

    def __init__(self, lib_path: Optional[str | Path] = None):
        self._lib: Optional[ctypes.CDLL] = None
        self._available = False

        if lib_path:
            self._load(Path(lib_path))
        else:
            found = _find_library()
            if found:
                self._load(found)

    def _load(self, path: Path) -> None:
        try:
            self._lib = ctypes.CDLL(str(path))

            # Audio API — use c_void_p for all JSON-returning functions so
            # we can pass the raw pointer to se_free (c_char_p copies the
            # string and loses the original pointer, causing heap corruption).
            self._lib.se_analyze_audio.restype = ctypes.c_void_p
            self._lib.se_analyze_audio.argtypes = [
                ctypes.POINTER(ctypes.c_float), ctypes.c_size_t, ctypes.c_double
            ]

            self._lib.se_detect_beats.restype = ctypes.c_void_p
            self._lib.se_detect_beats.argtypes = [
                ctypes.POINTER(ctypes.c_float), ctypes.c_size_t,
                ctypes.c_double, ctypes.c_double
            ]

            self._lib.se_fft_magnitude.restype = ctypes.c_void_p
            self._lib.se_fft_magnitude.argtypes = [
                ctypes.POINTER(ctypes.c_float), ctypes.c_size_t
            ]

            # Video API
            self._lib.se_analyze_video.restype = ctypes.c_void_p
            self._lib.se_analyze_video.argtypes = [
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_double
            ]

            self._lib.se_diff_frames.restype = ctypes.c_void_p
            self._lib.se_diff_frames.argtypes = [
                ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_int, ctypes.c_int, ctypes.c_double
            ]

            # Combined API
            self._lib.se_correlate_signals.restype = ctypes.c_void_p
            self._lib.se_correlate_signals.argtypes = [
                ctypes.POINTER(ctypes.c_float), ctypes.c_size_t, ctypes.c_double,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_double
            ]

            # Ring buffer API
            self._lib.se_ring_create.restype = ctypes.c_void_p
            self._lib.se_ring_create.argtypes = [ctypes.c_size_t]

            self._lib.se_ring_destroy.restype = None
            self._lib.se_ring_destroy.argtypes = [ctypes.c_void_p]

            self._lib.se_ring_push.restype = ctypes.c_int
            self._lib.se_ring_push.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t
            ]

            self._lib.se_ring_pop.restype = ctypes.c_size_t
            self._lib.se_ring_pop.argtypes = [
                ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_size_t
            ]

            self._lib.se_ring_size.restype = ctypes.c_size_t
            self._lib.se_ring_size.argtypes = [ctypes.c_void_p]

            self._lib.se_ring_empty.restype = ctypes.c_int
            self._lib.se_ring_empty.argtypes = [ctypes.c_void_p]

            # Utility
            self._lib.se_free.restype = None
            self._lib.se_free.argtypes = [ctypes.c_void_p]

            self._lib.se_version.restype = ctypes.c_void_p
            self._lib.se_version.argtypes = []

            self._available = True
            logger.info("Signal Engine loaded: %s", path)

        except Exception as e:
            logger.warning("Failed to load Signal Engine: %s", e)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _parse_result(self, raw: Optional[int]) -> Dict[str, Any]:
        """Parse a JSON result from a c_void_p pointer, then free the C memory."""
        if raw is None:
            return {"success": False, "error": "null pointer"}
        try:
            data_bytes = ctypes.string_at(raw)
            data = json.loads(data_bytes.decode("utf-8"))
            return data
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            self._lib.se_free(raw)

    # ── Audio ──────────────────────────────────────────────────────────────

    def analyze_audio(
        self,
        samples: List[float],
        sample_rate: float = 44100.0,
    ) -> Dict[str, Any]:
        """Analyze audio samples. Returns FFT spectrum, beats, energy, etc."""
        if not self._available:
            return {"success": False, "error": "signal_engine not available"}

        n = len(samples)
        arr = (ctypes.c_float * n)(*samples)
        raw = self._lib.se_analyze_audio(arr, n, sample_rate)
        return self._parse_result(raw)

    def detect_beats(
        self,
        samples: List[float],
        sample_rate: float = 44100.0,
        threshold: float = 0.3,
    ) -> Dict[str, Any]:
        """Fast beat detection only."""
        if not self._available:
            return {"success": False, "error": "signal_engine not available"}

        n = len(samples)
        arr = (ctypes.c_float * n)(*samples)
        raw = self._lib.se_detect_beats(arr, n, sample_rate, threshold)
        return self._parse_result(raw)

    def fft_magnitude(self, samples: List[float]) -> Dict[str, Any]:
        """Compute FFT magnitude spectrum."""
        if not self._available:
            return {"success": False, "error": "signal_engine not available"}

        n = len(samples)
        arr = (ctypes.c_float * n)(*samples)
        raw = self._lib.se_fft_magnitude(arr, n)
        return self._parse_result(raw)

    # ── Video ──────────────────────────────────────────────────────────────

    def analyze_video(
        self,
        frames: bytes,
        width: int,
        height: int,
        frame_count: int,
        fps: float = 30.0,
    ) -> Dict[str, Any]:
        """Analyze RGB24 video frames for scene changes and motion."""
        if not self._available:
            return {"success": False, "error": "signal_engine not available"}

        n = len(frames)
        arr = (ctypes.c_uint8 * n)(*frames)
        raw = self._lib.se_analyze_video(arr, width, height, frame_count, fps)
        return self._parse_result(raw)

    def diff_frames(
        self,
        prev_frame: bytes,
        curr_frame: bytes,
        width: int,
        height: int,
        threshold: float = 0.35,
    ) -> Dict[str, Any]:
        """Diff two RGB24 frames."""
        if not self._available:
            return {"success": False, "error": "signal_engine not available"}

        n = len(prev_frame)
        arr_prev = (ctypes.c_uint8 * n)(*prev_frame)
        arr_curr = (ctypes.c_uint8 * n)(*curr_frame)
        raw = self._lib.se_diff_frames(arr_prev, arr_curr, width, height, threshold)
        return self._parse_result(raw)

    # ── Combined ───────────────────────────────────────────────────────────

    def correlate_signals(
        self,
        audio_samples: List[float],
        sample_rate: float,
        video_frames: bytes,
        width: int,
        height: int,
        frame_count: int,
        video_fps: float = 30.0,
    ) -> Dict[str, Any]:
        """Correlate audio + video for viral moments."""
        if not self._available:
            return {"success": False, "error": "signal_engine not available"}

        audio_n = len(audio_samples)
        audio_arr = (ctypes.c_float * audio_n)(*audio_samples)
        video_n = len(video_frames)
        video_arr = (ctypes.c_uint8 * video_n)(*video_frames)

        raw = self._lib.se_correlate_signals(
            audio_arr, audio_n, sample_rate,
            video_arr, width, height, frame_count, video_fps,
        )
        return self._parse_result(raw)

    # ── Ring Buffer ────────────────────────────────────────────────────────

    def create_ring_buffer(self, capacity: int = 65536) -> "RingBuffer":
        """Create a lock-free ring buffer for streaming audio."""
        if not self._available:
            raise RuntimeError("signal_engine not available")
        return RingBuffer(self._lib, capacity)

    # ── Version ────────────────────────────────────────────────────────────

    def version(self) -> str:
        if not self._available:
            return "signal_engine not available"
        raw = self._lib.se_version()
        if raw:
            data = ctypes.string_at(raw).decode("utf-8")
            self._lib.se_free(raw)
            return data
        return "unknown"


class RingBuffer:
    """Lock-free ring buffer for real-time audio streaming."""

    def __init__(self, lib: ctypes.CDLL, capacity: int):
        self._lib = lib
        self._capacity = capacity
        self._handle = lib.se_ring_create(capacity)
        if not self._handle:
            raise RuntimeError("Failed to create ring buffer")

    def __del__(self):
        if hasattr(self, '_handle') and self._handle:
            self._lib.se_ring_destroy(self._handle)

    def push(self, data: List[float]) -> int:
        n = len(data)
        arr = (ctypes.c_float * n)(*data)
        return self._lib.se_ring_push(self._handle, arr, n)

    def pop(self, max_count: int) -> List[float]:
        arr = (ctypes.c_float * max_count)()
        count = self._lib.se_ring_pop(self._handle, arr, max_count)
        return [arr[i] for i in range(count)]

    @property
    def size(self) -> int:
        return self._lib.se_ring_size(self._handle)

    @property
    def empty(self) -> bool:
        return self._lib.se_ring_empty(self._handle) == 1

    @property
    def capacity(self) -> int:
        return self._capacity


# ── Singleton ─────────────────────────────────────────────────────────────────

signal_engine = SignalEngine()
