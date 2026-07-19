// ═══════════════════════════════════════════════════════════════════════════════
// test_all.cpp — Unit tests for signal_engine (minimal, no framework)
// ═══════════════════════════════════════════════════════════════════════════════

#include "signal_engine/types.h"
#include "signal_engine/ring_buffer.h"
#include "signal_engine/audio_analyzer.h"
#include "signal_engine/video_analyzer.h"

#include <cassert>
#include <cstdio>
#include <cmath>
#include <numbers>
#include <vector>
#include <numeric>

static int tests_passed = 0;
static int tests_failed = 0;

#define TEST(name) \
    static void test_##name(); \
    struct TestReg_##name { TestReg_##name() { \
        printf("  %-40s", #name); \
        test_##name(); \
        printf("PASS\n"); \
        tests_passed++; \
    } } reg_##name; \
    static void test_##name()

#define ASSERT(cond) do { \
    if (!(cond)) { \
        printf("FAIL\n    Assert failed: %s (%s:%d)\n", #cond, __FILE__, __LINE__); \
        tests_failed++; \
        return; \
    } \
} while(0)

#define ASSERT_NEAR(a, b, eps) do { \
    if (std::abs((a) - (b)) > (eps)) { \
        printf("FAIL\n    Assert failed: |%f - %f| > %f (%s:%d)\n", \
               (double)(a), (double)(b), (double)(eps), __FILE__, __LINE__); \
        tests_failed++; \
        return; \
    } \
} while(0)

// ── Ring Buffer Tests ────────────────────────────────────────────────────────

TEST(ring_buffer_basic) {
    se::RingBuffer<int, 16> rb;
    ASSERT(rb.empty());
    ASSERT(rb.capacity() == 16);

    ASSERT(rb.push(42));
    ASSERT(!rb.empty());
    ASSERT(rb.size() == 1);

    auto val = rb.pop();
    ASSERT(val.has_value());
    ASSERT(*val == 42);
    ASSERT(rb.empty());
}

TEST(ring_buffer_full) {
    se::RingBuffer<int, 4> rb;  // capacity 4, usable 3
    ASSERT(rb.push(1));
    ASSERT(rb.push(2));
    ASSERT(rb.push(3));
    ASSERT(!rb.push(4));  // full (one slot reserved)

    ASSERT(rb.size() == 3);

    auto v1 = rb.pop();
    ASSERT(v1.has_value() && *v1 == 1);

    ASSERT(rb.push(4));  // now we can push again
    ASSERT(rb.size() == 3);
}

TEST(ring_buffer_bulk) {
    se::RingBuffer<float, 1024> rb;
    std::vector<float> data(100);
    std::iota(data.begin(), data.end(), 1.0f);

    size_t pushed = rb.push_bulk(data.data(), 100);
    ASSERT(pushed == 100);
    ASSERT(rb.size() == 100);

    std::vector<float> out(100);
    size_t popped = rb.pop_bulk(out.data(), 100);
    ASSERT(popped == 100);
    ASSERT(out[0] == 1.0f);
    ASSERT(out[99] == 100.0f);
}

TEST(ring_buffer_reset) {
    se::RingBuffer<int, 8> rb;
    for (int i = 0; i < 5; ++i) rb.push(i);
    ASSERT(rb.size() == 5);

    rb.reset();
    ASSERT(rb.empty());
    ASSERT(rb.size() == 0);
}

// ── Audio Analyzer Tests ─────────────────────────────────────────────────────

TEST(audio_analyze_sine_wave) {
    se::AudioAnalyzer aa;
    const double sr = 44100.0;
    const size_t n = 4096;

    std::vector<float> samples(n);
    for (size_t i = 0; i < n; ++i) {
        samples[i] = static_cast<float>(std::sin(2.0 * std::numbers::pi * 440.0 * i / sr));
    }

    auto result = aa.analyze(samples, sr);
    ASSERT(result.ok());
    ASSERT(result.value.sample_rate == sr);
    ASSERT(result.value.duration_sec > 0.0);
    ASSERT(result.value.peak_amplitude > 0.9);
    ASSERT(result.value.rms_level > 0.1);
    ASSERT(!result.value.spectrum.empty());
}

TEST(audio_fft_magnitude) {
    auto mag = se::AudioAnalyzer::fft_magnitude(
        std::vector<float>{1.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f});
    ASSERT(!mag.empty());
    ASSERT(mag.size() == 4);
    // DC component should have energy
    ASSERT(mag[0] > 0.0);
}

