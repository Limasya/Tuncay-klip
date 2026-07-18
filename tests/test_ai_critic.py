"""
AI Critic (Closed-Loop QC) v2 Testleri
───────────────────────────────────────
services/ai_critic.py (5 boyut) + services/critic_analytics.py için birim testler.
Ağır bağımlılıklar (ffprobe, cv2, LLM API) mock'lanır.
"""
import pytest

from services.ai_critic import (
    AICritic,
    CriticIssue,
    CritiqueReport,
    SUBTITLE_MIN_RATIO,
    ZOOM_LATE_THRESHOLD_S,
    DIMENSION_WEIGHTS,
)


# ═══════════════════════════════════════════════════════════════════════════
#  SUBTITLE ÖLÇÜM
# ═══════════════════════════════════════════════════════════════════════════


class TestSubtitleMeasure:
    def test_small_font_low_score(self):
        critic = AICritic()
        score, ratio = critic._measure_subtitle(fontsize=24, height=1920)
        assert ratio == pytest.approx(24 / 1920)
        assert score < 0.6

    def test_large_font_high_score(self):
        critic = AICritic()
        score, ratio = critic._measure_subtitle(fontsize=80, height=1920)
        assert score >= 0.6

    def test_missing_info_is_neutral(self):
        critic = AICritic()
        score, ratio = critic._measure_subtitle(fontsize=None, height=1920)
        assert score == 1.0
        assert ratio == 0.0

    def test_optimal_ratio(self):
        critic = AICritic()
        # SUBTITLE_MIN_RATIO * 2 = 0.06 → skor ~1.0
        fontsize = int(1920 * SUBTITLE_MIN_RATIO * 2)
        score, ratio = critic._measure_subtitle(fontsize=fontsize, height=1920)
        assert score >= 0.9


# ═══════════════════════════════════════════════════════════════════════════
#  ZOOM ÖLÇÜM
# ═══════════════════════════════════════════════════════════════════════════


class TestZoomTiming:
    @pytest.mark.asyncio
    async def test_early_peak_perfect(self, monkeypatch):
        critic = AICritic()
        monkeypatch.setattr(critic, "_first_peak_time", _fake_peak(1.0))
        score = await critic._measure_zoom_timing("x.mp4")
        assert score == 1.0

    @pytest.mark.asyncio
    async def test_late_peak_penalized(self, monkeypatch):
        critic = AICritic()
        monkeypatch.setattr(critic, "_first_peak_time", _fake_peak(9.0))
        score = await critic._measure_zoom_timing("x.mp4")
        assert score < 1.0

    @pytest.mark.asyncio
    async def test_no_peak_neutral(self, monkeypatch):
        critic = AICritic()
        monkeypatch.setattr(critic, "_first_peak_time", _fake_peak(-1.0))
        score = await critic._measure_zoom_timing("x.mp4")
        assert score == 0.6


# ═══════════════════════════════════════════════════════════════════════════
#  CUT PRECISION ÖLÇÜM
# ═══════════════════════════════════════════════════════════════════════════


