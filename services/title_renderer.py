"""Title and subtitle track renderer for the NLE timeline.

Provides:
- SRT subtitle generation from timeline title tracks
- ASS/SSA subtitle generation with styling
- FFmpeg drawtext filter generation for simple titles
- Title/subtitle template presets
- Word-level highlight timing for karaoke-style subtitles
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from services.timeline_engine import (
    RationalTime,
    TimeRange,
    Timeline,
    TimelineClip,
    TrackType,
)


class SubtitleFormat(str, Enum):
    SRT = "srt"
    ASS = "ass"
    WEBVTT = "webvtt"


class TitlePosition(str, Enum):
    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"
    CUSTOM = "custom"


class TitleStyle(str, Enum):
    CLASSIC = "classic"
    MODERN = "modern"
    BOLD = "bold"
    NEON = "neon"
    MINIMAL = "minimal"
    ANIMATED_POP = "animated_pop"


@dataclass
class SubtitleEntry:
    """A single subtitle line with timing and style."""

    index: int = 0
    text: str = ""
    start: RationalTime = field(default_factory=lambda: RationalTime.zero())
    end: RationalTime = field(
        default_factory=lambda: RationalTime(1, 1)
    )
    style: TitleStyle = TitleStyle.CLASSIC
    font_size: int = 48
    color: str = "#FFFFFF"
    bg_color: Optional[str] = None
    position: TitlePosition = TitlePosition.BOTTOM
    margin_v: int = 30
    word_timings: List[Tuple[str, RationalTime, RationalTime]] = field(
        default_factory=list
    )

    @property
    def duration(self) -> RationalTime:
        return self.end - self.start

    def to_srt_time(self, t: RationalTime) -> str:
        total_seconds = t.to_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        millis = int((total_seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    def to_ass_time(self, t: RationalTime) -> str:
        total_seconds = t.to_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        seconds = int(total_seconds % 60)
        centis = int((total_seconds % 1) * 100)
        return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "text": self.text,
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "style": self.style.value,
            "font_size": self.font_size,
            "color": self.color,
            "bg_color": self.bg_color,
            "position": self.position.value,
        }


def _hex_to_ass_color(hex_color: str) -> str:
    """Convert #RRGGBB to ASS &HBBGGRR& format."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H00{b:02X}{g:02X}{r:02X}&"


