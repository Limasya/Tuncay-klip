"""
Advanced API Router — FAZ-2/3/4 Endpoint'leri
──────────────────────────────────────────────
Signal Fusion, Clip Optimization, Publisher, AB Test,
Multilingual Subtitles, Quality Dashboard, Cost Tracker, User Feedback
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("api.advanced")

router = APIRouter(prefix="/api/advanced", tags=["Advanced Features"])


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-2.1: SIGNAL FUSION
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/signal-fusion/ablation")
async def signal_fusion_ablation():
    """Sinyal ablation çalıştır — her sinyali kapatarak etki analizi."""
    from microservices.event_detector.service import EventDetectorService
    from services.signal_fusion import AblationEngine
    engine = EventDetectorService()
    ablation = AblationEngine(engine.scoring)
    results = await ablation.run_ablation()
    return {
        "results": [r.model_dump() for r in results],
        "recommendations": ablation.get_recommendations(results),
    }


@router.get("/signal-fusion/correlation")
async def signal_fusion_correlation():
    """Sinyaller arası korelasyon matrisi."""
    from microservices.event_detector.service import EventDetectorService
    from services.signal_fusion import SignalCorrelationAnalyzer
    engine = EventDetectorService()
    analyzer = SignalCorrelationAnalyzer(engine.scoring)
    matrix = analyzer.compute_correlation_matrix()
    redundant = analyzer.get_redundant_pairs()
    return {
        "matrix": matrix,
        "redundant_pairs": [p.model_dump() for p in redundant],
    }


@router.get("/signal-fusion/spam-detect")
async def spam_detect(message: str = "", username: str = ""):
    """Chat mesajı spam/emoji analizi."""
    from services.signal_fusion import spam_detector
    result = spam_detector.detect(message, username)
    return result.model_dump()


@router.post("/signal-fusion/spam-filter")
async def spam_filter(messages: list[dict]):
    """Mesaj listesinden spam'leri filtrele."""
    from services.signal_fusion import spam_detector
    filtered = spam_detector.filter_messages(messages)
    return {"original_count": len(messages), "filtered_count": len(filtered), "messages": filtered}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-2.2: SEGMENT CLASSIFIER
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/segments/classify")
async def get_segments(min_confidence: float = 0.0):
    """Mevcut segmentleri getir."""
    from services.segment_classifier import segment_classifier
    segments = segment_classifier.get_segments(min_confidence)
    return {
        "segments": [s.to_dict() for s in segments],
        "stats": segment_classifier.get_stats(),
    }


@router.get("/segments/clip-candidates")
async def get_clip_candidates(top_n: int = 5):
    """En yüksek öncelikli klip adaylarını getir."""
    from services.segment_classifier import segment_classifier
    candidates = segment_classifier.get_clip_candidates(top_n)
    return {"candidates": [c.to_dict() for c in candidates]}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-2.3: CLIP OPTIMIZER
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/clip-optimizer/platforms")
async def get_platform_specs():
    """Tüm platform spec'lerini listele."""
    from services.clip_optimizer import clip_optimizer
    return {"platforms": clip_optimizer.get_all_platforms()}


@router.get("/clip-optimizer/optimize")
async def optimize_clip(
    duration: float,
    platform: str = "tiktok",
    source_width: int = 1920,
    source_height: int = 1080,
):
    """Klibi belirli bir platform için optimize et."""
    from services.clip_optimizer import clip_optimizer
    result = clip_optimizer.optimize_for_platform(
        video_duration=duration,
        platform=platform,
        source_width=source_width,
        source_height=source_height,
    )
    return result.model_dump()


@router.get("/clip-optimizer/optimize-all")
async def optimize_clip_all_platforms(
    duration: float,
    platforms: str = "tiktok,youtube_shorts,instagram_reels",
):
    """Klibi tüm platformlar için optimize et."""
    from services.clip_optimizer import clip_optimizer
    platform_list = [p.strip() for p in platforms.split(",")]
    results = clip_optimizer.optimize_for_all_platforms(duration, platform_list)
    return {k: v.model_dump() for k, v in results.items()}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-3.1: MULTI-PLATFORM PUBLISHER
# ═══════════════════════════════════════════════════════════════════════════════

class PublishRequest(BaseModel):
    clip_id: str
    platforms: list[str] = ["tiktok"]
    video_path: str = ""
    title: str = ""
    description: str = ""
    hashtags: list[str] = []
    privacy: str = "private"


@router.post("/publisher/publish")
async def publish_clip(req: PublishRequest):
    """Klip'i birden fazla platforma yükle."""
    from services.multi_platform_publisher import multi_platform_publisher
    jobs = multi_platform_publisher.create_multi_platform_jobs(
        clip_id=req.clip_id,
        platforms=req.platforms,
        video_path=req.video_path,
        title=req.title,
        description=req.description,
        hashtags=req.hashtags,
        thumbnail_path="",
    )
    return {
        "jobs_created": len(jobs),
        "jobs": [{"job_id": j.job_id, "platform": j.platform.value} for j in jobs],
    }


