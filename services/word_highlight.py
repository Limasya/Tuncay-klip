"""
Kelime vurgulama motoru (karaoke tarzi).
Whisper kelime zamanlamasi ile ASS formatinda kelime kelime renk degisimi.
"""
import asyncio
import logging
import math
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

TEMP_DIR = Path("data/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class WordTiming:
    """Kelime zamanlama bilgisi."""
    word: str
    start: float
    end: float
    confidence: float = 1.0


class WordHighlightEngine:
    """
    Karaoke tarzi kelime vurgulama motoru.
    Whisper kelime zamanlamasi veya segment tabanli tahmini kullanir.
    Her kelimeyi zamanina gore farkli renge boyar.
    """

    # Vurgulama renk paletleri (ASS &HBBGGRR formatinda)
    COLOR_PALETTES = {
        "neon": {
            "highlighted": "&H0000FFFF",    # Sarı
            "default": "&H00FFFFFF",        # Beyaz
            "outline": "&H00FF00FF",        # Pembe outline
            "glow": "&H000080FF",           # Turuncu glow
        },
        "fire": {
            "highlighted": "&H000080FF",    # Turuncu
            "default": "&H00FFFFFF",
            "outline": "&H000000FF",        # Kirmizi
            "glow": "&H000040FF",
        },
        "ice": {
            "highlighted": "&H00FFFF00",    # Cyan
            "default": "&H00E0E0E0",        # Acik gri
            "outline": "&H00808080",
            "glow": "&H00FFD000",
        },
        "green": {
            "highlighted": "&H0000FF00",    # Yesil
            "default": "&H00FFFFFF",
            "outline": "&H00008000",
            "glow": "&H0000C000",
        },
        "purple": {
            "highlighted": "&H00FF00FF",    # Mor
            "default": "&H00FFFFFF",
            "outline": "&H00800080",
            "glow": "&H00CC00CC",
        },
        "classic": {
            "highlighted": "&H0000FFFF",    # Sarı
            "default": "&H00FFFFFF",
            "outline": "&H00000000",
            "glow": "&H0000B4FF",
        },
        "gradient": {
            "highlighted": "&H0000B4FF",    # Altin
            "default": "&H00808080",        # Gri
            "outline": "&H00000000",
            "glow": "&H000060C0",
        },
    }

    def __init__(self):
        self._palettes = dict(self.COLOR_PALETTES)
        self._whisper_model = None

    def _load_whisper(self):
        """Whisper modelini yukle (lazy loading)."""
        if self._whisper_model is not None:
            return True
        try:
            import whisper
            model_size = "base"
            try:
                from config import get_settings
                settings = get_settings()
                model_size = getattr(settings, "whisper_model_size", "base")
            except Exception as e:
                logger.debug("whisper_model_size config'ten okunamadı, 'base' kullanılıyor: %s", e)
            logger.info("Whisper modeli yukleniyor: %s", model_size)
            self._whisper_model = whisper.load_model(model_size)
            logger.info("Whisper modeli yuklendi.")
            return True
        except ImportError:
            logger.warning("openai-whisper yuklu degil, segment bazli zamanlama kullanilacak")
            return False
        except Exception as e:
            logger.error("Whisper yukleme hatasi: %s", e)
            return False

    async def extract_word_timings(
        self,
        audio_path: str,
        language: Optional[str] = None,
    ) -> List[WordTiming]:
        """
        Whisper ile kelime kelime zamanlama cikarir.

        word_timestamps=True ile her kelime icin ayri start/end degeri.
        Whisper mevcut degilse segment bazli tahmin yapar.
        """
        # Whisper dene
        if self._load_whisper() and self._whisper_model is not None:
            try:
                return await self._whisper_word_timings(audio_path, language)
            except Exception as e:
                logger.warning("Whisper kelime zamanlama hatasi: %s, fallback", e)

        # Fallback: segment bazli tahmin
        return await self._segment_based_timings(audio_path, language)

    async def _whisper_word_timings(
        self,
        audio_path: str,
        language: Optional[str],
    ) -> List[WordTiming]:
        """Whisper word_timestamps=True ile gercek kelime zamanlamasi."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._whisper_model.transcribe(
                audio_path,
                language=language,
                task="transcribe",
                verbose=False,
                word_timestamps=True,
            ),
        )

        words = []
        for segment in result.get("segments", []):
            for w in segment.get("words", []):
                word_text = w.get("word", "").strip()
                if not word_text:
                    continue
                words.append(WordTiming(
                    word=word_text,
                    start=w.get("start", 0.0),
                    end=w.get("end", 0.0),
                    confidence=w.get("probability", 0.9),
                ))

        logger.info("Whisper kelime zamanlama: %d kelime cikarildi", len(words))
        return words

    async def _segment_based_timings(
        self,
        audio_path: str,
        language: Optional[str],
    ) -> List[WordTiming]:
        """
        Segment bazli tahmini kelime zamanlamasi.
        Mevcut subtitle_service transkripsiyonunu kullanir,
        her segmenti kelimelerine bolup esit zaman araliginda dagitir.
        """
        try:
            from services.subtitle_service import subtitle_service
            transcription = await subtitle_service.transcribe_audio(
                audio_path, language=language
            )
        except Exception as e:
            logger.debug("Transcription failed for word highlighting: %s", e)
            return []

        words = []
        for seg in transcription.get("segments", []):
            text = seg.get("text", "").strip()
            if not text:
                continue
            seg_start = seg.get("start", 0.0)
            seg_end = seg.get("end", seg_start + 1.0)
            seg_words = text.split()
            if not seg_words:
                continue

            word_duration = (seg_end - seg_start) / len(seg_words)
            for i, w in enumerate(seg_words):
                w_start = seg_start + i * word_duration
                w_end = seg_start + (i + 1) * word_duration
                words.append(WordTiming(
                    word=w,
                    start=round(w_start, 3),
                    end=round(w_end, 3),
                    confidence=0.7,
                ))

        logger.info("Segment bazli kelime zamanlama: %d kelime", len(words))
        return words

    async def extract_timings_from_video(
        self,
        video_path: str,
        language: Optional[str] = None,
    ) -> List[WordTiming]:
        """
        Video dosyasindan kelime zamanlamasi cikarir.
        Once ses cikarir, sonra Whisper ile isler.
        """
        # Ses cikar
        ext = Path(video_path).suffix.lower()
        if ext in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv"):
            audio_path = await self._extract_audio(video_path)
            if not audio_path:
                return []
        else:
            audio_path = video_path

        words = await self.extract_word_timings(audio_path, language)

        # Gecici dosyayi temizle
        if audio_path != video_path:
            try:
                Path(audio_path).unlink(missing_ok=True)
            except Exception as e:
                logger.debug("Geçici audio dosyası silinemedi: %s", e)

        return words

    async def _extract_audio(self, video_path: str) -> Optional[str]:
        """Video dosyasindan ses cikarir."""
        out_path = str(TEMP_DIR / f"wh_audio_{Path(video_path).stem}.wav")
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
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

    # --- ASS Uretimi ---

    def generate_karaoke_ass(
        self,
        words: List[WordTiming],
        video_width: int = 1080,
        video_height: int = 1920,
        palette: str = "neon",
        font_size: int = 52,
        max_chars_per_line: int = 30,
        position: str = "bottom",
        outline: float = 3.0,
        shadow: float = 2.0,
    ) -> str:
        """
        Karaoke tarzi ASS dosyasi uretir.
        Her kelime zamanina gore renk degistirir.

        Uses ASS override tags:
        \\c&HBBGGRR& - rengi degistir
        \\kf<delay> - karaoke timing (renk kaymasi)
        \\fscx/fscy - olcek animasyonu
        \\move - konum degisikligi
        """
        colors = self._palettes.get(palette, self._palettes["neon"])

        lines = []
        lines.append("[Script Info]")
        lines.append("Title: Karaoke Word Highlight")
        lines.append("ScriptType: v4.00+")
        lines.append(f"PlayResX: {video_width}")
        lines.append(f"PlayResY: {video_height}")
        lines.append("WrapStyle: 0")
        lines.append("ScaledBorderAndShadow: yes")
        lines.append("YCbCr Matrix: TV.709")
        lines.append("")

        lines.append("[V4+ Styles]")
        lines.append(
            "Format: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        )

        # Ana stil
        align_map = {"top": 8, "center": 5, "bottom": 2}
        align = align_map.get(position, 2)

        lines.append(
            f"Style: Karaoke,Arial,{font_size},"
            f"{colors['default']},"
            f"{colors['highlighted']},"
            f"{colors['outline']},"
            f"&H80000000,"
            f"-1,0,0,0,"
            f"100,100,0,0,"
            f"1,{outline:.0f},{shadow:.0f},"
            f"{align},20,20,40,1"
        )

        # Highlighted stil (buyuk + parlak)
        lines.append(
            f"Style: Highlight,Arial,{font_size + 4},"
            f"{colors['highlighted']},"
            f"{colors['glow']},"
            f"{colors['outline']},"
            f"&H80000000,"
            f"-1,0,0,0,"
            f"105,105,0,0,"
            f"1,{outline + 1:.0f},{shadow + 1:.0f},"
            f"{align},20,20,40,1"
        )
        lines.append("")

        lines.append("[Events]")
        lines.append(
            "Format: Layer, Start, End, Style, Name, "
            "MarginL, MarginR, MarginV, Effect, Text"
        )

        # Kelimeleri satirlara bol
        word_lines = self._split_words_to_lines(words, max_chars_per_line)

        for line_words, line_start, line_end in word_lines:
            ass_text = self._build_karaoke_line(line_words, colors)
            start_str = self._fmt_time(line_start)
            end_str = self._fmt_time(line_end)

            lines.append(
                f"Dialogue: 0,{start_str},{end_str},Karaoke,,0,0,0,,{ass_text}"
            )

        return "\n".join(lines)

    def generate_word_highlight_filter(
        self,
        words: List[WordTiming],
        highlight_color: str = "yellow",
        unhighlight_color: str = "white",
        font_size: int = 48,
    ) -> str:
        """
        FFmpeg drawtext ile kelime vurgulama filter'i uretir.
        Zaman bazli renk degisimi (max 20 kelime).
        """
        if not words:
            return "null"

        filters = []
        for i, w in enumerate(words[:20]):
            # Her kelime icin enable araligi
            enable = f"between(t,{w.start:.3f},{w.end:.3f})"
            # X pozisyonu: Ortala (yaklasik)
            text_len = len(w.word)
            filters.append(
                f"drawtext=text='{w.word}':"
                f"fontsize={font_size}:"
                f"fontcolor={highlight_color}@{enable}:"
                f"x=(w-tw)/2:y=h-120"
            )

        return ",".join(filters) if filters else "null"

    def generate_bounce_animation(
        self,
        word: str,
        start_time: float,
        end_time: float,
        amplitude: float = 5.0,
    ) -> str:
        """Kelime icin ziplama animasyonu uretir."""
        return (
            f"{{\\move(0,0,0,-{amplitude:.0f})}}"
            f"{word}"
            f"{{\\move(0,-{amplitude:.0f},0,0)}}"
        )

    def generate_pop_animation(
        self,
        word: str,
        start_time: float,
        scale_from: float = 0.5,
        scale_to: float = 1.2,
    ) -> str:
        """Kelime icin pop animasyonu uretir."""
        return (
            f"{{\\fscx{int(scale_from*100)}\\fscy{int(scale_from*100)}}}"
            f"{word}"
            f"{{\\fscx{int(scale_to*100)}\\fscy{int(scale_to*100)}}}"
            f"{{\\fscx100\\fscy100}}"
        )

    def generate_wave_animation(
        self,
        text: str,
        start_time: float,
        wave_speed: float = 3.0,
        wave_height: float = 10.0,
    ) -> str:
        """Dalga animasyonu (harf harf yukari-asagi)."""
        result = []
        for i, char in enumerate(text):
            result.append(
                f"{{\\move(0,0,0,-{wave_height:.0f})}}"
                f"{char}"
                f"{{\\move(0,-{wave_height:.0f},0,0)}}"
            )
        return "".join(result)

    def _build_karaoke_line(
        self,
        words: List[WordTiming],
        colors: Dict,
    ) -> str:
        """
        Tek satir kelime icin karaoke ASS text'i uretir.
        Modern TikTok stili: aktif kelime aninda buyur ve rengi parlar, sonra eski haline spring ile kuculur.
        \\t(start, end, ...) ile kelime bazli zamanlanmis animasyonlar.
        """
        parts = []
        if not words:
            return ""
            
        line_start = words[0].start
        
        for w in words:
            # Saniyeyi milisaniyeye (ms) cevir
            t_start = int((w.start - line_start) * 1000)
            t_end = int((w.end - line_start) * 1000)
            
            # Animasyon suresi
            spring_duration = min(150, max(50, t_end - t_start))
            t_spring = t_start + spring_duration
            
            # Orijinal renk
            c_default = colors['default']
            c_high = colors['highlighted']
            
            # \t(t1,t2,...) transform etiketleri ile zamanlanmis tetikleme
            # 1. Kelimenin baslangicinda aniden renk degisir ve %115 buyur
            # 2. t_start'tan t_spring'e kadar yavasca %100'e ve default renge doner
            part1 = f"\\t({t_start},{t_start},\\c{c_high}\\fscx115\\fscy115)"
            part2 = f"\\t({t_start},{t_spring},\\c{c_default}\\fscx100\\fscy100)"
            tag = f"{{{part1}{part2}}}"
            
            parts.append(f"{tag}{w.word}")

        return " ".join(parts)

    def _split_words_to_lines(
        self,
        words: List[WordTiming],
        max_chars: int,
    ) -> List[Tuple[List[WordTiming], float, float]]:
        """Kelimeleri satirlara boler."""
        lines = []
        current_line = []
        current_chars = 0
        line_start = 0.0

        for w in words:
            if current_chars + len(w.word) + 1 > max_chars and current_line:
                lines.append((
                    list(current_line),
                    line_start,
                    current_line[-1].end,
                ))
                current_line = []
                current_chars = 0

            if not current_line:
                line_start = w.start

            current_line.append(w)
            current_chars += len(w.word) + 1

        if current_line:
            lines.append((
                current_line,
                line_start,
                current_line[-1].end,
            ))

        return lines

    def _fmt_time(self, seconds: float) -> str:
        """Saniye -> ASS zaman formati."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centiseconds = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


# Singleton
word_highlight = WordHighlightEngine()
