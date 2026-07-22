"""
Viral Edit API — AI-powered viral video editing endpoints
────────────────────────────────────────────────────────
TikTok/Instagram Reels viral optimizasyon API'leri:
  1. Viral analiz endpoint'leri
  2. Edit öneri endpoint'leri
  3. Meme overlay endpoint'leri
  4. SFX otomasyon endpoint'leri
  5. Fotoğraf animasyon endpoint'leri
  6. Trend tracking endpoint'leri
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/viral", tags=["viral", "ai-editing"])


# ── Request/Response Models ─────────────────────────────────

class ViralAnalysisRequest(BaseModel):
    content_description: str = Field(default="Viral clip content analysis", description="İçerik açıklaması")
    clip_path: str = Field(default="", description="Klip veya video dosyası yolu")
    video_duration: float = Field(default=30.0, ge=5.0, le=180.0, description="Video süresi (saniye)")
    target_platform: str = Field(default="tiktok", description="Hedef platform")
    content_category: str = Field(default="general", description="İçerik kategorisi")
    transcript: str = Field(default="", description="Video transkripti")
    emotions: list[str] = Field(default_factory=list, description="Tespit edilen duygular")


class MemeOverlayRequest(BaseModel):
    video_path: str = Field(..., description="Video path")
    context: str = Field(default="", description="Video içeriği")
    emotion: str = Field(default="funny", description="Duygu kategorisi")
    num_memes: int = Field(default=2, ge=1, le=5, description="Meme sayısı")


class SFXRequest(BaseModel):
    video_path: str = Field(..., description="Video path")
    transcript: str = Field(default="", description="Video transkripti")
    emotions: list[str] = Field(default_factory=list, description="Duygular")
    hook_points: list[float] = Field(default_factory=list, description="Hook noktaları")


class PhotoAnimationRequest(BaseModel):
    photo_path: str = Field(..., description="Fotoğraf path")
    context: str = Field(default="", description="Fotoğraf içeriği")
    emotion: str = Field(default="neutral", description="Duygu")
    effect: str = Field(default="zoom_in", description="Animasyon efekti")
    duration: float = Field(default=5.0, ge=3.0, le=10.0, description="Animasyon süresi")


class EditRecommendationRequest(BaseModel):
    content_description: str = Field(..., description="İçerik açıklaması")
    video_path: str = Field(default="", description="Video path")
    video_duration: float = Field(default=30.0, ge=5.0, le=180.0)
    target_platform: str = Field(default="tiktok")
    content_category: str = Field(default="general")
    transcript: str = Field(default="")
    emotions: list[str] = Field(default_factory=list)
    user_preferences: dict[str, Any] = Field(default_factory=dict)


# ── Viral Analysis Endpoints ────────────────────────────────

@router.post("/analyze")
async def analyze_viral_potential(request: ViralAnalysisRequest):
    """
    İçeriğin viral potansiyelini analiz et.
    
    LLM ve viral analytics kullanarak detaylı edit önerileri üretir.
    """
    try:
        from services.viral_llm_analyzer import viral_llm_analyzer
        
        analysis = await viral_llm_analyzer.analyze_content_for_viral_potential(
            content_description=request.content_description,
            video_duration=request.video_duration,
            target_platform=request.target_platform,
            content_category=request.content_category,
            transcript=request.transcript,
            emotions=request.emotions,
        )
        
        return {
            "status": "success",
            "analysis": analysis,
        }
        
    except Exception as e:
        logger.error("Viral analizi hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trends")
async def get_viral_trends(
    platform: str = "tiktok",
    lookback_days: int = 7,
):
    """
    Güncel viral trend'leri getir.
    
    Platform ve zaman aralığına göre trend'leri döndürür.
    """
    try:
        from services.viral_llm_analyzer import viral_llm_analyzer
        
        trends = await viral_llm_analyzer.get_trending_edit_techniques(
            platform=platform,
            lookback_days=lookback_days,
        )
        
        return {
            "status": "success",
            "trends": trends,
        }
        
    except Exception as e:
        logger.error("Trend getirme hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Meme Overlay Endpoints ─────────────────────────────────

@router.post("/memes/analyze")
async def analyze_meme_opportunities(request: MemeOverlayRequest):
    """
    Video için meme overlay önerileri üret.
    
    Context ve duygu analizine uygun meme'leri önerir.
    """
    try:
        from services.meme_overlay import meme_overlay
        
        suggestions = await meme_overlay.analyze_and_suggest_memes(
            video_path=request.video_path,
            transcript=request.context,
            emotions=[request.emotion] if request.emotion else [],
        )
        
        return {
            "status": "success",
            "suggestions": suggestions,
            "count": len(suggestions),
        }
        
    except Exception as e:
        logger.error("Meme analizi hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memes/apply")
async def apply_meme_overlays(
    request: MemeOverlayRequest,
    background_tasks: BackgroundTasks,
):
    """
    Videoya meme overlay'leri uygula (background task).
    
    Analiz edilen meme'leri videoya ekler.
    """
    try:
        from services.meme_overlay import meme_overlay
        
        # Önce analiz et
        suggestions = await meme_overlay.analyze_and_suggest_memes(
            video_path=request.video_path,
            transcript=request.context,
            emotions=[request.emotion] if request.emotion else [],
        )
        
        if not suggestions:
            return {
                "status": "error",
                "message": "Meme önerisi bulunamadı",
            }
        
        # Output path oluştur
        from pathlib import Path
        input_path = Path(request.video_path)
        output_path = input_path.parent / f"{input_path.stem}_memed.mp4"
        
        # Background task olarak uygula
        async def apply_memes():
            await meme_overlay.add_multiple_overlays(
                str(input_path),
                suggestions[:request.num_memes],
                str(output_path),
            )
        
        background_tasks.add_task(apply_memes)
        
        return {
            "status": "processing",
            "message": "Meme overlay'leri uygulanıyor",
            "output_path": str(output_path),
            "num_memes": min(len(suggestions), request.num_memes),
        }
        
    except Exception as e:
        logger.error("Meme uygulama hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── SFX Endpoints ─────────────────────────────────────────

@router.post("/sfx/analyze")
async def analyze_sfx_opportunities(request: SFXRequest):
    """
    Video için ses efekti önerileri üret.
    
    Transkript ve hook noktalarına göre SFX önerir.
    """
    try:
        from services.auto_sfx import auto_sfx
        
        suggestions = await auto_sfx.analyze_and_suggest_sfx(
            video_path=request.video_path,
            transcript=request.transcript,
            emotions=request.emotions,
            hook_points=request.hook_points,
        )
        
        return {
            "status": "success",
            "suggestions": suggestions,
            "count": len(suggestions),
        }
        
    except Exception as e:
        logger.error("SFX analizi hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sfx/apply")
async def apply_sfx(
    request: SFXRequest,
    background_tasks: BackgroundTasks,
):
    """
    Videoya ses efektleri uygula (background task).
    
    Analiz edilen SFX'leri videoya ekler.
    """
    try:
        from services.auto_sfx import auto_sfx
        
        # Önce analiz et
        suggestions = await auto_sfx.analyze_and_suggest_sfx(
            video_path=request.video_path,
            transcript=request.transcript,
            emotions=request.emotions,
            hook_points=request.hook_points,
        )
        
        if not suggestions:
            return {
                "status": "error",
                "message": "SFX önerisi bulunamadı",
            }
        
        # Output path oluştur
        from pathlib import Path
        input_path = Path(request.video_path)
        output_path = input_path.parent / f"{input_path.stem}_sfx.mp4"
        
        # Background task olarak uygula
        async def apply_sfx_task():
            await auto_sfx.add_multiple_sfx(
                str(input_path),
                suggestions,
                str(output_path),
            )
        
        background_tasks.add_task(apply_sfx_task)
        
        return {
            "status": "processing",
            "message": "SFX'ler uygulanıyor",
            "output_path": str(output_path),
            "num_sfx": len(suggestions),
        }
        
    except Exception as e:
        logger.error("SFX uygulama hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Photo Animation Endpoints ─────────────────────────────

@router.post("/photos/animate")
async def animate_photo(request: PhotoAnimationRequest):
    """
    Fotoğrafı animasyonlu videoya çevir.
    
    Ken Burns efektleri ile statik fotoğrafı viral videoya çevirir.
    """
    try:
        from services.photo_animator import photo_animator
        from pathlib import Path
        
        input_path = Path(request.photo_path)
        output_path = input_path.parent / f"{input_path.stem}_animated.mp4"
        
        # Animasyon önerisi al
        suggestion = await photo_animator.analyze_and_suggest_animation(
            photo_path=request.photo_path,
            context=request.context,
            emotion=request.emotion,
        )
        
        # Animasyonu uygula
        success = await photo_animator.animate_single_photo(
            photo_path=request.photo_path,
            output_path=str(output_path),
            effect=suggestion.get("effect", request.effect),
            duration=suggestion.get("duration", request.duration),
        )
        
        if success:
            return {
                "status": "success",
                "output_path": str(output_path),
                "effect_used": suggestion.get("effect"),
                "duration": suggestion.get("duration"),
            }
        else:
            return {
                "status": "error",
                "message": "Animasyon başarısız",
            }
        
    except Exception as e:
        logger.error("Fotoğraf animasyonu hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/photos/slideshow")
async def create_photo_slideshow(
    photo_paths: list[str],
    output_path: str,
    context: str = "",
    emotion: str = "neutral",
):
    """
    Birden fazla fotoğraflı slideshow videoya çevir.
    
    Fotoğrafları viral pattern'lere göre animasyonlu videoya çevirir.
    """
    try:
        from services.photo_animator import photo_animator
        
        # Her fotoğraf için animasyon önerisi al
        effects = []
        for photo_path in photo_paths:
            suggestion = await photo_animator.analyze_and_suggest_animation(
                photo_path=photo_path,
                context=context,
                emotion=emotion,
            )
            effects.append(suggestion.get("effect", "zoom_in"))
        
        # Slideshow oluştur
        success = await photo_animator.create_photo_slideshow(
            photo_paths=photo_paths,
            output_path=output_path,
            effects=effects,
        )
        
        if success:
            return {
                "status": "success",
                "output_path": output_path,
                "num_photos": len(photo_paths),
            }
        else:
            return {
                "status": "error",
                "message": "Slideshow oluşturma başarısız",
            }
        
    except Exception as e:
        logger.error("Slideshow oluşturma hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Edit Recommendation Endpoints ───────────────────────────

@router.post("/recommendations")
async def get_edit_recommendations(request: EditRecommendationRequest):
    """
    Kapsamlı edit önerileri üret.
    
    Viral analizi, LLM ve pattern learning kullanarak detaylı öneriler üretir.
    """
    try:
        from services.edit_recommendation import edit_recommendation_engine
        
        recommendations = await edit_recommendation_engine.generate_comprehensive_recommendations(
            content_description=request.content_description,
            video_path=request.video_path,
            video_duration=request.video_duration,
            target_platform=request.target_platform,
            content_category=request.content_category,
            transcript=request.transcript,
            emotions=request.emotions,
            user_preferences=request.user_preferences,
        )
        
        return {
            "status": "success",
            "recommendations": recommendations,
        }
        
    except Exception as e:
        logger.error("Edit öneri hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/recommendations/actionable")
async def get_actionable_steps(request: EditRecommendationRequest):
    """
    Eyleme geçirilebilir edit adımlarını getir.
    
    Önerileri somut implementasyon adımlarına çevirir.
    """
    try:
        from services.edit_recommendation import edit_recommendation_engine
        
        # Önce kapsamlı önerileri al
        recommendations = await edit_recommendation_engine.generate_comprehensive_recommendations(
            content_description=request.content_description,
            video_path=request.video_path,
            video_duration=request.video_duration,
            target_platform=request.target_platform,
            content_category=request.content_category,
            transcript=request.transcript,
            emotions=request.emotions,
            user_preferences=request.user_preferences,
        )
        
        # Eylem adımlarına çevir
        action_steps = await edit_recommendation_engine.get_actionable_edit_steps(
            recommendations=recommendations,
            video_path=request.video_path,
        )
        
        return {
            "status": "success",
            "action_steps": action_steps,
            "total_steps": len(action_steps),
        }
        
    except Exception as e:
        logger.error("Eylem adımı hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── Viral Technique Analysis Endpoints ───────────────────────

class DeepAnalysisRequest(BaseModel):
    platform: str = Field(default="tiktok", description="Hedef platform")
    analysis_depth: str = Field(default="comprehensive", description="Analiz derinliği")
    lookback_days: int = Field(default=30, ge=1, le=90, description="Kaç gün geriye bakılacak")


@router.post("/techniques/analyze")
async def analyze_viral_techniques(request: DeepAnalysisRequest):
    """
    Viral video tekniklerini derinlemeli analiz et.
    
    LLM ile viral pattern'leri analiz et ve net implementasyon kararları al.
    """
    try:
        from services.viral_technique_analyzer import viral_technique_analyzer
        
        # Derinlemeli analiz
        deep_analysis = await viral_technique_analyzer.deep_viral_analysis(
            platform=request.platform,
            analysis_depth=request.analysis_depth,
            lookback_days=request.lookback_days,
        )
        
        # Teknik kararları al
        decisions = await viral_technique_analyzer.make_technique_decisions(
            deep_analysis=deep_analysis,
            platform=request.platform,
        )
        
        return {
            "status": "success",
            "deep_analysis": deep_analysis,
            "decisions": decisions,
        }
        
    except Exception as e:
        logger.error("Viral teknik analizi hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/techniques/apply")
async def apply_technique_decisions(
    platform: str = "tiktok",
    background_tasks: BackgroundTasks = None,
):
    """
    Teknik kararları sisteme uygula.
    
    Derinlemeli analiz sonuçlarına dayalı kararları tüm servislere uygula.
    """
    try:
        from services.viral_technique_analyzer import viral_technique_analyzer
        
        # Önce kararları al
        deep_analysis = await viral_technique_analyzer.deep_viral_analysis(platform=platform)
        decisions = await viral_technique_analyzer.make_technique_decisions(
            deep_analysis=deep_analysis,
            platform=platform,
        )
        
        # Kararları uygula
        if background_tasks:
            async def apply_decisions_task():
                await viral_technique_analyzer.apply_decisions_to_system(decisions)
            
            background_tasks.add_task(apply_decisions_task)
            
            return {
                "status": "processing",
                "message": "Teknik kararları uygulanıyor (background)",
                "decisions_applied": len(decisions),
            }
        else:
            success = await viral_technique_analyzer.apply_decisions_to_system(decisions)
            
            return {
                "status": "completed" if success else "failed",
                "message": "Teknik kararları uygulandı" if success else "Uygulama başarısız",
                "decisions_applied": len(decisions),
            }
        
    except Exception as e:
        logger.error("Teknik kararları uygulama hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/techniques/decisions")
async def get_current_decisions(platform: str = "tiktok"):
    """
    Mevcut teknik kararlarını getir.
    
    Sistemde aktif olan viral edit kararlarını göster.
    """
    try:
        from services.viral_technique_analyzer import viral_technique_analyzer
        
        # En son kararları getir
        decision_key = f"{platform}_{datetime.now().strftime('%Y%m%d')}"
        current_decisions = viral_technique_analyzer._decisions.get(decision_key)
        
        if not current_decisions:
            # Bugünün kararları yoksa, en sonkararları al
            all_keys = sorted(viral_technique_analyzer._decisions.keys(), reverse=True)
            if all_keys:
                latest_key = all_keys[0]
                current_decisions = viral_technique_analyzer._decisions[latest_key]
        
        return {
            "status": "success",
            "platform": platform,
            "decisions": current_decisions,
            "has_decisions": current_decisions is not None,
        }
        
    except Exception as e:
        logger.error("Kararları getirme hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/techniques/compare")
async def compare_platform_techniques(
    platforms: list[str] = ["tiktok", "instagram_reels", "youtube_shorts"],
):
    """
    Platformlar arası viral teknik karşılaştırması.
    
    Farklı platformlar için viral tekniklerini analiz et ve karşılaştır.
    """
    try:
        from services.viral_technique_analyzer import viral_technique_analyzer
        
        comparison = {}
        
        for platform in platforms:
            try:
                # Her platform için analiz
                deep_analysis = await viral_technique_analyzer.deep_viral_analysis(
                    platform=platform,
                    analysis_depth="standard",
                    lookback_days=30,
                )
                
                decisions = await viral_technique_analyzer.make_technique_decisions(
                    deep_analysis=deep_analysis,
                    platform=platform,
                )
                
                comparison[platform] = {
                    "analysis": deep_analysis,
                    "decisions": decisions,
                }
                
            except Exception as e:
                logger.error("Platform karşılaştırma hatası (%s): %s", platform, e)
                comparison[platform] = {"error": str(e)}
        
        return {
            "status": "success",
            "comparison": comparison,
            "platforms_analyzed": len(platforms),
        }
        
    except Exception as e:
        logger.error("Platform karşılaştırma hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# ── System Endpoints ───────────────────────────────────────

@router.get("/health")
async def viral_health():
    """Viral edit sistemi health check."""
    try:
        from services.viral_llm_analyzer import viral_llm_analyzer
        from services.meme_overlay import meme_overlay
        from services.auto_sfx import auto_sfx
        from services.photo_animator import photo_animator
        from services.edit_recommendation import edit_recommendation_engine
        from services.viral_technique_analyzer import viral_technique_analyzer
        
        return {
            "status": "healthy",
            "services": {
                "viral_llm_analyzer": "available",
                "meme_overlay": "available",
                "auto_sfx": "available",
                "photo_animator": "available",
                "edit_recommendation_engine": "available",
                "viral_technique_analyzer": "available",
            }
        }
        
    except Exception as e:
        logger.error("Viral health check hatası: %s", e)
        return {
            "status": "degraded",
            "error": str(e)
        }