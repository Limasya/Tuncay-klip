"""Layered video compositor and gap analysis for the NLE timeline.

This module provides:
- Layer composition with blend modes (normal, multiply, screen, overlay, etc.)
- Dirty region tracking for incremental re-rendering
- Gap analysis for timeline tracks
- FFmpeg filter graph generation for multi-layer compositing

The compositor bridges the timeline model (RationalTime/Track/Track)
to the render pipeline's FFmpeg filter graph generation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from services.timeline_engine import RationalTime, TimeRange, Timeline, Track, TrackType


class BlendMode(str, Enum):
    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    DARKEN = "darken"
    LIGHTEN = "lighten"
    ADD = "add"
    SUBTRACT = "subtract"
    DIFFERENCE = "difference"
    EXCLUSION = "exclusion"
    SOFT_LIGHT = "soft_light"
    HARD_LIGHT = "hard_light"
    COLOR_DODGE = "color_dodge"
    COLOR_BURN = "color_burn"


BLEND_TO_FFMPEG: Dict[BlendMode, str] = {
    BlendMode.NORMAL: "overlay",
    BlendMode.MULTIPLY: "multiply",
    BlendMode.SCREEN: "screen",
    BlendMode.OVERLAY: "overlay",
    BlendMode.DARKEN: "darken",
    BlendMode.LIGHTEN: "lighten",
    BlendMode.ADD: "blend_all_mode=addition",
    BlendMode.SUBTRACT: "blend_all_mode=subtraction",
    BlendMode.DIFFERENCE: "blend_all_mode=difference",
    BlendMode.EXCLUSION: "blend_all_mode=exclusion",
    BlendMode.SOFT_LIGHT: "blend_all_mode=softlight",
    BlendMode.HARD_LIGHT: "blend_all_mode=hardlight",
    BlendMode.COLOR_DODGE: "blend_all_mode=colordodge",
    BlendMode.COLOR_BURN: "blend_all_mode=colorburn",
}


class AlphaMode(str, Enum):
    PREMULTIPLIED = "premultiplied"
    STRAIGHT = "straight"


@dataclass
class Transform2D:
    """2D affine transform for a compositing layer."""

    x: float = 0.0
    y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotation: float = 0.0
    anchor_x: float = 0.5
    anchor_y: float = 0.5

    def to_ffmpeg_overlay(self) -> str:
        return f"overlay={self.x}:{self.y}"

    def to_ffmpeg_scale(self, target_w: int, target_h: int) -> str:
        w = int(target_w * self.scale_x)
        h = int(target_h * self.scale_y)
        return f"scale={w}:{h}"

    def is_identity(self) -> bool:
        return (
            self.x == 0.0
            and self.y == 0.0
            and self.scale_x == 1.0
            and self.scale_y == 1.0
            and self.rotation == 0.0
        )


@dataclass
class DirtyRegion:
    """A rectangular region that needs re-composition."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0

    @property
    def area(self) -> int:
        return self.width * self.height

    def intersects(self, other: "DirtyRegion") -> bool:
        return (
            self.x < other.x + other.width
            and self.x + self.width > other.x
            and self.y < other.y + other.height
            and self.y + self.height > other.y
        )

    def merge(self, other: "DirtyRegion") -> "DirtyRegion":
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x + self.width, other.x + other.width)
        y2 = max(self.y + self.height, other.y + other.height)
        return DirtyRegion(x1, y1, x2 - x1, y2 - y1)


@dataclass
class CompositeLayer:
    """A single layer in the compositing stack."""

    layer_id: str = field(default_factory=lambda: str(uuid4()))
    source_clip_id: Optional[str] = None
    source_path: Optional[str] = None
    transform: Transform2D = field(default_factory=Transform2D)
    opacity: float = 1.0
    blend_mode: BlendMode = BlendMode.NORMAL
    alpha_mode: AlphaMode = AlphaMode.PREMULTIPLIED
    crop_rect: Optional[Tuple[int, int, int, int]] = None
    visible: bool = True
    z_order: int = 0
    time_range: Optional[TimeRange] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CompositorConfig:
    """Configuration for the compositing engine."""

    width: int = 1920
    height: int = 1080
    pixel_format: str = "yuv420p"
    color_space: str = "bt709"
    max_layers: int = 100
    use_gpu: bool = False


