"""
Gelişmiş altyazı motoru.
ASS formatında animasyonlu stiller, word-level timing, burn-in.
"""
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

SUBTITLES_DIR = Path("data/subtitles")
SUBTITLES_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class ASSStyle:
    """ASS stil tanımı."""
    name: str = "Default"
    fontname: str = "Arial"
    fontsize: int = 48
    primary_color: str = "&H00FFFFFF"    # &HAABBGGRR
    secondary_color: str = "&H000000FF"
    outline_color: str = "&H00000000"
    back_color: str = "&H80000000"
    bold: int = -1
    italic: int = 0
    underline: int = 0
    strikeout: int = 0
    scale_x: int = 100
    scale_y: int = 100
    spacing: float = 0
    angle: float = 0
    border_style: int = 1
    outline: float = 2.0
    shadow: float = 1.0
    alignment: int = 2   # 1-9 numpad (2=alt orta)
    margin_l: int = 20
    margin_r: int = 20
    margin_v: int = 30
    encoding: int = 1

    def to_ass(self) -> str:
        """ASS formatında stil satırı üretir."""
        return (
            f"Style: {self.name},"
            f"{self.fontname},{self.fontsize},"
            f"{self.primary_color},{self.secondary_color},"
            f"{self.outline_color},{self.back_color},"
            f"{self.bold},{self.italic},{self.underline},{self.strikeout},"
            f"{self.scale_x},{self.scale_y},{self.spacing},{self.angle},"
            f"{self.border_style},{self.outline},{self.shadow},"
            f"{self.alignment},{self.margin_l},{self.margin_r},{self.margin_v},"
            f"{self.encoding}"
        )


# Hazır stiller
STYLES = {
    "classic": ASSStyle(
        name="Classic", fontsize=48, bold=-1,
        outline=2.0, shadow=1.0, alignment=2,
    ),
    "modern": ASSStyle(
        name="Modern", fontsize=44, bold=-1, italic=0,
        outline=1.5, shadow=0, spacing=2, alignment=2,
    ),
    "bold": ASSStyle(
        name="Bold", fontsize=56, bold=-1,
        outline=3.0, shadow=2.0, alignment=2,
        primary_color="&H0000FFFF",  # Sarı
    ),
    "neon": ASSStyle(
        name="Neon", fontsize=52, bold=-1,
        outline=4.0, shadow=3.0, alignment=2,
        primary_color="&H00FF00FF",  # Neon pembe
        outline_color="&H000000FF",  # Kırmızı outline
    ),
    "minimal": ASSStyle(
        name="Minimal", fontsize=40, bold=0,
        outline=0, shadow=0, alignment=2,
        primary_color="&H00FFFFFF",
        back_color="&H80000000", border_style=3,
    ),
    "animated_pop": ASSStyle(
        name="AnimPop", fontsize=54, bold=-1,
        outline=3.0, shadow=2.0, alignment=2,
        primary_color="&H0000FFFF",  # Sarı
    ),
    "top_title": ASSStyle(
        name="TopTitle", fontsize=36, bold=-1,
        outline=2.0, shadow=1.0, alignment=8,  # üst orta
        margin_v=60,
    ),
    "bottom_small": ASSStyle(
        name="BottomSmall", fontsize=32, bold=0,
        outline=1.0, shadow=0, alignment=2,
        margin_v=20,
    ),
}


@dataclass
class ASSDialogue:
    """ASS diyalog satırı."""
    layer: int = 0
    start: float = 0.0
    end: float = 0.0
    style: str = "Default"
    name: str = ""
    margin_l: int = 0
    margin_r: int = 0
    margin_v: int = 0
    effect: str = ""
    text: str = ""

    def to_ass(self) -> str:
        """ASS formatında diyalog satırı üretir."""
        return (
            f"Dialogue: {self.layer},"
            f"{_fmt_time(self.start)},{_fmt_time(self.end)},"
            f"{self.style},{self.name},"
            f"{self.margin_l},{self.margin_r},{self.margin_v},"
            f"{self.effect},{self.text}"
        )


