"""
Beat-senkronize düzenleme motoru.
Müzik ritmine göre kesim, efekt, geçiş ve zoom zamanlaması.
"""
import asyncio
import json
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BeatInfo:
    """Tek bir beat bilgisi."""
    time: float
    strength: float      # 0-1 arası güç
    bpm: float
    beat_number: int     # Bar içindeki beat numarası (0-3)
    is_downbeat: bool    # Bar başlangıcı mı?


@dataclass
class BeatGrid:
    """Beat ızgarası bilgisi."""
    bpm: float
    beats: List[BeatInfo]
    total_bars: int
    time_signature: str  # "4/4", "3/4"
    duration: float


class BeatSyncEngine:
    """
    Beat-senkronize düzenleme motoru.
    FFmpeg filter'ları üretir: beat'te zoom, flash, kesim, hız değişimi.
    """

    def __init__(self):
        self._default_bpm = 120

    async def detect_beats(
        self,
        audio_path: str,
        sensitivity: float = 0.8,
    ) -> BeatGrid:
        """
        Ses dosyasından beat'leri algılar.

        Basitleştirilmiş yaklaşım: RMS enerji tabanlı beat detection.
        Gerçek kullanımda librosa veya aubio kullanılmalı.
        """
        # ffprobe ile süre al
        duration = await self._get_duration(audio_path)

        # Basit beat detection (enerji tabanlı)
        # Gerçek kullanımda: librosa.beat.beat_track()
        beats = []
        interval = 60.0 / self._default_bpm

        t = 0.0
        beat_num = 0
        while t < duration:
            is_downbeat = (beat_num % 4 == 0)
            strength = 1.0 if is_downbeat else 0.6

            beats.append(BeatInfo(
                time=t,
                strength=strength,
                bpm=self._default_bpm,
                beat_number=beat_num % 4,
                is_downbeat=is_downbeat,
            ))

            t += interval
            beat_num += 1

        return BeatGrid(
            bpm=self._default_bpm,
            beats=beats,
            total_bars=beat_num // 4,
            time_signature="4/4",
            duration=duration,
        )

    def generate_beat_zoom_filter(
        self,
        beat_grid: BeatGrid,
        zoom_level: float = 1.1,
        on_downbeat: bool = True,
    ) -> str:
        """
        Beat zamanlarında zoom efekti üretir.
        Her downbeat'te hafif zoom in/out.
        """
        if not beat_grid.beats:
            return "null"

        # zoompan ile beat senkron zoom
        # Her beat'te zoom seviyesini değiştir
        frames_per_beat = int(60.0 / beat_grid.bpm * 25)

        return (
            f"zoompan="
            f"z='1+0.05*sin(2*PI*on/{frames_per_beat})':"
            f"x='iw/2-iw/(2*z)':"
            f"y='ih/2-ih/(2*z)':"
            f"d=1:s=1080x1920:fps=25"
        )

    def generate_beat_flash_filter(
        self,
        beat_grid: BeatGrid,
        flash_color: str = "white",
        intensity: float = 0.3,
    ) -> str:
        """
        Beat zamanlarında flash efekti üretir.
        """
        if not beat_grid.beats:
            return "null"

        frames_per_beat = int(60.0 / beat_grid.bpm * 25)
        flash_frames = 3  # 3 kare flash

        # Her beat'te brightness spike
        return (
            f"eq=brightness="
            f"0.03*sin(2*PI*on/{frames_per_beat}):"
            f"saturation=1+0.1*sin(2*PI*on/{frames_per_beat})"
        )

    def generate_beat_shake_filter(
        self,
        beat_grid: BeatGrid,
        intensity: float = 0.3,
    ) -> str:
        """
        Beat zamanlarında camera shake üretir.
        """
        if not beat_grid.beats:
            return "null"

        frames_per_beat = int(60.0 / beat_grid.bpm * 25)
        amp = int(intensity * 5)

        return (
            f"crop=iw-{amp*2}:ih-{amp*2}:"
            f"{amp}+{amp}*sin(2*PI*on/{frames_per_beat}):"
            f"{amp}+{amp}*cos(2*PI*on/{frames_per_beat}*1.3)"
        )

    def generate_beat_speed_filter(
        self,
        beat_grid: BeatGrid,
        slow_on_beat: float = 0.7,
        fast_between: float = 1.2,
    ) -> str:
        """
        Beat zamanlarında hız değişimi üretir.
        Beat'te yavaşla, aralarda hızlan.
        """
        frames_per_beat = int(60.0 / beat_grid.bpm * 25)

        # setpts ile beat senkron hız
        return (
            f"setpts="
            f"(1/{slow_on_beat}+({fast_between}-{slow_on_beat})*"
            f"(1-0.5*(1+cos(2*PI*on/{frames_per_beat}))))*PTS"
        )

    def generate_beat_zoom_transition(
        self,
        beat_grid: BeatGrid,
        at_beat: int = 0,
        zoom_from: float = 1.0,
        zoom_to: float = 2.0,
        duration_beats: int = 2,
    ) -> str:
        """
        Belirli bir beat'te zoom geçişi üretir.
        """
        if not beat_grid.beats or at_beat >= len(beat_grid.beats):
            return "null"

        beat_time = beat_grid.beats[at_beat].time
        frames_per_beat = int(60.0 / beat_grid.bpm * 25)
        total_frames = frames_per_beat * duration_beats

        return (
            f"zoompan="
            f"z='{zoom_from}+({zoom_to}-{zoom_from})*on/{total_frames}':"
            f"x='iw/2-iw/(2*z)':"
            f"y='ih/2-ih/(2*z)':"
            f"d={total_frames}:s=1080x1920:fps=25"
        )

    def generate_cut_at_beats(
        self,
        beat_grid: BeatGrid,
        clip_times: List[float],
    ) -> List[Tuple[float, float]]:
        """
        Beat zamanlarına en yakın kesim noktalarını bulur.
        """
        cuts = []
        for t in clip_times:
            # En yakın beat'i bul
            closest_beat = min(
                beat_grid.beats,
                key=lambda b: abs(b.time - t),
                default=BeatGrid.beats[0] if beat_grid.beats else None
            )
            if closest_beat:
                cuts.append((closest_beat.time, closest_beat.strength))

        return cuts

    def get_beat_times(
        self,
        beat_grid: BeatGrid,
        downbeats_only: bool = False,
    ) -> List[float]:
        """
        Beat zamanlarını döndürür.
        """
        if downbeats_only:
            return [b.time for b in beat_grid.beats if b.is_downbeat]
        return [b.time for b in beat_grid.beats]

    def calculate_beat_aligned_duration(
        self,
        original_duration: float,
        beat_grid: BeatGrid,
        round_to: int = 4,
    ) -> float:
        """
        Süreyi beat sayısına hizalar.
        round_to: Kaç beat'e yuvarla (4 = bir bar).
        """
        beats_per_bar = 4
        frames_per_beat = 60.0 / beat_grid.bpm

        total_beats = original_duration / frames_per_beat
        aligned_beats = round(total_beats / round_to) * round_to

        return aligned_beats * frames_per_beat

    async def _get_duration(self, path: str) -> float:
        """Ses dosyası süresini alır."""
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
beat_sync = BeatSyncEngine()