class LayerCompositor:
    """Manages a stack of compositing layers and produces FFmpeg filter graphs.

    The compositor reads Timeline tracks (VIDEO type only) and converts
    overlapping or stacked clips into an FFmpeg filter_complex chain.
    """

    def __init__(self, config: Optional[CompositorConfig] = None) -> None:
        self._config = config or CompositorConfig()
        self._layers: List[CompositeLayer] = []
        self._dirty_regions: List[DirtyRegion] = []

    @property
    def config(self) -> CompositorConfig:
        return self._config

    @property
    def layers(self) -> List[CompositeLayer]:
        return list(self._layers)

    @property
    def dirty_regions(self) -> List[DirtyRegion]:
        return list(self._dirty_regions)

    def add_layer(self, layer: CompositeLayer) -> None:
        if len(self._layers) >= self._config.max_layers:
            raise ValueError(
                f"Layer limit reached ({self._config.max_layers})"
            )
        self._layers.append(layer)
        if layer.source_clip_id:
            self._dirty_regions.append(
                DirtyRegion(0, 0, self._config.width, self._config.height)
            )

    def remove_layer(self, layer_id: str) -> bool:
        for i, layer in enumerate(self._layers):
            if layer.layer_id == layer_id:
                self._layers.pop(i)
                self._dirty_regions.append(
                    DirtyRegion(0, 0, self._config.width, self._config.height)
                )
                return True
        return False

    def clear(self) -> None:
        self._layers.clear()
        self._dirty_regions.clear()

    def mark_clean(self) -> None:
        self._dirty_regions.clear()

    def build_filter_graph(
        self,
        timeline: Optional[Timeline] = None,
    ) -> str:
        """Build an FFmpeg filter_complex string for layer compositing.

        If a Timeline is provided, layers are derived from its video tracks.
        Otherwise, the manually-added layers are used.

        Returns an FFmpeg filter_complex string (without the -filter_complex prefix).
        Returns an empty string when compositing is not needed.
        """
        layers = self._layers
        if timeline is not None:
            layers = self._timeline_to_layers(timeline)

        visible = [l for l in layers if l.visible and l.opacity > 0.0]
        if len(visible) <= 1:
            return ""

        visible.sort(key=lambda l: l.z_order)
        return self._build_overlay_chain(visible)

    def _timeline_to_layers(self, timeline: Timeline) -> List[CompositeLayer]:
        """Convert Timeline video tracks to CompositeLayers.

        Video tracks are ordered by their track.order value.
        Within each track, clips are non-overlapping (enforced by Track).
        Multiple video tracks overlap spatially and need compositing.
        """
        layers: List[CompositeLayer] = []
        video_tracks = [
            t for t in timeline.tracks
            if t.track_type == TrackType.VIDEO and t.visible
        ]
        video_tracks.sort(key=lambda t: t.order)

        for track in video_tracks:
            for clip in track.clips:
                if not clip.enabled:
                    continue
                layer = CompositeLayer(
                    source_clip_id=clip.clip_id,
                    source_path=clip.asset_path,
                    opacity=clip.opacity,
                    time_range=clip.record_range,
                    z_order=track.order,
                    metadata={"clip_name": clip.name},
                )
                layers.append(layer)
        return layers

    def _build_overlay_chain(self, layers: List[CompositeLayer]) -> str:
        """Build sequential overlay filters: [0:v][1:v]overlay...[tmp]; [tmp][2:v]overlay...[out].

        Each layer except the first is overlaid on top of the previous result.
        """
        if len(layers) <= 1:
            return ""

        parts: List[str] = []
        prev_label = "v0"

        for i in range(1, len(layers)):
            layer = layers[i]
            out_label = f"v{i}" if i < len(layers) - 1 else "vout"

            overlay_expr = layer.transform.to_ffmpeg_overlay()
            opacity_val = layer.opacity
            blend = layer.blend_mode

            if opacity_val < 1.0 or blend != BlendMode.NORMAL:
                if opacity_val < 1.0 and blend == BlendMode.NORMAL:
                    parts.append(
                        f"[{prev_label}][{i}:v]format=yuva420p,"
                        f"colorchannelmixer=aa={opacity_val:.2f},"
                        f"{overlay_expr}[{out_label}]"
                    )
                elif blend in (BlendMode.MULTIPLY, BlendMode.SCREEN):
                    ffmpeg_blend = BLEND_TO_FFMPEG.get(blend, "overlay")
                    parts.append(
                        f"[{prev_label}][{i}:v]{ffmpeg_blend}[{out_label}]"
                    )
                else:
                    parts.append(
                        f"[{prev_label}][{i}:v]{overlay_expr}[{out_label}]"
                    )
            else:
                parts.append(
                    f"[{prev_label}][{i}:v]{overlay_expr}[{out_label}]"
                )

            prev_label = out_label

        return ";".join(parts)

    def get_composite_count(self, timeline: Timeline) -> int:
        """Count how many video tracks need compositing (layers > 1)."""
        video_tracks = [
            t for t in timeline.tracks
            if t.track_type == TrackType.VIDEO
            and t.visible
            and t.clips
        ]
        return len(video_tracks)


