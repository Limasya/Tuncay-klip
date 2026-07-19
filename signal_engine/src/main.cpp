// ═══════════════════════════════════════════════════════════════════════════════
// main.cpp — CLI tool for signal_engine (standalone testing)
// ═══════════════════════════════════════════════════════════════════════════════

#include "signal_engine/api.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cmath>
#include <numbers>
#include <vector>

static void print_usage() {
    std::printf(
        "signal_engine CLI v1.0.0\n"
        "\n"
        "Usage:\n"
        "  se_cli audio-demo       Run audio analysis demo (sine wave)\n"
        "  se_cli video-demo        Run video analysis demo (motion blocks)\n"
        "  se_cli ring-demo         Run ring buffer demo\n"
        "  se_cli version           Print version\n"
        "\n"
    );
}

static void audio_demo() {
    std::printf("=== Audio Analysis Demo ===\n\n");

    // Generate a test signal: 440 Hz sine wave + 880 Hz harmonics
    const double sample_rate = 44100.0;
    const double duration = 2.0;
    const size_t n = static_cast<size_t>(sample_rate * duration);

    std::vector<float> samples(n);
    for (size_t i = 0; i < n; ++i) {
        double t = static_cast<double>(i) / sample_rate;
        // Simulate beat drops at 2 Hz (120 BPM)
        double beat_env = 0.5 + 0.5 * std::sin(2.0 * std::numbers::pi * 2.0 * t);
        samples[i] = static_cast<float>(
            beat_env * (
                0.6 * std::sin(2.0 * std::numbers::pi * 440.0 * t) +
                0.3 * std::sin(2.0 * std::numbers::pi * 880.0 * t) +
                0.1 * std::sin(2.0 * std::numbers::pi * 1320.0 * t)
            )
        );
    }

    const char* result = se_analyze_audio(samples.data(), n, sample_rate);
    if (result) {
        std::printf("%s\n", result);
        se_free(const_cast<char*>(result));
    }
}

static void video_demo() {
    std::printf("=== Video Analysis Demo ===\n\n");

    const int w = 64, h = 64;
    const int frames = 30;
    const double fps = 10.0;

    // Generate simple motion frames (moving white block)
    std::vector<uint8_t> all_frames(w * h * 3 * frames);

    for (int f = 0; f < frames; ++f) {
        int offset = (f * 4) % (w - 8);  // block moves right
        for (int y = 0; y < h; ++y) {
            for (int x = 0; x < w; ++x) {
                size_t idx = (f * w * h + y * w + x) * 3;
                bool in_block = (x >= offset && x < offset + 8 && y >= 20 && y < 28);
                all_frames[idx + 0] = in_block ? 255 : 30;
                all_frames[idx + 1] = in_block ? 200 : 30;
                all_frames[idx + 2] = in_block ? 100 : 30;
            }
        }
    }

    const char* result = se_analyze_video(all_frames.data(), w, h, frames, fps);
    if (result) {
        std::printf("%s\n", result);
        se_free(const_cast<char*>(result));
    }
}

static void ring_demo() {
    std::printf("=== Ring Buffer Demo ===\n\n");

    se_ring_buffer rb = se_ring_create(1024);

    // Push 100 samples
    std::vector<float> data(100);
    for (int i = 0; i < 100; ++i) data[i] = static_cast<float>(i) * 0.1f;

    int pushed = se_ring_push(rb, data.data(), 100);
    std::printf("Pushed: %d samples\n", pushed);
    std::printf("Buffer size: %zu\n", se_ring_size(rb));

    // Pop 50
    std::vector<float> out(50);
    size_t popped = se_ring_pop(rb, out.data(), 50);
    std::printf("Popped: %zu samples\n", popped);
    std::printf("Buffer size: %zu\n", se_ring_size(rb));

    // Pop rest
    std::vector<float> rest(100);
    popped = se_ring_pop(rb, rest.data(), 100);
    std::printf("Popped remaining: %zu samples\n", popped);
    std::printf("Buffer empty: %d\n", se_ring_empty(rb));

    se_ring_destroy(rb);
    std::printf("\nRing buffer OK.\n");
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        print_usage();
        return 0;
    }

    const char* cmd = argv[1];

    if (std::strcmp(cmd, "version") == 0) {
        const char* v = se_version();
        std::printf("%s\n", v);
        se_free(const_cast<char*>(v));
    } else if (std::strcmp(cmd, "audio-demo") == 0) {
        audio_demo();
    } else if (std::strcmp(cmd, "video-demo") == 0) {
        video_demo();
    } else if (std::strcmp(cmd, "ring-demo") == 0) {
        ring_demo();
    } else {
        std::printf("Unknown command: %s\n", cmd);
        print_usage();
        return 1;
    }

    return 0;
}
