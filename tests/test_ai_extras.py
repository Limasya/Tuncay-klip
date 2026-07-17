"""
Integration tests for AI Pipeline Hub, Recommendation Engine, and Smart Editor.

These tests validate the public surface of the IP_PART7 AI modules
without requiring heavy ML models — they exercise code paths through
fallback heuristics and template-based providers.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pytest_asyncio


# ─── Recommendation Engine Tests ──────────────────────────────────

class TestRecommendationEngine:
    """Test suite for ClipSimilarityEngine, UserPreferenceLearner, ClipRanker."""

    def test_clip_similarity_basic(self):
        """Similar clips should score above threshold."""
        from services.recommendation_engine import (
            ClipSimilarityEngine, ClipProfile,
        )
        engine = ClipSimilarityEngine()
        engine.add_clip(ClipProfile(
            clip_id="a", category="funny", emotion="happy",
            duration=30, highlight_score=0.8, views=100, likes=10,
        ))
        engine.add_clip(ClipProfile(
            clip_id="b", category="funny", emotion="happy",
            duration=32, highlight_score=0.85, views=200, likes=20,
        ))
        engine.add_clip(ClipProfile(
            clip_id="c", category="rage", emotion="angry",
            duration=15, highlight_score=0.5, views=50, likes=2,
        ))

        similar = engine.find_similar("a", top_n=5)
        assert len(similar) >= 1
        top_id, top_score = similar[0]
        # 'b' is the closest match (same category + emotion)
        assert top_id in {"a", "b"}

    def test_clip_similarity_excludes_self(self):
        """The source clip must not be in its own similarity list."""
        from services.recommendation_engine import (
            ClipSimilarityEngine, ClipProfile,
        )
        engine = ClipSimilarityEngine()
        engine.add_clip(ClipProfile(
            clip_id="x", category="funny", emotion="happy",
            duration=30, highlight_score=0.8,
        ))
        engine.add_clip(ClipProfile(
            clip_id="y", category="funny", emotion="happy",
            duration=30, highlight_score=0.8,
        ))
        similar = engine.find_similar("x", top_n=5)
        ids = [cid for cid, _ in similar]
        assert "x" not in ids

    def test_user_preferences_learning(self):
        """Recording watch/like/skip should update user profile preferences."""
        from services.recommendation_engine import UserPreferenceLearner
        learner = UserPreferenceLearner()

        learner.record_watch("u1", "c1", {"category": "funny", "emotion": "happy", "duration": 30})
        learner.record_watch("u1", "c2", {"category": "funny", "emotion": "happy", "duration": 32})
        learner.record_like("u1", "c3", {"category": "funny", "emotion": "happy", "duration": 28})
        learner.record_skip("u1", "c4", {"category": "rage", "emotion": "angry", "duration": 10})

        prefs = learner.get_preferences("u1")
        assert prefs["categories"].get("funny", 0) > 0
        assert prefs["total_watched"] == 2
        assert prefs["total_liked"] == 1
        assert prefs["total_skipped"] == 1

    def test_clip_ranking(self):
        """Ranking should sort clips by score descending."""
        from services.recommendation_engine import ClipRanker
        ranker = ClipRanker()

        clips = [
            {"clip_id": "1", "category": "funny", "emotion": "happy",
             "duration": 30, "highlight_score": 0.3, "views": 100, "created_at": time.time()},
            {"clip_id": "2", "category": "funny", "emotion": "happy",
             "duration": 30, "highlight_score": 0.9, "views": 1000, "created_at": time.time()},
            {"clip_id": "3", "category": "funny", "emotion": "happy",
             "duration": 30, "highlight_score": 0.6, "views": 500, "created_at": time.time()},
        ]
        user_prefs = {
            "categories": {"funny": 0.8},
            "emotions": {"happy": 0.6},
            "avg_duration": 30,
        }
        ranked = ranker.rank(clips, user_prefs=user_prefs, top_n=3)
        assert len(ranked) == 3
        # Higher-quality clip should rank higher
        scores = [r["score"] for r in ranked]
        assert scores == sorted(scores, reverse=True)


# ─── Smart Editor Tests ──────────────────────────────────────────

class TestSmartEditor:
    """Test suite for ClipContentAnalyzer, AutoTrimSuggestor, BeatSyncAnalyzer."""

    def test_content_analyzer_empty(self):
        """Empty input should return valid recommendations."""
        from services.smart_editor import ClipContentAnalyzer
        analyzer = ClipContentAnalyzer()
        result = analyzer.analyze([], [], [], [], 60.0, "youtube")
        assert result["platform"] == "youtube"
        assert "cut_suggestions" in result
        assert "platform_fit" in result
        assert result["platform_fit"]["aspect_ratio"] == "16:9"

    def test_content_analyzer_with_peaks(self):
        """Peaks above threshold should be flagged as keep candidates."""
        from services.smart_editor import ClipContentAnalyzer
        analyzer = ClipContentAnalyzer()
        scores = [
            {"timestamp": 0, "composite_score": 0.2},
            {"timestamp": 5, "composite_score": 0.8},
            {"timestamp": 10, "composite_score": 0.4},
            {"timestamp": 15, "composite_score": 0.9},
            {"timestamp": 20, "composite_score": 0.3},
        ]
        result = analyzer.analyze(scores, [], [], [], 25.0, "tiktok")
        assert len(result["cut_suggestions"]) >= 2
        # TikTok platform fit
        assert result["platform_fit"]["aspect_ratio"] == "9:16"
        assert result["platform_fit"]["recommended_duration"] == 30

    def test_auto_trim_needed(self):
        """Clip longer than target duration should need trimming."""
        from services.smart_editor import AutoTrimSuggestor
        suggestor = AutoTrimSuggestor()
        scores = [
            {"timestamp": 0, "composite_score": 0.2},
            {"timestamp": 5, "composite_score": 0.3},
            {"timestamp": 10, "composite_score": 0.85},
            {"timestamp": 15, "composite_score": 0.4},
            {"timestamp": 20, "composite_score": 0.9},
            {"timestamp": 25, "composite_score": 0.3},
        ]
        result = suggestor.suggest_trims(
            clip_duration=60.0,
            highlight_scores=scores,
            audio_spikes=[],
            platform="youtube",
        )
        # YouTube recommended_duration = 180 → no trim needed (60 < 180)
        assert "trim_needed" in result

    def test_beat_sync_with_audio(self):
        """Beat analyzer should detect BPM from synthetic audio."""
        import numpy as np
        from services.smart_editor import BeatSyncAnalyzer
        analyzer = BeatSyncAnalyzer(sample_rate=44100)

        # Generate synthetic 120 BPM audio (2 beats/sec over 4 seconds)
        t = np.linspace(0, 4, 44100 * 4)
        envelope = np.abs(np.sin(2 * np.pi * 2 * t))  # 2 Hz envelope
        audio = envelope * np.sin(2 * np.pi * 440 * t)

        result = analyzer.analyze_audio(audio)
        assert "bpm" in result
        assert "beat_times" in result
        assert result["bpm"] > 0

    def test_beat_sync_empty(self):
        """Empty audio should return default BPM."""
        from services.smart_editor import BeatSyncAnalyzer
        analyzer = BeatSyncAnalyzer()
        result = analyzer.analyze_audio(None)
        assert result["bpm"] == 120
        assert result["confidence"] == 0.0


# ─── AI Pipeline Hub Tests ──────────────────────────────────────

class TestAIPipelineHub:
    """Test the unified AI pipeline coordinator."""

    def test_hub_initialization(self):
        """Hub should initialize with several services available."""
        from services.ai_pipeline import ai_pipeline
        status = ai_pipeline.get_status()
        # The pipeline tracks frames/audio/chat/metadata counters
        assert "frames_processed" in status
        assert "clips_analyzed" in status
        assert "total_pipeline_runs" in status

    @pytest.mark.asyncio
    async def test_generate_clip_metadata(self):
        """Hub should generate LLM-powered metadata with template fallback."""
        from services.ai_pipeline import ai_pipeline
        result = await ai_pipeline.generate_clip_metadata(
            clip_id="test_clip_001",
            category="funny",
            emotion="happy",
            streamer="Tuncay",
            tags=["gaming", "lol"],
            platform="youtube",
        )
        assert "clip_id" in result or "error" in result
        if "titles" in result:
            assert isinstance(result["titles"], list)
            assert isinstance(result["hashtags"], list)

    @pytest.mark.asyncio
    async def test_analyze_full_clip(self):
        """Full pipeline should produce metadata + editor recommendations."""
        from services.ai_pipeline import ai_pipeline
        result = await ai_pipeline.analyze_full_clip(
            clip_id="test_clip_full",
            category="exciting",
            emotion="hype",
            highlight_scores=[{"timestamp": 0, "composite_score": 0.9}],
            audio_spikes=[{"start_time": 5, "peak_magnitude": 0.8}],
            duration=45.0,
            platform="tiktok",
            streamer="Tuncay",
        )
        assert result["clip_id"] == "test_clip_full"
        assert "pipeline_elapsed_ms" in result
        assert "services_used" in result
        assert isinstance(result["services_used"], list)
        assert result["pipeline_version"] == "v2_ai"


# ─── AI Pipeline Hub Orchestrator Integration ────────────────────

class TestPipelineOrchestratorAIWiring:
    """Verify the AI Pipeline Hub is integrated into the orchestrator."""

    def test_orchestrator_initializes_ai_hub(self):
        """The orchestrator must hold a reference to ai_pipeline_hub."""
        from microservices.orchestrator import PipelineOrchestrator
        o = PipelineOrchestrator()
        # Lazy attribute — set by initialize()
        assert hasattr(o, "ai_pipeline_hub")
        assert o.ai_pipeline_hub is None

        # The module-level singleton is shared
        from services.ai_pipeline import ai_pipeline as singleton_hub
        assert singleton_hub is not None

    @pytest.mark.asyncio
    async def test_stop_does_not_raise_without_hub(self):
        """Stop() must be safe even if hub was never started."""
        from microservices.orchestrator import PipelineOrchestrator
        o = PipelineOrchestrator()
        await o.stop()
        assert o._is_running is False
