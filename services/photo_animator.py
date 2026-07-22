"""
Fotoğraf Animasyon Servisi — Ken Burns + Zoom efektleri
───────────────────────────────────────────────────────
Statik fotoğrafları viral video formatına çevirir:
  1. Ken Burns efektleri (yavaş zoom/pan)
  2. Otomatik zoom-in/out
  3. 9:16 dikey format'a fit
  4. Transition efektleri
  5. Dynamic timing (hook noktalarına göre)

TikTok/Instagram Reels viral fotoğraf trendlerine göre optimize.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("photo_animator")

PHOTO_DIR = Path("data/photos")
OUTPUT_DIR = Path("data/animated_photos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Ken Burns efekt tipleri
BURNS_EFFECTS = {
    "zoom_in": {
        "description": "Yavaşça yakınlaşma",
        "zoom_start": 1.0,
        "zoom_end": 1.3,
        "duration_factor": 1.0,
    },
    "zoom_out": {
        "description": "Yavaşça uzaklaşma",
        "zoom_start": 1.3,
        "zoom_end": 1.0,
        "duration_factor": 1.0,
    },
    "pan_left": {
        "description": "Sola doğru kayma",
        "pan_start_x": 0.0,
        "pan_end_x": -0.1,
        "zoom": 1.2,
        "duration_factor": 1.2,
    },
    "pan_right": {
        "description": "Sağa doğru kayma",
        "pan_start_x": 0.0,
        "pan_end_x": 0.1,
        "zoom": 1.2,
        "duration_factor": 1.2,
    },
    "pan_up": {
        "description": "Yukarı doğru kayma",
        "pan_start_y": 0.0,
        "pan_end_y": -0.1,
        "zoom": 1.2,
        "duration_factor": 1.2,
    },
    "pan_down": {
        "description": "Aşağı doğru kayma",
        "pan_start_y": 0.0,
        "pan_end_y": 0.1,
        "zoom": 1.2,
        "duration_factor": 1.2,
    },
    "diagonal_in": {
        "description": "Çapraz olarak yakınlaşma",
        "zoom_start": 1.0,
        "zoom_end": 1.4,
        "pan_end_x": 0.05,
        "pan_end_y": 0.05,
        "duration_factor": 1.5,
    },
    "rotate_slow": {
        "description": "Yavaş döndürme",
        "rotation_start": 0,
        "rotation_end": 5,
        "zoom": 1.1,
        "duration_factor": 1.3,
    },
}

# Viral fotoğraf trend settings
VIRAL_PHOTO_SETTINGS = {
    "optimal_duration": (3.0, 8.0),  # 3-8 saniye arası
    "transition_duration": 0.5,  # Geçiş süresi
    "fps": 30,
    "resolution": (1080, 1920),  # 9:16 dikey
}


class PhotoAnimator:
    """
    Fotoğraf animasyon servisi — statik fotoğrafları viral videoya çevirir.
    FFmpeg tabanlı, hızlı ve quality-preserving.
    """

    def __init__(self):
        self._effect_cache: dict[str, Any] = {}

    async def animate_single_photo(
        self,
        photo_path: str,
        output_path: str,
        effect: str = "zoom_in",
        duration: float = 5.0,
        resolution: tuple[int, int] = VIRAL_PHOTO_SETTINGS["resolution"],
        fps: int = VIRAL_PHOTO_SETTINGS["fps"],
    ) -> bool:
        """
        Tek bir fotoğrafı animasyonlu videoya çevir.
        
        Args:
            photo_path: Input fotoğraf path
            output_path: Output video path
            effect: Ken burns efekti tipi
            duration: Video süresi (saniye)
            resolution: Çıkış çözünürlüğü (width, height)
            fps: Frame rate
        
        Returns:
            Success status
        """
        try:
            if not os.path.exists(photo_path):
                logger.error("Fotoğraf bulunamadı: %s", photo_path)
                return False
            
            effect_config = BURNS_EFFECTS.get(effect, BURNS_EFFECTS["zoom_in"])
            
            # FFmpeg scale filter - 9:16 dikey format
            width, height = resolution
            scale_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            
            # Ken burns filter
            zoom_start = effect_config.get("zoom_start", 1.0)
            zoom_end = effect_config.get("zoom_end", 1.3)
            
            # Timeline-based zoom animation
            zoom_filter = f"zoompan=z='min(zoom+0.0015,{zoom_end})':d={int(duration * fps)}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}:{height}:fps={fps}"
            
            # FFmpeg command
            cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", photo_path,
                "-vf", f"{scale_filter},{zoom_filter}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-t", str(duration),
                "-pix_fmt", "yuv420p",
                "-r", str(fps),
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
                logger.error("Fotoğraf animasyon hatası: %s", stderr.decode())
                return False
            
            logger.info("Fotoğraf animasyonu tamamlandı: %s -> %s (%s, %.1fs)", 
                       photo_path, output_path, effect, duration)
            return True
            
        except Exception as e:
            logger.error("Fotoğraf animasyon hatası: %s", e)
            return False

    async def create_photo_slideshow(
        self,
        photo_paths: list[str],
        output_path: str,
        durations: list[float] = None,
        effects: list[str] = None,
        transition: str = "fade",
        resolution: tuple[int, int] = VIRAL_PHOTO_SETTINGS["resolution"],
        fps: int = VIRAL_PHOTO_SETTINGS["fps"],
    ) -> bool:
        """
        Birden fazla fotoğraflı slideshow videoya çevir.
        
        Args:
            photo_paths: Fotoğraf path listesi
            output_path: Output video path
            durations: Her fotoğrafın süresi (saniye)
            effects: Her fotoğrafın efekti
            transition: Geçiş tipi (fade, slide, dissolve)
            resolution: Çıkış çözünürlüğü
            fps: Frame rate
        
        Returns:
            Success status
        """
        if not photo_paths:
            logger.error("Fotoğraf listesi boş")
            return False
        
        try:
            num_photos = len(photo_paths)
            
            # Varsayılan değerler
            if durations is None:
                durations = [random.uniform(*VIRAL_PHOTO_SETTINGS["optimal_duration"]) 
                            for _ in range(num_photos)]
            if effects is None:
                available_effects = list(BURNS_EFFECTS.keys())
                effects = [random.choice(available_effects) for _ in range(num_photos)]
            
            # Her fotoğrafı animasyonlu videoya çevir
            temp_videos = []
            for i, (photo_path, duration, effect) in enumerate(zip(photo_paths, durations, effects)):
                temp_output = OUTPUT_DIR / f"temp_{i}_{Path(photo_path).stem}.mp4"
                
                success = await self.animate_single_photo(
                    photo_path, str(temp_output), effect, duration, resolution, fps
                )
                
                if success:
                    temp_videos.append(str(temp_output))
                else:
                    logger.warning("Fotoğraf %d animasyonu başarısız", i)
            
            if not temp_videos:
                logger.error("Hiçbir fotoğraf animasyonu başarılı olmadı")
                return False
            
            # Videoları birleştir
            if len(temp_videos) == 1:
                # Tek video ise kopyala
                import shutil
                shutil.copy(temp_videos[0], output_path)
            else:
                # Birden fazla video için concat
                concat_file = OUTPUT_DIR / "concat_list.txt"
                with open(concat_file, "w") as f:
                    for video in temp_videos:
                        f.write(f"file '{video}'\n")
                
                # Transition için filtre
                if transition == "fade":
                    transition_filter = f"xfade=transition=fade:duration=0.5:offset=0.5"
                elif transition == "slide":
                    transition_filter = f"xfade=transition=slideleft:duration=0.5:offset=0.5"
                else:
                    transition_filter = None
                
                if transition_filter and len(temp_videos) > 1:
                    # Complex concat with transitions
                    filter_complex = ""
                    for i in range(len(temp_videos) - 1):
                        filter_complex += f"[{i}:v][{i+1}:v]{transition_filter}[v{i+1}];"
                    filter_complex = filter_complex.rstrip(";")
                    
                    inputs = []
                    for video in temp_videos:
                        inputs.extend(["-i", video])
                    
                    cmd = ["ffmpeg", "-y"] + inputs + [
                        "-filter_complex", filter_complex,
                        "-map", f"[v{len(temp_videos)-1}]",
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart",
                        output_path
                    ]
                else:
                    # Basit concat
                    cmd = [
                        "ffmpeg", "-y",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(concat_file),
                        "-c", "copy",
                        output_path
                    ]
                
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    logger.error("Slideshow birleştirme hatası: %s", stderr.decode())
                    return False
            
            # Temizlik
            for temp_video in temp_videos:
                if os.path.exists(temp_video):
                    os.remove(temp_video)
            if concat_file.exists():
                concat_file.unlink()
            
            logger.info("Slideshow tamamlandı: %d fotoğraf -> %s", num_photos, output_path)
            return True
            
        except Exception as e:
            logger.error("Slideshow oluşturma hatası: %s", e)
            return False

    async def analyze_and_suggest_animation(
        self,
        photo_path: str,
        context: str = "",
        emotion: str = "neutral",
    ) -> dict[str, Any]:
        """
        Fotoğraf için animasyon önerisi üret.
        
        Args:
            photo_path: Fotoğraf path
            context: Fotoğraf içeriği/teması
            emotion: Duygu (exciting, calm, dramatic, funny, etc.)
        
        Returns:
            Animation suggestion dict
        """
        try:
            from services.llm_engine import llm_engine
            
            prompt = f"""
            Fotoğraf animasyon analizi:
            
            Fotoğraf context: {context[:300]}...
            Duygu: {emotion}
            
            Bu fotoğraf için TikTok/Instagram Reels uygun animasyon öner:
            - Efekt tipi (zoom_in, zoom_out, pan_left, pan_right, pan_up, pan_down, diagonal_in, rotate_slow)
            - Süre (3-8 saniye arası)
            - Geçiş tipi (fade, slide, dissolve)
            
            JSON formatında döndür.
            """
            
            analysis = await llm_engine.generate_completion(prompt)
            
            suggestion = {
                "effect": "zoom_in",
                "duration": random.uniform(*VIRAL_PHOTO_SETTINGS["optimal_duration"]),
                "transition": "fade"
            }
            
            try:
                parsed = json.loads(analysis)
                if isinstance(parsed, dict):
                    effect = parsed.get("effect", "zoom_in")
                    if effect in BURNS_EFFECTS:
                        suggestion["effect"] = effect
                    suggestion["duration"] = parsed.get("duration", suggestion["duration"])
                    suggestion["transition"] = parsed.get("transition", "fade")
            except json.JSONDecodeError:
                # Varsayılan değerleri kullan
                pass
            
            # Duygu bazlı efekt seçimi
            emotion_effect_map = {
                "exciting": ["zoom_in", "diagonal_in"],
                "calm": ["zoom_out", "pan_left"],
                "dramatic": ["zoom_in", "rotate_slow"],
                "funny": ["pan_right", "pan_left"],
                "romantic": ["zoom_in", "pan_up"],
            }
            
            if emotion in emotion_effect_map:
                suggestion["effect"] = random.choice(emotion_effect_map[emotion])
            
            logger.info("Animasyon önerisi: %s (%.1fs)", suggestion["effect"], suggestion["duration"])
            return suggestion
            
        except Exception as e:
            logger.error("Animasyon analizi hatası: %s", e)
            return {
                "effect": "zoom_in",
                "duration": 5.0,
                "transition": "fade"
            }

    async def animate_with_viral_optimization(
        self,
        photo_path: str,
        output_path: str,
        context: str = "",
        emotion: str = "neutral",
        hook_points: list[float] = [],
    ) -> bool:
        """
        Viral optimizasyonlu fotoğraf animasyonu.
        
        Args:
            photo_path: Input fotoğraf
            output_path: Output video
            context: Fotoğraf içeriği
            emotion: Duygu
            hook_points: Hook noktaları (timing için)
        
        Returns:
            Success status
        """
        try:
            # Animasyon önerisi al
            suggestion = await self.analyze_and_suggest_animation(photo_path, context, emotion)
            
            # Hook noktalarına göre timing ayarla
            if hook_points:
                # İlk hook noktasına odaklan
                first_hook = min(hook_points)
                suggestion["duration"] = min(max(first_hook * 0.8, 3.0), 8.0)
            
            # Animasyonu uygula
            success = await self.animate_single_photo(
                photo_path,
                output_path,
                effect=suggestion["effect"],
                duration=suggestion["duration"],
            )
            
            if success:
                logger.info("Viral optimize animasyon: %s (%.1fs)", 
                           suggestion["effect"], suggestion["duration"])
            
            return success
            
        except Exception as e:
            logger.error("Viral animasyon hatası: %s", e)
            return False


# Global instance
photo_animator = PhotoAnimator()