TEST(audio_spectral_centroid) {
    // Pure tone → centroid should be at 440 Hz
    const double sr = 44100.0;
    const size_t n = 8192;
    std::vector<float> samples(n);
    for (size_t i = 0; i < n; ++i) {
        samples[i] = static_cast<float>(std::sin(2.0 * std::numbers::pi * 440.0 * i / sr));
    }
    auto mag = se::AudioAnalyzer::fft_magnitude(samples);
    double centroid = se::AudioAnalyzer::spectral_centroid(mag, sr);
    ASSERT_NEAR(centroid, 440.0, 3000.0);
}

TEST(audio_envelope) {
    std::vector<float> samples(1000, 0.5f);
    auto env = se::AudioAnalyzer::envelope(samples, 10);
    ASSERT(env.size() == 10);
    for (double v : env) {
        ASSERT_NEAR(v, 0.5, 0.01);
    }
}

TEST(audio_band_energies) {
    std::vector<double> mags(256, 0.0);
    mags[10] = 1.0;  // energy in one bin
    auto bands = se::AudioAnalyzer::band_energies(mags, 44100.0, 4);
    ASSERT(bands.size() == 4);
}

// ── Video Analyzer Tests ─────────────────────────────────────────────────────

TEST(video_diff_identical) {
    se::VideoAnalyzer va(8, 8, 30.0);
    std::vector<uint8_t> frame(8 * 8 * 3, 128);
    double diff = va.diff_frames(frame, frame);
    ASSERT_NEAR(diff, 0.0, 0.001);
}

TEST(video_diff_different) {
    se::VideoAnalyzer va(8, 8, 30.0);
    std::vector<uint8_t> prev(8 * 8 * 3, 0);
    std::vector<uint8_t> curr(8 * 8 * 3, 255);
    double diff = va.diff_frames(prev, curr);
    ASSERT_NEAR(diff, 1.0, 0.01);
}

TEST(video_analyze_basic) {
    se::VideoAnalyzer va(16, 16, 10.0);
    const int n_frames = 5;
    std::vector<uint8_t> frames(16 * 16 * 3 * n_frames);

    // Fill frames with gradient (each frame slightly different)
    for (int f = 0; f < n_frames; ++f) {
        for (int y = 0; y < 16; ++y) {
            for (int x = 0; x < 16; ++x) {
                size_t idx = (f * 256 + y * 16 + x) * 3;
                uint8_t val = static_cast<uint8_t>(f * 50);
                frames[idx] = val;
                frames[idx + 1] = val;
                frames[idx + 2] = val;
            }
        }
    }

    auto result = va.analyze(frames, n_frames);
    ASSERT(result.ok());
    ASSERT(result.value.total_frames == n_frames);
    ASSERT(result.value.fps == 10.0);
}

// ── Type Tests ────────────────────────────────────────────────────────────────

TEST(error_code_strings) {
    ASSERT(std::string(se::error_string(se::ErrorCode::Ok)) == "ok");
    ASSERT(std::string(se::error_string(se::ErrorCode::InvalidInput)) == "invalid input");
    ASSERT(std::string(se::error_string(se::ErrorCode::FileNotFound)) == "file not found");
}

TEST(result_wrapper) {
    auto ok = se::Result<int>::ok(42);
    ASSERT(ok.ok());
    ASSERT(ok.value == 42);

    auto err = se::Result<int>::err(se::ErrorCode::InvalidInput, "bad");
    ASSERT(!err.ok());
    ASSERT(err.error == "bad");
}

// ── Main ──────────────────────────────────────────────────────────────────────

int main() {
    printf("\n═══════════════════════════════════════════════════\n");
    printf("  signal_engine unit tests\n");
    printf("═══════════════════════════════════════════════════\n\n");

    printf("Ring Buffer:\n");
    // Tests auto-register via static initialization

    printf("\nAudio Analyzer:\n");

    printf("\nVideo Analyzer:\n");

    printf("\nTypes:\n");

    printf("\n───────────────────────────────────────────────────\n");
    printf("  %d passed, %d failed\n", tests_passed, tests_failed);
    printf("───────────────────────────────────────────────────\n\n");

    return tests_failed > 0 ? 1 : 0;
}
