"""
Otomatik Ses Efekti Sistemi — SFX Synthesizer + Placer
───────────────────────────────────────────────────────
2026 viral Reels analizine gore en cok kullanilan ses efektleri:
- Vine boom / Bass drop (impact anlari)
- Record scratch / Brake (beklenmedik an)
- Click / Pop (scene degisimi)
- Ding / Bell (basari / victory)
- Whoosh / Swoosh (transition)
- Coin / Level up (oyun ici)
- Laugh track (komik an)
- Suspense riser (hook / buildup)

Iki kaynaktan SFX uretir:
1. data/sfx/ kutuphanesi (music_service.py)
2. FFmpeg sentetik ses uretimi (anoisesrc, sine — API gerektirmez)

Kullanim:
  from services.auto_sfx import auto_sfx
  result = await auto_sfx.add_sfx_to_clip(clip_path, event_type="impact", timestamp=3.5)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("auto_sfx")

SFX_DIR = Path("data/sfx")
SFX_DIR.mkdir(parents=True, exist_ok=True)

# Viral Reels SFX mapping (LLM analizinden)
SFX_EVENT_MAP = {
    "impact": {
        "keywords": ["boom", "impact", "hit", "slam", "bass_drop", "vine_boom"],
        "synthetic": "boom",
        "duration": 0.8,
        "viral_score": 90,
    },
    "transition": {
        "keywords": ["whoosh", "swoosh", "swipe", "transition", "whip"],
        "synthetic": "whoosh",
        "duration": 0.5,
        "viral_score": 80,
    },
    "victory": {
        "keywords": ["victory", "win", "clap", "cheer", "applause", "triumph"],
        "synthetic": "victory_jingle",
        "duration": 1.0,
        "viral_score": 75,
    },
    "fail": {
        "keywords": ["fail", "lose", "dead", "rip", "womp", "sadtrombone", "oof"],
        "synthetic": "fail_buzzer",
        "duration": 1.0,
        "viral_score": 80,
    },
    "surprise": {
        "keywords": ["surprise", "shock", "dramatic", "reveal", "dun_dun"],
        "synthetic": "dramatic_sting",
        "duration": 1.2,
        "viral_score": 85,
    },
    "laugh": {
        "keywords": ["laugh", "funny", "haha", "comedy", "giggle"],
        "synthetic": "laugh_track",
        "duration": 1.5,
        "viral_score": 70,
    },
    "suspense": {
        "keywords": ["suspense", "buildup", "riser", "tension", "cinematic"],
        "synthetic": "suspense_riser",
        "duration": 2.0,
        "viral_score": 82,
    },
    "notification": {
        "keywords": ["ding", "bell", "alert", "pop", "notification", "coin"],
        "synthetic": "ding",
        "duration": 0.3,
        "viral_score": 60,
    },
    "speed": {
        "keywords": ["speed", "fast", "zoom", "rush", "sonic", "nyoom"],
        "synthetic": "speed_zoom",
        "duration": 0.4,
        "viral_score": 65,
    },
    "record_scratch": {
        "keywords": ["scratch", "brake", "stop", "wait", "record_scratch"],
        "synthetic": "record_scratch",
        "duration": 0.5,
        "viral_score": 85,
    },
}


class AutoSFXService:
    """
    Otomatik ses efekti ekleme servisi.
    Kutuphanede varsa kullanir, yoksa FFmpeg ile sentetik uretir.
    """

    def __init__(self):
        self._sfx_library: list[str] = []
        self._scan_library()

    def _scan_library(self):
        """data/sfx/ klasorundeki ses dosyalarini tara."""
        self._sfx_library = []
        for ext in ("*.mp3", "*.wav", "*.ogg", "*.m4a"):
            for f in SFX_DIR.rglob(ext):
                self._sfx_library.append(str(f))
        logger.info("SFX kutuphanesi tarandi: %d dosya", len(self._sfx_library))

    def get_available_sfx(self) -> list[str]:
        return self._sfx_library

    async def add_sfx_to_clip(
        self,
        video_path: str,
        output_path: str,
        event_type: str = "impact",
        timestamp: float = 3.0,
        volume_db: float = -8.0,
        mix_ratio: float = 0.6,
    ) -> bool:
        """
        Videoya belirli bir zamanda ses efekti ekle.
        Rust audio-mixer varsa tek pas, yoksa FFmpeg fallback.
        """
        # Rust audio-mixer dene
        from shared.utils.audio_mixer_client import mix_audio as _rust_mix
        sfx_path = self._find_or_generate_sfx(
            SFX_EVENT_MAP.get(event_type, SFX_EVENT_MAP["impact"])
        )
        if sfx_path:
            rust_ok = await _rust_mix(
                video_path=video_path,
                output_path=output_path,
                sfx_events=[{
                    "file": sfx_path,
                    "timestamp": timestamp,
                    "volume_db": volume_db,
                    "mix_ratio": mix_ratio,
                }],
            )
            if rust_ok:
                return True

        # Fallback: FFmpeg subprocess (original)
        event_info = SFX_EVENT_MAP.get(event_type, SFX_EVENT_MAP["impact"])
        sfx_path = self._find_or_generate_sfx(event_info)

        if not sfx_path or not os.path.exists(sfx_path):
            logger.warning("SFX bulunamadi/olusturulamadi: %s", event_type)
            cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return False

        delay_ms = int(timestamp * 1000)

        # SFX'i video'ya mix et:
        # Video'nun orijinal sesini koru, SFX'i belirtilen zamanda ekle
        # volume ayari, delay, mix
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", str(sfx_path),
            "-filter_complex",
            (
                f"[1:a]adelay={delay_ms}|{delay_ms},"
                f"volume={volume_db}dB[sfx];"
                f"[0:a][sfx]amix=inputs=2:duration=first:"
                f"weights={1-mix_ratio} {mix_ratio}[aout]"
            ),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_text = stderr.decode()[:300]
                logger.error("SFX overlay failed: %s", err_text)
                fb = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
                proc2 = await asyncio.create_subprocess_exec(
                    *fb, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                )
                await proc2.communicate()
                return False
            logger.info("SFX eklendi: %s t=%.1fs vol=%.1fdB -> %s",
                        event_type, timestamp, volume_db, Path(output_path).name)
            return True
        except Exception as e:
            logger.error("SFX error: %s", e)
            return False

    async def analyze_and_suggest_sfx(
        self,
        video_path: str,
        transcript: str = "",
        emotions: list[str] = [],
        hook_points: list[float] = [],
    ) -> list[dict[str, Any]]:
        """
        Video analizi yap ve SFX önerileri üret.
        
        Args:
            video_path: Video path
            transcript: Video transkripti
            emotions: Tespit edilen duygular
            hook_points: Hook noktaları (saniye cinsinden)
        
        Returns:
            List of SFX suggestions [{event_type, timestamp, volume_db, mix_ratio}]
        """
        try:
            from services.llm_engine import llm_engine
            
            prompt = f"""
            Video ses efekti analizi ve önerileri:
            
            Transkript: {transcript[:500]}...
            Duygular: {', '.join(emotions) if emotions else 'Belirlenmedi'}
            Hook noktaları: {hook_points}
            
            Bu video için TikTok/Instagram Reels uygun 3-5 ses efekti öner.
            Her öneri için:
            - Event type (impact, transition, victory, fail, surprise, laugh, suspense, notification, speed, record_scratch)
            - Zamanlama (hangi saniyede)
            - Ses seviyesi önerisi (dB, -12 ile 0 arası)
            
            JSON formatında döndür.
            """
            
            analysis = await llm_engine.generate_completion(prompt)
            
            suggestions = []
            try:
                parsed = json.loads(analysis)
                if isinstance(parsed, list):
                    suggestions = parsed
                elif isinstance(parsed, dict) and "suggestions" in parsed:
                    suggestions = parsed["suggestions"]
            except json.JSONDecodeError:
                # Fallback: Hook noktalarına göre basit SFX
                for hook in hook_points[:3] if hook_points else [2.0, 8.0, 15.0]:
                    suggestions.append({
                        "event_type": "impact",
                        "timestamp": hook,
                        "volume_db": -8.0,
                        "mix_ratio": 0.6
                    })
            
            # Validasyon ve varsayılan değerler
            final_sfx = []
            for suggestion in suggestions:
                event_type = suggestion.get("event_type", "impact")
                if event_type not in SFX_EVENT_MAP:
                    event_type = "impact"
                
                final_sfx.append({
                    "event_type": event_type,
                    "timestamp": suggestion.get("timestamp", random.uniform(1, 20)),
                    "volume_db": suggestion.get("volume_db", -8.0),
                    "mix_ratio": suggestion.get("mix_ratio", 0.6)
                })
            
            logger.info("%d SFX önerisi üretildi", len(final_sfx))
            return final_sfx
            
        except Exception as e:
            logger.error("SFX analizi hatası: %s", e)
            # Fallback basit öneriler
            return [{
                "event_type": "impact",
                "timestamp": 2.0,
                "volume_db": -8.0,
                "mix_ratio": 0.6
            }]

    async def add_multiple_sfx(
        self,
        video_path: str,
        sfx_events: list[dict[str, Any]],
        output_path: str,
    ) -> bool:
        """
        Birden fazla ses efektini video'ya ekle.
        Rust audio-mixer varsa tek FFmpeg pasusu, yoksa sequential FFmpeg.
        """
        if not sfx_events:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return True

        # Rust audio-mixer dene (tek pas)
        from shared.utils.audio_mixer_client import mix_audio as _rust_mix
        rust_ok = await _rust_mix(
            video_path=video_path,
            output_path=output_path,
            sfx_events=sfx_events,
        )
        if rust_ok:
            return True

        # Fallback: sequential FFmpeg (original logic)
        inputs = [video_path]
        filter_parts = []
        sfx_labels = []

        for i, ev in enumerate(sfx_events):
            event_type = ev.get("event_type", "impact")
            event_info = SFX_EVENT_MAP.get(event_type, SFX_EVENT_MAP["impact"])
            sfx_path = self._find_or_generate_sfx(event_info)

            if not sfx_path or not os.path.exists(sfx_path):
                logger.warning("SFX %d (%s) bulunamadi, atlaniyor", i, event_type)
                continue

            inputs.append(str(sfx_path))
            input_idx = len(inputs) - 1
            ts = ev.get("timestamp", 2.0)
            vol = ev.get("volume_db", -8.0)
            delay_ms = int(ts * 1000)
            label = f"sfx{i}"

            filter_parts.append(
                f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume={vol}dB[{label}]"
            )
            sfx_labels.append(f"[{label}]")

        if not sfx_labels:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return True

        amix_inputs = ";".join(filter_parts)
        amix_count = len(sfx_labels) + 1  # video audio + tüm sfx'ler
        amix_expr = f"[0:a]{''.join(sfx_labels)}amix=inputs={amix_count}:duration=first[aout]"

        full_filter = f"{amix_inputs};{amix_expr}" if filter_parts else amix_expr

        cmd = [
            "ffmpeg", "-y",
            *[a for inp in inputs for a in ("-i", inp)],
            "-filter_complex", full_filter,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("Multiple SFX failed: %s", stderr.decode()[:400])
                fb = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
                proc2 = await asyncio.create_subprocess_exec(
                    *fb, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                )
                await proc2.communicate()
                return False
            logger.info("Multiple SFX eklendi: %d efekt -> %s",
                        len(sfx_labels), Path(output_path).name)
            return True
        except Exception as e:
            logger.error("Multiple SFX error: %s", e)
            return False

    async def add_background_music(
        self,
        video_path: str,
        music_path: str,
        output_path: str,
        volume_db: float = -18.0,
        enable_ducking: bool = True,
    ) -> bool:
        """
        Videoya arka plan muzigi ekle.
        Rust audio-mixer varsa onu kullan, yoksa FFmpeg ile yap.
        """
        # Rust audio-mixer dene
        from shared.utils.audio_mixer_client import mix_audio as _rust_mix
        rust_ok = await _rust_mix(
            video_path=video_path,
            output_path=output_path,
            music_path=music_path,
            music_volume_db=volume_db,
            enable_ducking=enable_ducking,
        )
        if rust_ok:
            return True

        # Fallback: FFmpeg
        if not os.path.exists(music_path):
            logger.warning("Muzik dosyasi bulunamadi: %s", music_path)
            return False

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", music_path,
            "-filter_complex",
            (
                f"[1:a]volume={volume_db}dB[music];"
                f"[0:a][music]amix=inputs=2:duration=first:"
                f"weights=1 0.4[aout]"
            ),
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ac", "2",
            "-ar", "44100",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("Background music failed: %s", stderr.decode()[:300])
                fb = ["ffmpeg", "-y", "-i", video_path, "-c", "copy", output_path]
                proc2 = await asyncio.create_subprocess_exec(
                    *fb, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
                )
                await proc2.communicate()
                return False
            logger.info("Arka plan muzigi eklendi: %.1fdB -> %s",
                        volume_db, Path(output_path).name)
            return True
        except Exception as e:
            logger.error("Background music error: %s", e)
            return False

    async def generate_synthetic_sfx(
        self, sfx_type: str, output_path: str, duration: float = 1.0
    ) -> Optional[str]:
        """
        FFmpeg ile sentetik ses efekti uret (API gerektirmez).
        
        Args:
            sfx_type: Efekt tipi (boom|whoosh|victory_jingle|fail_buzzer|dramatic_sting|
                     laugh_track|suspense_riser|ding|speed_zoom|record_scratch)
            output_path: Cikti dosya yolu (.wav)
            duration: Sure (saniye)
        """
        synthetic_recipes = {
            "boom": {
                "filter": f"anoisesrc=d={duration:.1f}:c=brown:a=0.8",
                "af": "lowpass=f=200,volume=6dB,afade=t=out:st=0.4:d=0.6",
            },
            "whoosh": {
                "filter": f"anoisesrc=d={duration:.1f}:c=pink:a=0.6",
                "af": "highpass=f=500,lowpass=f=3000,volume=3dB,"
                     "afade=t=in:d=0.05,afade=t=out:st=0.3:d=0.2",
            },
            "victory_jingle": {
                "filter": (
                    f"aevalsrc='sin(2*PI*523.25*t)+sin(2*PI*659.25*t)+sin(2*PI*783.99*t)':"
                    f"d={duration:.1f}:s=44100"
                ),
                "af": "afade=t=in:d=0.05,afade=t=out:st=0.6:d=0.4,volume=2dB",
            },
            "fail_buzzer": {
                "filter": f"sine=f=150:d={duration:.1f}",
                "af": "acrusher=bits=4:mix=0.5:mode=log:aa=1,"
                     "afade=t=in:d=0.1,afade=t=out:st=0.6:d=0.4,volume=3dB",
            },
            "dramatic_sting": {
                "filter": (
                    f"aevalsrc='sin(2*PI*t*(100+t*4000))':d={duration:.1f}:s=44100"
                ),
                "af": "afade=t=in:d=0.1,afade=t=out:st=0.8:d=0.4,volume=4dB",
            },
            "laugh_track": {
                "filter": f"anoisesrc=d={duration:.1f}:c=white:a=0.3",
                "af": "lowpass=f=2000,highpass=f=300,"
                     "volume=2dB,afade=t=in:d=0.2,afade=t=out:d=0.5",
            },
            "suspense_riser": {
                "filter": (
                    f"aevalsrc='sin(2*PI*t*(100+t*2000))':d={duration:.1f}:s=44100"
                ),
                "af": "lowpass=f=800+f*1200:t=linear,volume=3dB,"
                     "afade=t=in:d=0.3,afade=t=out:d=0.5",
            },
            "ding": {
                "filter": f"sine=f=2000:d={duration:.1f}",
                "af": "afade=t=out:st=0.05:d=0.3,volume=4dB",
            },
            "speed_zoom": {
                "filter": (
                    f"aevalsrc='sin(2*PI*t*(400+t*3000))':d={duration:.1f}:s=44100"
                ),
                "af": "afade=t=in:d=0.05,afade=t=out:d=0.2,volume=3dB",
            },
            "record_scratch": {
                "filter": f"anoisesrc=d={duration:.1f}:c=white:a=0.5",
                "af": "acrusher=bits=2:mix=0.8:mode=log:aa=0.5,"
                     "volume=4dB,afade=t=out:d=0.3",
            },
        }

        recipe = synthetic_recipes.get(sfx_type)
        if not recipe:
            logger.warning("Unknown SFX type: %s", sfx_type)
            return None

        output_file = SFX_DIR / output_path

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", recipe["filter"],
            "-af", recipe["af"],
            "-ac", "1",
            "-ar", "44100",
            str(output_file),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("Synthetic SFX failed [%s]: %s", sfx_type, stderr.decode()[:200])
                return None
            logger.info("Sentetik SFX uretildi: %s -> %s", sfx_type, output_file.name)
            return str(output_file)
        except Exception as e:
            logger.error("Synthetic SFX error: %s", e)
            return None

    def _find_or_generate_sfx(self, event_info: dict) -> Optional[str]:
        """
        Once kutuphanede ara, yoksa sentetik uret.
        """
        keywords = event_info.get("keywords", [])
        synthetic_type = event_info.get("synthetic", "impact")
        duration = event_info.get("duration", 1.0)

        if self._sfx_library:
            for kw in keywords:
                for f in self._sfx_library:
                    fname = Path(f).name.lower()
                    if kw in fname:
                        return f
            return random.choice(self._sfx_library)

        output_filename = f"synthetic_{synthetic_type}_{int(duration*1000)}ms.wav"
        out_path = SFX_DIR / output_filename
        if out_path.exists():
            return str(out_path)

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            self.generate_synthetic_sfx(synthetic_type, output_filename, duration)
        )
        return result


# Singleton
auto_sfx = AutoSFXService()