@dataclass
class GapInfo:
    """Describes a gap (empty region) on a timeline track."""

    track_id: str
    track_name: str
    gap_start: RationalTime
    gap_end: RationalTime

    @property
    def duration(self) -> RationalTime:
        return self.gap_end - self.gap_start

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "track_name": self.track_name,
            "gap_start": self.gap_start.to_dict(),
            "gap_end": self.gap_end.to_dict(),
            "duration": self.duration.to_dict(),
        }


def analyze_gaps(timeline: Timeline) -> List[GapInfo]:
    """Analyze all tracks and return a list of gaps (empty regions).

    A gap is the space between the end of one clip and the start of the next,
    or before the first clip / after the last clip relative to the timeline duration.
    """
    gaps: List[GapInfo] = []
    tl_duration = timeline.duration
    if tl_duration == RationalTime.zero():
        return gaps

    for track in timeline.tracks:
        if not track.clips:
            continue
        sorted_clips = sorted(
            track.clips, key=lambda c: c.record_range.start.value
        )

        if sorted_clips[0].record_range.start > RationalTime.zero():
            gaps.append(GapInfo(
                track_id=track.track_id,
                track_name=track.name,
                gap_start=RationalTime.zero(),
                gap_end=sorted_clips[0].record_range.start,
            ))

        for i in range(len(sorted_clips) - 1):
            gap_start = sorted_clips[i].record_range.end
            gap_end = sorted_clips[i + 1].record_range.start
            if gap_end > gap_start:
                gaps.append(GapInfo(
                    track_id=track.track_id,
                    track_name=track.name,
                    gap_start=gap_start,
                    gap_end=gap_end,
                ))

        last_end = sorted_clips[-1].record_range.end
        if last_end < tl_duration:
            gaps.append(GapInfo(
                track_id=track.track_id,
                track_name=track.name,
                gap_start=last_end,
                gap_end=tl_duration,
            ))

    return gaps


def has_gaps(timeline: Timeline) -> bool:
    """Quick check: does any video track have gaps?"""
    for track in timeline.tracks:
        if track.track_type != TrackType.VIDEO or not track.clips:
            continue
        sorted_clips = sorted(
            track.clips, key=lambda c: c.record_range.start.value
        )
        if sorted_clips[0].record_range.start > RationalTime.zero():
            return True
        for i in range(len(sorted_clips) - 1):
            if sorted_clips[i].record_range.end < sorted_clips[i + 1].record_range.start:
                return True
    return False


def fill_gaps_with_color(
    timeline: Timeline,
    color: str = "0x000000",
) -> List[Dict[str, Any]]:
    """Return a list of FFmpeg lavfi color source specs to fill gaps.

    Each entry is suitable for use as an FFmpeg input:
      {"filter": "color=c=black:s=1920x1080:d=2.5:r=30", "duration": RationalTime}
    """
    gaps = analyze_gaps(timeline)
    specs: List[Dict[str, Any]] = []
    for gap in gaps:
        d = gap.duration.to_seconds()
        if d <= 0:
            continue
        specs.append({
            "filter": (
                f"color=c={color}"
                f":s={timeline.width}x{timeline.height}"
                f":d={d}"
                f":r={timeline.fps}"
            ),
            "duration": gap.duration,
            "gap": gap,
        })
    return specs
