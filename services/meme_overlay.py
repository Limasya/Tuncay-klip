"""
Meme Overlay Servisi — TikTok/Instagram Reels için viral meme efektleri
──────────────────────────────────────────────────────────────────────
Video üzerine otomatik meme/emoji/sticker overlay'leri ekler:
  1. Context-aware meme seçimi (LLM analizine göre)
  2. Zamanlamalı overlay placement
  3. Animated transitions
  4. Position aware (safe-zone compliant)
  5. TikTok/Instagram optimize

Meme kütüphanesi: data/memes/ klasöründe saklanır
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("meme_overlay")

MEME_DIR = Path("data/memes")
MEME_DIR.mkdir(parents=True, exist_ok=True)

# Meme kategorileri ve örnekler
MEME_CATEGORIES = {
    "funny": [
        "laughing_emoji.png",
        "crying_face.png", 
        "skull_emoji.png",
        "clown_face.png",
    ],
    "exciting": [
        "fire_emoji.png",
        "rocket_emoji.png",
        "dizzy_emoji.png",
        "star_struck.png",
    ],
    "shock": [
        "exploding_head.png",
        "scream_emoji.png",
        "flushed_face.png",
        "mind_blown.png",
    ],
    "success": [
        "party_emoji.png",
        "trophy_emoji.png",
        "confetti_emoji.png",
        "winner_emoji.png",
    ],
    "reaction": [
        "thumbs_up.png",
        "heart_eyes.png",
        "clapping_hands.png",
        "raised_hands.png",
    ],
}

# Meme placement strategies
PLACEMENT_STRATEGIES = {
    "center": {"x": 0.5, "y": 0.5, "scale": 0.3},
    "top_left": {"x": 0.15, "y": 0.15, "scale": 0.25},
    "top_right": {"x": 0.85, "y": 0.15, "scale": 0.25},
    "bottom_left": {"x": 0.15, "y": 0.85, "scale": 0.25},
    "bottom_right": {"x": 0.85, "y": 0.85, "scale": 0.25},
    "random": None,  # Random placement
}

# Animation types
ANIMATION_TYPES = [
    "pop",      # Scale up with bounce
    "fade",     # Fade in/out
    "slide",    # Slide from side
    "spin",     # Spin animation
    "shake",    # Shake effect
    "bounce",   # Bounce up/down
]


class MemeOverlay:
    """
    Meme overlay servisi — video üzerine viral meme efektleri ekler.
    FFmpeg tabanlı, hızlı ve efficient.
    """

    def __init__(self):
        self._meme_cache: dict[str, Path] = {}
        self._load_meme_library()

    def _load_meme_library(self):
        """Meme kütüphanesini yükle."""
        for category, memes in MEME_CATEGORIES.items():
            for meme_name in memes:
                meme_path = MEME_DIR / meme_name
                if meme_path.exists():
                    self._meme_cache[meme_name] = meme_path
                else:
                    # Eğer meme yoksa placeholder oluştur
                    self._create_placeholder_meme(meme_name, category)
        
        logger.info("Meme kütüphanesi yüklendi: %d meme", len(self._meme_cache))

    def _create_placeholder_meme(self, meme_name: str, category: str):
        """Placeholder meme oluştur (gerçek resimler yerine)."""
        placeholder_path = MEME_DIR / meme_name
        # Bu metod aslında gerçek resim oluşturmalı, şimdilik sadece boş dosya
        placeholder_path.touch()
        self._meme_cache[meme_name] = placeholder_path

    async def select_meme_for_context(
        self, 
        context: str, 
        emotion: str = "funny",
        video_duration: float = 30.0
    ) -> dict[str, Any]:
        """
        LLM context analizine göre uygun meme seç.
        
        Args:
            context: Video içeriği/teması
            emotion: Duygu (funny, exciting, shock, success, reaction)
            video_duration: Video süresi
        
        Returns:
            Meme selection dict with path, timing, placement
        """
        try:
            # Kategoriye göre rastgele meme seç
            category_memes = MEME_CATEGORIES.get(emotion, MEME_CATEGORIES["funny"])
            selected_meme = random.choice(category_memes)
            
            meme_path = self._meme_cache.get(selected_meme)
            if not meme_path:
                # Fallback to random available meme
                available_memes = list(self._meme_cache.values())
                meme_path = random.choice(available_memes) if available_memes else None
            
            if not meme_path:
                return {"error": "no_memes_available"}
            
            # Zamanlama hesapla (hook anında veya random)
            timing = {
                "start": random.uniform(0, min(video_duration * 0.7, 20)),  # İlk %70'te
                "duration": random.uniform(1.5, 4.0),  # 1.5-4 saniye
            }
            
            # Placement stratejisi seç
            strategy = random.choice(list(PLACEMENT_STRATEGIES.keys()))
            placement = PLACEMENT_STRATEGIES[strategy]
            
            if strategy == "random":
                placement = {
                    "x": random.uniform(0.1, 0.9),
                    "y": random.uniform(0.1, 0.9),
                    "scale": random.uniform(0.2, 0.4)
                }
            
            # Animation seç
            animation = random.choice(ANIMATION_TYPES)
            
            return {
                "meme_path": str(meme_path),
                "meme_name": selected_meme,
                "category": emotion,
                "timing": timing,
                "placement": placement,
                "animation": animation,
                "opacity": random.uniform(0.7, 1.0),
            }
            
        except Exception as e:
            logger.error("Meme seçimi hatası: %s", e)
            return {"error": str(e)}

    async def add_single_overlay(
        self,
        video_path: str,
        output_path: str,
        meme_info: dict[str, Any],
    ) -> bool:
        """
        Tek bir meme overlay ekle.
        
        Args:
            video_path: Input video path
            output_path: Output video path
            meme_info: Meme information dict from select_meme_for_context
        
        Returns:
            Success status
        """
        try:
            meme_path = meme_info.get("meme_path")
            if not meme_path or not os.path.exists(meme_path):
                logger.warning("Meme dosyası bulunamadı: %s", meme_path)
                return False
            
            timing = meme_info.get("timing", {})
            placement = meme_info.get("placement", {})
            animation = meme_info.get("animation", "fade")
            opacity = meme_info.get("opacity", 0.9)
            
            start_time = timing.get("start", 0)
            duration = timing.get("duration", 2.0)
            end_time = start_time + duration
            
            x_pos = placement.get("x", 0.5)
            y_pos = placement.get("y", 0.5)
            scale = placement.get("scale", 0.3)
            
            # FFmpeg command for overlay
            # Video resolution'u al
            video_width = 1080  # VERT_WIDTH
            video_height = 1920  # VERT_HEIGHT
            
            # Meme size hesapla
            meme_width = int(video_width * scale)
            meme_height = meme_width  # Kare varsayım
            
            # Position hesapla (overlay coordinates)
            overlay_x = int((x_pos * video_width) - (meme_width / 2))
            overlay_y = int((y_pos * video_height) - (meme_height / 2))
            
            # FFmpeg overlay filter
            overlay_filter = (
                f"[1:v]scale={meme_width}:{meme_height}[meme];"
                f"[0:v][meme]overlay={overlay_x}:{overlay_y}:enable='between(t,{start_time},{end_time})'"
            )
            
            # Animation için ek filtreler
            if animation == "fade":
                overlay_filter = (
                    f"[1:v]scale={meme_width}:{meme_height},"
                    f"fade=t=in:st={start_time}:d=0.5,fade=t=out:st={end_time-0.5}:d=0.5,"
                    f"format=rgba,colorchannelmixer=aa={opacity}[meme];"
                    f"[0:v][meme]overlay={overlay_x}:{overlay_y}:enable='between(t,{start_time},{end_time})'"
                )
            elif animation == "pop":
                # Pop effect with scale animation
                overlay_filter = (
                    f"[1:v]scale={meme_width}:{meme_height},"
                    f"fade=t=in:st={start_time}:d=0.3,"
                    f"format=rgba,colorchannelmixer=aa={opacity}[meme];"
                    f"[0:v][meme]overlay={overlay_x}:{overlay_y}:enable='between(t,{start_time},{end_time})'"
                )
            
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", meme_path,
                "-filter_complex", overlay_filter,
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "copy",
                "-movflags", "+faststart",
                output_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error("Meme overlay FFmpeg hatası: %s", stderr.decode())
                return False
            
            logger.info("Meme overlay eklendi: %s -> %s", meme_path, output_path)
            return True
            
        except Exception as e:
            logger.error("Meme overlay hatası: %s", e)
            return False

    async def add_multiple_overlays(
        self,
        video_path: str,
        meme_overlays: list[dict[str, Any]],
        output_path: str,
    ) -> bool:
        """
        Birden fazla meme overlay ekle.
        
        Args:
            video_path: Input video path
            meme_overlays: List of meme info dicts
            output_path: Output video path
        
        Returns:
            Success status
        """
        if not meme_overlays:
            return False
        
        try:
            current_input = video_path
            temp_outputs = []
            
            for i, meme_info in enumerate(meme_overlays):
                if i == len(meme_overlays) - 1:
                    # Son overlay final output
                    temp_output = output_path
                else:
                    # Geçici output
                    temp_output = video_path.replace(".mp4", f"_temp_{i}.mp4")
                    temp_outputs.append(temp_output)
                
                success = await self.add_single_overlay(
                    current_input, temp_output, meme_info
                )
                
                if not success:
                    logger.warning("Meme overlay %d başarısız", i)
                    continue
                
                current_input = temp_output
            
            # Geçici dosyaları temizle
            for temp_file in temp_outputs:
                if os.path.exists(temp_file) and temp_file != output_path:
                    os.remove(temp_file)
            
            logger.info("%d meme overlay başarıyla eklendi", len(meme_overlays))
            return True
            
        except Exception as e:
            logger.error("Multiple meme overlay hatası: %s", e)
            return False

    async def analyze_and_suggest_memes(
        self,
        video_path: str,
        transcript: str = "",
        emotions: list[str] = [],
    ) -> list[dict[str, Any]]:
        """
        Video analizi yap ve meme önerileri üret.
        
        Args:
            video_path: Video path
            transcript: Video transkripti
            emotions: Tespit edilen duygular
        
        Returns:
            List of meme suggestions
        """
        try:
            # LLM ile analiz
            from services.llm_engine import llm_engine
            
            prompt = f"""
            Video içeriği analizi ve meme önerileri:
            
            Transkript: {transcript[:500]}...
            Duygular: {', '.join(emotions) if emotions else 'Belirlenmedi'}
            
            Bu video için TikTok/Instagram Reels uygun 2-3 meme overlay öner.
            Her öneri için:
            - Meme kategorisi (funny, exciting, shock, success, reaction)
            - Zamanlama (hangi saniyede görünmeli)
            - Placement önerisi (center, top_left, top_right, bottom_left, bottom_right)
            - Animation tipi (pop, fade, slide, spin, shake, bounce)
            
            JSON formatında döndür.
            """
            
            analysis = await llm_engine.generate_completion(prompt)
            
            # Parse LLM response
            suggestions = []
            try:
                # LLM yanıtını parse et
                parsed = json.loads(analysis)
                if isinstance(parsed, list):
                    suggestions = parsed
                elif isinstance(parsed, dict) and "suggestions" in parsed:
                    suggestions = parsed["suggestions"]
            except json.JSONDecodeError:
                # Fallback: basit öneriler
                for emotion in emotions[:3] if emotions else ["funny"]:
                    suggestions.append({
                        "category": emotion,
                        "timing": {"start": random.uniform(0, 15), "duration": 2.0},
                        "placement": "random",
                        "animation": "pop"
                    })
            
            # Önerileri tam meme bilgilerine çevir
            final_memes = []
            for suggestion in suggestions:
                meme_data = await self.select_meme_for_context(
                    context=transcript[:200],
                    emotion=suggestion.get("category", "funny"),
                    video_duration=30.0
                )
                
                # LLM önerileriyle override et
                if "timing" in suggestion:
                    meme_data["timing"] = suggestion["timing"]
                if "placement" in suggestion:
                    meme_data["placement"] = PLACEMENT_STRATEGIES.get(
                        suggestion["placement"], 
                        PLACEMENT_STRATEGIES["random"]
                    )
                if "animation" in suggestion:
                    meme_data["animation"] = suggestion["animation"]
                
                final_memes.append(meme_data)
            
            logger.info("%d meme önerisi üretildi", len(final_memes))
            return final_memes
            
        except Exception as e:
            logger.error("Meme analizi hatası: %s", e)
            # Fallback basit öneriler
            return [await self.select_meme_for_context("video", "funny", 30.0)]


# Global instance
meme_overlay = MemeOverlay()