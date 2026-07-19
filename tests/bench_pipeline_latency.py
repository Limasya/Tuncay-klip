"""
Benchmark: End-to-end pipeline latency measurement.
Measures how long each analysis engine takes to process data,
then recommends ring buffer size for the given pipeline.
"""
import math
import struct
import sys
import time
import statistics

import numpy as np

sys.path.insert(0, ".")


def bench_signal_engine_analyze_audio(iterations=20):
    """C++ signal_engine analyze_audio latency."""
    from signal_engine.python.signal_client import SignalEngine
    se = SignalEngine()
    if not se.available:
        return None

    sr = 44100.0
    n = int(sr * 5)  # 5 seconds of audio
    samples = [math.sin(2 * math.pi * 440 * i / sr) for i in range(n)]

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = se.analyze_audio(samples, sr)
        times.append(time.perf_counter() - t0)

    return {
        "engine": "C++ signal_engine.analyze_audio",
        "input_size": f"{n} samples ({n/sr:.1f}s)",
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(len(times) * 0.95)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
    }


def bench_streaming_audio_analyze(iterations=50):
    """Streaming AudioAnalyzer._process_chunk latency."""
    from services.analysis.audio_analysis import AudioAnalyzer
    analyzer = AudioAnalyzer()

    sr = 16000
    chunk_size = 1024
    samples = np.random.randn(chunk_size).astype(np.float32) * 0.1

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        analyzer._process_chunk(samples)
        times.append(time.perf_counter() - t0)

    return {
        "engine": "streaming AudioAnalyzer._process_chunk",
        "input_size": f"{chunk_size} samples ({chunk_size/sr*1000:.1f}ms)",
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(len(times) * 0.95)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
    }


def bench_diff_frames(iterations=20):
    """C++ signal_engine diff_frames latency."""
    from signal_engine.python.signal_client import SignalEngine
    se = SignalEngine()
    if not se.available:
        return None

    w, h = 320, 240
    frame_size = w * h * 3
    prev_frame = np.random.randint(0, 256, frame_size, dtype=np.uint8).tobytes()
    curr_frame = np.random.randint(0, 256, frame_size, dtype=np.uint8).tobytes()

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = se.diff_frames(prev_frame, curr_frame, w, h, 0.35)
        times.append(time.perf_counter() - t0)

    return {
        "engine": "C++ signal_engine.diff_frames",
        "input_size": f"{w}x{h} RGB24 ({frame_size} bytes)",
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(len(times) * 0.95)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
    }


def bench_face_emotion(iterations=10):
    """FaceEmotionAnalyzer.analyze_frame latency (model dependent)."""
    try:
        from services.analysis.face_emotion import FaceEmotionAnalyzer
        analyzer = FaceEmotionAnalyzer()
    except Exception as e:
        return {"engine": "FaceEmotionAnalyzer", "error": str(e)}

    w, h = 320, 240
    frame = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

    # Warmup
    for _ in range(3):
        analyzer.analyze_frame(frame)

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        analyzer.analyze_frame(frame)
        times.append(time.perf_counter() - t0)

    return {
        "engine": "FaceEmotionAnalyzer.analyze_frame",
        "input_size": f"{w}x{h} BGR",
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(len(times) * 0.95)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
    }


def bench_motion_detection(iterations=20):
    """MotionAnalyzer.analyze_frame latency."""
    try:
        from services.analysis.motion_detection import MotionAnalyzer
        analyzer = MotionAnalyzer()
    except Exception as e:
        return {"engine": "MotionAnalyzer", "error": str(e)}

    w, h = 320, 240
    frame = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)

    # Warmup
    for _ in range(3):
        analyzer.analyze_frame(frame)

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        analyzer.analyze_frame(frame)
        times.append(time.perf_counter() - t0)

    return {
        "engine": "MotionAnalyzer.analyze_frame",
        "input_size": f"{w}x{h} BGR",
        "median_ms": statistics.median(times) * 1000,
        "p95_ms": sorted(times)[int(len(times) * 0.95)] * 1000,
        "min_ms": min(times) * 1000,
        "max_ms": max(times) * 1000,
    }


def bench_ring_buffer_push_pop(iterations=100):
    """C++ ring buffer push/pop throughput."""
    from signal_engine.python.signal_client import SignalEngine
    se = SignalEngine()
    if not se.available:
        return None

    rb = se.create_ring_buffer(65536)
    chunk = [0.1] * 44100  # 1 second of audio

    # Push benchmark
    push_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        rb.push(chunk)
        push_times.append(time.perf_counter() - t0)

    # Pop benchmark
    pop_times = []
    for _ in range(iterations):
        rb.push(chunk)
        t0 = time.perf_counter()
        rb.pop(44100)
        pop_times.append(time.perf_counter() - t0)

    return {
        "engine": "C++ RingBuffer push/pop",
        "input_size": f"44100 floats (1s @ 44100Hz)",
        "push_median_us": statistics.median(push_times) * 1e6,
        "pop_median_us": statistics.median(pop_times) * 1e6,
        "throughput_push_samples_per_sec": 44100 / statistics.median(push_times),
    }


def print_result(result):
    if result is None:
        print("  SKIP (engine not available)")
        return
    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return
    for k, v in result.items():
        if k == "engine":
            print(f"\n  [{v}]")
        elif k == "input_size":
            print(f"    Input: {v}")
        elif "_ms" in k:
            print(f"    {k}: {v:.3f} ms")
        elif "_us" in k:
            print(f"    {k}: {v:.1f} us")
        elif "throughput" in k:
            print(f"    {k}: {v:,.0f}")


def main():
    print("=" * 60)
    print("  Pipeline Latency Benchmark")
    print("=" * 60)

    benchmarks = [
        bench_streaming_audio_analyze,
        bench_signal_engine_analyze_audio,
        bench_diff_frames,
        bench_face_emotion,
        bench_motion_detection,
        bench_ring_buffer_push_pop,
    ]

    results = []
    for bench_fn in benchmarks:
        try:
            r = bench_fn()
            results.append(r)
            print_result(r)
        except Exception as e:
            print(f"  {bench_fn.__name__}: ERROR {e}")
            results.append(None)

    # Latency summary
    print("\n" + "=" * 60)
    print("  Pipeline Latency Summary")
    print("=" * 60)

    total_pipeline_ms = 0
    for r in results:
        if r and "median_ms" in r:
            total_pipeline_ms += r["median_ms"]

    print(f"\n  Estimated total pipeline latency: {total_pipeline_ms:.1f} ms")
    print(f"  Recommended analysis interval:    {max(total_pipeline_ms * 3, 1000):.0f} ms (3x pipeline)")

    # Ring buffer size recommendation
    sr = 44100
    buffer_seconds = 180  # 3 minutes
    recommended_capacity = 2 ** math.ceil(math.log2(buffer_seconds * sr))
    print(f"\n  Ring buffer recommendation:")
    print(f"    Current: 65536 samples (~{65536/sr:.1f}s)")
    print(f"    For 3min: {recommended_capacity} samples (~{recommended_capacity/sr:.0f}s)")
    print(f"    Memory:   {recommended_capacity * 4 / 1024 / 1024:.1f} MB (float32)")


if __name__ == "__main__":
    main()