@router.post("/publisher/process-queue")
async def process_publish_queue(max_concurrent: int = 3):
    """Yükleme kuyruğunu işle."""
    from services.multi_platform_publisher import multi_platform_publisher
    results = await multi_platform_publisher.process_queue(max_concurrent)
    return {"processed": len(results), "results": results}


@router.get("/publisher/stats")
async def publisher_stats():
    """Yükleme istatistikleri."""
    from services.multi_platform_publisher import multi_platform_publisher
    return multi_platform_publisher.get_stats()


@router.get("/publisher/optimal-time/{platform}")
async def get_optimal_time(platform: str):
    """Platform için en uygun paylaşma zamanı."""
    from services.multi_platform_publisher import multi_platform_publisher
    time_str = multi_platform_publisher.get_optimal_posting_time(platform)
    return {"platform": platform, "optimal_time": time_str}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-3.2: THUMBNAIL A/B TEST
# ═══════════════════════════════════════════════════════════════════════════════

class ABTestRequest(BaseModel):
    clip_id: str
    platform: str = "tiktok"
    video_path: str = ""
    streamer: str = "Tuncay"
    game: str = "Kick"
    highlight: str = ""
    num_variants: int = 3


@router.post("/ab-test/create")
async def create_ab_test(req: ABTestRequest):
    """Yeni A/B testi oluştur."""
    from services.thumbnail_ab_test import thumbnail_ab_test
    test = await thumbnail_ab_test.create_test(
        clip_id=req.clip_id,
        video_path=req.video_path,
        platform=req.platform,
        streamer=req.streamer,
        game=req.game,
        highlight_description=req.highlight,
        num_variants=req.num_variants,
    )
    return test.model_dump()