class AdvancedSubtitleEngine:
    """
    Gelişmiş altyazı motoru.
    ASS formatı, animasyonlu stiller, word-level timing, burn-in.
    """

    def __init__(self):
        self._styles = dict(STYLES)

    def generate_ass(
        self,
        entries: List[Dict],
        video_width: int = 1080,
        video_height: int = 1920,
        style_name: str = "classic",
        title: Optional[str] = None,
    ) -> str:
        """
        Entry listesinden ASS dosyası içeriği üretir.

        Args:
            entries: [{"text": str, "start": float, "end": float, "word_groups": [...]}]
            video_width: Video genişliği
            video_height: Video yüksekliği
            style_name: Stil adı
            title: Opsiyonel başlık (üstte gösterilir)
        """
        style = self._styles.get(style_name, STYLES["classic"])

        # PlayResX/Y ayarla (pixel-perfect positioning)
        style.scale_x = int(video_width / 1080 * 100)
        style.scale_y = int(video_height / 1920 * 100)

        lines = []
        lines.append("[Script Info]")
        lines.append("Title: Auto-Generated Subtitles")
        lines.append("ScriptType: v4.00+")
        lines.append(f"PlayResX: {video_width}")
        lines.append(f"PlayResY: {video_height}")
        lines.append("WrapStyle: 0")
        lines.append("ScaledBorderAndShadow: yes")
        lines.append("YCbCr Matrix: None")
        lines.append("")

        lines.append("[V4+ Styles]")
        lines.append("Format: Name, Fontname, Fontsize, PrimaryColour, "
                      "SecondaryColour, OutlineColour, BackColour, "
                      "Bold, Italic, Underline, StrikeOut, "
                      "ScaleX, ScaleY, Spacing, Angle, "
                      "BorderStyle, Outline, Shadow, "
                      "Alignment, MarginL, MarginR, MarginV, Encoding")
        lines.append(style.to_ass())

        # Başlık stili (farklı stil)
        if title:
            title_style = self._styles.get("top_title", STYLES["top_title"])
            lines.append(title_style.to_ass())

        lines.append("")

        lines.append("[Events]")
        lines.append("Format: Layer, Start, End, Style, Name, "
                      "MarginL, MarginR, MarginV, Effect, Text")

        # Başlık ekle
        if title:
            title_dial = ASSDialogue(
                start=0.0,
                end=min(5.0, entries[-1]["end"] if entries else 5.0),
                style="TopTitle",
                text=title.upper(),
            )
            lines.append(title_dial.to_ass())

        # Altyazı entry'leri
        for entry in entries:
            text = entry.get("text", "").strip()
            if not text:
                continue

            start = entry.get("start", 0.0)
            end = entry.get("end", 0.0)

            # Word-group bazlı animasyon
            word_groups = entry.get("word_groups", [])
            if word_groups:
                for wg in word_groups:
                    wg_text = wg.get("text", "")
                    wg_start = wg.get("start", start)
                    wg_end = wg.get("end", end)
                    anim = wg.get("animation", "")

                    ass_text = self._apply_animation(wg_text, anim)
                    dial = ASSDialogue(
                        start=wg_start,
                        end=wg_end,
                        style=style.name,
                        text=ass_text,
                    )
                    lines.append(dial.to_ass())
            else:
                dial = ASSDialogue(
                    start=start,
                    end=end,
                    style=style.name,
                    text=text,
                )
                lines.append(dial.to_ass())

        return "\n".join(lines)

    def generate_ass_from_whisper(
        self,
        whisper_segments: List[Dict],
        style_name: str = "classic",
        video_width: int = 1080,
        video_height: int = 1920,
        max_chars_per_line: int = 42,
        title: Optional[str] = None,
    ) -> str:
        """
        Whisper segmentlerinden ASS içeriği üretir.
        Word-level timing varsa kullanır.
        """
        entries = []
        for seg in whisper_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue

            start = seg.get("start", 0.0)
            end = seg.get("end", 0.0)
            words = seg.get("words", [])

            if words:
                lines = self._split_words_to_lines(words, max_chars_per_line)
                for line_text, line_start, line_end, word_groups in lines:
                    entries.append({
                        "text": line_text,
                        "start": line_start,
                        "end": line_end,
                        "word_groups": word_groups,
                    })
            else:
                entries.append({
                    "text": text,
                    "start": start,
                    "end": end,
                    "word_groups": [],
                })

        return self.generate_ass(
            entries, video_width, video_height, style_name, title
        )

    def save_ass(self, ass_content: str, output_path: str) -> str:
        """ASS dosyasını kaydeder."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(ass_content, encoding="utf-8-sig")
        logger.info("ASS kaydedildi: %s", output_path)
        return output_path

    async def burn_ass_subtitles(
        self,
        video_path: str,
        ass_path: str,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        """
        ASS altyazıyı videoya gömer (libass + HarfBuzz).
        """
        if not output_path:
            base = Path(video_path).stem
            output_path = str(
                Path(video_path).parent / f"{base}_subtitled.mp4"
            )

        # Windows path escape
        ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"ass={ass_escaped}",
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
                logger.info("ASS burn-in başarılı: %s", output_path)
                return output_path
            else:
                logger.error("ASS burn-in hatası: %s", stderr.decode()[:500])
                return None
        except Exception as e:
            logger.error("ASS burn-in hatası: %s", e)
            return None

    def build_srt_content(self, entries: List[Dict]) -> str:
        """Entry listesinden SRT içeriği üretir."""
        lines = []
        for i, entry in enumerate(entries, 1):
            start = self._fmt_srt_time(entry.get("start", 0))
            end = self._fmt_srt_time(entry.get("end", 0))
            text = entry.get("text", "").strip()
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")
        return "\n".join(lines)

    def register_style(self, name: str, style: ASSStyle):
        """Özel stil kaydeder."""
        self._styles[name] = style

    def get_available_styles(self) -> List[str]:
        """Mevcut stil isimlerini döndürür."""
        return list(self._styles.keys())

    # --- İç yardımcılar ---

    def _apply_animation(self, text: str, animation: str) -> str:
        """
        Metne ASS animasyon efekti uygular.

        Animasyon tipleri:
        - pop: Kelime kelime belirme
        - bounce: Zıplama
        - typewriter: Daktilo
        - glow: Parlama
        - shake: Sarsılma
        """
        if not animation:
            return text

        if animation == "pop":
            # Her harfe {\fscx150\fscy150} başlangıcı ekle
            return text

        elif animation == "bounce":
            # Zıplama efekti: {\move(0,10,0,0)}
            return f"{{\\move(0,10,0,0)}}{text}"

        elif animation == "typewriter":
            # Karakter karakter çıkma
            return text

        elif animation == "glow":
            # Glow efekti: {\3c&H00FFFF&}
            return f"{{\\3c&H00FFFF&\\bord4}}{text}"

        elif animation == "shake":
            # Sarsılma
            return f"{{\\frz2}}{text}{{\\frz-2}}"

        return text

    def _split_words_to_lines(
        self, words: List[Dict], max_chars: int
    ) -> List[Tuple[str, float, float, List[Dict]]]:
        """Kelimeleri satırlara böler, word-group bilgisi ile birlikte."""
        lines = []
        current_words = []
        current_text = []
        current_start = 0.0
        current_chars = 0

        for word in words:
            text = word.get("word", "").strip()
            if not text:
                continue

            start = word.get("start", 0.0)
            end = word.get("end", 0.0)

            if current_chars + len(text) + 1 > max_chars and current_words:
                line_text = " ".join(current_text)
                lines.append((
                    line_text,
                    current_start,
                    end,
                    list(current_words),
                ))
                current_words = []
                current_text = []
                current_chars = 0

            if not current_words:
                current_start = start

            current_words.append({
                "text": text,
                "start": start,
                "end": end,
                "animation": "",
            })
            current_text.append(text)
            current_chars += len(text) + 1

        if current_words:
            last_end = current_words[-1].get("end", current_start + 2)
            lines.append((
                " ".join(current_text),
                current_start,
                last_end,
                list(current_words),
            ))

        return lines

    def _fmt_srt_time(self, seconds: float) -> str:
        """Saniye -> SRT zaman formatı."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _fmt_time(seconds: float) -> str:
    """Saniye -> ASS zaman formatı (H:MM:SS.CC)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int((seconds % 1) * 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


# Singleton
advanced_subtitle = AdvancedSubtitleEngine()
