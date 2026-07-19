// ═══════════════════════════════════════════════════════════════════════════════
// api.cpp — Public C API implementation (JSON output for FFI)
// ═══════════════════════════════════════════════════════════════════════════════

#include "signal_engine/api.h"
#include "signal_engine/audio_analyzer.h"
#include "signal_engine/video_analyzer.h"
#include "signal_engine/ring_buffer.h"

#include <nlohmann/json.hpp>
#include <cstdlib>
#include <cstring>
#include <string>
#include <memory>

using json = nlohmann::ordered_json;

// ── Helpers ───────────────────────────────────────────────────────────────────

static char* to_cstring(const std::string& s) {
    char* buf = static_cast<char*>(std::malloc(s.size() + 1));
    if (!buf) return nullptr;
    std::memcpy(buf, s.c_str(), s.size() + 1);
    return buf;
}

static char* ok(const json& j) {
    return to_cstring(j.dump());
}

static char* err(se::ErrorCode code, const std::string& msg = "") {
    json j;
    j["success"] = false;
    j["error"] = se::error_string(code);
    if (!msg.empty()) j["message"] = msg;
    return to_cstring(j.dump());
}

// ── Version ───────────────────────────────────────────────────────────────────

extern "C" {

const char* se_version() {
    return to_cstring(std::string("signal_engine/1.0.0"));
}

// ── Audio Analysis ────────────────────────────────────────────────────────────

const char* se_analyze_audio(
    const float* samples,
    size_t sample_count,
    double sample_rate
) {
    if (!samples || sample_count == 0 || sample_rate <= 0) {
        return err(se::ErrorCode::InvalidInput);
    }

    se::AudioAnalyzer analyzer;
    auto result = analyzer.analyze(
        std::span<const float>(samples, sample_count),
        sample_rate
    );

    if (!result.ok()) {
        return err(result.code, result.error);
    }

    const auto& a = result.value;
    json j;
    j["success"] = true;
    j["sample_rate"] = a.sample_rate;
    j["duration_sec"] = a.duration_sec;
    j["total_energy"] = a.total_energy;
    j["peak_amplitude"] = a.peak_amplitude;
    j["rms_level"] = a.rms_level;
    j["spectral_centroid"] = a.spectral_centroid;
    j["zero_crossing_rate"] = a.zero_crossing_rate;

    // Beats
    json beats_arr = json::array();
    for (const auto& b : a.beats) {
        beats_arr.push_back({
            {"timestamp", b.timestamp},
            {"intensity", b.intensity},
            {"bpm", b.bpm}
        });
    }
    j["beats"] = beats_arr;
    j["beat_count"] = a.beats.size();

    // Spectrum
    json spec_arr = json::array();
    for (const auto& band : a.spectrum) {
        spec_arr.push_back({
            {"center_hz", band.center_hz},
            {"energy", band.energy}
        });
    }
    j["spectrum"] = spec_arr;

    // Envelope (downsampled)
    j["envelope"] = a.envelope;

    return ok(j);
}

const char* se_detect_beats(
    const float* samples,
    size_t sample_count,
    double sample_rate,
    double threshold
) {
    if (!samples || sample_count == 0 || sample_rate <= 0) {
        return err(se::ErrorCode::InvalidInput);
    }

    se::AudioAnalyzer analyzer;
    auto result = analyzer.detect_beats(
        std::span<const float>(samples, sample_count),
        sample_rate,
        threshold
    );

    if (!result.ok()) {
        return err(result.code, result.error);
    }

    json j;
    j["success"] = true;
    json beats = json::array();
    for (const auto& b : result.value) {
        beats.push_back({
            {"timestamp", b.timestamp},
            {"intensity", b.intensity},
            {"bpm", b.bpm}
        });
    }
    j["beats"] = beats;
    j["count"] = result.value.size();

    return ok(j);
}

const char* se_fft_magnitude(
    const float* samples,
    size_t sample_count
) {
    if (!samples || sample_count == 0) {
        return err(se::ErrorCode::InvalidInput);
    }

    auto mag = se::AudioAnalyzer::fft_magnitude(
        std::span<const float>(samples, sample_count)
    );

    json j;
    j["success"] = true;
    j["magnitudes"] = mag;
    j["bins"] = mag.size();

    return ok(j);
}

// ── Video Analysis ────────────────────────────────────────────────────────────

const char* se_analyze_video(
    const uint8_t* frames,
    int width,
    int height,
    int frame_count,
    double fps
) {
    if (!frames || width <= 0 || height <= 0 || frame_count < 2 || fps <= 0) {
        return err(se::ErrorCode::InvalidInput);
    }

    se::VideoAnalyzer analyzer(width, height, fps);
    auto result = analyzer.analyze(
        std::span<const uint8_t>(frames, static_cast<size_t>(frame_count) * width * height * 3),
        frame_count
    );

    if (!result.ok()) {
        return err(result.code, result.error);
    }

    const auto& v = result.value;
    json j;
    j["success"] = true;
    j["fps"] = v.fps;
    j["duration_sec"] = v.duration_sec;
    j["total_frames"] = v.total_frames;
    j["scene_changes"] = v.scene_changes;
    j["avg_motion"] = v.avg_motion;

    json diffs = json::array();
    for (const auto& d : v.diffs) {
        diffs.push_back({
            {"timestamp", d.timestamp},
            {"diff_score", d.diff_score},
            {"is_scene_change", d.is_scene_change}
        });
    }
    j["diffs"] = diffs;

    json motion = json::array();
    for (const auto& m : v.motion) {
        motion.push_back({
            {"timestamp", m.timestamp},
            {"magnitude", m.magnitude},
            {"direction", m.direction}
        });
    }
    j["motion"] = motion;

    return ok(j);
}

const char* se_diff_frames(
    const uint8_t* prev_frame,
    const uint8_t* curr_frame,
    int width,
    int height,
    double threshold
) {
    if (!prev_frame || !curr_frame || width <= 0 || height <= 0) {
        return err(se::ErrorCode::InvalidInput);
    }

    se::VideoAnalyzer analyzer(width, height, 30.0);
    int pixels = width * height;

    auto prev_gray = se::VideoAnalyzer::to_grayscale(
        std::span<const uint8_t>(prev_frame, pixels * 3), pixels);
    auto curr_gray = se::VideoAnalyzer::to_grayscale(
        std::span<const uint8_t>(curr_frame, pixels * 3), pixels);

    double diff = analyzer.diff_frames(prev_gray, curr_gray);

    json j;
    j["success"] = true;
    j["diff_score"] = diff;
    j["is_scene_change"] = diff > threshold;

    return ok(j);
}

const char* se_estimate_motion(
    const uint8_t* prev_frame,
    const uint8_t* curr_frame,
    int width,
    int height,
    double timestamp
) {
    if (!prev_frame || !curr_frame || width <= 0 || height <= 0) {
        return err(se::ErrorCode::InvalidInput);
    }

    se::VideoAnalyzer analyzer(width, height, 30.0);
    int pixels = width * height;

    auto prev_gray = se::VideoAnalyzer::to_grayscale(
        std::span<const uint8_t>(prev_frame, pixels * 3), pixels);
    auto curr_gray = se::VideoAnalyzer::to_grayscale(
        std::span<const uint8_t>(curr_frame, pixels * 3), pixels);

    auto mv = analyzer.estimate_motion(prev_gray, curr_gray, timestamp);

    json j;
    j["success"] = true;
    j["timestamp"] = mv.timestamp;
    j["magnitude"] = mv.magnitude;
    j["direction"] = mv.direction;
    j["center_x"] = mv.center_x;
    j["center_y"] = mv.center_y;

    return ok(j);
}

// ── Combined Analysis ─────────────────────────────────────────────────────────

const char* se_correlate_signals(
    const float* audio_samples,
    size_t audio_count,
    double sample_rate,
    const uint8_t* video_frames,
    int width,
    int height,
    int frame_count,
    double video_fps
) {
    if (!audio_samples || audio_count == 0 || !video_frames ||
        width <= 0 || height <= 0 || frame_count < 2) {
        return err(se::ErrorCode::InvalidInput);
    }

    // Analyze audio
    se::AudioAnalyzer aa;
    auto audio_result = aa.analyze(
        std::span<const float>(audio_samples, audio_count), sample_rate
    );

    // Analyze video
    se::VideoAnalyzer va(width, height, video_fps);
    auto video_result = va.analyze(
        std::span<const uint8_t>(video_frames, static_cast<size_t>(frame_count) * width * height * 3),
        frame_count
    );

    if (!audio_result.ok()) return err(audio_result.code, "audio: " + audio_result.error);
    if (!video_result.ok()) return err(video_result.code, "video: " + video_result.error);

    // Correlate
    auto moments = se::VideoAnalyzer::correlate_signals(audio_result.value, video_result.value);

    json j;
    j["success"] = true;
    j["audio_duration"] = audio_result.value.duration_sec;
    j["video_duration"] = video_result.value.duration_sec;

    json moments_arr = json::array();
    for (const auto& m : moments) {
        moments_arr.push_back({
            {"timestamp", m.timestamp},
            {"score", m.score},
            {"audio_energy", m.audio_energy},
            {"visual_motion", m.visual_motion},
            {"is_beat_drop", m.is_beat_drop},
            {"is_scene_change", m.is_scene_change},
            {"reason", m.reason}
        });
    }
    j["viral_moments"] = moments_arr;
    j["total_moments"] = moments.size();

    json summary;
    summary["best_moment"] = moments.empty() ? 0.0 : moments[0].timestamp;
    summary["best_score"] = moments.empty() ? 0.0 : moments[0].score;
    j["summary"] = summary;

    return ok(j);
}

// ── Ring Buffer ───────────────────────────────────────────────────────────────

struct RingBufferWrapper {
    std::unique_ptr<se::FloatRingBuffer> rb;
};

se_ring_buffer se_ring_create(size_t capacity) {
    auto* wrapper = new(std::nothrow) RingBufferWrapper();
    if (!wrapper) return nullptr;
    wrapper->rb = std::make_unique<se::FloatRingBuffer>();
    return static_cast<se_ring_buffer>(wrapper);
}

void se_ring_destroy(se_ring_buffer rb) {
    delete static_cast<RingBufferWrapper*>(rb);
}

int se_ring_push(se_ring_buffer rb, const float* data, size_t count) {
    if (!rb || !data) return 0;
    auto* wrapper = static_cast<RingBufferWrapper*>(rb);
    return static_cast<int>(wrapper->rb->push_bulk(data, count));
}

size_t se_ring_pop(se_ring_buffer rb, float* out, size_t max_count) {
    if (!rb || !out) return 0;
    auto* wrapper = static_cast<RingBufferWrapper*>(rb);
    return wrapper->rb->pop_bulk(out, max_count);
}

size_t se_ring_size(se_ring_buffer rb) {
    if (!rb) return 0;
    auto* wrapper = static_cast<RingBufferWrapper*>(rb);
    return wrapper->rb->size();
}

int se_ring_empty(se_ring_buffer rb) {
    if (!rb) return 1;
    auto* wrapper = static_cast<RingBufferWrapper*>(rb);
    return wrapper->rb->empty() ? 1 : 0;
}

// ── Utility ───────────────────────────────────────────────────────────────────

void se_free(char* ptr) {
    std::free(ptr);
}

} // extern "C"
