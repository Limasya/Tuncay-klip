"""
Kelime vurgulama motoru (karaoke tarzı).
ASS formatında kelime kelime renk değişimi animasyonu.
"""
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class WordTiming:
    """Kelime zamanlama bilgisi."""
    word: str
    start: float
    end: float
    confidence: float = 1.0


class WordHighlightEngine:
    """
    Karaoke tarzı kelime vurgulama motoru.
    Her kelimeyi zamanına göre farklı renge boyar.
    """

    # Vurgulama renk paletleri
    COLOR_PALETTES = {
        "neon": {
            "highlighted": "&H0000FFFF",    # Sarı
            "default": "&H00FFFFFF",        # Beyaz
            "outline": "&H00FF00FF",        # Pembe outline
        },
        "fire": {
            "highlighted": "&H000080FF",    # Turuncu
            "default": "&H00FFFFFF",
            "outline": "&H000000FF",        # Kırmızı
        },
        "ice": {
            "highlighted": "&H00FFFF00",    # Cyan
            "default": "&H00E0E0E0",        # Açık gri
            "outline": "&H00808080",
        },
        "green": {
            "highlighted": "&H0000FF00",    # Yeşil
            "default": "&H00FFFFFF",
            "outline": "&H00008000",
        },
        "purple": {
            "highlighted": "&H00FF00FF",    # Mor
            "default": "&H00FFFFFF",
            "outline": "&H00800080",
        },
        "classic": {
            "highlighted": "&H0000FFFF",    # Sarı
            "default": "&H00FFFFFF",
            "outline": "&H00000000",
        },
        "gradient": {
            "highlighted": "&H0000B4FF",    # Altın
            "default": "&H00808080",        # Gri
            "outline": "&H00000000",
        },
    }

    def __init__(self):
        self._palettes = dict(self.COLOR_PALETTES)

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
        Karaoke tarzı ASS dosyası üretir.
        Her kelime zamanına göre renk değiştirir.

        Uses ASS override tags:
        {\c&H00FFFF&} - rengi değiştir
        {\kf} - karaoke timing
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
        lines.append("")

        lines.append("[V4+ Styles]")
        lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, "
                      "SecondaryColour, OutlineColour, BackColour, "
                      "Bold, Italic, Underline, StrikeOut, "
                      "ScaleX, ScaleY, Spacing, Angle, "
                      "BorderStyle, Outline, Shadow, "
                      "Alignment, MarginL, MarginR, MarginV, Encoding")

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
        lines.append("")

        lines.append("[Events]")
        lines.append("Format: Layer, Start, End, Style, Name, "
                      "MarginL, MarginR, MarginV, Effect, Text")

        # Kelimeleri satırlara böl
        word_lines = self._split_words_to_lines(words, max_chars_per_line)

        for line_words, line_start, line_end in word_lines:
            # Her satır için karaoke efekti
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
    ) -> str:
        """
        FFmpeg drawtext ile kelime vurgulama filter'ı üretir.
        Basitleştirilmiş: zaman bazlı renk değişimi.
        """
        if not words:
            return "null"

        # Her kelime için ayrı drawtext (çok fazla filter olabilir)
        # Basitleştirilmiş: sadece ilk 10 kelime
        filters = []
        for i, w in enumerate(words[:10]):
            opacity = f"between(t,{w.start:.3f},{w.end:.3f})"
            filters.append(
                f"drawtext=text='{w.word}':"
                f"fontsize=48:"
                f"fontcolor={highlight_color}@{opacity}:"
                f"x=(w-tw)/2:y=h-100"
            )

        return ",".join(filters) if filters else "null"

    def generate_bounce_animation(
        self,
        word: str,
        start_time: float,
        end_time: float,
        amplitude: float = 5.0,
    ) -> str:
        """
        Kelime için zıplama animasyonu üretir.
        """
        duration = end_time - start_time
        frames = int(duration * 25)

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
        """
        Kelime için pop animasyonu üretir.
        """
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
        """
        Dalga animasyonu (harf harf yukarı-aşağı).
        """
        result = []
        for i, char in enumerate(text):
            delay = i * 0.05  # Her harf için 50ms gecikme
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
        Tek satır kelime için karaoke ASS text'i üretir.

        \\kf<delay> formatı kullanır:
        - Renk, delay süresince highlighted rengine geçer
        - Sonra default renge döner
        """
        parts = []
        for i, w in enumerate(words):
            delay_cs = int((w.end - w.start) * 100)  # Centiseconds

            # Renk değişimi
            parts.append(f"{{\\c{colors['highlighted']}}}{w.word}")
            parts.append(f"{{\\c{colors['default']}}}")

        return " ".join(parts)

    def _split_words_to_lines(
        self,
        words: List[WordTiming],
        max_chars: int,
    ) -> List[Tuple[List[WordTiming], float, float]]:
        """Kelimeleri satırlara böler."""
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
        """Saniye -> ASS zaman formatı."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        centiseconds = int((seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


# Singleton
word_highlight = WordHighlightEngine()
