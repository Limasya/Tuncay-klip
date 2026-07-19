#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// signal_engine/types.h — Shared data types for the signal processing engine
// ═══════════════════════════════════════════════════════════════════════════════

#include <cstdint>
#include <string>
#include <vector>
#include <chrono>

namespace se {

// ── Time types ────────────────────────────────────────────────────────────────
using Clock     = std::chrono::steady_clock;
using TimePoint = Clock::time_point;
using Duration  = Clock::duration;
using Millis    = std::chrono::milliseconds;

// ── Audio types ───────────────────────────────────────────────────────────────
struct Beat {
    double timestamp;   // seconds from start
    double intensity;   // 0.0 – 1.0
    double bpm;         // estimated BPM at this beat
};

struct FrequencyBand {
    double center_hz;
    double energy;      // 0.0 – 1.0 (normalized)
};

struct AudioAnalysis {
    double sample_rate;
    double duration_sec;
    double total_energy;
    double peak_amplitude;
    double rms_level;
    double spectral_centroid;    // "brightness" of audio
    double zero_crossing_rate;
    std::vector<Beat> beats;
    std::vector<FrequencyBand> spectrum;
    std::vector<double> envelope;  // amplitude envelope (downsampled)
};

// ── Video types ───────────────────────────────────────────────────────────────
struct FrameDiff {
    double timestamp;   // seconds
    double diff_score;  // 0.0 – 1.0 (pixel-level difference)
    bool is_scene_change;
};

struct MotionVector {
    double timestamp;
    double magnitude;   // average motion magnitude
    double direction;   // radians (0 = right, PI/2 = down)
    double center_x;    // normalized 0.0–1.0
    double center_y;    // normalized 0.0–1.0
};

struct VideoAnalysis {
    double fps;
    double duration_sec;
    int total_frames;
    int scene_changes;
    double avg_motion;
    std::vector<FrameDiff> diffs;
    std::vector<MotionVector> motion;
};

// ── Combined signal ───────────────────────────────────────────────────────────
struct ViralMoment {
    double timestamp;       // seconds
    double score;           // 0.0 – 1.0
    double audio_energy;
    double visual_motion;
    bool is_beat_drop;
    bool is_scene_change;
    std::string reason;
};

// ── Error codes ───────────────────────────────────────────────────────────────
enum class ErrorCode : uint32_t {
    Ok                  = 0,
    InvalidInput        = 1,
    FileNotFound        = 2,
    DecodeFailed        = 3,
    AllocFailed         = 4,
    TooLarge            = 5,
    UnsupportedFormat   = 6,
    InternalError       = 99,
};

inline const char* error_string(ErrorCode code) {
    switch (code) {
        case ErrorCode::Ok:                return "ok";
        case ErrorCode::InvalidInput:      return "invalid input";
        case ErrorCode::FileNotFound:      return "file not found";
        case ErrorCode::DecodeFailed:      return "decode failed";
        case ErrorCode::AllocFailed:       return "allocation failed";
        case ErrorCode::TooLarge:          return "input too large";
        case ErrorCode::UnsupportedFormat: return "unsupported format";
        case ErrorCode::InternalError:     return "internal error";
    }
    return "unknown error";
}

// ── Result wrapper ────────────────────────────────────────────────────────────
template<typename T>
struct Result {
    ErrorCode code = ErrorCode::Ok;
    T value{};
    std::string error;

    bool ok() const { return code == ErrorCode::Ok; }
    static Result<T> ok(T v) { return {ErrorCode::Ok, std::move(v), {}}; }
    static Result<T> err(ErrorCode c, std::string msg = "") {
        return {c, T{}, std::move(msg)};
    }
};

} // namespace se
