"""
Klip cikarici algoritma.
Indirilen/kaydedilen videodan otomatik klip segmentleri olusturur.
- Ses enerji analizi ile heyecanli an tespiti
- Scene change detection ile sahne degisikligi tespiti
- Belirli zaman araliklarinda otomatik bolme
"""
import asyncio
import logging
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from datetime import datetime

import numpy as np

logger = logging.getLogger(__name__)

CLIPS_DIR = Path("data/clips")
PROCESSED_DIR = Path("data/processed")
CLIPS_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


class ClipExtractor:
    """
    Video dosyasindan otomatik klip cikarici.
    Birden fazla strateji destekler.
    """

    async def extract_by_energy(
        self,
        video_path: str,
        min_clip_duration: float = 10.0,
        max_clip_duration: float = 60.0,
        energy_threshold: float = 2.0,
        top_n: int = 10,
    ) -> List[Dict]:
        """
        Ses enerjisi analizi ile en heyecanli anları bulur ve klip olarak cikarir.

        Args:
            video_path: Kaynak video dosyasi
            min_clip_duration: Minimum klip suresi (saniye)
            max_clip_duration: Maximum klip suresi (saniye)
            energy_threshold: Enerji esigi (baseline kat)
            top_n: En iyi N an

        Returns:
            [{"start": float, "end": float, "energy": float, "path": str}, ...]
        """
        # 1. Ses enerjisi profili cikar
        energy_profile = await self._get_audio_energy(video_path)
        if not energy_profile:
            logger.warning("Ses enerjisi profili alinamadi")
            return []

        # 2. Zirve noktalari bul
        peaks = self._find_peaks(energy_profile, energy_threshold, min_clip_duration)

        # 3. En iyi N zirveyi sec
        peaks.sort(key=lambda p: p["energy"], reverse=True)
        selected = peaks[:top_n]

        # 4. Her zirve icin klip olustur
        clips = []
        for peak in selected:
            start = max(0, peak["time"] - min_clip_duration / 2)
            end = min(peak["time"] + min_clip_duration / 2, energy_profile[-1]["time"])

            # Max duration kontrolu
            duration = min(end - start, max_clip_duration)

            clip = await self._cut_segment(
                video_path, start, duration,
                f"energy_clip_{len(clips):03d}"
            )

            if clip:
                clips.append({
                    "start": start,
                    "end": start + duration,
                    "energy": peak["energy"],
                    "path": clip,
                    "trigger": "audio_energy",
                })

        logger.info("Enerji bazli %d klip cikarildi", len(clips))
        return clips

    async def extract_by_intervals(
        self,
        video_path: str,
        interval_seconds: float = 30.0,
        clip_duration: float = 15.0,
    ) -> List[Dict]:
        """
        Sabit araliklarla video segmentleri cikarir.

        Args:
            video_path: Kaynak video
            interval_seconds: Her segment arasi (saniye)
            clip_duration: Her klip suresi (saniye)

        Returns:
            Klip listesi
        """
        # Video suresini al
        duration = await self._get_video_duration(video_path)
        if not duration:
            return []

        clips = []
        current = 0

        while current + clip_duration <= duration:
            clip = await self._cut_segment(
                video_path, current, clip_duration,
                f"interval_clip_{len(clips):03d}"
            )

            if clip:
                clips.append({
                    "start": current,
                    "end": current + clip_duration,
                    "path": clip,
                    "trigger": "interval",
                })

            current += interval_seconds

        logger.info("Aralik bazli %d klip cikarildi", len(clips))
        return clips

    async def extract_by_scene_change(
        self,
        video_path: str,
        threshold: float = 0.3,
        min_clip_duration: float = 10.0,
    ) -> List[Dict]:
        """
        FFmpeg scene change detection ile sahne degisikliklerine gore klip cikarir.

        Args:
            video_path: Kaynak video
            threshold: Sahne degisiklik hassasiyeti (0-1, dusuk = daha fazla)
            min_clip_duration: Iki sahne degisikligi arasi minimum sure

        Returns:
            Klip listesi
        """
        cmd = [
            "ffprobe",
            "-f", "lavfi",
            "-i", f"movie={video_path},select='gt(scene,{threshold})'",
            "-show_entries", "frame=pkt_pts_time",
            "-v", "quiet",
            "-of", "csv=p=0",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if not stdout:
                return []

            # Sahne degisikligi zamanlarini parse et
            timestamps = []
            for line in stdout.decode().strip().split("\n"):
                try:
                    timestamps.append(float(line.strip()))
                except ValueError:
                    continue

            if not timestamps:
                return []

            # Minimum aralik filtresi
            filtered = [timestamps[0]]
            for ts in timestamps[1:]:
                if ts - filtered[-1] >= min_clip_duration:
                    filtered.append(ts)

            # Her sahne arasi icin klip olustur
            clips = []
            duration = await self._get_video_duration(video_path)

            for i in range(len(filtered) - 1):
                start = filtered[i]
                end = filtered[i + 1]
                clip_dur = min(end - start, 60.0)

                clip = await self._cut_segment(
                    video_path, start, clip_dur,
                    f"scene_clip_{len(clips):03d}"
                )

                if clip:
                    clips.append({
                        "start": start,
                        "end": start + clip_dur,
                        "path": clip,
                        "trigger": "scene_change",
                    })

            logger.info("Sahne bazli %d klip cikarildi", len(clips))
            return clips

        except Exception as e:
            logger.error("Sahne tespiti hatasi: %s", e)
            return []

    async def extract_custom_segment(
        self,
        video_path: str,
        start: float,
        end: float,
        name: Optional[str] = None,
    ) -> Optional[str]:
        """
        Belirli zaman araligindan tek bir klip cikarir.
        """
        duration = end - start
        if not name:
            name = f"custom_{datetime.now().strftime('%H%M%S')}"

        return await self._cut_segment(video_path, start, duration, name)

    async def _get_audio_energy(self, video_path: str) -> List[Dict]:
        """
        FFmpeg ile ses enerji profili olusturur.
        Returns: [{"time": float, "energy": float}, ...]
        """
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", "astats=metadata=1:reset=1,ametadata=print:file=-",
            "-f", "null",
            "-",
        ]

        try:
            proc = subprocess.run(
                cmd, capture_output=True, timeout=120, text=True
            )

            # stdout'tan RMS enerji degerlerini parse et
            energy_data = []
            time_counter = 0.0

            for line in proc.stdout.split("\n"):
                if "lavfi.astats.Overall.RMS_level" in line:
                    try:
                        val = line.split("=")[-1].strip()
                        energy = float(val) if val != "-inf" else -100.0
                        energy_data.append({"time": time_counter, "energy": energy})
                        time_counter += 1.0  # ~1 saniyelik pencere
                    except (ValueError, IndexError):
                        continue

            return energy_data

        except Exception as e:
            logger.error("Ses enerji analizi hatasi: %s", e)
            return []

    def _find_peaks(
        self,
        energy_profile: List[Dict],
        threshold: float,
        min_distance: float,
    ) -> List[Dict]:
        """Enerji profilindeki zirve noktalarini bulur."""
        if not energy_profile:
            return []

        # Baseline hesapla
        energies = [p["energy"] for p in energy_profile]
        baseline = np.median(energies) if energies else -50
        peak_level = baseline + threshold * 10  # dB cinsinden

        peaks = []
        last_peak_time = -min_distance

        for point in energy_profile:
            if (point["energy"] > peak_level and
                    point["time"] - last_peak_time >= min_distance):
                peaks.append(point)
                last_peak_time = point["time"]

        return peaks

    async def _get_video_duration(self, video_path: str) -> Optional[float]:
        """ffprobe ile video suresini alir."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            video_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return float(stdout.decode().strip())
        except Exception:
            return None

    async def _cut_segment(
        self,
        video_path: str,
        start: float,
        duration: float,
        name: str,
    ) -> Optional[str]:
        """Video dosyasindan bir segment keser."""
        output_path = str(CLIPS_DIR / f"{name}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", str(start),
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()

            if proc.returncode == 0 and Path(output_path).exists():
                return output_path

        except Exception as e:
            logger.error("Segment kesme hatasi: %s", e)

        return None


# Singleton
clip_extractor = ClipExtractor()