class SubtitleRenderer:
    """Generate subtitle files and FFmpeg filters from timeline title clips."""

    def __init__(self, fps: Fraction = Fraction(30, 1)) -> None:
        self._fps = fps
        self._entries: List[SubtitleEntry] = []

    @property
    def entries(self) -> List[SubtitleEntry]:
        return list(self._entries)

    def add_entry(self, entry: SubtitleEntry) -> None:
        entry.index = len(self._entries) + 1
        self._entries.append(entry)

    def clear(self) -> None:
        self._entries.clear()

    def from_timeline(self, timeline: Timeline) -> int:
        """Extract subtitle entries from title tracks in a timeline.

        Returns the number of entries extracted.
        """
        self._entries.clear()
        count = 0
        for track in timeline.tracks:
            if track.track_type != TrackType.TITLE:
                continue
            for clip in track.clips:
                if not clip.enabled:
                    continue
                text = clip.metadata.get("text", clip.name)
                entry = SubtitleEntry(
                    text=text,
                    start=clip.record_range.start,
                    end=clip.record_range.end,
                    font_size=int(clip.metadata.get("font_size", 48)),
                    color=clip.metadata.get("color", "#FFFFFF"),
                    position=TitlePosition(
                        clip.metadata.get("position", "bottom")
                    ),
                )
                self.add_entry(entry)
                count += 1
        return count

    def render_srt(self) -> str:
        """Render subtitles in SRT format."""
        lines: List[str] = []
        for i, entry in enumerate(self._entries, 1):
            start_ts = entry.to_srt_time(entry.start)
            end_ts = entry.to_srt_time(entry.end)
            lines.append(str(i))
            lines.append(f"{start_ts} --> {end_ts}")
            lines.append(entry.text)
            lines.append("")
        return "\n".join(lines)

    def render_ass(
        self,
        title: str = "NLE Subtitles",
        play_res_x: int = 1920,
        play_res_y: int = 1080,
    ) -> str:
        """Render subtitles in ASS (Advanced SubStation Alpha) format."""
        header = (
            "[Script Info]\n"
            f"Title: {title}\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {play_res_x}\n"
            f"PlayResY: {play_res_y}\n"
            "WrapStyle: 0\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, "
            "SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
            "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
            "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, "
            "MarginV, Encoding\n"
        )

        styles: List[str] = []
        for style in TitleStyle:
            fs = 48 if style == TitleStyle.CLASSIC else 52
            bold = 1 if style in (TitleStyle.BOLD, TitleStyle.ANIMATED_POP) else 0
            outline = 3 if style in (TitleStyle.CLASSIC, TitleStyle.BOLD) else 2
            styles.append(
                f"Style: {style.value},Arial,{fs},"
                f"&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
                f"{bold},0,0,0,100,100,0,0,"
                f"1,{outline},1,2,10,10,30,1"
            )

        events_header = "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"

        events: List[str] = []
        for entry in self._entries:
            start = entry.to_ass_time(entry.start)
            end = entry.to_ass_time(entry.end)
            style = entry.style.value
            color = _hex_to_ass_color(entry.color)

            text = entry.text.replace("\n", "\\N")

            if entry.word_timings and style == "animated_pop":
                text = self._build_karaoke_text(entry)

            events.append(
                f"Dialogue: 0,{start},{end},{style},,0,0,0,,{color}{text}"
            )

        return header + "\n".join(styles) + events_header + "\n".join(events)

    def _build_karaoke_text(self, entry: SubtitleEntry) -> str:
        """Build ASS karaoke text with word-level highlighting."""
        parts: List[str] = []
        for word, w_start, w_end in entry.word_timings:
            duration_cs = int((w_end - w_start).to_seconds() * 100)
            parts.append(f"{{\\kf{duration_cs}}}{word}")
        return " ".join(parts)

    def build_drawtext_filters(
        self,
        timeline_width: int = 1920,
        timeline_height: int = 1080,
    ) -> List[str]:
        """Build FFmpeg drawtext filter strings for each subtitle entry.

        Returns a list of drawtext filter strings that can be chained
        in a video filter graph.
        """
        filters: List[str] = []
        for entry in self._entries:
            text_escaped = entry.text.replace("'", "'\\''").replace(":", "\\:")
            x = "w/2-tw/2"
            y_map = {
                TitlePosition.TOP: "h*0.1",
                TitlePosition.CENTER: "h/2-th/2",
                TitlePosition.BOTTOM: "h-th-h*0.05",
            }
            y = y_map.get(entry.position, "h-th-h*0.05")
            fontcolor = entry.color
            fontsize = entry.font_size

            drawtext = (
                f"drawtext=text='{text_escaped}'"
                f":fontsize={fontsize}"
                f":fontcolor={fontcolor}"
                f":x={x}"
                f":y={y}"
                f":enable='between(t,{entry.start.to_seconds():.3f},{entry.end.to_seconds():.3f})'"
            )

            if entry.bg_color:
                drawtext += f":box=1:boxcolor={entry.bg_color}@0.6:boxborderw=5"

            filters.append(drawtext)

        return filters

    def build_word_highlight_filters(
        self,
        entry: SubtitleEntry,
        timeline_width: int = 1920,
        timeline_height: int = 1080,
    ) -> List[str]:
        """Build per-word drawtext filters for karaoke-style highlighting.

        Each word gets its own drawtext with precise enable timing.
        """
        if not entry.word_timings:
            return []

        filters: List[str] = []
        base_y = "h-th-h*0.05"

        words_text = " ".join(w for w, _, _ in entry.word_timings)
        full_text_escaped = words_text.replace("'", "'\\''").replace(":", "\\:")

        filters.append(
            f"drawtext=text='{full_text_escaped}'"
            f":fontsize={entry.font_size}"
            f":fontcolor={entry.color}@0.3"
            f":x=w/2-tw/2"
            f":y={base_y}"
            f":enable='between(t,{entry.start.to_seconds():.3f},{entry.end.to_seconds():.3f})'"
        )

        for word, w_start, w_end in entry.word_timings:
            word_escaped = word.replace("'", "'\\''").replace(":", "\\:")
            filters.append(
                f"drawtext=text='{word_escaped}'"
                f":fontsize={entry.font_size}"
                f":fontcolor={entry.color}"
                f":x=w/2-tw/2"
                f":y={base_y}"
                f":enable='between(t,{w_start.to_seconds():.3f},{w_end.to_seconds():.3f})'"
            )

        return filters


TITLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "classic_bottom": {
        "position": "bottom",
        "font_size": 48,
        "color": "#FFFFFF",
        "style": "classic",
    },
    "modern_top": {
        "position": "top",
        "font_size": 36,
        "color": "#FFFFFF",
        "style": "modern",
    },
    "bold_center": {
        "position": "center",
        "font_size": 72,
        "color": "#FFFFFF",
        "style": "bold",
    },
    "neon_bottom": {
        "position": "bottom",
        "font_size": 52,
        "color": "#00FF88",
        "style": "neon",
    },
    "minimal_small": {
        "position": "bottom",
        "font_size": 28,
        "color": "#CCCCCC",
        "style": "minimal",
    },
    "animated_pop": {
        "position": "bottom",
        "font_size": 56,
        "color": "#FFFFFF",
        "style": "animated_pop",
    },
}


def get_title_preset(name: str) -> Optional[Dict[str, Any]]:
    """Get a named title preset."""
    return TITLE_PRESETS.get(name)
