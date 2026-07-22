"""
Edit Recommendation Engine — AI-powered video editing suggestions
──────────────────────────────────────────────────────────────
Viral analizi ve LLM sonuçlarını birleştirerek somut edit önerileri üretir:
  1. Content analysis integration
  2. Multi-factor scoring (viral potential, technical feasibility, user preferences)
  3. Actionable edit suggestions
  4. Platform-specific optimization
  5. Real-time adaptation

Entegrasyon:
- viral_llm_analyzer.py (LLM analysis)
- viral_analytics.py (pattern data)
- auto_editor.py (edit application)
- user preferences (learning system)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("edit_recommendation")


class EditRecommendationEngine:
    """
    Edit öneri motoru — viral potansiyel ve teknik uygulanabilirlik bazlı öneriler.
    """

    def __init__(self):
        self._recommendation_cache: dict[str, Any] = {}
        self._user_preferences: dict[str, Any] = {}
        self._performance_history: list[dict[str, Any]] = []

    async def generate_comprehensive_recommendations(
        self,
        content_description: str,
        video_path: str = "",
        video_duration: float = 30.0,
        target_platform: str = "tiktok",
        content_category: str = "general",
        transcript: str = "",
        emotions: list[str] = [],
        user_preferences: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """
        Kapsamlı edit önerileri üret.
        
        Args:
            content_description: İçerik açıklaması
            video_path: Video path
            video_duration: Video süresi
            target_platform: Hedef platform
            content_category: İçerik kategorisi
            transcript: Video transkripti
            emotions: Tespit edilen duygular
            user_preferences: Kullanıcı tercihleri
        
        Returns:
            Comprehensive edit recommendations
        """
        try:
            from services.viral_llm_analyzer import viral_llm_analyzer
            from services.viral_analytics import viral_analytics
            
            # LLM viral analizi
            llm_analysis = await viral_llm_analyzer.analyze_content_for_viral_potential(
                content_description=content_description,
                video_duration=video_duration,
                target_platform=target_platform,
                content_category=content_category,
                transcript=transcript,
                emotions=emotions
            )
            
            # Viral analytics pattern'leri
            viral_patterns = await viral_analytics.get_viral_recommendations(
                content_type=content_category,
                platform=target_platform,
                top_n=5
            )
            
            # Trending teknikler
            trending_techs = await viral_llm_analyzer.get_trending_edit_techniques(
                platform=target_platform,
                lookback_days=7
            )
            
            # Edit specification üret
            edit_spec = await viral_llm_analyzer.generate_edit_specification(
                analysis=llm_analysis,
                video_path=video_path
            )
            
            # Önerileri skorla ve sırala
            scored_recommendations = self._score_and_rank_recommendations(
                llm_analysis=llm_analysis,
                viral_patterns=viral_patterns,
                trending_techs=trending_techs,
                edit_spec=edit_spec,
                user_preferences=user_preferences or {}
            )
            
            # Final recommendation package
            comprehensive_package = {
                "content_info": {
                    "description": content_description,
                    "duration": video_duration,
                    "platform": target_platform,
                    "category": content_category,
                    "video_path": video_path,
                },
                "llm_analysis": llm_analysis,
                "viral_patterns": viral_patterns,
                "trending_techniques": trending_techs,
                "edit_specification": edit_spec,
                "scored_recommendations": scored_recommendations,
                "generated_at": datetime.now().isoformat(),
                "confidence_score": self._calculate_overall_confidence(scored_recommendations),
            }
            
            # Cache'e ekle
            cache_key = f"{hash(content_description)}_{target_platform}_{video_duration}"
            self._recommendation_cache[cache_key] = comprehensive_package
            
            logger.info("Kapsamlı edit önerileri üretildi: %s (%d öneri)", 
                       content_category, len(scored_recommendations))
            return comprehensive_package
            
        except Exception as e:
            logger.error("Edit öneri üretme hatası: %s", e)
            return self._get_fallback_recommendations(content_description, target_platform)

    def _score_and_rank_recommendations(
        self,
        llm_analysis: dict[str, Any],
        viral_patterns: list[dict[str, Any]],
        trending_techs: dict[str, Any],
        edit_spec: dict[str, Any],
        user_preferences: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Önerileri çok faktörlü skorla ve sırala.
        
        Scoring factors:
        - Viral potential (LLM confidence)
        - Pattern strength (viral analytics)
        - Trend alignment (trending techniques)
        - Technical feasibility (edit constraints)
        - User preference alignment
        """
        recommendations = []
        
        # Hook stratejisi önerisi
        hook_strategy = llm_analysis.get("hook_strategy", {})
        hook_rec = {
            "type": "hook_strategy",
            "recommendation": hook_strategy,
            "viral_score": hook_strategy.get("confidence", 0.7),
            "trend_score": self._calculate_trend_alignment("hook", trending_techs),
            "feasibility_score": 0.9,  # Hook'lar genellikle uygulanabilir
            "user_alignment": self._calculate_user_alignment("hook", user_preferences),
            "priority": "high",
            "implementation_difficulty": "low",
        }
        hook_rec["overall_score"] = self._calculate_overall_score(hook_rec)
        recommendations.append(hook_rec)
        
        # Transition önerisi
        transition_plan = llm_analysis.get("transition_plan", {})
        transition_rec = {
            "type": "transition_plan",
            "recommendation": transition_plan,
            "viral_score": transition_plan.get("confidence", 0.6),
            "trend_score": self._calculate_trend_alignment("transition", trending_techs),
            "feasibility_score": 0.8,
            "user_alignment": self._calculate_user_alignment("transition", user_preferences),
            "priority": "medium",
            "implementation_difficulty": "medium",
        }
        transition_rec["overall_score"] = self._calculate_overall_score(transition_rec)
        recommendations.append(transition_rec)
        
        # Effect önerisi
        effect_plan = llm_analysis.get("effect_plan", {})
        effect_rec = {
            "type": "effect_plan",
            "recommendation": effect_plan,
            "viral_score": effect_plan.get("confidence", 0.65),
            "trend_score": self._calculate_trend_alignment("effect", trending_techs),
            "feasibility_score": 0.7,
            "user_alignment": self._calculate_user_alignment("effect", user_preferences),
            "priority": "medium",
            "implementation_difficulty": "medium",
        }
        effect_rec["overall_score"] = self._calculate_overall_score(effect_rec)
        recommendations.append(effect_rec)
        
        # Caption önerisi
        caption_strategy = llm_analysis.get("caption_strategy", {})
        caption_rec = {
            "type": "caption_strategy",
            "recommendation": caption_strategy,
            "viral_score": caption_strategy.get("confidence", 0.7),
            "trend_score": self._calculate_trend_alignment("caption", trending_techs),
            "feasibility_score": 0.95,
            "user_alignment": self._calculate_user_alignment("caption", user_preferences),
            "priority": "high",
            "implementation_difficulty": "low",
        }
        caption_rec["overall_score"] = self._calculate_overall_score(caption_rec)
        recommendations.append(caption_rec)
        
        # Pacing önerisi
        pacing = llm_analysis.get("pacing", {})
        pacing_rec = {
            "type": "pacing",
            "recommendation": pacing,
            "viral_score": pacing.get("confidence", 0.6),
            "trend_score": self._calculate_trend_alignment("pacing", trending_techs),
            "feasibility_score": 0.85,
            "user_alignment": self._calculate_user_alignment("pacing", user_preferences),
            "priority": "medium",
            "implementation_difficulty": "medium",
        }
        pacing_rec["overall_score"] = self._calculate_overall_score(pacing_rec)
        recommendations.append(pacing_rec)
        
        # Audio önerisi
        audio_strategy = llm_analysis.get("audio_strategy", {})
        audio_rec = {
            "type": "audio_strategy",
            "recommendation": audio_strategy,
            "viral_score": audio_strategy.get("confidence", 0.65),
            "trend_score": self._calculate_trend_alignment("audio", trending_techs),
            "feasibility_score": 0.9,
            "user_alignment": self._calculate_user_alignment("audio", user_preferences),
            "priority": "high",
            "implementation_difficulty": "low",
        }
        audio_rec["overall_score"] = self._calculate_overall_score(audio_rec)
        recommendations.append(audio_rec)
        
        # Overall score'a göre sırala
        recommendations = sorted(recommendations, key=lambda x: x["overall_score"], reverse=True)
        
        return recommendations

    def _calculate_overall_score(self, recommendation: dict[str, Any]) -> float:
        """Önerinin genel skorunu hesapla."""
        weights = {
            "viral_score": 0.35,
            "trend_score": 0.25,
            "feasibility_score": 0.20,
            "user_alignment": 0.20,
        }
        
        overall = (
            recommendation["viral_score"] * weights["viral_score"] +
            recommendation["trend_score"] * weights["trend_score"] +
            recommendation["feasibility_score"] * weights["feasibility_score"] +
            recommendation["user_alignment"] * weights["user_alignment"]
        )
        
        return round(overall, 3)

    def _calculate_trend_alignment(self, category: str, trending_techs: dict[str, Any]) -> float:
        """Trend alignment skorunu hesapla."""
        try:
            trends = trending_techs.get("trends", [])
            
            for trend in trends:
                if trend["category"] == category:
                    return min(0.95, trend["trend_score"])
            
            # Kategori trend'lerde yoksa ortalama skor
            if trends:
                avg_trend = sum(t["trend_score"] for t in trends) / len(trends)
                return avg_trend * 0.7  # Discount factor
            
            return 0.5  # No trend data
            
        except Exception:
            return 0.5

    def _calculate_user_alignment(self, category: str, user_preferences: dict[str, Any]) -> float:
        """Kullanıcı tercihlerine göre alignment hesapla."""
        try:
            if not user_preferences:
                return 0.7  # Neutral score
            
            category_pref = user_preferences.get(category, {})
            
            if isinstance(category_pref, dict):
                # Preference varsa
                preference_value = category_pref.get("importance", 0.7)
                return min(0.95, preference_value)
            elif isinstance(category_pref, (int, float)):
                return min(0.95, category_pref)
            
            return 0.7
            
        except Exception:
            return 0.7

    def _calculate_overall_confidence(self, recommendations: list[dict[str, Any]]) -> float:
        """Genel confidence score hesapla."""
        if not recommendations:
            return 0.5
        
        avg_score = sum(r["overall_score"] for r in recommendations) / len(recommendations)
        return round(avg_score, 3)

    def _get_fallback_recommendations(self, content_description: str, platform: str) -> dict[str, Any]:
        """Fallback öneriler."""
        return {
            "content_info": {
                "description": content_description,
                "platform": platform,
            },
            "scored_recommendations": [
                {
                    "type": "hook_strategy",
                    "recommendation": {"hook_type": "combo", "timing": "0-3s"},
                    "overall_score": 0.7,
                    "priority": "high",
                    "implementation_difficulty": "low",
                },
                {
                    "type": "caption_strategy",
                    "recommendation": {"style": "karaoke"},
                    "overall_score": 0.65,
                    "priority": "high",
                    "implementation_difficulty": "low",
                },
            ],
            "is_fallback": True,
            "generated_at": datetime.now().isoformat(),
        }

    async def get_actionable_edit_steps(
        self,
        recommendations: dict[str, Any],
        video_path: str = "",
    ) -> list[dict[str, Any]]:
        """
        Önerileri eyleme geçirilebilir adımlara çevir.
        
        Args:
            recommendations: Comprehensive recommendations
            video_path: Video path
        
        Returns:
            Actionable edit steps
        """
        try:
            action_steps = []
            scored_recs = recommendations.get("scored_recommendations", [])
            edit_spec = recommendations.get("edit_specification", {})
            
            # Her öneriyi eylem adımına çevir
            for rec in scored_recs:
                step = {
                    "step_type": rec["type"],
                    "priority": rec["priority"],
                    "difficulty": rec["implementation_difficulty"],
                    "estimated_time": self._estimate_implementation_time(rec["type"]),
                    "commands": self._generate_edit_commands(rec, edit_spec, video_path),
                    "expected_viral_impact": rec["overall_score"],
                }
                action_steps.append(step)
            
            # Priority ve difficulty'ye göre sırala
            action_steps = sorted(
                action_steps,
                key=lambda x: (self._priority_value(x["priority"]), -self._difficulty_value(x["difficulty"]))
            )
            
            logger.info("%d eylem adımı üretildi", len(action_steps))
            return action_steps
            
        except Exception as e:
            logger.error("Eylem adımı üretme hatası: %s", e)
            return []

    def _estimate_implementation_time(self, step_type: str) -> str:
        """Implementation süresi tahmini."""
        time_estimates = {
            "hook_strategy": "2-5 minutes",
            "transition_plan": "5-10 minutes",
            "effect_plan": "10-20 minutes",
            "caption_strategy": "3-8 minutes",
            "pacing": "5-15 minutes",
            "audio_strategy": "3-10 minutes",
        }
        return time_estimates.get(step_type, "5-10 minutes")

    def _generate_edit_commands(
        self,
        recommendation: dict[str, Any],
        edit_spec: dict[str, Any],
        video_path: str,
    ) -> list[str]:
        """Edit komutları üret."""
        commands = []
        step_type = recommendation["step_type"]
        rec_data = recommendation["recommendation"]
        
        if step_type == "hook_strategy":
            hook_type = rec_data.get("hook_type", "combo")
            timing = rec_data.get("timing", "0-3s")
            commands = [
                f"Apply {hook_type} hook at {timing}",
                "Ensure strong visual impact in first 3 seconds",
                "Add attention-grabbing audio or text overlay"
            ]
        
        elif step_type == "caption_strategy":
            style = rec_data.get("style", "karaoke")
            commands = [
                f"Generate {style} captions using Whisper",
                "Sync captions word-by-word with audio",
                "Apply high-contrast color scheme for readability"
            ]
        
        elif step_type == "effect_plan":
            commands = [
                "Add meme overlays at key moments",
                "Insert SFX for impact events",
                "Apply subtle visual effects (zoom/pan)"
            ]
        
        elif step_type == "audio_strategy":
            music_type = rec_data.get("music_type", "trending")
            volume = rec_data.get("volume", "-12dB")
            commands = [
                f"Add {music_type} background music at {volume}",
                "Enable beat synchronization",
                "Balance voice and music levels"
            ]
        
        else:
            commands = [f"Apply {step_type} according to recommendations"]
        
        return commands

    def _priority_value(self, priority: str) -> int:
        """Priority değerini sayısal olarak döndür."""
        priority_map = {"high": 3, "medium": 2, "low": 1}
        return priority_map.get(priority, 2)

    def _difficulty_value(self, difficulty: str) -> int:
        """Difficulty değerini sayısal olarak döndür."""
        difficulty_map = {"low": 1, "medium": 2, "high": 3}
        return difficulty_map.get(difficulty, 2)

    async def track_recommendation_performance(
        self,
        recommendation_id: str,
        actual_performance: dict[str, float],
    ):
        """
        Öneri performansını takip et (learning system için).
        
        Args:
            recommendation_id: Öneri ID'si
            actual_performance: Gerçek performans metrikleri
        """
        try:
            performance_record = {
                "recommendation_id": recommendation_id,
                "actual_performance": actual_performance,
                "tracked_at": datetime.now().isoformat(),
            }
            
            self._performance_history.append(performance_record)
            
            # Performans geçmişini kullanarak user preferences'ı güncelle
            self._update_user_preferences_from_performance(performance_record)
            
            logger.info("Öneri performansı takip edildi: %s", recommendation_id)
            
        except Exception as e:
            logger.error("Performans takibi hatası: %s", e)

    def _update_user_preferences_from_performance(self, performance_record: dict[str, Any]):
        """Performans verisine göre kullanıcı tercihlerini güncelle."""
        try:
            actual_perf = performance_record.get("actual_performance", {})
            
            # Basit learning rule: başarılı teknikleri ödüllendir
            for technique, score in actual_perf.items():
                if score > 0.7:  # Başarılı kabul et
                    if technique not in self._user_preferences:
                        self._user_preferences[technique] = {}
                    
                    current_importance = self._user_preferences[technique].get("importance", 0.7)
                    # Importance'u artır (max 0.95)
                    new_importance = min(0.95, current_importance + 0.05)
                    self._user_preferences[technique]["importance"] = new_importance
            
        except Exception as e:
            logger.error("Preference güncelleme hatası: %s", e)


# Global instance
edit_recommendation_engine = EditRecommendationEngine()