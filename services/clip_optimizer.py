"""
Clip Optimizer — Platforma Göre Klip Uzunluğu Optimizasyonu
────────────────────────────────────────────────────────────
FAZ-2.3: Her platform için ideal klip uzunluğunu belirleme ve otomatik kırpma.

Platform limitleri:
  - TikTok: 60s (ideal 15-30s)
  - Instagram Reels: 90s (ideal 15-30s)
  - YouTube Shorts: 60s (ideal 30-60s)
  - Kick: 60s (ideal 30-60s)
  - YouTube (normal): 300s

Her platform için:
  - Maksimum süre
  - İdeal süre aralığı
  - Önerilen kesim noktaları
  - Otomatik kırpma stratejisi
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("clip_optimizer")


# ── Platform Specifications ──

class PlatformSpec(BaseModel):
    """Platform clip specifications."""
    name: str
    max_duration: float  # saniye
    ideal_min: float     # ideal minimum süre
    ideal_max: float     # ideal maksimum süre
    aspect_ratio: str    # "9:16", "16:9", "1:1"
    width: int
    height: int
    fps: int = 30
    max_file_size_mb: float = 100.0
    supports_subtitles: bool = True
    supports_hashtags: bool = True
    caption_limit: int = 300  # karakter
    recommended_hashtags: int = 5


PLATFORM_SPECS: Dict[str, PlatformSpec] = {
    "tiktok": PlatformSpec(
        name="TikTok",
        max_duration=60.0,
        ideal_min=15.0,
        ideal_max=30.0,
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fps=30,
        max_file_size_mb=50.0,
        caption_limit=2200,
        recommended_hashtags=5,
    ),
    "instagram_reels": PlatformSpec(
        name="Instagram Reels",
        max_duration=90.0,
        ideal_min=15.0,
        ideal_max=30.0,
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fps=30,
        max_file_size_mb=100.0,
        caption_limit=2200,
        recommended_hashtags=10,
    ),
    "youtube_shorts": PlatformSpec(
        name="YouTube Shorts",
        max_duration=60.0,
        ideal_min=30.0,
        ideal_max=60.0,
        aspect_ratio="9:16",
        width=1080,
        height=1920,
        fps=30,
        max_file_size_mb=100.0,
        caption_limit=100,
        recommended_hashtags=3,
    ),
    "youtube": PlatformSpec(
        name="YouTube",
        max_duration=300.0,
        ideal_min=30.0,
        ideal_max=120.0,
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        fps=30,
        max_file_size_mb=500.0,
        caption_limit=5000,
        recommended_hashtags=15,
    ),
    "kick": PlatformSpec(
        name="Kick",
        max_duration=60.0,
        ideal_min=30.0,
        ideal_max=60.0,
        aspect_ratio="16:9",
        width=1920,
        height=1080,
        fps=30,
        max_file_size_mb=100.0,
        caption_limit=500,
        recommended_hashtags=5,
    ),
    "twitter": PlatformSpec(
        name="Twitter/X",
        max_duration=140.0,
        ideal_min=15.0,
        ideal_max=45.0,
        aspect_ratio="16:9",
        width=1280,
        height=720,
        fps=30,
        max_file_size_mb=512.0,
        caption_limit=280,
        recommended_hashtags=3,
    ),
}


# ── Cut Point Detection ──

class CutPoint(BaseModel):
    """Kırpma noktası önerisi."""
    time: float  # saniye
    score: float  # 0-1, ne kadar iyi bir kesim noktası
    reason: str = ""
    is_sentence_end: bool = False
    is_silence: bool = False
    is_scene_change: bool = False


# ── Clip Optimization Result ──

class OptimizedClip(BaseModel):
    """Optimize edilmiş klip sonucu."""
    platform: str
    start_time: float
    end_time: float
    duration: float
    width: int
    height: int
    needs_resize: bool = False
    needs_reencode: bool = False
    trim_start: float = 0.0  # kaynak videoya göre kırpma
    trim_end: float = 0.0
    quality_score: float = 0.0
    fit_score: float = 0.0  # platform ideal süresine ne kadar uygun
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ── Clip Optimizer ──

class ClipOptimizer:
    """
    Klip uzunluğunu platforma göre optimize et.
    """

    def __init__(self):
        self._platform_specs = PLATFORM_SPECS

    def get_platform_spec(self, platform: str) -> Optional[PlatformSpec]:
        """Platform spec'ini getir."""
        return self._platform_specs.get(platform.lower())

    def get_all_platforms(self) -> List[Dict[str, Any]]:
        """Tüm platform spec'lerini listele."""
        return [spec.model_dump() for spec in self._platform_specs.values()]

    def optimize_for_platform(
        self,
        video_duration: float,
        platform: str,
        transcript_words: Optional[List[Dict]] = None,
        cut_points: Optional[List[CutPoint]] = None,
        source_width: int = 1920,
        source_height: int = 1080,
    ) -> OptimizedClip:
        """
        Verilen videoyu belirli bir platform için optimize et.
        """
        spec = self._platform_specs.get(platform.lower())
        if not spec:
            return OptimizedClip(
                platform=platform,
                start_time=0,
                end_time=video_duration,
                duration=video_duration,
                width=source_width,
                height=source_height,
                warnings=[f"Bilinmeyen platform: {platform}"],
            )

        # İdeal süre hesapla
        ideal_duration = self._find_ideal_duration(
            video_duration, spec, transcript_words, cut_points
        )

        # Kesim noktalarını belirle
        start_time, end_time = self._compute_cut_boundaries(
            ideal_duration, spec, video_duration, cut_points, transcript_words
        )

        actual_duration = end_time - start_time

        # Boyut kontrolü
        needs_resize = (
            source_width != spec.width or source_height != spec.height
        )
        needs_reencode = needs_resize or actual_duration != video_duration

        # Uygunluk skoru
        fit_score = self._compute_fit_score(actual_duration, spec)

        # Uyarılar
        warnings = []
        if actual_duration > spec.max_duration:
            warnings.append(f"Süre fazla: {actual_duration:.1f}s > {spec.max_duration}s")
        if actual_duration < spec.ideal_min:
            warnings.append(f"Süre kısa: {actual_duration:.1f}s < {spec.ideal_min}s")

        return OptimizedClip(
            platform=platform,
            start_time=round(start_time, 3),
            end_time=round(end_time, 3),
            duration=round(actual_duration, 3),
            width=spec.width,
            height=spec.height,
            needs_resize=needs_resize,
            needs_reencode=needs_reencode,
            trim_start=round(start_time, 3),
            trim_end=round(video_duration - end_time, 3),
            quality_score=round(fit_score, 3),
            fit_score=round(fit_score, 3),
            warnings=warnings,
            metadata={
                "platform_label": spec.name,
                "aspect_ratio": spec.aspect_ratio,
                "ideal_range": f"{spec.ideal_min}-{spec.ideal_max}s",
                "max_duration": spec.max_duration,
            },
        )

    def optimize_for_all_platforms(
        self,
        video_duration: float,
        platforms: Optional[List[str]] = None,
        **kwargs,
    ) -> Dict[str, OptimizedClip]:
        """Birden fazla platform için optimize et."""
        target_platforms = platforms or list(self._platform_specs.keys())
        results = {}
        for platform in target_platforms:
            results[platform] = self.optimize_for_platform(
                video_duration, platform, **kwargs
            )
        return results

    def _find_ideal_duration(
        self,
        video_duration: float,
        spec: PlatformSpec,
        transcript_words: Optional[List[Dict]],
        cut_points: Optional[List[CutPoint]],
    ) -> float:
        """İdeal klip süresini hesapla."""
        # Video zaten ideal aralıksa olduğu gibi bırak
        if spec.ideal_min <= video_duration <= spec.ideal_max:
            return video_duration

        # Video çok uzunsa ideal maksimuma kırp
        if video_duration > spec.ideal_max:
            # Kesim noktaları varsa en iyi olanı seç
            if cut_points:
                best = max(cut_points, key=lambda c: c.score)
                # Kesim noktasından ideal süreyi hesapla
                return min(spec.ideal_max, video_duration - best.time)

            # Transcript varsa cümle sonuna göre kes
            if transcript_words:
                return self._find_sentence_end(
                    transcript_words, spec.ideal_max
                )

            return spec.ideal_max

        # Video çok kısaysa olduğu gibi bırak (uzatma yapamayız)
        return video_duration

    def _compute_cut_boundaries(
        self,
        target_duration: float,
        spec: PlatformSpec,
        video_duration: float,
        cut_points: Optional[List[CutPoint]],
        transcript_words: Optional[List[Dict]],
    ) -> Tuple[float, float]:
        """Kesim sınırlarını hesapla (start, end)."""
        if target_duration >= video_duration:
            return 0.0, video_duration

        # Kesim noktaları varsa en iyi başlangıç-bitiş çiftini seç
        if cut_points:
            best_start = 0.0
            best_end = video_duration
            best_score = -1

            for i, cp in enumerate(cut_points):
                # Bu noktadan başlayan bir klip
                end = min(cp.time + target_duration, video_duration)
                actual_dur = end - cp.time
                if actual_dur < spec.ideal_min:
                    continue

                score = cp.score
                if actual_dur <= spec.ideal_max:
                    score += 0.2

                if score > best_score:
                    best_score = score
                    best_start = cp.time
                    best_end = end

            if best_score > 0:
                return best_start, best_end

        # Transcript varsa cümle başlangıcından başlat
        if transcript_words:
            start = self._find_sentence_start(transcript_words)
            end = min(start + target_duration, video_duration)
            return start, end

        # Varsayılan: ortadan al
        start = max(0, (video_duration - target_duration) / 2)
        return start, start + target_duration

    def _find_sentence_end(
        self, words: List[Dict], max_duration: float
    ) -> float:
        """Transcript'ten cümle sonu bul."""
        if not words:
            return max_duration

        # Son max_duration saniyedeki kelimeler
        end_candidates = []
        for w in words:
            word_end = float(w.get("end", 0))
            if word_end <= max_duration:
                # Cümle sonu mu? Nokta, soru işareti, ünlem
                text = w.get("word", "").rstrip()
                if text and text[-1] in ".!?":
                    end_candidates.append(word_end)

        if end_candidates:
            return max(end_candidates)

        return max_duration

    def _find_sentence_start(self, words: List[Dict]) -> float:
        """Transcript'ten cümle başlangıcı bul."""
        if not words:
            return 0.0

        for w in words:
            text = w.get("word", "").strip()
            # Büyük harfle başlayan kelimeler genellikle cümle başlangıcı
            if text and text[0].isupper():
                return float(w.get("start", 0))

        return float(words[0].get("start", 0))

    def _compute_fit_score(self, duration: float, spec: PlatformSpec) -> float:
        """Platform ideal süresine uygunluk skoru."""
        if duration < spec.ideal_min:
            return max(0.0, duration / spec.ideal_min)
        if duration > spec.max_duration:
            return max(0.0, 1.0 - (duration - spec.max_duration) / spec.max_duration)
        if spec.ideal_min <= duration <= spec.ideal_max:
            return 1.0
        # Ideal ile max arasında
        return 1.0 - (duration - spec.ideal_max) / (spec.max_duration - spec.ideal_max) * 0.3


# Singleton
clip_optimizer = ClipOptimizer()
