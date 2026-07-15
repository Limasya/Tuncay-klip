"""
Ses analiz servisi.
- Ses enerjisi tespiti (volume spike detection)
- Konuşma algılama (VAD - Voice Activity Detection)
- Ses tonu / duygu analizi
- Olay tetikleyici olarak ses trigger'ları
"""
import asyncio
import subprocess
import logging
import numpy as np
from pathlib import Path
from typing import Dict, Optional, List, Tuple
from collections import deque
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class AudioAnalyzer:
    """
    Canlı yayın sesini analiz eder.
    - FFmpeg ile ses stream'ini ayıklar
    - Ses enerjisi (RMS) hesaplar
    - Ani ses yükselmelerini (spike) tespit eder
    """

    def __init__(self):
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.energy_history: deque = deque(maxlen=100)
        self.baseline_energy: float = 0.0
        self._ffmpeg_process: Optional[subprocess.Popen] = None
        self.is_running = False
        self._spike_threshold = 2.5  # Baseline'dan X kat fazlası = spike

    async def start_audio_capture(self, stream_url: str):
        """Stream'den ses çıkarmaya ve analiz etmeye başlar."""
        self.is_running = True
        asyncio.create_task(self._capture_audio(stream_url))

    async def stop(self):
        self.is_running = False
        if self._ffmpeg_process:
            self._ffmpeg_process.terminate()
            self._ffmpeg_process = None
        self.energy_history.clear()

    async def _capture_audio(self, stream_url: str):
        """FFmpeg ile stream'den PCM ses verisi okur."""
        cmd = [
            "ffmpeg",
            "-i", stream_url,
            "-vn",                    # video yok
            "-acodec", "pcm_s16le",   # 16-bit PCM
            "-ar", str(self.sample_rate),
            "-ac", "1",               # mono
            "-f", "s16le",
            "-v", "quiet",
            "pipe:1"
        ]

        try:
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.chunk_size * 2,
            )

            while self.is_running:
                raw = self._ffmpeg_process.stdout.read(self.chunk_size * 2)
                if not raw:
                    break

                # PCM 16-bit -> numpy array
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                samples = samples / 32768.0  # Normalize [-1, 1]

                self._process_chunk(samples)

        except Exception as e:
            logger.error("Ses yakalama hatası: %s", e)

    def _process_chunk(self, samples: np.ndarray) -> Dict:
        """Bir ses chunk'ını analiz eder."""
        # RMS enerji
        rms = float(np.sqrt(np.mean(samples ** 2)))
        self.energy_history.append(rms)

        # Baseline güncelle (son 50 chunk ortalaması)
        if len(self.energy_history) >= 50:
            self.baseline_energy = float(
                np.mean(list(self.energy_history)[-50:])
            )

        # Spike tespiti
        is_spike = False
        spike_ratio = 0.0
        if self.baseline_energy > 0.001:
            spike_ratio = rms / self.baseline_energy
            is_spike = spike_ratio > self._spike_threshold

        # Konuşma algılama (basit VAD: enerji eşik üstü)
        speech_detected = rms > 0.02

        return {
            "rms_energy": rms,
            "baseline_energy": self.baseline_energy,
            "spike_ratio": spike_ratio,
            "is_spike": is_spike,
            "speech_detected": speech_detected,
        }

    def get_current_analysis(self) -> Dict:
        """Mevcut ses analiz durumunu döndürür."""
        if not self.energy_history:
            return {
                "rms_energy": 0.0,
                "baseline_energy": 0.0,
                "spike_ratio": 0.0,
                "is_spike": False,
                "speech_detected": False,
            }

        rms = float(self.energy_history[-1])
        return {
            "rms_energy": rms,
            "baseline_energy": self.baseline_energy,
            "spike_ratio": rms / max(self.baseline_energy, 0.001),
            "is_spike": rms / max(self.baseline_energy, 0.001) > self._spike_threshold,
            "speech_detected": rms > 0.02,
        }


class ClipAudioAnalyzer:
    """
    Kaydedilmiş klip dosyaları için ses analizi.
    - Whisper ile transkripsiyon
    - Ses enerji profili
    - Konuşma segmentleri
    """

    def __init__(self):
        self.sample_rate = 16000

    async def extract_audio(self, video_path: str) -> Optional[str]:
        """Video dosyasından ses çıkartır (WAV)."""
        audio_path = video_path.rsplit(".", 1)[0] + "_audio.wav"

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", str(self.sample_rate),
            "-ac", "1",
            audio_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0 and Path(audio_path).exists():
                return audio_path
        except Exception as e:
            logger.error("Ses çıkarma hatası: %s", e)

        return None

    def analyze_audio_file(self, audio_path: str) -> Dict:
        """Ses dosyasının enerji profilini hesaplar."""
        import wave

        try:
            with wave.open(audio_path, "r") as wf:
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)
                samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
                samples = samples / 32768.0

            # Genel enerji
            rms = float(np.sqrt(np.mean(samples ** 2)))
            max_amp = float(np.max(np.abs(samples)))
            peak_ratio = max_amp / max(rms, 0.001)

            # 1 saniyelik pencere enerji profili
            window = self.sample_rate
            energy_profile = []
            for i in range(0, len(samples), window):
                chunk = samples[i:i + window]
                if len(chunk) > 0:
                    energy_profile.append(float(np.sqrt(np.mean(chunk ** 2))))

            # En yüksek enerji anı
            peak_time = 0.0
            if energy_profile:
                peak_idx = int(np.argmax(energy_profile))
                peak_time = float(peak_idx)

            return {
                "rms_energy": rms,
                "max_amplitude": max_amp,
                "peak_ratio": peak_ratio,
                "energy_profile": energy_profile,
                "peak_time_seconds": peak_time,
                "duration_seconds": len(samples) / self.sample_rate,
                "has_loud_moments": peak_ratio > 3.0,
            }

        except Exception as e:
            logger.error("Ses dosyası analiz hatası: %s", e)
            return {
                "rms_energy": 0.0,
                "max_amplitude": 0.0,
                "peak_ratio": 0.0,
                "energy_profile": [],
                "peak_time_seconds": 0.0,
                "duration_seconds": 0.0,
                "has_loud_moments": False,
            }

    async def transcribe(self, audio_path: str) -> Dict:
        """
        Whisper ile ses transkripsiyonu.
        (Detaylar subtitle_service'de)
        """
        from services.subtitle_service import SubtitleService
        svc = SubtitleService()
        return await svc.transcribe_audio(audio_path)


# Singleton
audio_analyzer = AudioAnalyzer()
clip_audio_analyzer = ClipAudioAnalyzer()
