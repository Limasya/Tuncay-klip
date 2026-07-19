#pragma once
// ═══════════════════════════════════════════════════════════════════════════════
// signal_engine/video_analyzer.h — Frame differencing, motion, scene detection
// ═══════════════════════════════════════════════════════════════════════════════
//
// Features:
//   - Pairwise frame differencing (L1 norm on grayscale)
//   - Adaptive scene change detection (threshold auto-tuning)
//   - Block-based motion estimation (8x8 blocks, SAD matching)
//   - Motion magnitude and direction per frame
//
// Input: raw RGB24 frames as contiguous uint8 arrays (width * height * 3).

#include "types.h"
#include <span>
#include <vector>
#include <cstddef>
#include <cstdint>

namespace se {

class VideoAnalyzer {
public:
    VideoAnalyzer(int width, int height, double fps);

    /// Analyze a sequence of RGB24 frames.
    Result<VideoAnalysis> analyze(std::span<const uint8_t> frames, int frame_count);

    /// Diff two grayscale frames (L1 norm, normalized 0-1).
    double diff_frames(
        std::span<const uint8_t> prev,
        std::span<const uint8_t> curr
    ) const;

    /// Detect scene changes with adaptive threshold.
    std::vector<FrameDiff> detect_scene_changes(
        std::span<const uint8_t> frames,
        int frame_count,
        double threshold = 0.35
    ) const;

    /// Estimate motion vector between two frames using block matching.
    MotionVector estimate_motion(
        std::span<const uint8_t> prev,
        std::span<const uint8_t> curr,
        double timestamp
    ) const;

    /// Detect viral moments (audio energy + visual motion correlation).
    static std::vector<ViralMoment> correlate_signals(
        const AudioAnalysis& audio,
        const VideoAnalysis& video,
        double correlation_window = 2.0
    );

    int width() const { return width_; }
    int height() const { return height_; }
    double fps() const { return fps_; }

    /// Convert RGB24 frame to grayscale (weighted average).
    static std::vector<uint8_t> to_grayscale(
        std::span<const uint8_t> rgb,
        int pixel_count
    );

private:
    int width_;
    int height_;
    double fps_;

    /// Compute SAD (Sum of Absolute Differences) for a block.
    static int block_sad(
        const uint8_t* prev,
        const uint8_t* curr,
        int stride,
        int block_size
    );

    /// Compute adaptive threshold from running statistics.
    static double adaptive_threshold(
        const std::vector<double>& diffs,
        double base_threshold
    );
};

} // namespace se
