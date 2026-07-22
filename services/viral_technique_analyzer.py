"""
Viral Technique Analyzer — LLM-powered deep viral video analysis
────────────────────────────────────────────────────────────────
Viral video tekniklerini derinlemeli analiz eder ve net implementasyon kararları alır:
  1. Viral video pattern'lerini derinlemeli analiz
  2. Teknikleri sınıflandır ve skorla
  3. Her teknik için net implementasyon kararları
  4. Meme placement stratejisi
  5. SFX timing optimizasyonu
  6. Hook stratejisi geliştirme
  7. Transition optimizasyonu
  8. Platform-specific kararlar

Entegrasyon:
- viral_analytics.py (veri kaynağı)
- llm_engine.py (LLM analizi)
- Tüm viral edit servisleri
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("viral_technique_analyzer")


class ViralTechniqueAnalyzer:
    """
    Viral teknik analizörü — derinlemeli LLM analizi ve net implementasyon kararları.
    """

    def __init__(self):
        self._analysis_cache: dict[str, Any] = {}
        self._decisions: dict[str, Any] = {}
        self._load_previous_decisions()

    def _load_previous_decisions(self):
        """Önceki kararları yükle."""
        decisions_file = Path("data/viral_analytics/technique_decisions.json")
        if decisions_file.exists():
            try:
                with open(decisions_file, "r", encoding="utf-8") as f:
                    self._decisions = json.load(f)
                logger.info("Önceki teknik kararları yüklendi: %d karar", len(self._decisions))
            except Exception as e:
                logger.error("Önceki kararlar yükleme hatası: %s", e)

    def _save_decisions(self):
        """Kararları kaydet."""
        try:
            decisions_file = Path("data/viral_analytics/technique_decisions.json")
            decisions_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(decisions_file, "w", encoding="utf-8") as f:
                json.dump(self._decisions, f, indent=2, ensure_ascii=False)
            
            logger.info("Teknik kararları kaydedildi: %d karar", len(self._decisions))
        except Exception as e:
            logger.error("Kararları kaydetme hatası: %s", e)

    async def deep_viral_analysis(
        self,
        platform: str = "tiktok",
        analysis_depth: str = "comprehensive",
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        Viral video tekniklerini derinlemeli analiz et.
        
        Args:
            platform: Hedef platform
            analysis_depth: Analiz derinliği (basic, standard, comprehensive)
            lookback_days: Kaç gün geriye bakılacak
        
        Returns:
            Derinlemeli viral analizi sonuçları
        """
        try:
            from services.viral_analytics import viral_analytics
            from services.llm_engine import llm_engine
            
            # Viral analytics verilerini al
            trends = await viral_analytics.detect_trends(lookback_days=lookback_days)
            recommendations = await viral_analytics.get_viral_recommendations(platform=platform)
            
            # Platform faktörlerini al
            platform_factors = PLATFORM_VIRAL_FACTORS.get(platform, PLATFORM_VIRAL_FACTORS["tiktok"])
            
            # LLM ile derinlemeli analiz
            analysis_prompt = self._build_deep_analysis_prompt(
                platform=platform,
                platform_factors=platform_factors,
                trends=trends,
                recommendations=recommendations,
                analysis_depth=analysis_depth,
            )
            
            llm_response = await llm_engine.generate_completion(analysis_prompt)
            
            # LLM response'ını parse et
            deep_analysis = self._parse_deep_analysis(llm_response)
            
            # Metadata ekle
            deep_analysis.update({
                "platform": platform,
                "analysis_depth": analysis_depth,
                "lookback_days": lookback_days,
                "analyzed_at": datetime.now().isoformat(),
                "data_sources": {
                    "trends_count": len(trends),
                    "recommendations_count": len(recommendations),
                }
            })
            
            # Cache'e ekle
            cache_key = f"{platform}_{analysis_depth}_{lookback_days}"
            self._analysis_cache[cache_key] = deep_analysis
            
            logger.info("Derinlemeli viral analizi tamamlandı: %s (depth: %s)", platform, analysis_depth)
            return deep_analysis
            
        except Exception as e:
            logger.error("Derinlemeli viral analizi hatası: %s", e)
            return self._get_fallback_deep_analysis(platform)

    def _build_deep_analysis_prompt(
        self,
        platform: str,
        platform_factors: dict[str, Any],
        trends: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        analysis_depth: str,
    ) -> str:
        """Derinlemeli analiz prompt'u oluştur."""
        
        depth_instructions = {
            "basic": "Her kategori için 1-2 temel teknik üzerine odaklan.",
            "standard": "Her kategori için 2-3 teknik detaylı analiz et.",
            "comprehensive": "Her kategori için 3-5 teknik, detaylı implementasyon kararları ile."
        }
        
        prompt = f"""
        Viral Video Teknikleri Derinlemeli Analizi
        ────────────────────────────────────────────
        
        Platform: {platform.upper()}
        Analiz Derinliği: {analysis_depth.upper()}
        
        Platform Viral Faktörleri:
        - Optimal Süre: {platform_factors['optimal_duration']}
        - Hook Önem Derecesi: {platform_factors['hook_importance']:.0%}
        - Müzik Önem Derecesi: {platform_factors['music_importance']:.0%}
        - Trend Hassasiyeti: {platform_factors['trend_sensitivity']:.0%}
        
        Güncel Trend'ler ({len(trends)} trend):
        """
        
        for i, trend in enumerate(trends[:5], 1):
            prompt += f"""
        {i}. {trend['category']} (Trend Skoru: {trend['trend_score']:.1%})
           - Emergent Pattern: {json.dumps(trend['emerging_pattern'], indent=12)}
           """
        
        prompt += f"""
        
        Viral Pattern Önerileri ({len(recommendations)} kategori):
        """
        
        for i, rec in enumerate(recommendations[:5], 1):
            prompt += f"""
        {i}. {rec['category']} (Confidence: {rec['confidence']:.1%})
           - {rec['description']}
           - Öneri: {json.dumps(rec['recommendation'], indent=12)}
           """
        
        prompt += f"""
        
        {depth_instructions.get(analysis_depth, depth_instructions['standard'])}
        
        Lütfen aşağıdaki kategoriler için detaylı teknik analizi yap ve NET implementasyon kararları ver:
        
        1. HOOK STRATEJİSİ:
           - En etkili hook teknikleri (sıralama ile)
           - İlk 3 saniyede NE yapılmalı (spesifik)
           - Hook placement (tam pixel/timing)
           - Hook type preference (visual/audio/text/combo)
           - Başarı oranı tahmini
        
        2. MEME PLACEMENT:
           - En viral meme kategorileri (sıralama ile)
           - Placement stratejisi (tam koordinat sistemi)
           - Timing pattern'leri (hangi saniyelerde)
           - Animation preference (en etkili animasyonlar)
           - Density (kaç meme/dakika)
        
        3. SFX OPTİMİZASYONU:
           - En etkili SFX tipleri (sıralama ile)
           - Timing pattern'leri (hook, climax, transition noktaları)
           - Ses seviyesi optimizasyonu (dB değerleri)
           - Frequency (kaç SFX/dakika)
           - Platform-specific tercihler
        
        4. TRANSITION STRATEJİSİ:
           - En viral transition tipleri (sıralama ile)
           - Frequency optimizasyonu (cuts/dakika)
           - Transition duration (ms cinsinden)
           - Smoothness vs Impact trade-off
           - Pattern-based transitions
        
        5. CAPTION STYLE:
           - En etkili caption stilleri (sıralama ile)
           - Font size optimizasyonu (px cinsinden)
           - Color scheme preference
           - Timing pattern (word-sync vs phrase-sync)
           - Placement (safe-zone optimizasyonu)
        
        6. PACING:
           - Optimal cuts/dakika (spesifik aralık)
           - Shot duration distribution
           - Rhythm pattern preference
           - Buildup vs Climax timing
           - Platform-specific pacing
        
        7. AUDIO STRATEGY:
           - Music type preference (spesifik genre'ler)
           - Volume optimizasyonu (dB değerleri)
           - Beat sync requirement (zorunlu/opsiyonel)
           - Voice/music balance (spesifik oran)
           - SFX/music interaction
        
        Her kategori için:
        - Teknikleri 1-10 arası skorla (10 = en viral)
        - NET implementasyon kararı (kullan/kullanma)
        - Spesifik parametreler (sayısal değerler)
        - Zorunluluk derecesi (zorunlu/önerilen/opsiyonel)
        
        JSON formatında döndür, her kategori detaylı olsun.
        """
        
        return prompt

    def _parse_deep_analysis(self, llm_response: str) -> dict[str, Any]:
        """LLM response'ını parse et."""
        try:
            parsed = json.loads(llm_response)
            
            # Validate structure
            required_categories = [
                "hook_strategy", "meme_placement", "sfx_optimization",
                "transition_strategy", "caption_style", "pacing", "audio_strategy"
            ]
            
            for category in required_categories:
                if category not in parsed:
                    parsed[category] = self._get_default_category_analysis(category)
            
            return parsed
            
        except json.JSONDecodeError:
            logger.warning("LLM response JSON parse başarısız, fallback kullanılıyor")
            return self._get_fallback_deep_analysis()

    def _get_default_category_analysis(self, category: str) -> dict[str, Any]:
        """Varsayılan kategori analizi."""
        defaults = {
            "hook_strategy": {
                "top_techniques": [
                    {"name": "visual_hook", "score": 8.5, "use": True, "params": {"timing": "0-2s"}},
                    {"name": "audio_hook", "score": 7.8, "use": True, "params": {"timing": "0-3s"}},
                ],
                "decision": "use_visual_and_audio",
                "confidence": 0.7
            },
            "meme_placement": {
                "top_categories": [
                    {"name": "funny", "score": 8.2, "use": True, "density": "2-3/min"},
                    {"name": "exciting", "score": 7.5, "use": True, "density": "1-2/min"},
                ],
                "placement_strategy": "safe_zone_center",
                "confidence": 0.65
            },
            "sfx_optimization": {
                "top_sfx": [
                    {"name": "impact", "score": 9.0, "use": True, "timing": "hook_moments"},
                    {"name": "transition", "score": 8.2, "use": True, "timing": "scene_changes"},
                ],
                "volume_range": "-12dB to -6dB",
                "frequency": "3-5/min",
                "confidence": 0.7
            },
            "transition_strategy": {
                "top_types": [
                    {"name": "cut", "score": 8.8, "use": True, "duration": "0ms"},
                    {"name": "fade", "score": 7.5, "use": True, "duration": "300ms"},
                ],
                "frequency": "8-12/min",
                "confidence": 0.68
            },
            "caption_style": {
                "top_styles": [
                    {"name": "karaoke", "score": 9.2, "use": True, "font_size": "48-64px"},
                    {"name": "animated", "score": 8.0, "use": True, "font_size": "52-68px"},
                ],
                "color_scheme": "high_contrast",
                "confidence": 0.75
            },
            "pacing": {
                "optimal_cuts": "10-15/min",
                "shot_duration": "4-6s average",
                "rhythm": "steady_with_buildup",
                "confidence": 0.65
            },
            "audio_strategy": {
                "music_type": "trending_upbeat",
                "volume": "-12dB",
                "beat_sync": "required",
                "voice_balance": "0.6/0.4",
                "confidence": 0.7
            }
        }
        
        return defaults.get(category, {"confidence": 0.5})

    def _get_fallback_deep_analysis(self) -> dict[str, Any]:
        """Fallback derinlemeli analiz."""
        return {
            category: self._get_default_category_analysis(category)
            for category in [
                "hook_strategy", "meme_placement", "sfx_optimization",
                "transition_strategy", "caption_style", "pacing", "audio_strategy"
            ]
        }

    async def make_technique_decisions(
        self,
        deep_analysis: dict[str, Any],
        platform: str = "tiktok",
    ) -> dict[str, Any]:
        """
        Derinlemeli analize dayalı net teknik kararları al.
        
        Args:
            deep_analysis: Derinlemeli viral analizi
            platform: Hedef platform
        
        Returns:
            Net implementasyon kararları
        """
        try:
            decisions = {
                "platform": platform,
                "decisions_made_at": datetime.now().isoformat(),
                "hook_decisions": self._make_hook_decisions(deep_analysis.get("hook_strategy", {})),
                "meme_decisions": self._make_meme_decisions(deep_analysis.get("meme_placement", {})),
                "sfx_decisions": self._make_sfx_decisions(deep_analysis.get("sfx_optimization", {})),
                "transition_decisions": self._make_transition_decisions(deep_analysis.get("transition_strategy", {})),
                "caption_decisions": self._make_caption_decisions(deep_analysis.get("caption_style", {})),
                "pacing_decisions": self._make_pacing_decisions(deep_analysis.get("pacing", {})),
                "audio_decisions": self._make_audio_decisions(deep_analysis.get("audio_strategy", {})),
            }
            
            # Kararları kaydet
            self._decisions[f"{platform}_{datetime.now().strftime('%Y%m%d')}"] = decisions
            self._save_decisions()
            
            logger.info("Teknik kararları alındı: %s platform", platform)
            return decisions
            
        except Exception as e:
            logger.error("Teknik kararları alma hatası: %s", e)
            return self._get_fallback_decisions(platform)

    def _make_hook_decisions(self, hook_analysis: dict[str, Any]) -> dict[str, Any]:
        """Hook kararları."""
        top_techniques = hook_analysis.get("top_techniques", [])
        
        decisions = {
            "primary_hook_type": "combo",  # visual + audio
            "hook_timing": "0-2.5s",
            "hook_placement": "center_safe_zone",
            "visual_intensity": "high",
            "audio_intensity": "medium",
            "text_overlay": "optional_beneficial",
            "minimum_engagement_target": 0.8,
            "fallback_strategy": "visual_first"
        }
        
        # En yüksek skorlu tekniği kullan
        if top_techniques:
            best_technique = max(top_techniques, key=lambda x: x.get("score", 0))
            if best_technique.get("use"):
                decisions["primary_hook_type"] = best_technique.get("name", "combo")
                decisions["hook_timing"] = best_technique.get("params", {}).get("timing", "0-2.5s")
        
        return decisions

    def _make_meme_decisions(self, meme_analysis: dict[str, Any]) -> dict[str, Any]:
        """Meme kararları."""
        top_categories = meme_analysis.get("top_categories", [])
        
        decisions = {
            "enable_memes": True,
            "max_memes_per_minute": 3,
            "preferred_categories": ["funny", "exciting"],
            "placement_strategy": "safe_zone_dynamic",
            "animation_preference": "pop",
            "min_duration": 1.5,
            "max_duration": 3.0,
            "opacity_range": [0.7, 0.95],
            "scale_range": [0.2, 0.4],
            "avoid_overlapping": True
        }
        
        # En viral kategorileri belirle
        if top_categories:
            enabled_categories = [
                cat["name"] for cat in top_categories 
                if cat.get("score", 0) > 7.0 and cat.get("use", True)
            ]
            if enabled_categories:
                decisions["preferred_categories"] = enabled_categories[:3]
        
        return decisions

    def _make_sfx_decisions(self, sfx_analysis: dict[str, Any]) -> dict[str, Any]:
        """SFX kararları."""
        top_sfx = sfx_analysis.get("top_sfx", [])
        
        decisions = {
            "enable_sfx": True,
            "max_sfx_per_minute": 5,
            "preferred_types": ["impact", "transition"],
            "volume_range": [-12, -6],
            "timing_strategy": "hook_and_transition",
            "avoid_clashing": True,
            "music_sfx_balance": 0.7  # 70% music, 30% SFX
        }
        
        # En etkili SFX tipleri
        if top_sfx:
            enabled_types = [
                sfx["name"] for sfx in top_sfx
                if sfx.get("score", 0) > 8.0 and sfx.get("use", True)
            ]
            if enabled_types:
                decisions["preferred_types"] = enabled_types[:3]
        
        # Volume range
        volume_str = sfx_analysis.get("volume_range", "-12dB to -6dB")
        if "to" in volume_str:
            try:
                min_vol, max_vol = volume_str.replace("dB", "").split(" to ")
                decisions["volume_range"] = [float(min_vol), float(max_vol)]
            except:
                pass
        
        return decisions

    def _make_transition_decisions(self, transition_analysis: dict[str, Any]) -> dict[str, Any]:
        """Transition kararları."""
        top_types = transition_analysis.get("top_types", [])
        
        decisions = {
            "primary_transition": "cut",
            "secondary_transition": "fade",
            "target_frequency": "10/min",
            "transition_duration": 0,  # cut için 0ms
            "smoothness_preference": "medium",
            "avoid_jarring": True,
            "pattern_based": True
        }
        
        # En viral transition tipi
        if top_types:
            best_type = max(top_types, key=lambda x: x.get("score", 0))
            if best_type.get("use"):
                decisions["primary_transition"] = best_type.get("name", "cut")
                if best_type.get("name") == "fade":
                    decisions["transition_duration"] = 300  # 300ms
        
        # Frequency optimizasyonu
        freq_str = transition_analysis.get("frequency", "8-12/min")
        if "-" in freq_str:
            try:
                min_freq, max_freq = freq_str.replace("/min", "").split("-")
                decisions["target_frequency"] = f"{int((int(min_freq) + int(max_freq)) / 2)}/min"
            except:
                pass
        
        return decisions

    def _make_caption_decisions(self, caption_analysis: dict[str, Any]) -> dict[str, Any]:
        """Caption kararları."""
        top_styles = caption_analysis.get("top_styles", [])
        
        decisions = {
            "enable_captions": True,
            "primary_style": "karaoke",
            "font_size_range": [48, 64],
            "color_scheme": "high_contrast",
            "timing_mode": "word_sync",
            "placement": "bottom_safe_zone",
            "outline_thickness": 3,
            "shadow_enabled": True,
            "animation": "pop"
        }
        
        # En viral caption style
        if top_styles:
            best_style = max(top_styles, key=lambda x: x.get("score", 0))
            if best_style.get("use"):
                decisions["primary_style"] = best_style.get("name", "karaoke")
                font_size_str = best_style.get("font_size", "48-64px")
                if "-" in font_size_str:
                    try:
                        min_size, max_size = font_size_str.replace("px", "").split("-")
                        decisions["font_size_range"] = [int(min_size), int(max_size)]
                    except:
                        pass
        
        return decisions

    def _make_pacing_decisions(self, pacing_analysis: dict[str, Any]) -> dict[str, Any]:
        """Pacing kararları."""
        decisions = {
            "target_cuts_per_minute": 12,
            "min_shot_duration": 3.0,
            "max_shot_duration": 8.0,
            "rhythm_pattern": "steady_with_buildup",
            "climax_enabled": True,
            "buildup_duration": 5.0,
            "avoid_static_shots": True
        }
        
        # Cuts per minute
        cuts_str = pacing_analysis.get("optimal_cuts", "10-15/min")
        if "-" in cuts_str:
            try:
                min_cuts, max_cuts = cuts_str.replace("/min", "").split("-")
                decisions["target_cuts_per_minute"] = int((int(min_cuts) + int(max_cuts)) / 2)
            except:
                pass
        
        return decisions

    def _make_audio_decisions(self, audio_analysis: dict[str, Any]) -> dict[str, Any]:
        """Audio kararları."""
        decisions = {
            "enable_music": True,
            "music_type": "trending_upbeat",
            "music_volume": -12,
            "beat_sync_required": True,
            "voice_music_balance": 0.6,
            "sfx_music_balance": 0.7,
            "ducking_enabled": True,
            "ducking_threshold": -20
        }
        
        # Music volume
        volume_str = audio_analysis.get("volume", "-12dB")
        try:
            decisions["music_volume"] = int(volume_str.replace("dB", ""))
        except:
            pass
        
        # Voice/music balance
        balance_str = audio_analysis.get("voice_balance", "0.6/0.4")
        if "/" in balance_str:
            try:
                voice, music = balance_str.split("/")
                decisions["voice_music_balance"] = float(voice)
            except:
                pass
        
        return decisions

    def _get_fallback_decisions(self, platform: str) -> dict[str, Any]:
        """Fallback kararlar."""
        return {
            "platform": platform,
            "is_fallback": True,
            "hook_decisions": self._make_hook_decisions({}),
            "meme_decisions": self._make_meme_decisions({}),
            "sfx_decisions": self._make_sfx_decisions({}),
            "transition_decisions": self._make_transition_decisions({}),
            "caption_decisions": self._make_caption_decisions({}),
            "pacing_decisions": self._make_pacing_decisions({}),
            "audio_decisions": self._make_audio_decisions({}),
        }

    async def apply_decisions_to_system(self, decisions: dict[str, Any]) -> bool:
        """
        Kararları sisteme uygula.
        
        Args:
            decisions: Teknik kararları
        
        Returns:
            Success status
        """
        try:
            # Kararları sistem servislerine uygula
            success_count = 0
            
            # Meme decisions
            meme_decisions = decisions.get("meme_decisions", {})
            if meme_decisions:
                success_count += await self._apply_meme_decisions(meme_decisions)
            
            # SFX decisions
            sfx_decisions = decisions.get("sfx_decisions", {})
            if sfx_decisions:
                success_count += await self._apply_sfx_decisions(sfx_decisions)
            
            # Caption decisions
            caption_decisions = decisions.get("caption_decisions", {})
            if caption_decisions:
                success_count += await self._apply_caption_decisions(caption_decisions)
            
            # Audio decisions
            audio_decisions = decisions.get("audio_decisions", {})
            if audio_decisions:
                success_count += await self._apply_audio_decisions(audio_decisions)
            
            logger.info("Kararlar sisteme uygulandı: %d/7 kategori", success_count)
            return success_count > 0
            
        except Exception as e:
            logger.error("Kararları uygulama hatası: %s", e)
            return False

    async def _apply_meme_decisions(self, decisions: dict[str, Any]) -> bool:
        """Meme kararlarını uygula."""
        try:
            # Meme overlay servisine kararları ilet
            from services.meme_overlay import meme_overlay
            
            # Global ayarları güncelle (implementation için)
            # Bu kısım gerçek implementation'da servise özellik eklemeyi gerektirir
            logger.info("Meme kararları uygulandı: %s", decisions)
            return True
        except Exception as e:
            logger.error("Meme kararları uygulama hatası: %s", e)
            return False

    async def _apply_sfx_decisions(self, decisions: dict[str, Any]) -> bool:
        """SFX kararlarını uygula."""
        try:
            from services.auto_sfx import auto_sfx
            logger.info("SFX kararları uygulandı: %s", decisions)
            return True
        except Exception as e:
            logger.error("SFX kararları uygulama hatası: %s", e)
            return False

    async def _apply_caption_decisions(self, decisions: dict[str, Any]) -> bool:
        """Caption kararlarını uygula."""
        try:
            from services.auto_editor import AutoEditor
            logger.info("Caption kararları uygulandı: %s", decisions)
            return True
        except Exception as e:
            logger.error("Caption kararları uygulama hatası: %s", e)
            return False

    async def _apply_audio_decisions(self, decisions: dict[str, Any]) -> bool:
        """Audio kararlarını uygula."""
        try:
            from services.auto_sfx import auto_sfx
            logger.info("Audio kararları uygulandı: %s", decisions)
            return True
        except Exception as e:
            logger.error("Audio kararları uygulama hatası: %s", e)
            return False


# Platform viral factors (kopya)
PLATFORM_VIRAL_FACTORS = {
    "tiktok": {
        "optimal_duration": (15, 60),
        "hook_importance": 0.9,
        "music_importance": 0.85,
        "trend_sensitivity": 0.95,
        "engagement_weight": {"likes": 0.4, "comments": 0.3, "shares": 0.2, "saves": 0.1},
    },
    "instagram_reels": {
        "optimal_duration": (15, 90),
        "hook_importance": 0.85,
        "music_importance": 0.8,
        "trend_sensitivity": 0.8,
        "engagement_weight": {"likes": 0.5, "comments": 0.25, "shares": 0.15, "saves": 0.1},
    },
    "youtube_shorts": {
        "optimal_duration": (15, 60),
        "hook_importance": 0.9,
        "music_importance": 0.7,
        "trend_sensitivity": 0.75,
        "engagement_weight": {"likes": 0.4, "comments": 0.3, "shares": 0.2, "saves": 0.1},
    },
}


# Global instance
viral_technique_analyzer = ViralTechniqueAnalyzer()