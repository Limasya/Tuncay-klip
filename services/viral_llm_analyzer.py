"""
LLM-based Viral Video Analyzer — AI-powered edit recommendations
────────────────────────────────────────────────────────────────
Viral video pattern'lerini LLM ile analiz eder ve edit önerileri üretir:
  1. Viral analytics verilerini LLM'e iletir
  2. LLM ile detaylı edit stratejisi geliştirir
  3. Content-specific öneriler üretir
  4. Platform optimization yapar
  5. Real-time trend adaptation

Entegrasyon:
- viral_analytics.py (veri kaynağı)
- llm_engine.py (LLM motoru)
- auto_editor.py (edit uygulaması)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("viral_llm_analyzer")


class ViralLLMAnalyzer:
    """
    LLM tabanlı viral video analizörü — AI-powered edit önerileri.
    """

    def __init__(self):
        self._analysis_cache: dict[str, Any] = {}
        self._trend_cache: dict[str, Any] = {}

    async def analyze_content_for_viral_potential(
        self,
        content_description: str,
        video_duration: float = 30.0,
        target_platform: str = "tiktok",
        content_category: str = "general",
        transcript: str = "",
        emotions: list[str] = [],
    ) -> dict[str, Any]:
        """
        İçeriğin viral potansiyelini analiz et ve edit önerileri üret.
        
        Args:
            content_description: İçerik açıklaması
            video_duration: Video süresi
            target_platform: Hedef platform
            content_category: İçerik kategorisi
            transcript: Video transkripti
            emotions: Tespit edilen duygular
        
        Returns:
            Viral analysis and edit recommendations
        """
        try:
            from services.viral_analytics import viral_analytics
            from services.llm_engine import llm_engine
            
            # Viral analytics'ten veri al
            viral_prompt = await viral_analytics.generate_llm_analysis_prompt(
                content_context=content_description,
                target_platform=target_platform
            )
            
            # LLM analysis prompt'u oluştur
            full_prompt = f"""
            Viral Video Edit Analizi
            ─────────────────────────
            
            {viral_prompt}
            
            Spesifik İçerik Bilgileri:
            - Süre: {video_duration} saniye
            - Platform: {target_platform}
            - Kategori: {content_category}
            - Transkript: {transcript[:800] if transcript else 'Yok'}...
            - Duygular: {', '.join(emotions) if emotions else 'Belirlenmedi'}
            
            Lütfen bu içerik için viral optimizasyon önerileri üret:
            
            1. HOOK STRATEJİSİ:
               - İlk 3 saniyede ne yapılmalı?
               - Hook type (visual/audio/text/combo)
               - Hook placement ve timing
            
            2. TRANSITION PLAN:
               - Kaç transition?
               - Transition tipi ve frequency
               - Transition timing (hangi saniyelerde)
            
            3. EFFECT PLAN:
               - SFX kullanımı (event types, timing)
               - Meme overlay (kategoriler, placement, animation)
               - Visual effects (zoom, filters, etc.)
            
            4. CAPTION STRATEGY:
               - Caption style (karaoke/static/animated)
               - Text timing
               - Font ve color scheme
            
            5. PACING:
               - Cuts per minute
               - Average shot duration
               - Rhythm pattern
            
            6. AUDIO STRATEGY:
               - Music type ve volume
               - Beat sync stratejisi
               - Voice/music balance
            
            7. SPECIFIC RECOMMENDATIONS:
               - Bu içerik için özel öneriler
               - Kaçınacak teknikler
               - Viral trend'lerden yararlanma
            
            JSON formatında döndür, her kategori detaylı olsun.
            """
            
            # LLM analizi
            llm_response = await llm_engine.generate_completion(full_prompt)
            
            # Response'ı parse et
            analysis = self._parse_llm_response(llm_response)
            
            # Metadata ekle
            analysis.update({
                "content_description": content_description,
                "video_duration": video_duration,
                "target_platform": target_platform,
                "content_category": content_category,
                "analyzed_at": datetime.now().isoformat(),
                "transcript_summary": transcript[:200] if transcript else "",
                "emotions": emotions,
            })
            
            # Cache'e ekle
            cache_key = f"{hash(content_description)}_{target_platform}"
            self._analysis_cache[cache_key] = analysis
            
            logger.info("LLM viral analizi tamamlandı: %s (%s)", 
                       content_category, target_platform)
            return analysis
            
        except Exception as e:
            logger.error("LLM viral analizi hatası: %s", e)
            return self._get_fallback_analysis(content_description, target_platform)

    def _parse_llm_response(self, llm_response: str) -> dict[str, Any]:
        """LLM response'ını parse et."""
        try:
            # JSON parse dene
            parsed = json.loads(llm_response)
            
            # Validate structure
            required_sections = [
                "hook_strategy", "transition_plan", "effect_plan",
                "caption_strategy", "pacing", "audio_strategy"
            ]
            
            for section in required_sections:
                if section not in parsed:
                    parsed[section] = self._get_default_section(section)
            
            return parsed
            
        except json.JSONDecodeError:
            # JSON parse başarısızsa, fallback
            logger.warning("LLM response JSON parse başarısız, fallback kullanılıyor")
            return self._get_fallback_structure()

    def _get_default_section(self, section_name: str) -> dict[str, Any]:
        """Varsayılan section yapısı."""
        defaults = {
            "hook_strategy": {
                "hook_type": "combo",
                "timing": "0-3s",
                "description": "Visual + audio hook combination",
                "confidence": 0.7
            },
            "transition_plan": {
                "transition_type": "cut",
                "frequency": "2-3 per 10s",
                "timing": "Regular intervals",
                "confidence": 0.6
            },
            "effect_plan": {
                "sfx_usage": "impact events at key moments",
                "meme_usage": "context-aware overlays",
                "visual_effects": "subtle zoom/pan",
                "confidence": 0.65
            },
            "caption_strategy": {
                "style": "karaoke",
                "timing": "word-by-word sync",
                "font_size": "48-64px",
                "color_scheme": "high_contrast",
                "confidence": 0.7
            },
            "pacing": {
                "cuts_per_minute": "10-15",
                "shot_duration": "4-6s average",
                "rhythm": "steady with buildup",
                "confidence": 0.6
            },
            "audio_strategy": {
                "music_type": "trending upbeat",
                "volume": "-12dB",
                "beat_sync": "enabled",
                "voice_balance": "0.6 voice / 0.4 music",
                "confidence": 0.65
            }
        }
        
        return defaults.get(section_name, {"confidence": 0.5})

    def _get_fallback_structure(self) -> dict[str, Any]:
        """Fallback analysis yapısı."""
        return {
            "hook_strategy": self._get_default_section("hook_strategy"),
            "transition_plan": self._get_default_section("transition_plan"),
            "effect_plan": self._get_default_section("effect_plan"),
            "caption_strategy": self._get_default_section("caption_strategy"),
            "pacing": self._get_default_section("pacing"),
            "audio_strategy": self._get_default_section("audio_strategy"),
            "specific_recommendations": [
                "Focus on strong opening hook",
                "Use trending audio",
                "Keep captions readable",
                "Optimize for platform format"
            ],
            "avoid_techniques": [
                "Long static shots",
                "Poor audio quality",
                "Illegible text"
            ],
            "is_fallback": True
        }

    def _get_fallback_analysis(self, content_description: str, platform: str) -> dict[str, Any]:
        """Fallback analysis."""
        fallback = self._get_fallback_structure()
        fallback.update({
            "content_description": content_description,
            "target_platform": platform,
            "analyzed_at": datetime.now().isoformat(),
            "is_fallback": True
        })
        return fallback

    async def analyze_trending_videos_batch(
        self,
        video_descriptions: list[str],
        platform: str = "tiktok",
    ) -> list[dict[str, Any]]:
        """
        Birden fazla videoyu batch olarak analiz et.
        
        Args:
            video_descriptions: Video açıklamaları listesi
            platform: Hedef platform
        
        Returns:
            List of analyses
        """
        analyses = []
        
        for description in video_descriptions:
            try:
                analysis = await self.analyze_content_for_viral_potential(
                    content_description=description,
                    target_platform=platform
                )
                analyses.append(analysis)
            except Exception as e:
                logger.error("Batch analizi hatası: %s", e)
                analyses.append(self._get_fallback_analysis(description, platform))
        
        logger.info("Batch viral analizi tamamlandı: %d video", len(analyses))
        return analyses

    async def generate_edit_specification(
        self,
        analysis: dict[str, Any],
        video_path: str = "",
    ) -> dict[str, Any]:
        """
        Analiz sonuçlarını edit specification'a çevir.
        
        Args:
            analysis: Viral analysis results
            video_path: Video path (opsiyonel)
        
        Returns:
            Edit specification for auto_editor
        """
        try:
            from services.meme_overlay import meme_overlay
            from services.auto_sfx import auto_sfx
            
            edit_spec = {
                "video_path": video_path,
                "platform": analysis.get("target_platform", "tiktok"),
                "duration": analysis.get("video_duration", 30.0),
                "hook_strategy": analysis.get("hook_strategy", {}),
                "caption_strategy": analysis.get("caption_strategy", {}),
                "pacing": analysis.get("pacing", {}),
                "audio_strategy": analysis.get("audio_strategy", {}),
            }
            
            # Effect plan'ı somut komutlara çevir
            effect_plan = analysis.get("effect_plan", {})
            transition_plan = analysis.get("transition_plan", {})
            
            # Meme overlay'leri
            if "meme_usage" in effect_plan:
                # Basit implementation - gerçek için daha sophisticated logic
                meme_suggestions = await meme_overlay.analyze_and_suggest_memes(
                    video_path=video_path,
                    transcript=analysis.get("transcript_summary", ""),
                    emotions=analysis.get("emotions", [])
                )
                edit_spec["meme_overlays"] = meme_suggestions
            
            # SFX events
            if "sfx_usage" in effect_plan:
                sfx_suggestions = await auto_sfx.analyze_and_suggest_sfx(
                    video_path=video_path,
                    transcript=analysis.get("transcript_summary", ""),
                    emotions=analysis.get("emotions", []),
                    hook_points=self._extract_hook_points(analysis)
                )
                edit_spec["sfx_events"] = sfx_suggestions
            
            # Transitions
            if transition_plan:
                edit_spec["transitions"] = self._parse_transition_plan(transition_plan)
            
            logger.info("Edit specification üretildi: %s", video_path or "no_path")
            return edit_spec
            
        except Exception as e:
            logger.error("Edit specification üretme hatası: %s", e)
            return {"error": str(e)}

    def _extract_hook_points(self, analysis: dict[str, Any]) -> list[float]:
        """Analizden hook noktalarını çıkar."""
        hook_strategy = analysis.get("hook_strategy", {})
        timing = hook_strategy.get("timing", "0-3s")
        
        # Basit parsing - gerçek için daha sophisticated
        if "-" in timing:
            try:
                start, end = timing.replace("s", "").split("-")
                return [float(start), float(end)]
            except:
                return [0.0, 3.0]
        return [0.0, 3.0]

    def _parse_transition_plan(self, transition_plan: dict[str, Any]) -> list[dict[str, Any]]:
        """Transition plan'ını parse et."""
        transitions = []
        
        trans_type = transition_plan.get("transition_type", "cut")
        frequency = transition_plan.get("frequency", "2-3 per 10s")
        
        # Basit implementation
        if "per" in frequency:
            try:
                count, duration = frequency.split(" per ")
                count = int(count.split("-")[0])  # "2-3" -> "2"
                duration_sec = float(duration.replace("s", ""))
                
                interval = duration_sec / max(count, 1)
                
                for i in range(count):
                    transitions.append({
                        "type": trans_type,
                        "timestamp": i * interval,
                        "duration": 0.5
                    })
            except:
                pass
        
        return transitions

    async def get_trending_edit_techniques(
        self,
        platform: str = "tiktok",
        lookback_days: int = 7,
    ) -> dict[str, Any]:
        """
        Trending edit tekniklerini getir.
        
        Args:
            platform: Hedef platform
            lookback_days: Kaç gün geriye bakılacak
        
        Returns:
            Trending techniques summary
        """
        try:
            from services.viral_analytics import viral_analytics
            
            # Trend'leri al
            trends = await viral_analytics.detect_trends(
                lookback_days=lookback_days,
                min_engagement=10000
            )
            
            # Trend'leri özetle
            trend_summary = {
                "platform": platform,
                "lookback_days": lookback_days,
                "total_trends": len(trends),
                "trends": trends,
                "recommendations": []
            }
            
            # Her trend için öneri üret
            for trend in trends:
                category = trend["category"]
                pattern = trend["emerging_pattern"]
                
                recommendation = {
                    "category": category,
                    "technique": pattern,
                    "adoption_rate": trend["trend_score"],
                    "sample_size": trend["sample_size"],
                    "when_to_use": f"When targeting {category} optimization"
                }
                
                trend_summary["recommendations"].append(recommendation)
            
            logger.info("Trending teknikler getirildi: %d trend", len(trends))
            return trend_summary
            
        except Exception as e:
            logger.error("Trending teknikleri getirme hatası: %s", e)
            return {"error": str(e)}


# Global instance
viral_llm_analyzer = ViralLLMAnalyzer()