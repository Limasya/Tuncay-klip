"""
Benchmark: C++ signal_engine FFT vs scipy.fft
Measures wall-clock time for FFT computation at various sizes.
"""
import math
import sys
import time
import statistics

sys.path.insert(0, ".")


def generate_sine_wave(n: int, freq: float = 440.0, sr: float = 44100.0):
    return [math.sin(2 * math.pi * freq * i / sr) for i in range(n)]


def bench_scipy(samples, iterations=50):
    import scipy.fft
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        scipy.fft.fft(samples)
        times.append(time.perf_counter() - t0)
    return times


def bench_cpp(samples, iterations=50):
    from signal_engine.python.signal_client import SignalEngine
    se = SignalEngine()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        se.fft_magnitude(samples)
        times.append(time.perf_counter() - t0)
    return times


def main():
    sizes = [1024, 4096, 8192, 16384, 32768, 65536]
    print(f"{'N':>8} | {'scipy (ms)':>12} | {'C++ (ms)':>12} | {'Speedup':>8}")
    print("-" * 50)

    for n in sizes:
        samples = generate_sine_wave(n)
        try:
            scipy_times = bench_scipy(samples)
            scipy_median = statistics.median(scipy_times) * 1000
        except Exception as e:
            scipy_median = float('nan')
            print(f"  scipy error at N={n}: {e}")

        try:
            cpp_times = bench_cpp(samples)
            cpp_median = statistics.median(cpp_times) * 1000
        except Exception as e:
            cpp_median = float('nan')
            print(f"  C++ error at N={n}: {e}")

        if not math.isnan(scipy_median) and not math.isnan(cpp_median) and cpp_median > 0:
            speedup = scipy_median / cpp_median
            print(f"{n:>8} | {scipy_median:>10.3f}ms | {cpp_median:>10.3f}ms | {speedup:>7.1f}x")
        else:
            print(f"{n:>8} | {'N/A':>12} | {'N/A':>12} | {'N/A':>8}")


if __name__ == "__main__":
    main()
