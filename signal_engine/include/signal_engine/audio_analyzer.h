#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// signal_engine/audio_analyzer.h — Audio FFT analysis, beat detection, energy
// ═══════════════════════════════════════════════════════════════════════════════
//
// Features:
//   - In-place FFT via radix-2 Cooley-Tukey (no external deps)
//   - Spectral analysis with configurable frequency bands
//   - Beat detection via onset detection function
//   - Amplitude envelope extraction
//   - RMS / peak / zero-crossing / spectral centroid
//
// All methods operate on raw float arrays (interleaved stereo → mono assumed).

#include "types.h"
#include <complex>
#include <vector>
#include <span>
#include <cstddef>

namespace se {

class AudioAnalyzer {
public:
    AudioAnalyzer() = default;

    /// Analyze a mono float buffer (sample_rate Hz).
    Result<AudioAnalysis> analyze(
        std::span<const float> samples,
        double sample_rate
    );

    /// Detect beats from a pre-computed energy envelope.
    Result<std::vector<Beat>> detect_beats(
        std::span<const float> samples,
        double sample_rate,
        double threshold = 0.3
    );

    /// Compute FFT magnitude spectrum (power-of-2 length required).
    static std::vector<double> fft_magnitude(std::span<const float> input);

    /// Compute spectral centroid from FFT magnitudes.
    static double spectral_centroid(std::span<const double> magnitudes, double sample_rate);

    /// Extract amplitude envelope (downsampled to `target_frames`).
    static std::vector<double> envelope(std::span<const float> samples, size_t target_frames);

    /// Compute frequency band energies from FFT.
    static std::vector<FrequencyBand> band_energies(
        std::span<const double> magnitudes,
        double sample_rate,
        size_t num_bands = 8
    );

    /// Detect onset strength (for beat tracking).
    static std::vector<double> onset_strength(
        std::span<const float> samples,
        double sample_rate,
        size_t hop_size = 512
    );

private:
    /// Radix-2 Cooley-Tukey FFT (in-place, complex<double>).
    static void fft_inplace(std::vector<std::complex<double>>& data);

    /// Next power of 2 >= n.
    static size_t next_pow2(size_t n);

    /// Running BPM estimation from beat intervals.
    static double estimate_bpm(const std::vector<double>& beat_times);
};

} // namespace se
