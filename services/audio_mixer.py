"""
Gelişmiş ses miksaj motoru.
Çoklu track, crossfade, LUFS normalization, ducking, sessizlik algılama.
"""
import asyncio
import json
import logging
import struct
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

AUDIO_DIR = Path("data/audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AudioSegment:
    """Ses segment bilgisi."""
    path: str
    duration: float
    sample_rate: int = 44100
    channels: int = 2
    peak_db: float = 0.0
    rms_db: float = -20.0
    lufs: float = -23.0


class AudioMixer:
    """
    Gelişmiş ses miksaj motoru.
    """

    def __init__(self):
        self._target_lufs = -14.0  # Sosyal medya standardı
        self._true_peak_limit = -1.0  # dBTP

    async def get_audio_info(self, path: str) -> AudioSegment:
        """Ses dosyası bilgilerini ffprobe ile alır."""
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            path,
        ]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            data = json.loads(stdout.decode())

            fmt = data.get("format", {})
            streams = data.get("streams", [{}])
            audio_stream = next(
                (s for s in streams if s.get("codec_type") == "audio"), {}
            )

            return AudioSegment(
                path=path,
                duration=float(fmt.get("duration", 0)),
                sample_rate=int(audio_stream.get("sample_rate", 44100)),
                channels=int(audio_stream.get("channels", 2)),
            )
        except Exception as e:
            logger.error("Ses bilgi alma hatası: %s", e)
            return AudioSegment(path=path, duration=0)

    async def mix_tracks(
        self,
        tracks: List[Dict],
        output_path: str,
        normalize: bool = True,
        target_lufs: float = -14.0,
    ) -> Optional[str]:
        """
        Çoklu ses track'ini karıştırır.

        tracks: [
            {"path": str, "volume": float, "start_at": float,
             "fade_in": float, "fade_out": float, "loop": bool},
            ...
        ]
        """
        if not tracks:
            return None

        if len(tracks) == 1:
            return tracks[0]["path"]

        # FFmpeg filter_complex oluştur
        inputs = []
        filter_parts = []

        for i, track in enumerate(tracks):
            inputs.extend(["-i", track["path"]])
            vol = track.get("volume", 1.0)
            fade_in = track.get("fade_in", 0)
            fade_out = track.get("fade_out", 0)
            start_at = track.get("start_at", 0)

            # Volume + fade + delay
            af_parts = [f"[{i}:a]volume={vol}"]

            if fade_in > 0:
                af_parts.append(f"afade=t=in:d={fade_in}")

            if fade_out > 0:
                af_parts.append(f"afade=t=out:d={fade_out}")

            if start_at > 0:
                delay_ms = int(start_at * 1000)
                af_parts.append(f"adelay={delay_ms}|{delay_ms}")

            filter_chain = ",".join(af_parts) + f"[a{i}]"
            filter_parts.append(filter_chain)

        # amix ile birleştir
        mix_inputs = "".join(f"[a{i}]" for i in range(len(tracks)))
        filter_parts.append(
            f"{mix_inputs}amix=inputs={len(tracks)}:duration=longest"
            f":dropout_transition=3"
        )

        # LUFS normalization
        if normalize:
            filter_parts.append(
                f"loudnorm=I={target_lufs}:TP=-1:LRA=11"
            )

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
        ] + inputs + [
            "-filter_complex", filter_complex,
            "-map", f"[{len(filter_parts)-1}]"
            if normalize else f"[{len(filter_parts)-1}]",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

        # Map düzeltmesi
        cmd[-2] = "-map"
        cmd[-1] = f"[{len(filter_parts)-1}]"

        return await self._run_ffmpeg(cmd, output_path)

    async def crossfade_tracks(
        self,
        track_a: str,
        track_b: str,
        crossfade_duration: float = 2.0,
        output_path: str = "",
    ) -> Optional[str]:
        """
        İki ses dosyasını crossfade ile birleştirir.
        """
        if not output_path:
            output_path = str(AUDIO_DIR / "crossfaded.mp3")

        cmd = [
            "ffmpeg", "-y",
            "-i", track_a,
            "-i", track_b,
            "-filter_complex",
            f"[0:a][1:a]acrossfade=d={crossfade_duration}:c1=tri:c2=tri[out]",
            "-map", "[out]",
            "-c:a", "libmp3lame",
            "-q:a", "2",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def normalize_lufs(
        self,
        input_path: str,
        output_path: str,
        target_lufs: float = -14.0,
        true_peak: float = -1.0,
    ) -> Optional[str]:
        """
        LUFS loudness normalization (EBU R128).
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", f"loudnorm=I={target_lufs}:TP={true_peak}:LRA=11",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def analyze_loudness(self, input_path: str) -> Dict:
        """
        EBU R128 loudness analizi yapar.
        Two-pass: önce measurement, sonra normalization.
        """
        # Pass 1: Measurement
        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", "ebur128=peak=true",
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

            # Parse loudness values
            result = {
                "input_i": -23.0,
                "input_tp": -1.0,
                "input_lra": 7.0,
                "input_thresh": -33.0,
            }

            for line in output.split("\n"):
                line = line.strip()
                if "Input Integrated:" in line:
                    try:
                        result["input_i"] = float(
                            line.split(":")[-1].strip().split(" ")[0]
                        )
                    except (ValueError, IndexError):
                        pass
                elif "Input True Peak:" in line:
                    try:
                        result["input_tp"] = float(
                            line.split(":")[-1].strip().split(" ")[0]
                        )
                    except (ValueError, IndexError):
                        pass
                elif "Input LRA:" in line:
                    try:
                        result["input_lra"] = float(
                            line.split(":")[-1].strip().split(" ")[0]
                        )
                    except (ValueError, IndexError):
                        pass

            return result

        except Exception as e:
            logger.error("Loudness analiz hatası: %s", e)
            return {"input_i": -23.0, "input_tp": -1.0}

    async def extract_audio(
        self,
        video_path: str,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """Video dosyasından sesi çıkarır."""
        if not output_path:
            base = Path(video_path).stem
            output_path = str(AUDIO_DIR / f"{base}.wav")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "48000",
            "-ac", "2",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def remove_silence(
        self,
        input_path: str,
        output_path: str,
        threshold_db: float = -40.0,
        min_silence_duration: float = 0.5,
    ) -> Optional[str]:
        """
        Sessizlik kısımlarını kaldırır (basitleştirilmiş).
        """
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-af", f"silenceremove=start_periods=1:"
            f"start_duration={min_silence_duration}:"
            f"start_threshold={threshold_db}dB,"
            f"areverse,"
            f"silenceremove=start_periods=1:"
            f"start_duration={min_silence_duration}:"
            f"start_threshold={threshold_db}dB,"
            f"areverse",
            "-c:a", "aac",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def create_silence(
        self,
        duration: float,
        output_path: str,
        sample_rate: int = 48000,
    ) -> Optional[str]:
        """
        Sessiz bir ses dosyası oluşturur.
        """
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=r={sample_rate}:cl=stereo",
            "-t", str(duration),
            "-c:a", "aac",
            output_path,
        ]

        return await self._run_ffmpeg(cmd, output_path)

    def build_ducking_filter(
        self,
        speech_volume: float = 1.0,
        music_volume: float = 0.3,
        threshold: float = 0.02,
        ratio: float = 8.0,
        attack: int = 200,
        release: int = 1000,
    ) -> str:
        """
        FFmpeg ducking filter string'i üretir.
        """
        return (
            f"[0:a]volume={speech_volume}[speech];"
            f"[1:a]volume={music_volume}[music];"
            f"[music][speech]sidechaincompress="
            f"threshold={threshold}:"
            f"ratio={ratio}:"
            f"attack={attack}:"
            f"release={release}[ducked];"
            f"[speech][ducked]amix=inputs=2:duration=first[out]"
        )

    async def _run_ffmpeg(
        self, cmd: List[str], output_path: str
    ) -> Optional[str]:
        """FFmpeg komutunu çalıştırır."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=300
            )

            if proc.returncode == 0:
                logger.info("Ses işlemi başarılı: %s", output_path)
                return output_path
            else:
                logger.error("FFmpeg ses hatası: %s", stderr.decode()[:500])
                return None

        except Exception as e:
            logger.error("FFmpeg ses hatası: %s", e)
            return None


# Singleton
audio_mixer = AudioMixer()
