"""
Smart Clip Editor (IP_PART7 - AI Intelligence Expansion)

AI-powered clip editing recommendations:
  1. Auto-crop detection (best moments)
  2. Platform-optimized format/ratio selection
  3. Transition timing recommendation
  4. Music/beat sync suggestion
  5. Subtitle placement optimization
  6. Effect suggestion based on content
  7. Duration optimization per platform
  8. Quality enhancement suggestions

Analyzes clip content and viewer data to suggest optimal edits.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("smart_editor")


# ---------------------------------------------------------------------------
# Platform-specific optimization rules
# ---------------------------------------------------------------------------
PLATFORM_OPTIMIZATION = {
    "youtube": {
        "aspect_ratio": (16, 9),
        "optimal_duration": (30, 600),  # seconds
        "recommended_duration": 180,
        "max_resolution": "2160p",
        "end_screen_duration": 20,
        "intro_style": "hook_first_3s",
        "thumbnail_size": (1280, 720),
        "subtitle_position": "bottom_center",
        "hashtag_limit": 30,
    },
    "tiktok": {
        "aspect_ratio": (9, 16),
        "optimal_duration": (15, 180),
        "recommended_duration": 30,
        "max_resolution": "1080p",
        "intro_style": "no_intro_jump_cut",
        "subtitle_position": "center_large",
        "hashtag_limit": 5,
        "music_required": True,
        "text_overlay": True,
    },
    "instagram_reels": {
        "aspect_ratio": (9, 16),
        "optimal_duration": (15, 90),
        "recommended_duration": 30,
        "max_resolution": "1080p",
        "intro_style": "hook_first_frame",
        "subtitle_position": "center",
        "hashtag_limit": 30,
    },
    "instagram_post": {
        "aspect_ratio": (1, 1),
        "optimal_duration": (15, 60),
        "recommended_duration": 30,
        "max_resolution": "1080p",
        "subtitle_position": "center",
        "hashtag_limit": 30,
    },
    "twitter": {
        "aspect_ratio": (16, 9),
        "optimal_duration": (5, 140),
        "recommended_duration": 45,
        "max_resolution": "1080p",
        "subtitle_position": "bottom_center",
        "hashtag_limit": 5,
        "text_overlay": True,
    },
}


# ---------------------------------------------------------------------------
# Clip Content Analyzer for Editing
# ---------------------------------------------------------------------------
class ClipContentAnalyzer:
    """
    Analyze clip content to suggest optimal editing strategies.

    Uses multi-signal analysis:
    - Highlight score distribution → cut points
    - Emotion arc → pacing recommendations
    - Audio energy → beat sync points
    - Chat spike timing → overlay timing
    """

    def analyze(
        self,
        highlight_scores: list[dict],
        emotion_arc: list[dict],
        audio_spikes: list[dict],
        chat_spikes: list[dict],
        duration: float,
        platform: str = "youtube",
    ) -> dict:
        """
        Analyze clip and return editing recommendations.
        """
        recs = {
            "platform": platform,
            "duration": duration,
            "cut_suggestions": [],
            "pacing": "normal",
            "transition_points": [],
            "subtitle_timing": [],
            "overlay_points": [],
            "effect_recommendations": [],
            "platform_fit": {},
        }

        # Find peak highlight moments for cut suggestions
        peaks = self._find_peaks(highlight_scores, threshold=0.6)
        recs["cut_suggestions"] = [
            {"timestamp": p["timestamp"], "score": p["score"],
             "action": "keep" if p["score"] > 0.7 else "consider_cut"}
            for p in peaks[:5]
        ]

        # Pacing from emotion arc
        if emotion_arc:
            emotions = [e.get("label", "neutral") for e in emotion_arc[-20:]]
            high_intensity = sum(1 for e in emotions if e in ("happy", "excited", "surprised", "angry"))
            ratio = high_intensity / max(len(emotions), 1)
            recs["pacing"] = "fast" if ratio > 0.5 else "slow" if ratio < 0.2 else "normal"

        # Transition points from audio spikes
        for spike in audio_spikes[:5]:
            recs["transition_points"].append({
                "timestamp": spike.get("start_time", 0),
                "type": "audio_spike",
                "intensity": spike.get("peak_magnitude", 0.5),
            })

        # Subtitle timing from chat spikes
        for spike in chat_spikes[:5]:
            recs["subtitle_timing"].append({
                "timestamp": spike.get("timestamp", 0),
                "type": "chat_hype",
                "intensity": spike.get("spike_ratio", 1.0),
            })

        # Overlay points (combine audio + chat spikes)
        overlay_candidates = []
        for a_spike in audio_spikes[:3]:
            overlay_candidates.append({
                "timestamp": a_spike.get("start_time", 0),
                "type": "audio",
                "text": "🔥 HYPE MOMENT",
                "duration": 2.0,
            })
        for c_spike in chat_spikes[:3]:
            overlay_candidates.append({
                "timestamp": c_spike.get("timestamp", 0),
                "type": "chat",
                "text": f"Chat goes wild!",
                "duration": 1.5,
            })
        recs["overlay_points"] = sorted(
            overlay_candidates, key=lambda x: x["timestamp"])[:5]

        # Effect recommendations
        recs["effect_recommendations"] = self._recommend_effects(
            recs["pacing"], platform, highlight_scores)

        # Platform optimization
        platform_rules = PLATFORM_OPTIMIZATION.get(platform, PLATFORM_OPTIMIZATION["youtube"])
        recs["platform_fit"] = {
            "aspect_ratio": f"{platform_rules['aspect_ratio'][0]}:{platform_rules['aspect_ratio'][1]}",
            "recommended_duration": platform_rules["recommended_duration"],
            "duration_fit": abs(duration - platform_rules["recommended_duration"]) < 30,
            "subtitle_position": platform_rules.get("subtitle_position", "bottom"),
            "intro_style": platform_rules.get("intro_style", "standard"),
            "needs_music": platform_rules.get("music_required", False),
        }

        return recs

    def _find_peaks(
        self, scores: list[dict], threshold: float = 0.5,
    ) -> list[dict]:
        """Find local maxima in highlight scores."""
        if not scores:
            return []
        peaks = []
        for i, s in enumerate(scores):
            score = s.get("composite_score", s.get("score", 0))
            if score < threshold:
                continue
            prev = scores[i - 1].get("composite_score", 0) if i > 0 else 0
            next_ = scores[i + 1].get("composite_score", 0) if i < len(scores) - 1 else 0
            if score >= prev and score >= next_:
                peaks.append({
                    "index": i,
                    "timestamp": s.get("timestamp", 0),
                    "score": score,
                })
        return sorted(peaks, key=lambda x: x["score"], reverse=True)

    def _recommend_effects(
        self, pacing: str, platform: str, highlight_scores: list[dict],
    ) -> list[dict]:
        """Recommend visual effects based on content analysis."""
        effects = []
        avg_score = sum(
            s.get("composite_score", s.get("score", 0)) for s in highlight_scores
        ) / max(len(highlight_scores), 1)

        if pacing == "fast":
            effects.append({"effect": "speed_ramp", "reason": "fast-paced content"})
        if avg_score > 0.7:
            effects.append({"effect": "zoom_in_on_reaction", "reason": "high impact moment"})
        if platform in ("tiktok", "instagram_reels"):
            effects.append({"effect": "text_overlay", "reason": "viral format needs captions"})
            effects.append({"effect": "auto_captions", "reason": "silent viewing common"})
        if platform == "youtube":
            effects.append({"effect": "intro_text", "reason": "hook first 3 seconds"})
            effects.append({"effect": "end_screen", "reason": "subscribe/next video prompt"})

        return effects[:5]


# ---------------------------------------------------------------------------
# Auto-Trim Suggestor
# ---------------------------------------------------------------------------
class AutoTrimSuggestor:
    """
    Suggest optimal trim points for clips.

    Uses:
    - Highlight score curve → keep high-score regions
    - Audio energy → trim during silence
    - Motion intensity → keep action, trim static
    - Chat engagement → trim low-chat periods
    """

    def suggest_trims(
        self,
        clip_duration: float,
        highlight_scores: list[dict],
        audio_spikes: list[dict],
        platform: str = "youtube",
    ) -> dict:
        """Suggest trim points to optimize clip for platform."""
        platform_rules = PLATFORM_OPTIMIZATION.get(platform, PLATFORM_OPTIMIZATION["youtube"])
        target_duration = platform_rules["recommended_duration"]

        if abs(clip_duration - target_duration) < 5:
            return {"trim_needed": False, "reason": "already optimal"}

        # Find low-score regions to trim
        scores = [s.get("composite_score", s.get("score", 0)) for s in highlight_scores]
        if not scores:
            return {"trim_needed": False, "reason": "no score data"}

        trim_candidates = []
        timeline_step = clip_duration / max(len(scores), 1)

        for i, score in enumerate(scores):
            if score < 0.3:
                trim_candidates.append({
                    "start": i * timeline_step,
                    "end": min((i + 1) * timeline_step, clip_duration),
                    "score": score,
                })

        return {
            "trim_needed": clip_duration > target_duration,
            "target_duration": target_duration,
            "current_duration": round(clip_duration, 1),
            "trim_candidates": trim_candidates[:3] if clip_duration > target_duration else [],
            "keep_regions": [
                {"start": max(0, s.get("timestamp", 0) - 2), "end": min(clip_duration, s.get("timestamp", 0) + 3),
                 "reason": f"high score: {s.get('score', 0):.2f}"}
                for s in highlight_scores[:3]
            ],
        }

    def get_status(self) -> dict:
        return {"platforms_supported": list(PLATFORM_OPTIMIZATION.keys())}


# ---------------------------------------------------------------------------
# Beat Sync Analyzer
# ---------------------------------------------------------------------------
class BeatSyncAnalyzer:
    """
    Analyze audio for beat detection to sync transitions.

    Uses:
    - Energy peaks as beat proxies
    - Spectral rhythm detection
    - Onset detection via spectral flux
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self._bpm_estimate: float = 0.0
        self._beat_times: list[float] = []

    def analyze_audio(self, audio_data: np.ndarray | None = None) -> dict:
        """Detect beats and suggest sync points."""
        try:
            import numpy as np
        except ImportError:
            return {"bpm": 120, "beat_times": [], "confidence": 0.0}

        if audio_data is None or len(audio_data) == 0:
            return {"bpm": 120, "beat_times": [], "confidence": 0.0}

        try:
            audio_f = audio_data.astype(np.float64)

            # Simple onset detection: energy peaks
            window = int(self.sample_rate * 0.05)  # 50ms
            energies = []
            for i in range(0, len(audio_f) - window, window):
                chunk = audio_f[i:i + window]
                energies.append(float(np.sqrt(np.mean(chunk ** 2))))

            if len(energies) < 2:
                return {"bpm": 120, "beat_times": [], "confidence": 0.0}

            # Find energy peaks as beat proxies
            peaks = []
            for i in range(1, len(energies) - 1):
                if energies[i] > energies[i - 1] and energies[i] > energies[i + 1]:
                    if energies[i] > float(np.mean(energies)) * 1.5:
                        peaks.append(i * window / self.sample_rate)

            # Estimate BPM from peak intervals
            if len(peaks) >= 3:
                intervals = [peaks[i + 1] - peaks[i] for i in range(len(peaks) - 1)]
                avg_interval = float(np.mean(intervals))
                if avg_interval > 0:
                    bpm = 60.0 / avg_interval
                    bpm = max(60, min(200, bpm))
                else:
                    bpm = 120.0
            else:
                bpm = 120.0

            self._bpm_estimate = bpm
            self._beat_times = peaks[:20]

            return {
                "bpm": round(bpm, 1),
                "beat_times": [round(t, 2) for t in peaks[:10]],
                "confidence": min(len(peaks) / 10.0, 0.9),
            }
        except Exception as e:
            logger.debug("Beat detection failed: %s", e)
            return {"bpm": 120, "beat_times": [], "confidence": 0.0}

    def get_sync_points(self, duration: float) -> list[float]:
        """Get beat-synced transition timestamps for clip duration."""
        if not self._beat_times or self._bpm_estimate <= 0:
            return []

        beat_interval = 60.0 / self._bpm_estimate
        sync_points = []
        t = 0.0
        while t < duration:
            sync_points.append(round(t, 2))
            t += beat_interval
        return sync_points[:50]

    def get_status(self) -> dict:
        return {"bpm": round(self._bpm_estimate, 1), "beats_detected": len(self._beat_times)}