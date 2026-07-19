#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// signal_engine/api.h — Public C API for FFI (Python ctypes, etc.)
// ═══════════════════════════════════════════════════════════════════════════════
//
// All functions return a null-terminated JSON string (UTF-8).
// Caller must free() the returned pointer.
//
// Usage from Python:
//   lib = ctypes.CDLL("signal_engine.dll")
//   lib.se_analyze_audio.restype = ctypes.c_char_p
//   result = lib.se_analyze_audio(samples, n, sample_rate)
//   data = json.loads(result)
//   ctypes.free(result)

#include <cstdint>
#include <cstddef>

#ifdef _WIN32
    #ifdef SE_EXPORT
        #define SE_API __declspec(dllexport)
    #else
        #define SE_API __declspec(dllimport)
    #endif
#else
    #define SE_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

// ── Version ───────────────────────────────────────────────────────────────────

SE_API const char* se_version();

// ── Audio Analysis ────────────────────────────────────────────────────────────

/// Analyze audio samples. Returns JSON: {sample_rate, duration_sec, beats, spectrum, ...}
SE_API const char* se_analyze_audio(
    const float* samples,
    size_t sample_count,
    double sample_rate
);

/// Detect beats only (faster than full analysis). Returns JSON: {beats: [...]}
SE_API const char* se_detect_beats(
    const float* samples,
    size_t sample_count,
    double sample_rate,
    double threshold
);

/// Compute FFT magnitude spectrum. Returns JSON: {magnitudes: [...]}
SE_API const char* se_fft_magnitude(
    const float* samples,
    size_t sample_count
);

// ── Video Analysis ────────────────────────────────────────────────────────────

/// Analyze video frames (RGB24). Returns JSON: {fps, scene_changes, motion, ...}
SE_API const char* se_analyze_video(
    const uint8_t* frames,
    int width,
    int height,
    int frame_count,
    double fps
);

/// Diff two frames. Returns JSON: {diff_score, is_scene_change}
SE_API const char* se_diff_frames(
    const uint8_t* prev_frame,
    const uint8_t* curr_frame,
    int width,
    int height,
    double threshold
);

/// Estimate motion vector between two frames. Returns JSON: {magnitude, direction, ...}
SE_API const char* se_estimate_motion(
    const uint8_t* prev_frame,
    const uint8_t* curr_frame,
    int width,
    int height,
    double timestamp
);

// ── Combined Analysis ─────────────────────────────────────────────────────────

/// Correlate audio + video signals to find viral moments.
/// Returns JSON: {viral_moments: [...], summary: {...}}
SE_API const char* se_correlate_signals(
    const float* audio_samples,
    size_t audio_count,
    double sample_rate,
    const uint8_t* video_frames,
    int width,
    int height,
    int frame_count,
    double video_fps
);

// ── Ring Buffer (for streaming) ───────────────────────────────────────────────

typedef void* se_ring_buffer;

SE_API se_ring_buffer se_ring_create(size_t capacity);
SE_API void          se_ring_destroy(se_ring_buffer rb);
SE_API int           se_ring_push(se_ring_buffer rb, const float* data, size_t count);
SE_API size_t        se_ring_pop(se_ring_buffer rb, float* out, size_t max_count);
SE_API size_t        se_ring_size(se_ring_buffer rb);
SE_API int           se_ring_empty(se_ring_buffer rb);

// ── Utility ───────────────────────────────────────────────────────────────────

/// Free a string returned by any se_* function.
SE_API void se_free(char* ptr);

#ifdef __cplusplus
}
#endif
