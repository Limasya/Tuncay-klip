"""
Beat-senkronize duzenleme motoru.
Muzik ritmine gore kesim, efekt, gecis ve zoom zamanlamasi.
librosa ile gercek beat detection.
"""
import asyncio
import json
import logging
import math
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

LIBROSA_AVAILABLE = False
try:
    import librosa
    import numpy as np
    LIBROSA_AVAILABLE = True
except ImportError:
    logger.warning("librosa bulunamadi, energy-based beat detection kullanilacak")
    np = None  # type: ignore


@dataclass
class BeatInfo:
    """Tek bir beat bilgisi."""
    time: float
    strength: float      # 0-1 arasi guc
    bpm: float
    beat_number: int     # Bar icindeki beat numarasi (0-3)
    is_downbeat: bool    # Bar baslangici mi?


@dataclass
class BeatGrid:
    """Beat izgarasi bilgisi."""
    bpm: float
    beats: List[BeatInfo]
    total_bars: int
    time_signature: str  # "4/4", "3/4"
    duration: float


class BeatSyncEngine:
    """
    Beat-senkronize duzenleme motoru.
    C++ signal_engine (native, fastest) → librosa (Python) → energy-based fallback (slow).
    """

    def __init__(self):
        self._default_bpm = 120
        self._temp_dir = Path("data/temp")
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        self._signal_engine = None
        self._cpp_available = False
        self._init_cpp_engine()

    def _init_cpp_engine(self):
        """C++ signal_engine yuklemeyi dene."""
        try:
            from signal_engine.python.signal_client import signal_engine
            if signal_engine.available:
                self._signal_engine = signal_engine
                self._cpp_available = True
                logger.info("C++ signal_engine aktif — native beat detection kullanilacak")
        except Exception as e:
            logger.debug("C++ signal_engine yuklenemedi: %s", e)

    async def detect_beats(
        self,
        audio_path: str,
        sensitivity: float = 0.8,
        bpm_override: Optional[float] = None,
    ) -> BeatGrid:
        """
        Ses/video dosyasindan beat'leri algilar.

        Sira:
          1. C++ signal_engine (en hizli, native)
          2. librosa (orta)
          3. Enerji tabanli fallback (en yavas)
        """
        duration = await self._get_duration(audio_path)

        # 1. C++ signal_engine ile native beat detection
        if self._cpp_available:
            try:
                return await self._cpp_signal_detect(
                    audio_path, duration, sensitivity, bpm_override
                )
            except Exception as e:
                logger.debug("C++ beat detection basarisiz: %s", e)

        # 2. librosa ile Python beat detection
        if LIBROSA_AVAILABLE:
            try:
                return await self._librosa_detect(
                    audio_path, duration, sensitivity, bpm_override
                )
            except Exception as e:
                logger.warning("librosa beat detection basarisiz: %s, fallback kullaniliyor", e)

        # 3. Enerji tabanli fallback
        return await self._energy_based_detect(audio_path, duration, bpm_override)

    async def _cpp_signal_detect(
        self,
        audio_path: str,
        duration: float,
        sensitivity: float,
        bpm_override: Optional[float],
    ) -> BeatGrid:
        """C++ signal_engine ile native beat detection — FFT + onset + BPM."""
        import numpy as np

        # Ses dosyasini WAV'a cevir (signal_engine ham float array alir)
        ext = Path(audio_path).suffix.lower()
        audio_tmp = None
        if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"):
            audio_tmp = await self._extract_audio(audio_path)
            if not audio_tmp:
                raise RuntimeError("Ses cikarma basarisiz")
            work_path = audio_tmp
        elif ext in (".mp3", ".wav", ".ogg", ".m4a"):
            # WAV'a cevir
            wav_path = str(self._temp_dir / f"cpp_beat_{Path(audio_path).stem}.wav")
            if not os.path.exists(wav_path):
                cmd = ["ffmpeg", "-y", "-i", audio_path, "-ac", "1", "-ar", "22050",
                       "-f", "wav", wav_path]
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.communicate()
                if proc.returncode != 0:
                    raise RuntimeError("WAV donusumu basarisiz")
            work_path = wav_path
        else:
            work_path = audio_path

        # WAV'dan float array oku (soundfile veya FFmpeg pipe)
        samples = await self._read_wav_to_floats(work_path)
        if not samples or len(samples) < 1024:
            raise RuntimeError("Samples yetersiz")

        sample_rate = 22050  # downsampled to 22kHz
        
        # C++ signal_engine.analyze_audio cagir (FFT + onset + beat)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._signal_engine.analyze_audio(samples, float(sample_rate)),
        )

        if not result.get("success", False):
            raise RuntimeError(f"C++ analysis failed: {result.get('error', 'unknown')}")

        beats_data = result.get("beats", [])
        bpm = result.get("bpm", bpm_override or 120.0)
        onset_strength = result.get("onset_strength", [])

        if bpm_override:
            bpm = bpm_override

        if not beats_data:
            raise RuntimeError("C++ beat detection returned no beats")

        # Beat listesi olustur
        beat_list = []
        for i, bt in enumerate(beats_data):
            bt_time = bt.get("time", 0.0) if isinstance(bt, dict) else float(bt)
            bt_strength = bt.get("strength", 0.5) if isinstance(bt, dict) else 0.5

            if bt_time > duration:
                break

            strength = max(0.1, min(1.0, bt_strength))
            is_downbeat = (i % 4 == 0)

            beat_list.append(BeatInfo(
                time=float(bt_time),
                strength=float(strength),
                bpm=float(bpm),
                beat_number=i % 4,
                is_downbeat=is_downbeat,
            ))

        if not beat_list:
            raise RuntimeError("No valid beats after filtering")

        total_bars = len(beat_list) // 4 if len(beat_list) >= 4 else 1

        logger.info(
            "C++ beat detection: BPM=%.1f, %d beat, %d bar, sure=%.1fs",
            bpm, len(beat_list), total_bars, duration,
        )

        # Temizlik
        if audio_tmp and Path(audio_tmp).exists():
            try:
                Path(audio_tmp).unlink()
            except Exception:
                pass

        return BeatGrid(
            bpm=float(bpm),
            beats=beat_list,
            total_bars=total_bars,
            time_signature="4/4",
            duration=duration,
        )

    async def _read_wav_to_floats(self, wav_path: str) -> list[float]:
        """FFmpeg pipe ile WAV'dan float32 array oku."""
        try:
            import numpy as np
            cmd = [
                "ffmpeg", "-y", "-i", wav_path,
                "-f", "f32le", "-ac", "1", "-ar", "22050",
                "-",
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            raw_data, _ = await proc.communicate()
            if proc.returncode != 0 or not raw_data:
                raise RuntimeError("FFmpeg pipe failed")

            samples = np.frombuffer(raw_data, dtype=np.float32).tolist()
            return samples
        except ImportError:
            raise RuntimeError("numpy required for C++ signal_engine bridge")

    async def _librosa_detect(
        self,
        audio_path: str,
        duration: float,
        sensitivity: float,
        bpm_override: Optional[float],
    ) -> BeatGrid:
        """
        librosa.beat.beat_track ile gercek beat detection.
        Onset strength analizi ile beat gucu hesaplama.
        """
        # Video dosyasi ise once ses cikar
        ext = Path(audio_path).suffix.lower()
        if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"):
            audio_tmp = await self._extract_audio(audio_path)
            if not audio_tmp:
                raise RuntimeError("Ses cikarma basarisiz")
            work_path = audio_tmp
        else:
            work_path = audio_path

        # librosa ile ses yukle (16kHz mono)
        loop = asyncio.get_event_loop()
        y, sr = await loop.run_in_executor(
            None, lambda: librosa.load(work_path, sr=22050, mono=True)
        )

        if bpm_override:
            # BPM zorlandiysa sabit tempo grid olustur
            tempo = bpm_override
            # beat_track yine de kullan ama hop_length ile
            _, beat_frames = await loop.run_in_executor(
                None,
                lambda: librosa.beat.beat_track(
                    y=y, sr=sr, bpm=bpm_override,
                    hop_length=512,
                ),
            )
            beat_times_raw = librosa.frames_to_time(
                beat_frames, sr=sr, hop_length=512
            )
        else:
            # Otomatik BPM algilama
            tempo_result, beat_frames = await loop.run_in_executor(
                None,
                lambda: librosa.beat.beat_track(
                    y=y, sr=sr,
                    hop_length=512,
                ),
            )
            # librosa 0.11+ returns array
            if hasattr(tempo_result, '__len__') and len(tempo_result) > 0:
                tempo = float(tempo_result[0])
            else:
                tempo = float(tempo_result)
            beat_times_raw = librosa.frames_to_time(
                beat_frames, sr=sr, hop_length=512
            )

        # Onset strength hesapla (beat gucu icin)
        onset_env = await loop.run_in_executor(
            None,
            lambda: librosa.onset.onset_strength(y=y, sr=sr, hop_length=512),
        )
        onset_times = librosa.frames_to_time(
            np.arange(len(onset_env)), sr=sr, hop_length=512
        )

        # Beat listesi olustur
        beats = []
        beat_num = 0
        for i, bt in enumerate(beat_times_raw):
            if bt > duration:
                break

            # En yakin onset strength degerini bul
            strength = self._get_onset_strength_at(bt, onset_times, onset_env)

            # Sensitivity esigi
            if strength < (1.0 - sensitivity) * 0.5:
                strength = max(0.3, strength)

            is_downbeat = (beat_num % 4 == 0)
            beats.append(BeatInfo(
                time=float(bt),
                strength=float(min(1.0, max(0.1, strength))),
                bpm=tempo,
                beat_number=beat_num % 4,
                is_downbeat=is_downbeat,
            ))
            beat_num += 1

        # Eger beat bulunamadiysa sabit grid olustur
        if not beats:
            logger.warning("librosa beat bulunamadi, sabit grid olusturuluyor")
            return await self._energy_based_detect(audio_path, duration, bpm_override)

        total_bars = beat_num // 4 if beat_num >= 4 else 1

        logger.info(
            "librosa beat detection: BPM=%.1f, %d beat, %d bar, sure=%.1fs",
            tempo, len(beats), total_bars, duration,
        )

        # Temizlik
        if audio_tmp and Path(audio_tmp).exists():
            try:
                Path(audio_tmp).unlink()
            except Exception as e:
                logger.debug("Geçici ses dosyası silinemedi (%s): %s", audio_tmp, e)

        return BeatGrid(
            bpm=tempo,
            beats=beats,
            total_bars=total_bars,
            time_signature="4/4",
            duration=duration,
        )

    def _get_onset_strength_at(
        self, time: float, onset_times: np.ndarray, onset_env: np.ndarray
    ) -> float:
        """Belirli bir zamandaki onset strength degerini al."""
        if len(onset_times) == 0:
            return 0.5
        idx = np.argmin(np.abs(onset_times - time))
        max_val = float(np.max(onset_env)) if np.max(onset_env) > 0 else 1.0
        return float(onset_env[idx]) / max_val

    async def _energy_based_detect(
        self,
        audio_path: str,
        duration: float,
        bpm_override: Optional[float],
    ) -> BeatGrid:
        """
        Fallback: RMS enerji tabanli beat detection.
        ffprobe ile ses analizi yapar.
        """
        bpm = bpm_override or self._default_bpm

        # RMS enerji analizi (ffprobe ile)
        energy_profile = await self._get_energy_profile(audio_path)

        interval = 60.0 / bpm
        beats = []
        beat_num = 0
        t = 0.0

        while t < duration:
            is_downbeat = (beat_num % 4 == 0)

            # Enerji profilinden gucu al
            energy_idx = min(
                int(t / duration * len(energy_profile)),
                len(energy_profile) - 1,
            ) if energy_profile else 0
            strength = energy_profile[energy_idx] if energy_profile else (1.0 if is_downbeat else 0.6)

            beats.append(BeatInfo(
                time=t,
                strength=float(strength),
                bpm=bpm,
                beat_number=beat_num % 4,
                is_downbeat=is_downbeat,
            ))
            t += interval
            beat_num += 1

        total_bars = beat_num // 4 if beat_num >= 4 else 1

        logger.info(
            "Enerji-based beat detection: BPM=%.1f, %d beat, %d bar",
            bpm, len(beats), total_bars,
        )

        return BeatGrid(
            bpm=bpm,
            beats=beats,
            total_bars=total_bars,
            time_signature="4/4",
            duration=duration,
        )

    async def _get_energy_profile(self, audio_path: str) -> List[float]:
        """
        FFmpeg volumedetect ile enerji profili olusturur.
        20 parca bolup her birinin RMS degerini alir.
        """
        duration = await self._get_duration(audio_path)
        segments = 20
        seg_dur = duration / segments
        energies = []

        for i in range(segments):
            start = i * seg_dur
            cmd = [
                "ffmpeg", "-v", "quiet",
                "-ss", str(start),
                "-t", str(seg_dur),
                "-i", audio_path,
                "-af", "volumedetect",
                "-f", "null", "-",
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await proc.communicate()
                output = stderr.decode()

                # mean_volume parse et
                mean_vol = 0.0
                for line in output.split("\n"):
                    if "mean_volume" in line:
                        parts = line.split(":")
                        if len(parts) >= 2:
                            val_str = parts[1].strip().replace(" dB", "")
                            try:
                                mean_vol = float(val_str)
                            except ValueError:
                                pass
                            break

                # dB'yi 0-1 araligina cevir (-60dB = 0, 0dB = 1)
                normalized = max(0.0, min(1.0, (mean_vol + 60) / 60))
                energies.append(normalized)
            except Exception:
                energies.append(0.5)

        return energies

    async def _extract_audio(self, video_path: str) -> Optional[str]:
        """Video dosyasindan ses cikarir (gecici dosya)."""
        ext = Path(video_path).suffix.lower()
        out_path = str(self._temp_dir / f"beat_audio_{Path(video_path).stem}.wav")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "22050",
            "-ac", "1",
            out_path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=60)
            if proc.returncode == 0 and Path(out_path).exists():
                return out_path
        except Exception as e:
            logger.error("Ses cikarma hatasi: %s", e)
        return None

    def generate_beat_zoom_filter(
        self,
        beat_grid: BeatGrid,
        zoom_level: float = 1.1,
        on_downbeat: bool = True,
    ) -> str:
        """
        Beat zamanlarinda zoom efekti uretir.
        Her downbeat'te hafif zoom in/out.
        """
        if not beat_grid.beats:
            return "null"

        frames_per_beat = int(60.0 / beat_grid.bpm * 25)
        zoom_amplitude = (zoom_level - 1.0) * 0.5

        return (
            f"zoompan="
            f"z='1+{zoom_amplitude:.4f}*sin(2*PI*on/{frames_per_beat})':"
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
        Beat zamanlarinda flash efekti uretir.
        """
        if not beat_grid.beats:
            return "null"

        frames_per_beat = int(60.0 / beat_grid.bpm * 25)
        flash_amp = intensity * 0.05

        return (
            f"eq=brightness="
            f"{flash_amp:.4f}*sin(2*PI*on/{frames_per_beat}):"
            f"saturation=1+{intensity * 0.1:.4f}*sin(2*PI*on/{frames_per_beat})"
        )

    def generate_beat_shake_filter(
        self,
        beat_grid: BeatGrid,
        intensity: float = 0.3,
    ) -> str:
        """
        Beat zamanlarinda camera shake uretir.
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
        Beat zamanlarinda hiz degisimi uretir.
        Beat'te yavasla, aralarda hizlan.
        """
        frames_per_beat = int(60.0 / beat_grid.bpm * 25)

        return (
            f"setpts="
            f"(1/{slow_on_beat:.4f}+({fast_between:.4f}-{slow_on_beat:.4f})*"
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
        Belirli bir beat'te zoom gecisi uretir.
        """
        if not beat_grid.beats or at_beat >= len(beat_grid.beats):
            return "null"

        frames_per_beat = int(60.0 / beat_grid.bpm * 25)
        total_frames = frames_per_beat * duration_beats

        return (
            f"zoompan="
            f"z='{zoom_from:.4f}+({zoom_to - zoom_from:.4f})*on/{total_frames}':"
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
        Beat zamanlarina en yakin kesim noktalarini bulur.
        """
        cuts = []
        for t in clip_times:
            closest_beat = min(
                beat_grid.beats,
                key=lambda b: abs(b.time - t),
            ) if beat_grid.beats else None
            if closest_beat:
                cuts.append((closest_beat.time, closest_beat.strength))

        return cuts

    def get_beat_times(
        self,
        beat_grid: BeatGrid,
        downbeats_only: bool = False,
    ) -> List[float]:
        """Beat zamanlarini dondurur."""
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
        Sureyi beat sayisina hizalar.
        round_to: Kac beat'e yuvarla (4 = bir bar).
        """
        frames_per_beat = 60.0 / beat_grid.bpm
        total_beats = original_duration / frames_per_beat
        aligned_beats = round(total_beats / round_to) * round_to
        return aligned_beats * frames_per_beat

    def get_onset_strength_profile(
        self,
        audio_path: str,
        hop_length: int = 512,
    ) -> Optional[List[float]]:
        """
        Onset strength zaman serisi dondurur.
        Duygu analizi ve sahne algilama icin kullanilir.
        """
        if not LIBROSA_AVAILABLE:
            return None

        try:
            y, sr = librosa.load(audio_path, sr=22050, mono=True)
            onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
            # Normalizasyon
            max_val = float(np.max(onset_env)) if np.max(onset_env) > 0 else 1.0
            return [float(v) / max_val for v in onset_env]
        except Exception as e:
            logger.error("Onset strength hatasi: %s", e)
            return None

    async def _get_duration(self, path: str) -> float:
        """Ses/video dosyasinin suresini alir."""
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