class TestCutPrecision:
    @pytest.mark.asyncio
    async def test_clean_cut_high_score(self, monkeypatch, tmp_path):
        critic = AICritic()
        # Video süresi kelimelerle uyumlu: son kelime 4.5'te bitiyor, video 5.0
        monkeypatch.setattr(critic, "_probe_duration", _fake_val(5.0))
        transcript = {
            "words": [
                {"word": "merhaba", "start": "0.1", "end": "0.5"},
                {"word": "dunya", "start": "0.6", "end": "1.0"},
                {"word": "nasil", "start": "1.1", "end": "1.5"},
                {"word": "gidiyor", "start": "4.0", "end": "4.5"},
            ]
        }
        score = await critic._measure_cut_precision("x.mp4", transcript)
        assert score >= 0.9

    @pytest.mark.asyncio
    async def test_leading_silence_penalized(self, monkeypatch):
        critic = AICritic()
        monkeypatch.setattr(critic, "_probe_duration", _fake_val(10.0))
        transcript = {
            "words": [
                {"word": "merhaba", "start": "2.0", "end": "2.5"},  # 2sn sessizlik
                {"word": "dunya", "start": "2.6", "end": "3.0"},
            ]
        }
        score = await critic._measure_cut_precision("x.mp4", transcript)
        assert score < 0.8

    @pytest.mark.asyncio
    async def test_trailing_silence_penalized(self, monkeypatch):
        critic = AICritic()
        monkeypatch.setattr(critic, "_probe_duration", _fake_val(10.0))
        transcript = {
            "words": [
                {"word": "merhaba", "start": "0.0", "end": "0.5"},
                {"word": "dunya", "start": "0.6", "end": "1.0"},
                # Son kelime 1.0'da bitiyor, video 10.0'a kadar → 9sn sessizlik
            ]
        }
        score = await critic._measure_cut_precision("x.mp4", transcript)
        assert score < 0.7

    @pytest.mark.asyncio
    async def test_no_transcript_neutral(self):
        critic = AICritic()
        score = await critic._measure_cut_precision("x.mp4", None)
        assert score == 0.8

    @pytest.mark.asyncio
    async def test_cut_info(self, monkeypatch):
        critic = AICritic()
        monkeypatch.setattr(critic, "_probe_duration", _fake_val(10.0))
        transcript = {
            "words": [
                {"word": "merhaba", "start": "0.5", "end": "1.0"},
                {"word": "dunya", "start": "1.5", "end": "2.0"},
            ]
        }
        info = await critic._get_cut_info("x.mp4", transcript)
        assert info["leading_silence_s"] == 0.5
        assert info["trailing_silence_s"] == 8.0
        assert info["word_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
#  ISSUE BUILDING
# ═══════════════════════════════════════════════════════════════════════════


class TestBuildIssues:
    def test_boring_opening_flagged(self):
        critic = AICritic()
        scores = {"opening": 0.2, "subtitle": 1.0, "thumbnail": 1.0, "zoom": 1.0, "cut": 1.0}
        issues = critic._build_issues(scores, subtitle_ratio=0.05, zoom_peak_s=1.0, cut_info={})
        dims = {i.dimension for i in issues}
        assert "opening" in dims

    def test_small_subtitle_flagged(self):
        critic = AICritic()
        scores = {"opening": 1.0, "subtitle": 0.3, "thumbnail": 1.0, "zoom": 1.0, "cut": 1.0}
        issues = critic._build_issues(scores, subtitle_ratio=0.012, zoom_peak_s=1.0, cut_info={})
        assert any(i.dimension == "subtitle" for i in issues)

    def test_late_zoom_flagged(self):
        critic = AICritic()
        scores = {"opening": 1.0, "subtitle": 1.0, "thumbnail": 1.0, "zoom": 0.4, "cut": 1.0}
        issues = critic._build_issues(
            scores, subtitle_ratio=0.05,
            zoom_peak_s=ZOOM_LATE_THRESHOLD_S + 2, cut_info={},
        )
        assert any(i.dimension == "zoom" for i in issues)

    def test_bad_cut_flagged(self):
        critic = AICritic()
        scores = {"opening": 1.0, "subtitle": 1.0, "thumbnail": 1.0, "zoom": 1.0, "cut": 0.3}
        cut_info = {"leading_silence_s": 2.0, "trailing_silence_s": 3.0}
        issues = critic._build_issues(
            scores, subtitle_ratio=0.05, zoom_peak_s=1.0, cut_info=cut_info,
        )
        assert any(i.dimension == "cut" for i in issues)

    def test_clean_video_no_issues(self):
        critic = AICritic()
        scores = {"opening": 0.9, "subtitle": 0.9, "thumbnail": 0.9, "zoom": 0.9, "cut": 0.9}
        issues = critic._build_issues(
            scores, subtitle_ratio=0.05, zoom_peak_s=1.0,
            cut_info={"leading_silence_s": 0.1, "trailing_silence_s": 0.5},
        )
        assert issues == []


# ═══════════════════════════════════════════════════════════════════════════
#  CRITIQUE REPORT
# ═══════════════════════════════════════════════════════════════════════════


class TestReport:
    def test_summary_contains_score_and_reasons(self):
        report = CritiqueReport(
            score=8.7, passed=True, verdict="İyi",
            issues=[CriticIssue("subtitle", "warning", "Altyazı küçük")],
            dimension_scores={"opening": 0.9, "subtitle": 0.4, "zoom": 0.8, "thumbnail": 0.9, "cut": 0.85},
        )
        s = report.summary()
        assert "8.7" in s
        assert "Altyazı küçük" in s
        assert "Boyutlar:" in s

    def test_to_dict_shape(self):
        report = CritiqueReport(
            score=7.0, passed=False, verdict="Orta",
            issues=[CriticIssue("opening", "warning", "İlk 3 saniye sıkıcı",
                                metric=0.3, suggested_fix="hook")],
            metrics={"opening": 0.3},
            dimension_scores={"opening": 0.3, "subtitle": 0.9, "zoom": 0.8, "thumbnail": 0.7, "cut": 0.8},
            applied_fixes=["hook"],
        )
        d = report.to_dict()
        assert d["score"] == 7.0
        assert d["passed"] is False
        assert "opening" in d["dimension_scores"]
        assert "cut" in d["dimension_scores"]
        assert d["applied_fixes"] == ["hook"]

    def test_dimension_scores_in_report(self):
        report = CritiqueReport(
            score=8.0, passed=True, verdict="İyi",
            dimension_scores={"opening": 0.9, "subtitle": 0.8, "zoom": 0.7, "thumbnail": 0.85, "cut": 0.88},
        )
        assert len(report.dimension_scores) == 5
        assert report.dimension_scores["cut"] == 0.88


# ═══════════════════════════════════════════════════════════════════════════
#  DIMENSION WEIGHTS
# ═══════════════════════════════════════════════════════════════════════════


class TestDimensionWeights:
    def test_weights_sum_to_one(self):
        total = sum(DIMENSION_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001

    def test_five_dimensions(self):
        assert len(DIMENSION_WEIGHTS) == 5
        assert "cut" in DIMENSION_WEIGHTS
        assert "opening" in DIMENSION_WEIGHTS
        assert "subtitle" in DIMENSION_WEIGHTS
        assert "zoom" in DIMENSION_WEIGHTS
        assert "thumbnail" in DIMENSION_WEIGHTS


# ═══════════════════════════════════════════════════════════════════════════
#  END-TO-END CRITIQUE (tüm ölçümler mock)
# ═══════════════════════════════════════════════════════════════════════════


class TestCritiqueFlow:
    @pytest.mark.asyncio
    async def test_critique_heuristic_no_llm(self, monkeypatch, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake")

        critic = AICritic(target_score=8.5)
        monkeypatch.setattr(critic, "_probe_dimensions", _fake_dims(1080, 1920))
        monkeypatch.setattr(critic, "_measure_opening", _fake_val(0.2))
        monkeypatch.setattr(critic, "_measure_thumbnail", _fake_val(0.9))
        monkeypatch.setattr(critic, "_measure_zoom_timing", _fake_val(1.0))
        monkeypatch.setattr(critic, "_first_peak_time", _fake_peak(1.0))
        monkeypatch.setattr(critic, "_probe_duration", _fake_val(10.0))
        monkeypatch.setattr(critic, "_measure_cut_precision", _fake_val(0.3))
        monkeypatch.setattr(critic, "_get_cut_info", _fake_dict({
            "leading_silence_s": 0.0, "trailing_silence_s": 0.5, "word_count": 50,
        }))
        _disable_llm(monkeypatch)

        report = await critic.critique(
            video_path=str(video),
            subtitle_fontsize=24,
        )
        assert isinstance(report, CritiqueReport)
        assert 0 <= report.score <= 10
        assert report.used_llm is False
        dims = {i.dimension for i in report.issues}
        assert "opening" in dims
        assert "subtitle" in dims
        assert "cut" in dims
        assert report.passed is False
        # dimension_scores mevcut mu?
        assert "cut" in report.dimension_scores
        assert "opening" in report.dimension_scores

    @pytest.mark.asyncio
    async def test_critique_high_quality_passes(self, monkeypatch, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake")

        critic = AICritic(target_score=8.5)
        monkeypatch.setattr(critic, "_probe_dimensions", _fake_dims(1080, 1920))
        monkeypatch.setattr(critic, "_measure_opening", _fake_val(0.95))
        monkeypatch.setattr(critic, "_measure_thumbnail", _fake_val(0.95))
        monkeypatch.setattr(critic, "_measure_zoom_timing", _fake_val(1.0))
        monkeypatch.setattr(critic, "_first_peak_time", _fake_peak(1.0))
        monkeypatch.setattr(critic, "_probe_duration", _fake_val(10.0))
        monkeypatch.setattr(critic, "_measure_cut_precision", _fake_val(0.95))
        monkeypatch.setattr(critic, "_get_cut_info", _fake_dict({
            "leading_silence_s": 0.0, "trailing_silence_s": 0.3, "word_count": 50,
        }))
        _disable_llm(monkeypatch)

        report = await critic.critique(video_path=str(video), subtitle_fontsize=120)
        assert report.passed is True
        assert report.issues == []
        # opening, zoom, thumbnail, cut hepsi mock'tan 0.95; subtitle 120/1920=0.0625 → skor >= 0.9
        assert all(s >= 0.9 for s in report.dimension_scores.values())

    @pytest.mark.asyncio
    async def test_missing_video(self):
        critic = AICritic()
        report = await critic.critique(video_path="/nonexistent/x.mp4")
        assert report.score == 0.0
        assert report.passed is False


# ═══════════════════════════════════════════════════════════════════════════
#  AUTO-FIX (birim test — FFmpeg çağrıları mock)
# ═══════════════════════════════════════════════════════════════════════════


class TestAutoFix:
    @pytest.mark.asyncio
    async def test_auto_fix_returns_none_when_no_issues(self, monkeypatch, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake")

        critic = AICritic()
        report = CritiqueReport(
            score=9.0, passed=True, verdict="Mükemmel",
            issues=[],
            dimension_scores={"opening": 0.9, "subtitle": 0.9, "zoom": 0.9, "thumbnail": 0.9, "cut": 0.9},
        )
        result_path, applied = await critic.auto_fix(
            video_path=str(video), report=report,
        )
        assert result_path is None
        assert applied == []

    @pytest.mark.asyncio
    async def test_auto_fix_skips_disabled_dims(self, monkeypatch, tmp_path):
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake")

        critic = AICritic()
        report = CritiqueReport(
            score=5.0, passed=False, verdict="Zayıf",
            issues=[
                CriticIssue("opening", "warning", "Sıkıcı"),
                CriticIssue("subtitle", "warning", "Küçük"),
            ],
            dimension_scores={"opening": 0.2, "subtitle": 0.3, "zoom": 0.9, "thumbnail": 0.9, "cut": 0.9},
        )
        # hook_fix retorna None (first_peak <= 3.0), subtitle_fix de None (ASS yok)
        monkeypatch.setattr(critic, "_first_peak_time", _fake_peak(1.0))
        result_path, applied = await critic.auto_fix(
            video_path=str(video), report=report,
            subtitle_fontsize=24,
        )
        # Hiçbiri başarılı olmadı
        assert result_path is None


# ═══════════════════════════════════════════════════════════════════════════
#  CRITIC ANALYTICS
# ═══════════════════════════════════════════════════════════════════════════


class TestCriticAnalytics:
    def test_record_round(self):
        from services.critic_analytics import CriticAnalytics
        analytics = CriticAnalytics()

        record = analytics.record_round(
            clip_id="test_clip",
            round_idx=0,
            dimension_scores={"opening": 0.5, "subtitle": 0.4, "zoom": 0.8, "thumbnail": 0.7, "cut": 0.6},
            total_score=5.8,
            applied_fixes=[],
        )
        assert record.clip_id == "test_clip"
        assert record.score_delta == 0.0

    def test_record_round_with_delta(self):
        from services.critic_analytics import CriticAnalytics
        analytics = CriticAnalytics()

        # İlk tur
        analytics.record_round(
            clip_id="c1", round_idx=0,
            dimension_scores={"opening": 0.3, "subtitle": 0.4, "zoom": 0.5, "thumbnail": 0.6, "cut": 0.5},
            total_score=4.5, applied_fixes=[],
        )
        # İkinci tur (fix uygulandı)
        record = analytics.record_round(
            clip_id="c1", round_idx=1,
            dimension_scores={"opening": 0.8, "subtitle": 0.4, "zoom": 0.5, "thumbnail": 0.6, "cut": 0.5},
            total_score=6.5, applied_fixes=["opening"],
            previous_scores={"opening": 0.3, "subtitle": 0.4, "zoom": 0.5, "thumbnail": 0.6, "cut": 0.5},
        )
        assert record.score_delta > 0
        assert record.dimension_deltas["opening"] > 0

    def test_ab_report_empty(self):
        from services.critic_analytics import CriticAnalytics
        analytics = CriticAnalytics()
        report = analytics.get_ab_report()
        assert report["total_rounds"] == 0

    def test_ab_report_with_data(self):
        from services.critic_analytics import CriticAnalytics
        analytics = CriticAnalytics()

        for i in range(8):
            analytics.record_round(
                clip_id=f"c{i}", round_idx=0,
                dimension_scores={"opening": 0.5 + i * 0.05, "subtitle": 0.6, "zoom": 0.7, "thumbnail": 0.8, "cut": 0.7},
                total_score=6.0 + i * 0.3,
                applied_fixes=["opening"],
            )

        report = analytics.get_ab_report(last_n=10)
        assert report["total_rounds"] == 8
        assert report["rounds_with_fix"] == 8
        assert "dimensions" in report
        assert "recommendations" in report

    def test_correlation_report_empty(self):
        from services.critic_analytics import CriticAnalytics
        analytics = CriticAnalytics()
        report = analytics.get_correlation_report()
        assert "message" in report

    def test_dimension_effectiveness(self):
        from services.critic_analytics import CriticAnalytics
        analytics = CriticAnalytics()

        analytics.record_round(
            clip_id="c1", round_idx=1,
            dimension_scores={"opening": 0.7, "subtitle": 0.5, "zoom": 0.6, "thumbnail": 0.8, "cut": 0.7},
            total_score=6.5, applied_fixes=["opening"],
            previous_scores={"opening": 0.3, "subtitle": 0.5, "zoom": 0.6, "thumbnail": 0.8, "cut": 0.7},
        )
        analytics.record_round(
            clip_id="c2", round_idx=1,
            dimension_scores={"opening": 0.4, "subtitle": 0.5, "zoom": 0.6, "thumbnail": 0.8, "cut": 0.7},
            total_score=5.5, applied_fixes=["opening"],
            previous_scores={"opening": 0.3, "subtitle": 0.5, "zoom": 0.6, "thumbnail": 0.8, "cut": 0.7},
        )

        eff = analytics.get_dimension_effectiveness()
        assert "opening" in eff
        assert eff["opening"]["applied_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════
#  TEST YARDIMCILARI
# ═══════════════════════════════════════════════════════════════════════════


def _fake_val(v):
    async def _inner(*a, **k):
        return v
    return _inner


def _fake_peak(v):
    async def _inner(*a, **k):
        return v
    return _inner


def _fake_dims(w, h):
    async def _inner(*a, **k):
        return (w, h)
    return _inner


def _fake_dict(d):
    async def _inner(*a, **k):
        return d
    return _inner


def _disable_llm(monkeypatch):
    async def _empty(*a, **k):
        return {}
    from services import llm_reasoner as lr_mod
    monkeypatch.setattr(lr_mod.llm_reasoner, "critique_video", _empty)
