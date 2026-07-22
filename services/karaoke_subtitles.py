"""
Karaoke Altyazi Ureteci (ASS format)
opensource-clipping projesinden adaptasyon - word-by-word highlighting.

Transkripsiyon segmentlerinden Advanced SubStation Alpha (ASS) dosyasi uretir.
Iki mod: basit (kelime kelime reveal) ve advanced (kinetic typography).
"""
import logging
import math
import os
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class TypographyPlan:
    """Kelime basina tipografi plani."""
    word: str
    scale_level: int = 2
    animation: str = "none"
    emphasis: bool = False


@dataclass
class KaraokeConfig:
    """ASS altyazi konfigurasyonu."""
    play_res_x: int = 1920
    play_res_y: int = 1080
    font_name: str = "Arial"
    font_name_emphasis: str = "Arial Bold"
    font_size: int = 52
    font_size_vertical: int = 64
    primary_color: str = "&H00FFFFFF"
    outline_color: str = "&H00000000"
    shadow_color: str = "&H80000000"
    emphasis_color: str = "&H0000FFFF"
    outline_width: float = 3.0
    shadow_depth: float = 2.5
    alignment: int = 2
    margin_lr: int = 60
    margin_v_vertical: int = 120
    margin_v_horizontal: int = 60
    use_karaoke: bool = True
    use_advanced_text: bool = False
    scale_emphasis: int = 130
    line_spacing: int = 15


@dataclass
class TranscriptSegment:
    """Tek bir transkripsiyon segmenti."""
    start: float
    end: float
    text: str
    words: List[Dict[str, Any]] = field(default_factory=list)


