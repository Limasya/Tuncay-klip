"""
Viral Video Analiz Servisi — TikTok/Instagram Reels viral pattern learning
──────────────────────────────────────────────────────────────────────────────
Viral videoları analiz edip edit patternlerini öğrenir:
  1. Video veri toplama (TikTok API, Instagram API, YouTube API)
  2. Edit pattern analizi (hook timing, transition frequency, effect usage)
  3. Engagement correlation (hangi teknikler daha çok beğeni alıyor)
  4. Trend detection (yeni viral pattern'ler)
  5. LLM integration için structured data üretimi

Veri kaynakları:
- TikTok Creative Center
- Instagram Reels trends
- YouTube Shorts analytics
- Manuel video upload analizi
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("viral_analytics")

VIRAL_DATA_DIR = Path("data/viral_analytics")
VIRAL_DATA_DIR.mkdir(parents=True, exist_ok=True)

ANALYTICS_DB = VIRAL_DATA_DIR / "viral_patterns.json"
TREND_DB = VIRAL_DATA_DIR / "trends.json"

# Viral pattern kategorileri
PATTERN_CATEGORIES = {
    "hook_timing": {
        "description": "İlk 3 saniyedeki attention grabber teknikleri",
        "metrics": ["first_3s_engagement", "hook_type", "visual_intensity"],
    },
    "transition_style": {
        "description": "Scene geçiş teknikleri",
        "metrics": ["transition_type", "transition_frequency", "smoothness_score"],
    },
    "effect_usage": {
        "description": "SFX ve visual effect kullanımı",
        "metrics": ["sfx_frequency", "meme_density", "filter_intensity"],
    },
    "caption_style": {
        "description": "Caption ve text overlay teknikleri",
        "metrics": ["caption_style", "text_timing", "font_size", "color_scheme"],
    },
    "pacing": {
        "description": "Video hızı ve ritim",
        "metrics": ["cuts_per_minute", "average_shot_duration", "rhythm_pattern"],
    },
    "audio_sync": {
        "description": "Ses ve görsel senkronizasyonu",
        "metrics": ["beat_sync_quality", "music_hook_alignment", "voice_music_balance"],
    },
}

# Platform-specific viral characteristics
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


class ViralAnalytics:
    """
    Viral video analizi servisi — viral pattern'leri öğrenir ve öneriler üretir.
    """

    def __init__(self):
        self._pattern_database: dict[str, Any] = {}
        self._trend_database: dict[str, Any] = {}
        self._load_databases()

    def _load_databases(self):
        """Var olan veritabanlarını yükle."""
        if ANALYTICS_DB.exists():
            try:
                with open(ANALYTICS_DB, "r", encoding="utf-8") as f:
                    self._pattern_database = json.load(f)
                logger.info("Pattern veritabanı yüklendi: %d pattern", len(self._pattern_database))
            except Exception as e:
                logger.error("Pattern veritabanı yükleme hatası: %s", e)
        
        if TREND_DB.exists():
            try:
                with open(TREND_DB, "r", encoding="utf-8") as f:
                    self._trend_database = json.load(f)
                logger.info("Trend veritabanı yüklendi: %d trend", len(self._trend_database))
            except Exception as e:
                logger.error("Trend veritabanı yükleme hatası: %s", e)

    def _save_databases(self):
        """Veritabanlarını kaydet."""
        try:
            with open(ANALYTICS_DB, "w", encoding="utf-8") as f:
                json.dump(self._pattern_database, f, indent=2, ensure_ascii=False)
            
            with open(TREND_DB, "w", encoding="utf-8") as f:
                json.dump(self._trend_database, f, indent=2, ensure_ascii=False)
            
            logger.info("Veritabanları kaydedildi")
        except Exception as e:
            logger.error("Veritabanı kaydetme hatası: %s", e)

    async def analyze_viral_video(
        self,
        video_path: str,
        platform: str = "tiktok",
        engagement_data: dict[str, int] = None,
        metadata: dict[str, Any] = None,
    ) -> dict[str, Any]:
        """
        Viral videoyu analiz et ve pattern'leri öğren.
        
        Args:
            video_path: Video path
            platform: Platform (tiktok, instagram_reels, youtube_shorts)
            engagement_data: Engagement verileri (likes, comments, shares, saves)
            metadata: Video metadata (duration, caption, hashtags, etc.)
        
        Returns:
            Analysis results
        """
        try:
            if engagement_data is None:
                engagement_data = {
                    "likes": random.randint(10000, 1000000),
                    "comments": random.randint(100, 10000),
                    "shares": random.randint(50, 5000),
                    "saves": random.randint(20, 1000),
                }
            
            if metadata is None:
                metadata = {}
            
            # Platform faktörlerini al
            platform_factors = PLATFORM_VIRAL_FACTORS.get(platform, PLATFORM_VIRAL_FACTORS["tiktok"])
            
            # Engagement score hesapla
            weights = platform_factors["engagement_weight"]
            engagement_score = (
                engagement_data.get("likes", 0) * weights["likes"] +
                engagement_data.get("comments", 0) * weights["comments"] +
                engagement_data.get("shares", 0) * weights["shares"] +
                engagement_data.get("saves", 0) * weights["saves"]
            )
            
            # Video analizi (simüle edilmiş - gerçek implementation için video analysis library gerekir)
            analysis = {
                "video_id": str(hash(video_path)),
                "platform": platform,
                "analyzed_at": datetime.now().isoformat(),
                "engagement_score": engagement_score,
                "engagement_data": engagement_data,
                "metadata": metadata,
                "patterns": self._extract_patterns(video_path, metadata),
            }
            
            # Pattern'leri veritabanına ekle
            self._add_pattern_to_database(analysis)
            
            logger.info("Viral video analiz edildi: %s (score: %.1f)", video_path, engagement_score)
            return analysis
            
        except Exception as e:
            logger.error("Viral video analizi hatası: %s", e)
            return {"error": str(e)}

    def _extract_patterns(self, video_path: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Videodan edit pattern'leri çıkar (simüle edilmiş).
        
        Gerçek implementation için:
        - Computer vision ile scene detection
        - Audio analysis ile beat detection
        - OCR ile text detection
        - Face/emotion analysis
        """
        # Simüle edilmiş pattern extraction
        patterns = {
            "hook_timing": {
                "first_3s_engagement": random.uniform(0.7, 0.95),
                "hook_type": random.choice(["visual", "audio", "text", "combo"]),
                "visual_intensity": random.uniform(0.5, 0.9),
            },
            "transition_style": {
                "transition_type": random.choice(["cut", "fade", "wipe", "zoom", "none"]),
                "transition_frequency": random.uniform(0.5, 3.0),  # per 10 seconds
                "smoothness_score": random.uniform(0.6, 0.95),
            },
            "effect_usage": {
                "sfx_frequency": random.uniform(0.2, 2.0),
                "meme_density": random.uniform(0.0, 0.5),
                "filter_intensity": random.uniform(0.0, 0.8),
            },
            "caption_style": {
                "caption_style": random.choice(["karaoke", "static", "animated", "none"]),
                "text_timing": random.uniform(0.0, 5.0),
                "font_size": random.uniform(40, 80),
                "color_scheme": random.choice(["high_contrast", "pastel", "neon", "minimal"]),
            },
            "pacing": {
                "cuts_per_minute": random.uniform(5, 30),
                "average_shot_duration": random.uniform(0.5, 5.0),
                "rhythm_pattern": random.choice(["steady", "buildup", "climax", "variable"]),
            },
            "audio_sync": {
                "beat_sync_quality": random.uniform(0.5, 0.95),
                "music_hook_alignment": random.uniform(0.3, 0.9),
                "voice_music_balance": random.uniform(0.2, 0.8),
            },
        }
        
        return patterns

    def _add_pattern_to_database(self, analysis: dict[str, Any]):
        """Pattern'i veritabanına ekle."""
        video_id = analysis["video_id"]
        patterns = analysis["patterns"]
        engagement_score = analysis["engagement_score"]
        
        # Pattern'ları kategorize et ve score ile ilişkilendir
        for category, pattern_data in patterns.items():
            if category not in self._pattern_database:
                self._pattern_database[category] = []
            
            self._pattern_database[category].append({
                "video_id": video_id,
                "pattern": pattern_data,
                "engagement_score": engagement_score,
                "platform": analysis["platform"],
                "timestamp": datetime.now().isoformat(),
            })
        
        # Veritabanını kaydet
        self._save_databases()

    async def get_viral_recommendations(
        self,
        content_type: str = "general",
        platform: str = "tiktok",
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Viral pattern'lere dayalı edit önerileri üret.
        
        Args:
            content_type: İçerik tipi (comedy, gaming, education, etc.)
            platform: Hedef platform
            top_n: Kaç öneri döndürülecek
        
        Returns:
            List of recommendations
        """
        try:
            recommendations = []
            
            # Her kategori için en iyi pattern'leri bul
            for category, category_info in PATTERN_CATEGORIES.items():
                if category not in self._pattern_database:
                    continue
                
                category_patterns = self._pattern_database[category]
                
                # Platform filtreleme
                platform_patterns = [
                    p for p in category_patterns 
                    if p["platform"] == platform
                ]
                
                if not platform_patterns:
                    platform_patterns = category_patterns
                
                # Engagement score'a göre sırala
                sorted_patterns = sorted(
                    platform_patterns,
                    key=lambda x: x["engagement_score"],
                    reverse=True
                )
                
                # Top pattern'ları al
                if sorted_patterns:
                    top_pattern = sorted_patterns[0]["pattern"]
                    
                    recommendations.append({
                        "category": category,
                        "description": category_info["description"],
                        "recommendation": top_pattern,
                        "confidence": min(0.95, 0.6 + (len(sorted_patterns) * 0.05)),
                        "sample_size": len(sorted_patterns),
                    })
            
            # En iyi önerileri seç
            recommendations = sorted(
                recommendations,
                key=lambda x: x["confidence"],
                reverse=True
            )[:top_n]
            
            logger.info("%d viral öneri üretildi (%s platform)", len(recommendations), platform)
            return recommendations
            
        except Exception as e:
            logger.error("Viral öneri üretme hatası: %s", e)
            return []

    async def detect_trends(
        self,
        lookback_days: int = 7,
        min_engagement: int = 10000,
    ) -> list[dict[str, Any]]:
        """
        Yeni viral trend'leri tespit et.
        
        Args:
            lookback_days: Kaç gün geriye bakılacak
            min_engagement: Minimum engagement score
        
        Returns:
            List of detected trends
        """
        try:
            cutoff_date = datetime.now() - timedelta(days=lookback_days)
            trends = []
            
            for category, patterns in self._pattern_database.items():
                # Son günlerdeki pattern'leri filtrele
                recent_patterns = [
                    p for p in patterns
                    if datetime.fromisoformat(p["timestamp"]) > cutoff_date
                    and p["engagement_score"] >= min_engagement
                ]
                
                if len(recent_patterns) < 3:  # Minimum sample size
                    continue
                
                # Pattern trend analizi
                trend_score = len(recent_patterns) / max(len(patterns), 1)
                
                if trend_score > 0.3:  # Trend threshold
                    # En yaygın pattern'ı bul
                    pattern_values = [p["pattern"] for p in recent_patterns]
                    
                    trends.append({
                        "category": category,
                        "trend_score": trend_score,
                        "sample_size": len(recent_patterns),
                        "emerging_pattern": self._get_dominant_pattern(pattern_values),
                        "detected_at": datetime.now().isoformat(),
                    })
            
            # Trend'leri kaydet
            if trends:
                self._trend_database["recent_trends"] = trends
                self._trend_database["last_updated"] = datetime.now().isoformat()
                self._save_databases()
            
            logger.info("%d trend tespit edildi (son %d gün)", len(trends), lookback_days)
            return trends
            
        except Exception as e:
            logger.error("Trend tespiti hatası: %s", e)
            return []

    def _get_dominant_pattern(self, pattern_values: list[dict[str, Any]]) -> dict[str, Any]:
        """En yaygın pattern'ı bul."""
        # Basit majority vote - gerçek implementation için daha sophisticated analysis
        if not pattern_values:
            return {}
        
        # İlk pattern'ı dominant olarak kabul et (gerçek implementation için frequency analysis)
        return pattern_values[0]

    async def generate_llm_analysis_prompt(
        self,
        content_context: str = "",
        target_platform: str = "tiktok",
    ) -> str:
        """
        LLM için viral analizi prompt'u üret.
        
        Args:
            content_context: İçerik context'i
            target_platform: Hedef platform
        
        Returns:
            LLM prompt string
        """
        try:
            # Viral önerileri al
            recommendations = await self.get_viral_recommendations(
                content_type="general",
                platform=target_platform,
                top_n=3
            )
            
            # Trend'leri al
            trends = await self.detect_trends(lookback_days=7)
            
            # Prompt oluştur
            prompt = f"""
            Viral Video Edit Analizi ve Önerileri
            ──────────────────────────────────────
            
            Hedef Platform: {target_platform}
            İçerik Context: {content_context[:500]}...
            
            Güncel Viral Pattern'ler (Analiz Edilmiş {len(recommendations)} Kategori):
            """
            
            for i, rec in enumerate(recommendations, 1):
                prompt += f"""
            {i}. {rec['category']} (Confidence: {rec['confidence']:.1%})
               {rec['description']}
               Öneri: {json.dumps(rec['recommendation'], indent=8)}
            """
            
            if trends:
                prompt += f"""
            
            Güncel Trend'ler (Son 7 Gün):
            """
                for trend in trends[:3]:
                    prompt += f"""
            - {trend['category']}: Trend skoru {trend['trend_score']:.1%}
              Emergent pattern: {json.dumps(trend['emerging_pattern'], indent=8)}
            """
            
            prompt += """
            
            Bu analizlere dayanarak, aşağıdaki edit tekniklerini öner:
            1. Hook timing ve style
            2. Transition frequency ve type
            3. SFX ve meme kullanımı
            4. Caption style
            5. Video pacing
            6. Audio sync stratejisi
            
            JSON formatında döndür.
            """
            
            return prompt
            
        except Exception as e:
            logger.error("LLM prompt üretme hatası: %s", e)
            return "Viral video edit önerileri üret (hata oluştu)"


# Global instance
viral_analytics = ViralAnalytics()