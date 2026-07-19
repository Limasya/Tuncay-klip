// ═══════════════════════════════════════════════════════════════════════════════
// video_analyzer.cpp — Frame differencing, motion estimation, scene detection
// ═══════════════════════════════════════════════════════════════════════════════

#include "signal_engine/video_analyzer.h"
#include <algorithm>
#include <cmath>
#include <numeric>

namespace se {

VideoAnalyzer::VideoAnalyzer(int width, int height, double fps)
    : width_(width), height_(height), fps_(fps) {}

// ── Public API ────────────────────────────────────────────────────────────────

Result<VideoAnalysis> VideoAnalyzer::analyze(
    std::span<const uint8_t> frames,
    int frame_count
) {
    const int pixels_per_frame = width_ * height_;
    const size_t frame_bytes = pixels_per_frame * 3;  // RGB24
    const size_t expected = frame_bytes * frame_count;

    if (frames.size() < expected || frame_count < 2) {
        return Result<VideoAnalysis>::err(ErrorCode::InvalidInput, "insufficient frame data");
    }

    VideoAnalysis result{};
    result.fps = fps_;
    result.duration_sec = static_cast<double>(frame_count) / fps_;
    result.total_frames = frame_count;

    // ── Pairwise frame diffs ──────────────────────────────────────────────
    std::vector<double> diff_scores;
    diff_scores.reserve(frame_count - 1);

    for (int i = 1; i < frame_count; ++i) {
        auto prev_gray = to_grayscale(frames.subspan((i - 1) * frame_bytes, frame_bytes), pixels_per_frame);
        auto curr_gray = to_grayscale(frames.subspan(i * frame_bytes, frame_bytes), pixels_per_frame);

        double diff = diff_frames(prev_gray, curr_gray);
        diff_scores.push_back(diff);

        double ts = static_cast<double>(i) / fps_;
        bool is_sc = diff > adaptive_threshold(diff_scores, 0.35);
        result.diffs.push_back({ts, diff, is_sc});

        if (is_sc) ++result.scene_changes;
    }

    // ── Motion estimation (every 3rd frame for performance) ───────────────
    double total_motion = 0.0;
    int motion_count = 0;
    const int motion_step = std::max(1, frame_count / 50);  // sample ~50 frames

    for (int i = motion_step; i < frame_count; i += motion_step) {
        auto prev_gray = to_grayscale(
            frames.subspan((i - motion_step) * frame_bytes, frame_bytes), pixels_per_frame);
        auto curr_gray = to_grayscale(
            frames.subspan(i * frame_bytes, frame_bytes), pixels_per_frame);

        double ts = static_cast<double>(i) / fps_;
        auto mv = estimate_motion(prev_gray, curr_gray, ts);
        result.motion.push_back(mv);

        total_motion += mv.magnitude;
        ++motion_count;
    }

    result.avg_motion = (motion_count > 0) ? total_motion / motion_count : 0.0;

    return Result<VideoAnalysis>::ok(std::move(result));
}

double VideoAnalyzer::diff_frames(
    std::span<const uint8_t> prev,
    std::span<const uint8_t> curr
) const {
    if (prev.size() != curr.size()) return 0.0;

    const size_t n = prev.size();
    double sum_diff = 0.0;

    // L1 norm (Manhattan distance), normalized to 0-1
    for (size_t i = 0; i < n; ++i) {
        sum_diff += std::abs(static_cast<int>(prev[i]) - static_cast<int>(curr[i]));
    }

    return sum_diff / (n * 255.0);
}

std::vector<FrameDiff> VideoAnalyzer::detect_scene_changes(
    std::span<const uint8_t> frames,
    int frame_count,
    double threshold
) const {
    const int pixels_per_frame = width_ * height_;
    const size_t frame_bytes = pixels_per_frame * 3;

    std::vector<double> all_diffs;
    std::vector<FrameDiff> results;

    for (int i = 1; i < frame_count; ++i) {
        auto prev_gray = to_grayscale(frames.subspan((i - 1) * frame_bytes, frame_bytes), pixels_per_frame);
        auto curr_gray = to_grayscale(frames.subspan(i * frame_bytes, frame_bytes), pixels_per_frame);

        double diff = diff_frames(prev_gray, curr_gray);
        all_diffs.push_back(diff);

        double ts = static_cast<double>(i) / fps_;
        bool is_sc = diff > adaptive_threshold(all_diffs, threshold);
        results.push_back({ts, diff, is_sc});
    }

    return results;
}

MotionVector VideoAnalyzer::estimate_motion(
    std::span<const uint8_t> prev,
    std::span<const uint8_t> curr,
    double timestamp
) const {
    if (prev.size() != curr.size()) {
        return {timestamp, 0.0, 0.0, 0.5, 0.5};
    }

    const int block_size = 8;
    const int stride = width_;
    const int blocks_x = width_ / block_size;
    const int blocks_y = height_ / block_size;

    double total_magnitude = 0.0;
    double sum_dx = 0.0;
    double sum_dy = 0.0;
    int valid_blocks = 0;

    const int search_range = 4;  // search ±4 blocks

    for (int by = 0; by < blocks_y; by += 2) {  // sample every other block
        for (int bx = 0; bx < blocks_x; bx += 2) {
            const int x = bx * block_size;
            const int y = by * block_size;

            const uint8_t* ref = prev.data() + y * stride + x;
            const uint8_t* cur = curr.data() + y * stride + x;

            int best_sad = block_sad(ref, cur, stride, block_size);
            int best_dx = 0, best_dy = 0;

            for (int dy = -search_range; dy <= search_range; dy += 2) {
                for (int dx = -search_range; dx <= search_range; dx += 2) {
                    int nx = x + dx * block_size;
                    int ny = y + dy * block_size;
                    if (nx < 0 || ny < 0 || nx + block_size > width_ || ny + block_size > height_) continue;

                    const uint8_t* cand = curr.data() + ny * stride + nx;
                    int sad = block_sad(ref, cand, stride, block_size);
                    if (sad < best_sad) {
                        best_sad = sad;
                        best_dx = dx;
                        best_dy = dy;
                    }
                }
            }

            double mag = std::sqrt(best_dx * best_dx + best_dy * best_dy);
            total_magnitude += mag;
            sum_dx += best_dx;
            sum_dy += best_dy;
            ++valid_blocks;
        }
    }

    double avg_mag = (valid_blocks > 0) ? total_magnitude / valid_blocks : 0.0;
    double avg_dx = (valid_blocks > 0) ? sum_dx / valid_blocks : 0.0;
    double avg_dy = (valid_blocks > 0) ? sum_dy / valid_blocks : 0.0;
    double direction = std::atan2(avg_dy, avg_dx);
    double cx = (valid_blocks > 0) ? 0.5 : 0.5;
    double cy = (valid_blocks > 0) ? 0.5 : 0.5;

    return {timestamp, avg_mag / search_range, direction, cx, cy};
}

std::vector<ViralMoment> VideoAnalyzer::correlate_signals(
    const AudioAnalysis& audio,
    const VideoAnalysis& video,
    double correlation_window
) {
    std::vector<ViralMoment> moments;

    if (audio.beats.empty() && video.diffs.empty()) return moments;

    // ── Build unified timeline ────────────────────────────────────────────
    double max_time = std::max(audio.duration_sec, video.duration_sec);
    double t = 0.0;

    while (t < max_time) {
        double t_end = std::min(t + correlation_window, max_time);

        // Audio energy in window
        double audio_energy = 0.0;
        int beat_count = 0;
        for (const auto& beat : audio.beats) {
            if (beat.timestamp >= t && beat.timestamp < t_end) {
                audio_energy += beat.intensity;
                ++beat_count;
            }
        }
        if (beat_count > 0) audio_energy /= beat_count;

        // Visual motion in window
        double visual_motion = 0.0;
        bool scene_change = false;
        int diff_count = 0;
        for (const auto& diff : video.diffs) {
            if (diff.timestamp >= t && diff.timestamp < t_end) {
                visual_motion += diff.diff_score;
                if (diff.is_scene_change) scene_change = true;
                ++diff_count;
            }
        }
        if (diff_count > 0) visual_motion /= diff_count;

        // Check motion vectors too
        for (const auto& mv : video.motion) {
            if (mv.timestamp >= t && mv.timestamp < t_end) {
                visual_motion = std::max(visual_motion, mv.magnitude);
            }
        }

        // ── Viral score ───────────────────────────────────────────────────
        double score = (audio_energy * 0.5 + visual_motion * 0.5);
        bool is_beat_drop = (beat_count >= 2);

        if (score > 0.25) {
            std::string reason;
            if (is_beat_drop && scene_change) {
                reason = "beat drop + scene change";
                score *= 1.3;
            } else if (is_beat_drop) {
                reason = "beat drop (high energy)";
            } else if (scene_change) {
                reason = "visual scene change";
            } else {
                reason = "correlated signal activity";
            }

            score = std::min(1.0, score);
            moments.push_back({
                t + correlation_window / 2.0,
                score,
                audio_energy,
                visual_motion,
                is_beat_drop,
                scene_change,
                std::move(reason)
            });
        }

        t = t_end;
    }

    // Sort by score descending
    std::sort(moments.begin(), moments.end(),
        [](const ViralMoment& a, const ViralMoment& b) { return a.score > b.score; });

    return moments;
}

// ── Private helpers ───────────────────────────────────────────────────────────

std::vector<uint8_t> VideoAnalyzer::to_grayscale(
    std::span<const uint8_t> rgb,
    int pixel_count
) {
    std::vector<uint8_t> gray(pixel_count);
    for (int i = 0; i < pixel_count; ++i) {
        // ITU-R BT.601
        gray[i] = static_cast<uint8_t>(
            0.299 * rgb[i * 3 + 0] +
            0.587 * rgb[i * 3 + 1] +
            0.114 * rgb[i * 3 + 2]
        );
    }
    return gray;
}

int VideoAnalyzer::block_sad(
    const uint8_t* prev,
    const uint8_t* curr,
    int stride,
    int block_size
) {
    int sad = 0;
    for (int y = 0; y < block_size; ++y) {
        for (int x = 0; x < block_size; ++x) {
            sad += std::abs(static_cast<int>(prev[y * stride + x]) - static_cast<int>(curr[y * stride + x]));
        }
    }
    return sad;
}

double VideoAnalyzer::adaptive_threshold(
    const std::vector<double>& diffs,
    double base_threshold
) {
    if (diffs.size() < 5) return base_threshold;

    // Use recent N frames for running statistics
    const size_t window = std::min(diffs.size(), static_cast<size_t>(30));
    auto start = diffs.end() - window;

    double mean = std::accumulate(start, diffs.end(), 0.0) / window;
    double sq_sum = 0.0;
    for (auto it = start; it != diffs.end(); ++it) {
        sq_sum += (*it - mean) * (*it - mean);
    }
    double stddev = std::sqrt(sq_sum / window);

    // Threshold = max(base, mean + 2*stddev)
    return std::max(base_threshold, mean + 2.0 * stddev);
}

} // namespace se
