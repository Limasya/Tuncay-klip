"""
Sahne algılama ve sahne tabanlı düzenleme motoru.
FFmpeg scene detection, sahne bazlı efekt uygulama.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Scene:
    """Tek bir sahne bilgisi."""
    index: int
    start: float
    end: float
    duration: float
    average_motion: float = 0.0
    dominant_emotion: str = "neutral"
    brightness: float = 0.0
    is_keyframe: bool = False


@dataclass
class SceneDetectionResult:
    """Sahne algılama sonucu."""
    scenes: List[Scene]
    total_scenes: int
    total_duration: float
    average_scene_duration: float


class SceneDetectionEngine:
    """
    Sahne algılama motoru.
    FFmpeg scene filter ile sahne değişimlerini tespit eder.
    """

    def __init__(self):
        self._default_threshold = 0.3

    async def detect_scenes(
        self,
        video_path: str,
        threshold: float = 0.3,
        min_scene_duration: float = 0.5,
    ) -> SceneDetectionResult:
        """
        Video dosyasından sahneleri algılar.

        FFmpeg'in scene filter'ını kullanır:
        ffmpeg -i input -vf "select='gt(scene,0.3)'" -vsync vfr output
        """
        # Scene detection komutu
        cmd = [
            "ffprobe", "-v", "quiet",
            "-show_entries", "frame=pts_time,pict_type",
            "-of", "json",
            "-f", "lavfi",
            f"movie={video_path},select='gt(scene\\,{threshold})'",
        ]

        scenes = []
        try:
            # Alternatif: FFmpeg ile scene change timestamps'leri al
            cmd = [
                "ffmpeg", "-i", video_path,
                "-vf", f"select='gt(scene,{threshold})',showinfo",
                "-f", "null", "-"
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            output = stderr.decode()

            # showinfo çıktısından zamanları parse et
            timestamps = [0.0]
            for line in output.split("\n"):
                if "pts_time:" in line:
                    try:
                        pts_part = line.split("pts_time:")[1].split()[0]
                        ts = float(pts_part)
                        timestamps.append(ts)
                    except (ValueError, IndexError):
                        pass

            # Sahneleri oluştur
            duration = await self._get_duration(video_path)
            timestamps.append(duration)

            for i in range(len(timestamps) - 1):
                start = timestamps[i]
                end = timestamps[i + 1]
                scene_dur = end - start

                if scene_dur >= min_scene_duration:
                    scenes.append(Scene(
                        index=i,
                        start=start,
                        end=end,
                        duration=scene_dur,
                    ))

        except Exception as e:
            logger.error("Sahne algılama hatası: %s", e)
            # Fallback: eşit bölümler
            duration = await self._get_duration(video_path)
            scene_dur = 5.0
            t = 0.0
            idx = 0
            while t < duration:
                end = min(t + scene_dur, duration)
                scenes.append(Scene(
                    index=idx, start=t, end=end,
                    duration=end - t,
                ))
                t = end
                idx += 1

        total_dur = sum(s.duration for s in scenes)
        avg_dur = total_dur / len(scenes) if scenes else 0

        result = SceneDetectionResult(
            scenes=scenes,
            total_scenes=len(scenes),
            total_duration=total_dur,
            average_scene_duration=avg_dur,
        )

        logger.info(
            "Sahne algılama: %d sahne, ortalama %.1fs",
            result.total_scenes, result.average_scene_duration,
        )

        return result

    def generate_scene_transition_filter(
        self,
        scenes: List[Scene],
        transition_type: str = "fade",
        transition_duration: float = 0.5,
    ) -> str:
        """
        Her sahne geçişine ayrı efekt uygular.
        """
        if len(scenes) < 2:
            return "null"

        # xfade zinciri oluştur
        # Basitleştirilmiş: sadece ilk 2 geçiş
        filters = []

        for i in range(min(2, len(scenes) - 1)):
            scene = scenes[i]
            next_scene = scenes[i + 1]
            offset = scene.end - transition_duration

            filters.append(
                f"xfade=transition={transition_type}:"
                f"duration={transition_duration}:"
                f"offset={offset:.3f}"
            )

        return ",".join(filters) if filters else "null"

    def apply_scene_based_effects(
        self,
        scenes: List[Scene],
        effect_map: Dict[str, str],
    ) -> List[Dict]:
        """
        Her sahneye ayrı efekt uygular.

        effect_map: {"high_motion": "shake", "low_motion": "slow_mo", ...}
        """
        scene_effects = []
        for scene in scenes:
            effects = []

            # Sahne süresine göre efekt seçimi
            if scene.duration < 1.0:
                # Kısa sahne → hızlı geçiş
                effects.append("fast_cut")
            elif scene.duration > 5.0:
                # Uzun sahne → yavaş zoom
                effects.append("slow_zoom")

            # Hareket seviyesine göre
            if scene.average_motion > 0.7:
                effects.append("shake")
            elif scene.average_motion < 0.3:
                effects.append("slow_mo")

            scene_effects.append({
                "scene": scene,
                "effects": effects,
                "start": scene.start,
                "end": scene.end,
            })

        return scene_effects

    def generate_scene_speed_filter(
        self,
        scenes: List[Scene],
        short_scene_speed: float = 1.5,
        long_scene_speed: float = 0.7,
    ) -> str:
        """
        Sahne uzunluğuna göre hız ayarı.
        Kısa sahneler hızlandırılır, uzun sahneler yavaşlatılır.
        """
        if not scenes:
            return "null"

        # Basitleştirilmiş: ortalama süreye göre tek hız
        avg_dur = sum(s.duration for s in scenes) / len(scenes)

        if avg_dur < 1.5:
            speed = short_scene_speed
        elif avg_dur > 4.0:
            speed = long_scene_speed
        else:
            speed = 1.0

        if speed != 1.0:
            return f"setpts={1.0/speed}*PTS"

        return "null"

    def generate_highlight_reel(
        self,
        scenes: List[Scene],
        max_scenes: int = 10,
        max_duration: float = 60.0,
    ) -> List[Tuple[float, float]]:
        """
        En ilginç sahneleri seçerek highlight reel oluşturur.
        Kısa + hareketli sahneler tercih edilir.
        """
        scored = []
        for scene in scenes:
            # Skor: kısa süre + yüksek hareket = yüksek skor
            score = 1.0 / max(scene.duration, 0.5)
            score *= (1 + scene.average_motion)
            scored.append((score, scene))

        # Skora göre sırala
        scored.sort(key=lambda x: x[0], reverse=True)

        # En iyi sahneleri seç
        selected = []
        total = 0.0
        for score, scene in scored[:max_scenes]:
            if total + scene.duration > max_duration:
                break
            selected.append((scene.start, scene.end))
            total += scene.duration

        # Zaman sırasına göre sırala
        selected.sort(key=lambda x: x[0])

        return selected

    async def _get_duration(self, path: str) -> float:
        """Video süresini alır."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout.decode())
            return float(data.get("format", {}).get("duration", 30.0))
        except Exception:
            return 30.0


# Singleton
scene_detection = SceneDetectionEngine()