@router.get("/ab-test/{test_id}")
async def get_ab_test(test_id: str):
    """A/B test detayı."""
    from services.thumbnail_ab_test import thumbnail_ab_test
    test = thumbnail_ab_test.get_test(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    return test.model_dump()


@router.get("/ab-test/active")
async def get_active_ab_tests():
    """Aktif A/B testleri."""
    from services.thumbnail_ab_test import thumbnail_ab_test
    tests = thumbnail_ab_test.get_active_tests()
    return {"tests": [t.model_dump() for t in tests]}


@router.get("/ab-test/{test_id}/winner")
async def get_ab_winner(test_id: str):
    """A/B test kazananını getir."""
    from services.thumbnail_ab_test import thumbnail_ab_test
    winner = thumbnail_ab_test.get_winner(test_id)
    if not winner:
        return {"message": "Henüz yeterli veri yok veya test henüz tamamlanmadı"}
    return winner.model_dump()


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-3.3: MULTILINGUAL SUBTITLES
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/subtitles/languages")
async def get_supported_languages():
    """Desteklenen dilleri listele."""
    from services.multilingual_subtitles import SUPPORTED_LANGUAGES
    return {"languages": SUPPORTED_LANGUAGES}


@router.post("/subtitles/translate")
async def translate_subtitles(
    source_language: str = "tr",
    target_languages: str = "en,de",
):
    """Altyazıları birden fazla dile çevir."""
    from services.multilingual_subtitles import multilingual_subs
    targets = [t.strip() for t in target_languages.split(",")]
    results = await multilingual_subs.translate_to_all(source_language, targets)
    return {
        "translated": list(results.keys()),
        "stats": multilingual_subs.get_stats(),
    }


@router.get("/subtitles/export/{language}")
async def export_subtitles(language: str, format: str = "srt"):
    """Altyazıyı dosya olarak dışa aktar."""
    from services.multilingual_subtitles import multilingual_subs
    file_path = await multilingual_subs.save_to_file(language, format)
    if not file_path:
        raise HTTPException(status_code=404, detail="Track not found")
    return {"file_path": file_path, "language": language, "format": format}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-4.1: QUALITY DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/quality/status")
async def quality_status():
    """Mevcut kalite durumu."""
    from services.quality_dashboard import quality_dashboard
    return quality_dashboard.get_current_status()


@router.get("/quality/trend/daily")
async def quality_daily_trend(days: int = 30):
    """Günlük kalite trendi."""
    from services.quality_dashboard import quality_dashboard
    trends = quality_dashboard.get_daily_trend(days)
    return {"trends": [t.model_dump() for t in trends]}


@router.get("/quality/trend/weekly")
async def quality_weekly_trend(weeks: int = 12):
    """Haftalık kalite trendi."""
    from services.quality_dashboard import quality_dashboard
    trends = quality_dashboard.get_weekly_trend(weeks)
    return {"trends": [t.model_dump() for t in trends]}


@router.get("/quality/report/weekly")
async def quality_weekly_report():
    """Haftalık kalite raporu."""
    from services.quality_dashboard import quality_dashboard
    report = await quality_dashboard.generate_weekly_report()
    return report.model_dump()


@router.get("/quality/alerts")
async def quality_alerts(severity: Optional[str] = None):
    """Kalite uyarıları."""
    from services.quality_dashboard import quality_dashboard
    return {"alerts": quality_dashboard.get_alerts(severity)}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-4.2: COST TRACKER
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/costs/summary")
async def cost_summary(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
):
    """Maliyet özeti."""
    from services.cost_tracker import cost_tracker
    return cost_tracker.get_summary(start_time, end_time).model_dump()


@router.get("/costs/daily")
async def cost_daily(days: int = 30):
    """Günlük maliyet raporu."""
    from services.cost_tracker import cost_tracker
    return {"daily": cost_tracker.get_daily_costs(days)}


@router.get("/costs/month")
async def cost_current_month():
    """Bu ayki toplam maliyet."""
    from services.cost_tracker import cost_tracker
    return {"month_usd": cost_tracker.get_current_month_cost()}


@router.get("/costs/clip/{clip_id}")
async def cost_per_clip(clip_id: str):
    """Tek bir klibin maliyeti."""
    from services.cost_tracker import cost_tracker
    return {"clip_id": clip_id, "costs": cost_tracker.estimate_clip_cost(clip_id)}


# ═══════════════════════════════════════════════════════════════════════════════
#  FAZ-4.3: USER FEEDBACK
# ═══════════════════════════════════════════════════════════════════════════════

class ThumbsRequest(BaseModel):
    clip_id: str
    is_up: bool
    comment: str = ""


class RatingRequest(BaseModel):
    clip_id: str
    rating: float
    comment: str = ""


class DimensionFeedbackRequest(BaseModel):
    clip_id: str
    dimension: str
    ai_score: float
    user_agrees: bool
    comment: str = ""


@router.post("/feedback/thumbs")
async def feedback_thumbs(req: ThumbsRequest):
    """Thumbs up/down geri bildirimi."""
    from services.user_feedback import user_feedback
    entry = user_feedback.record_thumbs(req.clip_id, req.is_up, comment=req.comment)
    return entry.model_dump()


@router.post("/feedback/rating")
async def feedback_rating(req: RatingRequest):
    """Puanlama geri bildirimi."""
    from services.user_feedback import user_feedback
    entry = user_feedback.record_rating(req.clip_id, req.rating, comment=req.comment)
    return entry.model_dump()


@router.post("/feedback/dimension")
async def feedback_dimension(req: DimensionFeedbackRequest):
    """Boyut bazında geri bildirim."""
    from services.user_feedback import user_feedback
    entry = user_feedback.record_dimension_feedback(
        req.clip_id, req.dimension, req.ai_score, req.user_agrees, comment=req.comment
    )
    return entry.model_dump()


@router.get("/feedback/sentiment")
async def feedback_sentiment():
    """Genel kullanıcı sentimenti."""
    from services.user_feedback import user_feedback
    return user_feedback.get_overall_sentiment()


@router.get("/feedback/clip/{clip_id}")
async def feedback_for_clip(clip_id: str):
    """Bir klibin tüm geri bildirimleri."""
    from services.user_feedback import user_feedback
    agg = user_feedback.get_clip_feedback(clip_id)
    return agg.model_dump()


@router.post("/feedback/calibrate")
async def feedback_calibrate():
    """AI Critic kalibrasyon hesapla."""
    from services.user_feedback import user_feedback
    adjustments = await user_feedback.compute_calibration_adjustments()
    return {
        "adjustments": [a.model_dump() for a in adjustments],
        "history": user_feedback.get_calibration_history(),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  UNIFIED STATUS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/status")
async def advanced_features_status():
    """Tüm ileri özelliklerin durumu."""
    from services.signal_fusion import signal_fusion_store
    from services.segment_classifier import segment_classifier
    from services.clip_optimizer import clip_optimizer
    from services.multi_platform_publisher import multi_platform_publisher
    from services.thumbnail_ab_test import thumbnail_ab_test
    from services.multilingual_subtitles import multilingual_subs
    from services.quality_dashboard import quality_dashboard
    from services.cost_tracker import cost_tracker
    from services.user_feedback import user_feedback

    return {
        "signal_fusion": signal_fusion_store is not None,
        "segment_classifier": segment_classifier.get_stats(),
        "clip_optimizer": len(clip_optimizer.get_all_platforms()),
        "publisher": multi_platform_publisher.get_stats(),
        "ab_tests": thumbnail_ab_test.get_stats(),
        "subtitles": multilingual_subs.get_stats(),
        "quality": quality_dashboard.get_stats(),
        "costs": cost_tracker.get_stats(),
        "feedback": user_feedback.get_stats(),
    }
