"""
FAZ-2/3/4 Services Testleri
────────────────────────────
signal_fusion, segment_classifier, clip_optimizer, multi_platform_publisher,
thumbnail_ab_test, multilingual_subtitles, quality_dashboard, cost_tracker, user_feedback
"""
import pytest
import time
import math


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-2.1: SIGNAL FUSION — SPAM DETECTOR
# ═══════════════════════════════════════════════════════════════════════════

class TestSpamDetector:
    def test_normal_message_not_spam(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("Harika oyun!", "viewer1")
        assert not r.is_spam
        assert r.cleaned_message == "Harika oyun!"

    def test_link_is_spam(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("Check http://spam.com now", "spammer")
        assert r.is_spam
        assert r.spam_type == "link"

    def test_caps_flood_is_spam(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("BUY NOW SUBSCRIBE PLEASE FOLLOW", "bot")
        assert r.is_spam

    def test_repetition_is_spam(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("aaaaaaaaaaaa", "user1")
        assert r.is_spam
        assert r.spam_type == "repetition"

    def test_emoji_only_is_spam(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("🔥🔥🔥", "emoji_user")
        assert r.is_spam
        assert r.is_emoji_only

    def test_known_bot_is_spam(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("regular message", "nightbot")
        assert r.is_spam
        assert r.spam_type == "bot"

    def test_clean_reduces_repetition(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        r = sd.detect("Nice game, soooo good", "viewer")
        assert not r.is_spam
        assert "sooo" in r.cleaned_message
        assert "soooo" not in r.cleaned_message

    def test_filter_messages(self):
        from services.signal_fusion import SpamDetector
        sd = SpamDetector()
        msgs = [
            {"message": "Hello!", "username": "a"},
            {"message": "BUY NOW http://spam.com", "username": "b"},
            {"message": "Great play!", "username": "c"},
        ]
        filtered = sd.filter_messages(msgs)
        assert len(filtered) == 2  # spam removed


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-2.1: SIGNAL FUSION — ABLATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════

class TestAblationEngine:
    def _make_engine(self):
        from microservices.event_detector.service import ScoringEngine
        return ScoringEngine(weights={
            "audio_spike": 0.30,
            "chat_velocity": 0.30,
            "emotion_intensity": 0.20,
            "pose_gesture": 0.20,
        })

    def test_ablation_returns_results(self):
        from services.signal_fusion import AblationEngine
        engine = self._make_engine()
        ablation = AblationEngine(engine)
        import asyncio
        results = asyncio.get_event_loop().run_until_complete(ablation.run_ablation())
        assert len(results) == 4

    def test_ablation_result_has_impact(self):
        from services.signal_fusion import AblationEngine
        engine = self._make_engine()
        for sig in engine.WEIGHTS:
            engine.update_signal(sig, 0.5)
        ablation = AblationEngine(engine)
        import asyncio
        results = asyncio.get_event_loop().run_until_complete(ablation.run_ablation())
        for r in results:
            assert hasattr(r, "impact")
            assert hasattr(r, "impact_pct")

    def test_recommendations_generated(self):
        from services.signal_fusion import AblationEngine
        engine = self._make_engine()
        ablation = AblationEngine(engine)
        import asyncio
        results = asyncio.get_event_loop().run_until_complete(ablation.run_ablation())
        recs = ablation.get_recommendations(results)
        assert isinstance(recs, list)


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-2.1: SIGNAL CORRELATION
# ═══════════════════════════════════════════════════════════════════════════

class TestSignalCorrelation:
    def test_empty_history_no_correlation(self):
        from microservices.event_detector.service import ScoringEngine
        from services.signal_fusion import SignalCorrelationAnalyzer
        engine = ScoringEngine()
        analyzer = SignalCorrelationAnalyzer(engine)
        matrix = analyzer.compute_correlation_matrix()
        assert isinstance(matrix, dict)

    def test_correlated_signals_detected(self):
        from microservices.event_detector.service import ScoringEngine
        from services.signal_fusion import SignalCorrelationAnalyzer
        engine = ScoringEngine(weights={"a": 0.5, "b": 0.5})
        # Inject perfectly correlated signals
        now = time.time()
        for i in range(20):
            engine.update_signal("a", 0.5 + 0.3 * math.sin(i))
            engine.update_signal("b", 0.5 + 0.3 * math.sin(i))
        analyzer = SignalCorrelationAnalyzer(engine)
        matrix = analyzer.compute_correlation_matrix()
        assert matrix["a"]["b"] > 0.9


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-2.2: SEGMENT CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════

class TestSegmentClassifier:
    def test_initial_state(self):
        from services.segment_classifier import SegmentClassifier
        sc = SegmentClassifier()
        stats = sc.get_stats()
        assert stats["total_segments"] == 0

    def test_segments_created_on_transitions(self):
        from services.segment_classifier import SegmentClassifier
        sc = SegmentClassifier()
        # Feed enough signals to create transitions
        for i in range(50):
            sc.update_signal("composite_score", 0.1 + (i % 5) * 0.01)
        # Force finalize
        finalized = sc.finalize()
        assert isinstance(finalized, list)

    def test_get_clip_candidates(self):
        from services.segment_classifier import SegmentClassifier
        sc = SegmentClassifier()
        candidates = sc.get_clip_candidates()
        assert isinstance(candidates, list)

    def test_segment_types(self):
        from services.segment_classifier import SegmentType
        types = [st.value for st in SegmentType]
        assert "hype_moment" in types
        assert "quiet_period" in types
        assert "reaction_moment" in types


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-2.3: CLIP OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════

class TestClipOptimizer:
    def test_all_platforms_available(self):
        from services.clip_optimizer import clip_optimizer
        platforms = clip_optimizer.get_all_platforms()
        assert len(platforms) >= 6
        names = [p["name"] for p in platforms]
        assert "TikTok" in names

    def test_tiktok_optimize_within_limit(self):
        from services.clip_optimizer import clip_optimizer
        result = clip_optimizer.optimize_for_platform(120.0, "tiktok")
        assert result.duration <= 60.0  # TikTok max
        assert result.platform == "tiktok"

    def test_tiktok_ideal_range(self):
        from services.clip_optimizer import clip_optimizer
        result = clip_optimizer.optimize_for_platform(45.0, "tiktok")
        assert result.fit_score > 0.8  # 45s > ideal 30s but close

    def test_short_video_stays_short(self):
        from services.clip_optimizer import clip_optimizer
        result = clip_optimizer.optimize_for_platform(10.0, "youtube")
        assert result.duration == 10.0  # Can't make it longer

    def test_unknown_platform_fallback(self):
        from services.clip_optimizer import clip_optimizer
        result = clip_optimizer.optimize_for_platform(30.0, "unknown_platform")
        assert result.warnings  # Should have warnings

    def test_needs_resize(self):
        from services.clip_optimizer import clip_optimizer
        result = clip_optimizer.optimize_for_platform(30.0, "tiktok", source_width=1920, source_height=1080)
        assert result.needs_resize  # 16:9 → 9:16

    def test_no_resize_needed(self):
        from services.clip_optimizer import clip_optimizer
        result = clip_optimizer.optimize_for_platform(30.0, "kick", source_width=1920, source_height=1080)
        assert not result.needs_resize

    def test_optimize_all_platforms(self):
        from services.clip_optimizer import clip_optimizer
        results = clip_optimizer.optimize_for_all_platforms(30.0)
        assert "tiktok" in results
        assert "youtube" in results


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-3.1: MULTI-PLATFORM PUBLISHER
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiPlatformPublisher:
    def test_create_job(self):
        from services.multi_platform_publisher import MultiPlatformPublisher
        pub = MultiPlatformPublisher()
        job = pub.create_job(
            clip_id="test123",
            platform="tiktok",
            video_path="/tmp/test.mp4",
            title="Test Clip",
        )
        assert job.platform.value == "tiktok"
        assert job.title == "Test Clip"
        assert len(job.job_id) > 0

    def test_create_multi_platform_jobs(self):
        from services.multi_platform_publisher import MultiPlatformPublisher
        pub = MultiPlatformPublisher()
        jobs = pub.create_multi_platform_jobs(
            clip_id="test123",
            platforms=["tiktok", "youtube", "instagram_reels"],
            video_path="/tmp/test.mp4",
            title="Test",
        )
        assert len(jobs) == 3

    def test_stats(self):
        from services.multi_platform_publisher import MultiPlatformPublisher
        pub = MultiPlatformPublisher()
        stats = pub.get_stats()
        assert "total_jobs" in stats
        assert stats["total_jobs"] == 0

    def test_get_optimal_time(self):
        from services.multi_platform_publisher import MultiPlatformPublisher
        pub = MultiPlatformPublisher()
        t = pub.get_optimal_posting_time("tiktok")
        assert t is not None

    def test_title_truncation(self):
        from services.multi_platform_publisher import MultiPlatformPublisher
        pub = MultiPlatformPublisher()
        job = pub.create_job(
            clip_id="test",
            platform="youtube_shorts",
            video_path="/tmp/test.mp4",
            title="A" * 200,
        )
        assert len(job.title) <= 100  # youtube_shorts max_title_length

    def test_hashtags_truncation(self):
        from services.multi_platform_publisher import MultiPlatformPublisher
        pub = MultiPlatformPublisher()
        job = pub.create_job(
            clip_id="test",
            platform="tiktok",
            video_path="/tmp/test.mp4",
            hashtags=[f"tag{i}" for i in range(20)],
        )
        assert len(job.hashtags) <= 5  # tiktok max_hashtags


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-3.2: THUMBNAIL A/B TEST
# ═══════════════════════════════════════════════════════════════════════════

class TestThumbnailABTest:
    def test_create_test(self):
        from services.thumbnail_ab_test import ThumbnailABTest
        ab = ThumbnailABTest()
        import asyncio
        test = asyncio.get_event_loop().run_until_complete(
            ab.create_test("clip1", "/tmp/video.mp4", "tiktok", num_variants=3)
        )
        assert len(test.variants) == 3
        assert test.variants[0].variant_label == "A"

    def test_record_impressions(self):
        from services.thumbnail_ab_test import ThumbnailABTest
        ab = ThumbnailABTest()
        import asyncio
        test = asyncio.get_event_loop().run_until_complete(
            ab.create_test("clip1", "/tmp/video.mp4", "tiktok", num_variants=2)
        )
        asyncio.get_event_loop().run_until_complete(
            ab.record_impression(test.test_id, test.variants[0].variant_id)
        )
        updated = ab.get_test(test.test_id)
        assert updated.variants[0].impressions == 1

    def test_stats(self):
        from services.thumbnail_ab_test import ThumbnailABTest
        ab = ThumbnailABTest()
        stats = ab.get_stats()
        assert stats["total_tests"] == 0

    def test_active_tests(self):
        from services.thumbnail_ab_test import ThumbnailABTest
        ab = ThumbnailABTest()
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            ab.create_test("clip1", "/tmp/v.mp4", "tiktok")
        )
        active = ab.get_active_tests()
        assert len(active) == 1


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-3.3: MULTILINGUAL SUBTITLES
# ═══════════════════════════════════════════════════════════════════════════

class TestMultilingualSubtitles:
    def test_supported_languages(self):
        from services.multilingual_subtitles import SUPPORTED_LANGUAGES
        assert "tr" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES
        assert "de" in SUPPORTED_LANGUAGES

    def test_words_to_entries(self):
        from services.multilingual_subtitles import MultilingualSubtitleManager
        mgr = MultilingualSubtitleManager()
        words = [
            {"word": "Merhaba", "start": 0.0, "end": 0.5},
            {"word": "dünya", "start": 0.6, "end": 1.0},
        ]
        entries = mgr._words_to_entries(words, "tr")
        assert len(entries) == 2
        assert entries[0].text == "Merhaba"

    def test_merge_into_sentences(self):
        from services.multilingual_subtitles import MultilingualSubtitleManager
        mgr = MultilingualSubtitleManager()
        from services.multilingual_subtitles import SubtitleEntry
        entries = [
            SubtitleEntry(index=1, start_time=0, end_time=0.5, text="Merhaba", language="tr"),
            SubtitleEntry(index=2, start_time=0.6, end_time=1.0, text="dünya", language="tr"),
            SubtitleEntry(index=3, start_time=1.1, end_time=1.5, text="Nasılsın", language="tr"),
        ]
        merged = mgr._merge_into_sentences(entries, max_chars=30)
        assert len(merged) >= 1

    def test_srt_format(self):
        from services.multilingual_subtitles import MultilingualSubtitleManager, SubtitleTrack, SubtitleEntry
        mgr = MultilingualSubtitleManager()
        mgr._tracks["tr"] = SubtitleTrack(
            language="tr",
            entries=[
                SubtitleEntry(index=1, start_time=0, end_time=2.5, text="Test", language="tr"),
            ],
        )
        srt = mgr.export_srt("tr")
        assert srt is not None
        assert "00:00:00" in srt

    def test_ass_format(self):
        from services.multilingual_subtitles import MultilingualSubtitleManager, SubtitleTrack, SubtitleEntry
        mgr = MultilingualSubtitleManager()
        mgr._tracks["tr"] = SubtitleTrack(
            language="tr",
            entries=[
                SubtitleEntry(index=1, start_time=0, end_time=2.5, text="Test", language="tr"),
            ],
        )
        ass = mgr.export_ass("tr")
        assert ass is not None
        assert "Dialogue:" in ass

    def test_stats(self):
        from services.multilingual_subtitles import MultilingualSubtitleManager
        mgr = MultilingualSubtitleManager()
        stats = mgr.get_stats()
        assert stats["total_languages"] == 0


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-4.1: QUALITY DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

class TestQualityDashboard:
    def test_empty_status(self):
        from services.quality_dashboard import QualityDashboard
        qd = QualityDashboard()
        status = qd.get_current_status()
        assert "message" in status

    def test_record_snapshot(self):
        from services.quality_dashboard import QualityDashboard, QualitySnapshot
        qd = QualityDashboard()
        snap = QualitySnapshot(
            clip_id="clip1",
            overall_score=8.5,
            dimension_scores={"opening": 0.9, "subtitle": 0.8},
            platform="tiktok",
        )
        qd.record_snapshot(snap)
        status = qd.get_current_status()
        assert status["total_snapshots"] == 1
        assert status["overall_avg"] == 8.5

    def test_multiple_snapshots(self):
        from services.quality_dashboard import QualityDashboard, QualitySnapshot
        qd = QualityDashboard()
        for i in range(5):
            qd.record_snapshot(QualitySnapshot(
                clip_id=f"clip{i}",
                overall_score=7.0 + i * 0.5,
            ))
        status = qd.get_current_status()
        assert status["total_snapshots"] == 5

    def test_daily_trend(self):
        from services.quality_dashboard import QualityDashboard, QualitySnapshot
        qd = QualityDashboard()
        qd.record_snapshot(QualitySnapshot(clip_id="c1", overall_score=8.0))
        trends = qd.get_daily_trend(days=7)
        assert isinstance(trends, list)

    def test_stats(self):
        from services.quality_dashboard import QualityDashboard
        qd = QualityDashboard()
        stats = qd.get_stats()
        assert "total_snapshots" in stats

    def test_weekly_report_empty(self):
        from services.quality_dashboard import QualityDashboard
        qd = QualityDashboard()
        import asyncio
        report = asyncio.get_event_loop().run_until_complete(qd.generate_weekly_report())
        assert report.total_clips == 0


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-4.2: COST TRACKER
# ═══════════════════════════════════════════════════════════════════════════

class TestCostTracker:
    def test_record_llm_call(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        rec = ct.record_llm_call("openai", 1000, 500, clip_id="test")
        assert rec.amount_usd > 0
        assert rec.tokens_input == 1000
        assert rec.category == "llm"

    def test_record_ffmpeg(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        rec = ct.record_ffmpeg_process("render", 30.0, clip_id="test")
        assert rec.processing_seconds == 30.0
        assert rec.category == "ffmpeg"

    def test_record_storage(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        rec = ct.record_storage(1024 * 1024 * 100, "video", "test")  # 100MB
        assert rec.amount_usd > 0
        assert rec.category == "storage"

    def test_summary(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record_llm_call("openai", 1000, 500, clip_id="c1")
        ct.record_ffmpeg_process("render", 10.0, clip_id="c1")
        summary = ct.get_summary()
        assert summary.total_usd > 0
        assert summary.clip_count == 1

    def test_daily_costs(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record_llm_call("openai", 1000, 500)
        daily = ct.get_daily_costs(days=7)
        assert len(daily) >= 1

    def test_estimate_clip_cost(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        ct.record_llm_call("openai", 1000, 500, clip_id="c1")
        ct.record_ffmpeg_process("render", 5.0, clip_id="c1")
        costs = ct.estimate_clip_cost("c1")
        assert "llm" in costs
        assert "ffmpeg" in costs

    def test_stats(self):
        from services.cost_tracker import CostTracker
        ct = CostTracker()
        stats = ct.get_stats()
        assert "total_records" in stats

    def test_pricing_correct(self):
        from services.cost_tracker import LLM_PRICING
        assert LLM_PRICING["openai"]["input"] == 0.15
        assert LLM_PRICING["ollama"]["input"] == 0.0


# ═══════════════════════════════════════════════════════════════════════════
#  FAZ-4.3: USER FEEDBACK
# ═══════════════════════════════════════════════════════════════════════════

class TestUserFeedback:
    def test_record_thumbs(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        entry = uf.record_thumbs("clip1", is_up=True)
        assert entry.feedback_type == "thumbs_up"
        assert entry.clip_id == "clip1"

    def test_record_thumbs_down(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        entry = uf.record_thumbs("clip1", is_up=False)
        assert entry.feedback_type == "thumbs_down"

    def test_record_rating(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        entry = uf.record_rating("clip1", 4.5)
        assert entry.rating == 4.5

    def test_rating_clamped(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        entry = uf.record_rating("clip1", 10.0)  # over max
        assert entry.rating == 5.0  # clamped

    def test_record_dimension_feedback(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        entry = uf.record_dimension_feedback("clip1", "opening", 0.7, user_agrees=False)
        assert entry.dimension == "opening"
        assert not entry.metadata["user_agrees"]

    def test_clip_feedback_aggregation(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        uf.record_thumbs("clip1", is_up=True)
        uf.record_thumbs("clip1", is_up=True)
        uf.record_thumbs("clip1", is_up=False)
        agg = uf.get_clip_feedback("clip1")
        assert agg.total_feedback == 3
        assert agg.thumbs_up == 2
        assert agg.thumbs_down == 1
        assert agg.sentiment == "positive"

    def test_overall_sentiment(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        uf.record_thumbs("c1", True)
        uf.record_thumbs("c2", True)
        uf.record_thumbs("c3", False)
        sentiment = uf.get_overall_sentiment()
        assert sentiment["total_feedback"] == 3
        assert sentiment["thumbs_up"] == 2

    def test_calibration(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        # Simulate disagreement with opening dimension
        for i in range(6):
            uf.record_dimension_feedback(
                "clip" + str(i), "opening", 0.9, user_agrees=False
            )
        import asyncio
        adjustments = asyncio.get_event_loop().run_until_complete(
            uf.compute_calibration_adjustments()
        )
        assert len(adjustments) >= 1
        assert adjustments[0].dimension == "opening"

    def test_stats(self):
        from services.user_feedback import UserFeedback
        uf = UserFeedback()
        stats = uf.get_stats()
        assert stats["total_feedback"] == 0


# ═══════════════════════════════════════════════════════════════════════════
#  API ROUTER SMOKE TEST
# ═══════════════════════════════════════════════════════════════════════════

class TestAdvancedRouter:
    def test_router_exists(self):
        from api.routers.advanced import router
        assert len(router.routes) == 36

    def test_advanced_domain_builds(self):
        from api.domains import build_advanced_domain
        d = build_advanced_domain()
        assert d.name == "advanced"
        assert d.endpoint_count == 36

    def test_all_domains_includes_advanced(self):
        from api.domains import register_all_domains, DomainRegistry
        reg = DomainRegistry()
        register_all_domains(reg)
        assert reg.get("advanced") is not None


# ═══════════════════════════════════════════════════════════════════════════
#  AUTO-BOOT INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════

class TestAutoBootIntegration:
    def test_boot_report_has_new_keys(self):
        from services.auto_boot import auto_boot
        import asyncio
        report = asyncio.get_event_loop().run_until_complete(auto_boot())
        assert "publisher" in report
        assert "ab_test" in report
        assert "quality_dashboard" in report
        assert "cost_tracker" in report
        assert "user_feedback" in report

    def test_shutdown_completes(self):
        from services.auto_boot import auto_shutdown
        import asyncio
        # Should not raise
        asyncio.get_event_loop().run_until_complete(auto_shutdown())
