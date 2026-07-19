// ═══════════════════════════════════════════════════════════════════════════════
// audio_analyzer.cpp — FFT, beat detection, spectral analysis
// ═══════════════════════════════════════════════════════════════════════════════

#include "signal_engine/audio_analyzer.h"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <numbers>

namespace se {

// ── Public API ────────────────────────────────────────────────────────────────

Result<AudioAnalysis> AudioAnalyzer::analyze(
    std::span<const float> samples,
    double sample_rate
) {
    if (samples.empty() || sample_rate <= 0.0) {
        return Result<AudioAnalysis>::err(ErrorCode::InvalidInput, "empty samples or invalid sample_rate");
    }

    AudioAnalysis result{};
    result.sample_rate = sample_rate;
    result.duration_sec = static_cast<double>(samples.size()) / sample_rate;

    // ── Peak & RMS ────────────────────────────────────────────────────────
    double sum_sq = 0.0;
    float peak = 0.0f;
    int zero_crossings = 0;

    for (size_t i = 0; i < samples.size(); ++i) {
        float s = std::abs(samples[i]);
        if (s > peak) peak = s;
        sum_sq += static_cast<double>(samples[i]) * samples[i];
        if (i > 0 && ((samples[i] >= 0) != (samples[i - 1] >= 0))) {
            ++zero_crossings;
        }
    }

    result.peak_amplitude = peak;
    result.rms_level = std::sqrt(sum_sq / samples.size());
    result.zero_crossing_rate = static_cast<double>(zero_crossings) / samples.size();
    result.total_energy = sum_sq;

    // ── FFT spectrum ──────────────────────────────────────────────────────
    auto fft_mag = fft_magnitude(samples);
    if (fft_mag.empty()) {
        return Result<AudioAnalysis>::err(ErrorCode::InternalError, "FFT failed");
    }

    result.spectral_centroid = spectral_centroid(fft_mag, sample_rate);
    result.spectrum = band_energies(fft_mag, sample_rate, 8);

    // ── Envelope ──────────────────────────────────────────────────────────
    result.envelope = envelope(samples, 1024);

    // ── Beat detection ────────────────────────────────────────────────────
    auto beats_result = detect_beats(samples, sample_rate);
    if (beats_result.ok()) {
        result.beats = std::move(beats_result.value);
    }

    return Result<AudioAnalysis>::ok(std::move(result));
}

Result<std::vector<Beat>> AudioAnalyzer::detect_beats(
    std::span<const float> samples,
    double sample_rate,
    double threshold
) {
    if (samples.empty()) {
        return Result<std::vector<Beat>>::err(ErrorCode::InvalidInput, "empty samples");
    }

    // ── Onset strength function ───────────────────────────────────────────
    auto onset = onset_strength(samples, sample_rate, 512);
    if (onset.empty()) {
        return Result<std::vector<Beat>>::ok(std::vector<Beat>{});
    }

    // ── Adaptive threshold ────────────────────────────────────────────────
    const double mean = std::accumulate(onset.begin(), onset.end(), 0.0) / onset.size();
    const double adaptive_thresh = mean * (1.0 + threshold);

    // ── Peak picking with minimum interval ────────────────────────────────
    const double min_interval_sec = 0.15;  // min 150ms between beats
    const size_t hop_size = 512;
    const double hop_sec = static_cast<double>(hop_size) / sample_rate;
    const size_t min_samples_between = static_cast<size_t>(min_interval_sec / hop_sec);

    std::vector<Beat> beats;
    size_t last_beat_idx = 0;

    for (size_t i = 1; i + 1 < onset.size(); ++i) {
        if (onset[i] > adaptive_thresh &&
            onset[i] >= onset[i - 1] &&
            onset[i] >= onset[i + 1] &&
            (i - last_beat_idx) >= min_samples_between)
        {
            double ts = static_cast<double>(i) * hop_sec;
            double intensity = std::min(1.0, onset[i] / (adaptive_thresh * 2.0));
            beats.push_back({ts, intensity, 0.0});
            last_beat_idx = i;
        }
    }

    // ── Estimate BPM ──────────────────────────────────────────────────────
    if (beats.size() >= 2) {
        std::vector<double> beat_times;
        beat_times.reserve(beats.size());
        for (const auto& b : beats) beat_times.push_back(b.timestamp);
        double bpm = estimate_bpm(beat_times);
        for (auto& b : beats) b.bpm = bpm;
    }

    return Result<std::vector<Beat>>::ok(std::move(beats));
}

// ── FFT ───────────────────────────────────────────────────────────────────────

std::vector<double> AudioAnalyzer::fft_magnitude(std::span<const float> input) {
    size_t n = next_pow2(input.size());
    if (n < 2) return {};

    std::vector<std::complex<double>> data(n);
    for (size_t i = 0; i < n; ++i) {
        data[i] = (i < input.size()) ? std::complex<double>(input[i], 0.0) : 0.0;
    }

    fft_inplace(data);

    size_t out_len = n / 2;
    std::vector<double> mag(out_len);
    for (size_t i = 0; i < out_len; ++i) {
        mag[i] = std::abs(data[i]) / static_cast<double>(n);
    }

    return mag;
}

double AudioAnalyzer::spectral_centroid(std::span<const double> magnitudes, double sample_rate) {
    if (magnitudes.empty()) return 0.0;

    double weighted_sum = 0.0;
    double total_mag = 0.0;
    const double bin_hz = sample_rate / (magnitudes.size() * 2);

    for (size_t i = 0; i < magnitudes.size(); ++i) {
        double freq = i * bin_hz;
        weighted_sum += freq * magnitudes[i];
        total_mag += magnitudes[i];
    }

    return (total_mag > 0.0) ? weighted_sum / total_mag : 0.0;
}

std::vector<double> AudioAnalyzer::envelope(std::span<const float> samples, size_t target_frames) {
    if (samples.empty() || target_frames == 0) return {};

    const double step = static_cast<double>(samples.size()) / target_frames;
    std::vector<double> env(target_frames);

    for (size_t i = 0; i < target_frames; ++i) {
        size_t start = static_cast<size_t>(i * step);
        size_t end = static_cast<size_t>((i + 1) * step);
        end = std::min(end, samples.size());

        double sum = 0.0;
        for (size_t j = start; j < end; ++j) {
            sum += std::abs(samples[j]);
        }
        env[i] = (end > start) ? sum / (end - start) : 0.0;
    }

    return env;
}

std::vector<FrequencyBand> AudioAnalyzer::band_energies(
    std::span<const double> magnitudes,
    double sample_rate,
    size_t num_bands
) {
    if (magnitudes.empty() || num_bands == 0) return {};

    const double max_freq = sample_rate / 2.0;
    const double band_width = max_freq / num_bands;
    const double bin_hz = sample_rate / (magnitudes.size() * 2);

    std::vector<FrequencyBand> bands;

    for (size_t b = 0; b < num_bands; ++b) {
        double lo = b * band_width;
        double hi = (b + 1) * band_width;
        double center = (lo + hi) / 2.0;

        size_t bin_lo = static_cast<size_t>(lo / bin_hz);
        size_t bin_hi = static_cast<size_t>(hi / bin_hz);
        bin_hi = std::min(bin_hi, magnitudes.size());

        double energy = 0.0;
        size_t count = 0;
        for (size_t i = bin_lo; i < bin_hi; ++i) {
            energy += magnitudes[i];
            ++count;
        }
        energy = (count > 0) ? energy / count : 0.0;

        bands.push_back({center, std::min(1.0, energy * 10.0)});
    }

    return bands;
}

std::vector<double> AudioAnalyzer::onset_strength(
    std::span<const float> samples,
    double sample_rate,
    size_t hop_size
) {
    if (samples.size() < hop_size * 2) return {};

    const size_t n_frames = (samples.size() - hop_size) / hop_size;
    std::vector<double> onset(n_frames);

    for (size_t i = 0; i < n_frames; ++i) {
        size_t offset = i * hop_size;

        // Spectral flux (simplified: energy difference)
        double energy_now = 0.0;
        double energy_prev = 0.0;

        for (size_t j = 0; j < hop_size && (offset + j) < samples.size(); ++j) {
            double s = samples[offset + j];
            energy_now += s * s;
        }
        if (offset >= hop_size) {
            for (size_t j = 0; j < hop_size; ++j) {
                double s = samples[offset - hop_size + j];
                energy_prev += s * s;
            }
        }

        // Half-wave rectified difference
        double diff = energy_now - energy_prev;
        onset[i] = (diff > 0.0) ? diff : 0.0;
    }

    return onset;
}

// ── FFT implementation (Cooley-Tukey radix-2) ────────────────────────────────

void AudioAnalyzer::fft_inplace(std::vector<std::complex<double>>& data) {
    const size_t n = data.size();
    if (n <= 1) return;

    // Bit-reversal permutation
    for (size_t i = 1, j = 0; i < n; ++i) {
        size_t bit = n >> 1;
        for (; j & bit; bit >>= 1) {
            j ^= bit;
        }
        j ^= bit;
        if (i < j) {
            std::swap(data[i], data[j]);
        }
    }

    // Butterfly stages
    for (size_t len = 2; len <= n; len <<= 1) {
        const double angle = -2.0 * std::numbers::pi / static_cast<double>(len);
        const std::complex<double> wn(std::cos(angle), std::sin(angle));

        for (size_t i = 0; i < n; i += len) {
            std::complex<double> w(1.0, 0.0);
            for (size_t j = 0; j < len / 2; ++j) {
                auto u = data[i + j];
                auto t = w * data[i + j + len / 2];
                data[i + j] = u + t;
                data[i + j + len / 2] = u - t;
                w *= wn;
            }
        }
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

size_t AudioAnalyzer::next_pow2(size_t n) {
    size_t p = 1;
    while (p < n) p <<= 1;
    return p;
}

double AudioAnalyzer::estimate_bpm(const std::vector<double>& beat_times) {
    if (beat_times.size() < 2) return 0.0;

    // Median inter-beat interval
    std::vector<double> intervals;
    intervals.reserve(beat_times.size() - 1);
    for (size_t i = 1; i < beat_times.size(); ++i) {
        intervals.push_back(beat_times[i] - beat_times[i - 1]);
    }
    std::sort(intervals.begin(), intervals.end());
    double median_interval = intervals[intervals.size() / 2];

    if (median_interval <= 0.0) return 0.0;
    return 60.0 / median_interval;
}

} // namespace se