def _fmt_ass_time(seconds: float) -> str:
    """Format seconds to ASS time format H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _is_vertical(aspect: str) -> bool:
    return aspect in ("9:16", "3:4", "4:5", "1:1")


def _wrap_text_to_lines(
    words: List[Dict[str, Any]],
    max_width: int,
    font_size: int,
    scale_map: Dict[str, int],
) -> List[List[Dict[str, Any]]]:
    """Kelime listesini satirlara boer (basit tahmini word-width)."""
    lines: List[List[Dict[str, Any]]] = []
    current_line: List[Dict[str, Any]] = []
    current_width = 0.0
    space_w = font_size * 0.3

    for w in words:
        word_text = w.get("word", "")
        clean = word_text.lower().strip(string.punctuation)
        scale = scale_map.get(clean, 100)
        char_width = font_size * (scale / 100.0) * 0.55
        word_width = len(word_text) * char_width * 0.95

        if current_line and current_width + space_w + word_width > max_width:
            lines.append(current_line)
            current_line = []
            current_width = 0

        offset = current_width if not current_line else current_width + space_w
        w_entry = {**w, "x_offset": offset, "scaled_width": word_width}
        current_line.append(w_entry)
        current_width = offset + word_width

    if current_line:
        lines.append(current_line)

    return lines


def generate_karaoke_ass(
    segments: List[TranscriptSegment],
    clip_start: float,
    clip_end: float,
    output_path: str,
    aspect: str = "9:16",
    config: Optional[KaraokeConfig] = None,
    typography_plans: Optional[List[TypographyPlan]] = None,
) -> str:
    """
    Karaoke etkili ASS altyazi dosyası uretir.

    Args:
        segments: Transkripsiyon segmentleri (kelime bazli zamanlama ile).
        clip_start: Klip baslangic zamani (saniye).
        clip_end: Klip bitis zamani (saniye).
        output_path: Cikis ASS dosya yolu.
        aspect: Goruntu oran ("9:16", "16:9", vb.)
        config: ASS konfigurasyonu (None ise varsayilan kullanilir).
        typography_plans: Kelime basina tipografi planlari (opsiyonel).

    Returns:
        Olusturulan ASS dosya yolu.
    """
    if config is None:
        config = KaraokeConfig()

    typo_map: Dict[str, TypographyPlan] = {}
    if typography_plans:
        for plan in typography_plans:
            typo_map[plan.word.lower().strip(string.punctuation)] = plan

    is_vert = _is_vertical(aspect)
    font_size = config.font_size_vertical if is_vert else config.font_size
    margin_lr = config.margin_lr
    margin_v = config.margin_v_vertical if is_vert else config.margin_v_horizontal
    play_res_x = config.play_res_x
    play_res_y = config.play_res_y
    scale_factor = play_res_y / (1920 if is_vert else 1080)
    font_size = int(font_size * scale_factor)
    margin_lr = int(margin_lr * scale_factor)
    margin_v = int(margin_v * scale_factor)
    outline_val = config.outline_width if config.use_karaoke else 0.2
    shadow_val = config.shadow_depth if config.use_karaoke else 0.2

    header = (
        "[Script Info]\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 1\n"
        "ScriptType: v4.00+\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, "
        "Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{config.font_name},{font_size},"
        f"{config.primary_color},{config.outline_color},{config.shadow_color},"
        f"0,0,0,0,100,100,0,0,1,{outline_val},{shadow_val},"
        f"{config.alignment},{margin_lr},{margin_lr},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines_content: List[str] = []
    lines_content.append(header)

    for seg in segments:
        seg_s = max(0, seg.start - clip_start)
        seg_e = min(clip_end - clip_start, seg.end - clip_start)
        if seg_s >= seg_e:
            continue

        words = seg.words if seg.words else [
            {"word": w, "start": seg.start + i * 0.3, "end": seg.start + (i + 1) * 0.3}
            for i, w in enumerate(seg.text.split())
        ]

        word_lines = _wrap_text_to_lines(
            words, play_res_x - margin_lr * 2, font_size,
            {p.word.lower().strip(string.punctuation): p.scale_level * 33 + 33
             for p in typography_plans or []}
        )

        for word_line in word_lines:
            for wi, w_data in enumerate(word_line):
                w_s = max(0, w_data["start"] - clip_start)
                if wi < len(word_line) - 1:
                    w_e = min(clip_end - clip_start, word_line[wi + 1]["start"] - clip_start)
                else:
                    w_e = min(clip_end - clip_start, w_data["end"] - clip_start)

                if w_s >= w_e:
                    continue

                clean = w_data["word"].lower().strip(string.punctuation)
                plan = typo_map.get(clean)

                if config.use_karaoke:
                    if plan and plan.emphasis:
                        color_tag = f"\\c{config.emphasis_color}"
                    else:
                        color_tag = "\\c&H00FFFF&"
                    event_text = (
                        f"{{\\an2\\pos({int(play_res_x // 2)},{int(play_res_y - margin_v)})"
                        f"\\fn{config.font_name}"
                        f"\\fscx{font_size}\\fscy{font_size}"
                        f"{color_tag}"
                        f"\\t({int(w_s * 1000)},{int(w_s * 1000)},\\c&H00FFFF&)"
                        f"\\t({int(w_e * 1000)},{int(w_e * 1000)},\\c&HFFFFFF&)"
                        f"}}{w_data['word']}"
                    )
                else:
                    alpha_tag = "\\alpha&H00&"
                    event_text = (
                        f"{{\\an2\\pos({int(play_res_x // 2)},{int(play_res_y - margin_v)})"
                        f"\\fn{config.font_name}"
                        f"\\fscx100\\fscy100"
                        f"{alpha_tag}"
                        f"}}{w_data['word']}"
                    )

                lines_content.append(
                    f"Dialogue: 0,{_fmt_ass_time(seg_s)},{_fmt_ass_time(seg_e)},"
                    f"Default,,0,0,0,,{event_text}\n"
                )

    Path(output_path).write_text("".join(lines_content), encoding="utf-8")
    logger.info("Karaoke ASS altyazi uretildi: %s", output_path)
    return output_path


def generate_simple_karaoke_ass(
    transcript_words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    output_path: str,
    aspect: str = "9:16",
    highlight_color: str = "&H0000FFFF",
) -> str:
    """
    Basit karaoke altyazi uretir — her kelimede onceki kelimeler acik, anlik kelim renk degistirir.

    transcript_words: [{"word": "Merhaba", "start": 1.2, "end": 1.6}, ...]
    """
    segments: List[TranscriptSegment] = []
    current_words: List[Dict] = []
    current_start = None

    for w in transcript_words:
        ws = w.get("start", 0)
        we = w.get("end", ws + 0.3)
        if current_start is None:
            current_start = ws
        current_words.append(w)
        if len(current_words) >= 8:
            segments.append(TranscriptSegment(
                start=current_start, end=we, text=" ".join(x["word"] for x in current_words),
                words=current_words[:],
            ))
            current_words = []
            current_start = None

    if current_words:
        segments.append(TranscriptSegment(
            start=current_start or 0,
            end=current_words[-1].get("end", 0),
            text=" ".join(x["word"] for x in current_words),
            words=current_words,
        ))

    config = KaraokeConfig(use_karaoke=True, use_advanced_text=False)
    return generate_karaoke_ass(
        segments, clip_start, clip_end, output_path, aspect, config
    )
