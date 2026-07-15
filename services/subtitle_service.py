"""
Altyazı üretim servisi.
- OpenAI Whisper ile otomatik konuşma tanıma (ASR)
- SRT dosyası oluşturma
- Altyazıyı videoya gömme (burn-in) veya ayrı dosya olarak ekleme
"""
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SUBTITLES_DIR = Path("data/subtitles")
SUBTITLES_DIR.mkdir(parents=True, exist_ok=True)


class SubtitleService:
    """
    Whisper tabanlı altyazı üretim servisi.
    """

    def __init__(self):
        self._whisper_model = None
        self._model_size = settings.whisper_model_size

    def _load_whisper(self):
        """Whisper modelini yükle (lazy loading)."""
        if self._whisper_model is not None:
            return

        try:
            import whisper
            logger.info("Whisper modeli yükleniyor: %s", self._model_size)
            self._whisper_model = whisper.load_model(self._model_size)
            logger.info("Whisper modeli yüklendi.")
        except ImportError:
            logger.error("openai-whisper paketi yüklü değil!")
        except Exception as e:
            logger.error("Whisper model yükleme hatası: %s", e)

    async def transcribe_audio(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> Dict:
        """
        Ses dosyasını Whisper ile metne çevirir.

        Returns:
            {
                "text": "Tam transkripsiyon metni",
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.5,
                        "text": "Merhaba arkadaşlar"
                    },
                    ...
                ],
                "language": "tr"
            }
        """
        self._load_whisper()

        if self._whisper_model is None:
            return {"text": "", "segments": [], "language": ""}

        # Whisper'ı thread'de çalıştır (blocking)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._whisper_model.transcribe(
                audio_path,
                language=language,
                task="transcribe",
                verbose=False,
            )
        )

        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            })

        return {
            "text": result.get("text", "").strip(),
            "segments": segments,
            "language": result.get("language", ""),
        }

    async def generate_srt(
        self,
        audio_path: str,
        output_path: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Optional[str]:
        """
        Ses dosyasından SRT altyazı dosyası oluşturur.

        Returns: SRT dosya yolu veya None.
        """
        transcription = await self.transcribe_audio(audio_path, language)

        if not transcription["segments"]:
            logger.warning("Transkripsiyon boş: %s", audio_path)
            return None

        if not output_path:
            base = Path(audio_path).stem
            output_path = str(SUBTITLES_DIR / f"{base}.srt")

        srt_content = self._segments_to_srt(transcription["segments"])

        Path(output_path).write_text(srt_content, encoding="utf-8")
        logger.info("SRT oluşturuldu: %s (%d segment)",
                     output_path, len(transcription["segments"]))

        return output_path

    def _segments_to_srt(self, segments: List[Dict]) -> str:
        """Segment listesini SRT formatına çevirir."""
        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_srt_time(seg["start"])
            end = self._format_srt_time(seg["end"])
            text = seg["text"]
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        return "\n".join(lines)

    def _format_srt_time(self, seconds: float) -> str:
        """Saniye -> SRT zaman formatı (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    async def burn_subtitles(
        self,
        video_path: str,
        srt_path: str,
        output_path: Optional[str] = None,
        style: Optional[str] = None,
    ) -> Optional[str]:
        """
        SRT altyazıyı videoya gömer (burn-in).
        FFmpeg subtitles filter kullanır.
        """
        if not output_path:
            base = Path(video_path).stem
            output_path = str(
                Path(video_path).parent / f"{base}_subtitled.mp4"
            )

        # Altyazı stili
        if not style:
            style = (
                "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,Outline=2,Shadow=1,"
                "MarginV=30"
            )

        # Windows path'leri düzelt (FFmpeg için)
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles={srt_escaped}:force_style='{style}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode == 0:
                logger.info("Altyazılı video oluşturuldu: %s", output_path)
                return output_path
            else:
                logger.error("Altyazı gömme hatası: %s",
                             stderr.decode()[:500])
                return None

        except asyncio.TimeoutError:
            logger.error("Altyazı gömme zaman aşımı")
            return None
        except Exception as e:
            logger.error("Altyazı gömme hatası: %s", e)
            return None

    async def process_clip_subtitles(
        self,
        video_path: str,
        language: Optional[str] = None,
        burn_in: bool = False,
        style: Optional[str] = None,
    ) -> Dict:
        """
        Klip için tam altyazı pipeline'ı:
        1. Ses çıkar
        2. Whisper ile transkripsiyon
        3. SRT oluştur
        4. (Opsiyonel) Videoya göm

        Returns:
            {
                "srt_path": str,
                "transcription": Dict,
                "subtitled_video_path": str or None
            }
        """
        from services.analysis.audio_analysis import clip_audio_analyzer

        # 1. Ses çıkar
        audio_path = await clip_audio_analyzer.extract_audio(video_path)
        if not audio_path:
            return {"srt_path": None, "transcription": {}, "subtitled_video_path": None}

        # 2+3. Transkripsiyon + SRT
        srt_path = await self.generate_srt(audio_path, language=language)
        transcription = await self.transcribe_audio(audio_path, language)

        # 4. Opsiyonel burn-in
        subtitled_path = None
        if burn_in and srt_path:
            subtitled_path = await self.burn_subtitles(
                video_path, srt_path, style=style
            )

        return {
            "srt_path": srt_path,
            "transcription": transcription,
            "subtitled_video_path": subtitled_path,
        }


# Singleton
subtitle_service = SubtitleService()
