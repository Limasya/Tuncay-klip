"""Extended transition effects engine for the NLE timeline.

Provides:
- Extended TransitionType enum aligned with SDD (20 values)
- FFmpeg xfade filter mapping for all transition types
- Transition graph builder for sequential pairwise transitions
- Transition overlap calculation and alignment

The transition engine bridges Timeline clips to FFmpeg filter_complex
generation for smooth inter-clip transitions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from services.edit_spec import TransitionType as LegacyTransitionType
from services.timeline_engine import RationalTime, TimeRange, Timeline, Track, TrackType


class TransitionAlignment(str, Enum):
    CENTER = "center"
    START = "start"
    END = "end"


class EasingType(str, Enum):
    LINEAR = "linear"
    EASE_IN = "ease_in"
    EASE_OUT = "ease_out"
    EASE_IN_OUT = "ease_in_out"
    BEZIER = "bezier"


XFADING_MAP: Dict[str, str] = {
    "fade": "fade",
    "dissolve": "dissolve",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "wipe_up": "wipeup",
    "wipe_down": "wipedown",
    "wipe_center": "radial",
    "slide_left": "slideleft",
    "slide_right": "slideright",
    "push_left": "slideleft",
    "push_right": "slideright",
    "zoom_in": "smoothup",
    "zoom_out": "smoothdown",
    "fade_black": "fadeblack",
    "fade_white": "fadewhite",
    "iris": "circlecrop",
    "blur": "fadeblack",
    "cross_dissolve": "dissolve",
    "fade_to_black": "fadeblack",
    "fade_to_white": "fadewhite",
    "morph": "dissolve",
    "cut": "",
    "custom": "",
}

SUPPORTED_XFADE: set = {
    name for name in XFADING_MAP.values() if name
}


@dataclass
class Transition:
    """A transition between two adjacent clips on a track."""

    transition_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    transition_type: str = "fade"
    duration: RationalTime = field(
        default_factory=lambda: RationalTime(1, 2)
    )
    alignment: TransitionAlignment = TransitionAlignment.CENTER
    parameters: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    clip_a_id: Optional[str] = None
    clip_b_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.duration < RationalTime.zero():
            raise ValueError("Transition duration cannot be negative")

    @property
    def overlap_duration(self) -> RationalTime:
        if self.alignment == TransitionAlignment.CENTER:
            return self.duration
        return self.duration

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transition_id": self.transition_id,
            "name": self.name,
            "transition_type": self.transition_type,
            "duration": self.duration.to_dict(),
            "alignment": self.alignment.value,
            "parameters": self.parameters,
            "enabled": self.enabled,
            "clip_a_id": self.clip_a_id,
            "clip_b_id": self.clip_b_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Transition":
        return cls(
            transition_id=data.get("transition_id", str(uuid4())),
            name=data.get("name", ""),
            transition_type=data.get("transition_type", "fade"),
            duration=RationalTime.from_dict(data["duration"]),
            alignment=TransitionAlignment(data.get("alignment", "center")),
            parameters=data.get("parameters", {}),
            enabled=data.get("enabled", True),
            clip_a_id=data.get("clip_a_id"),
            clip_b_id=data.get("clip_b_id"),
        )

    @classmethod
    def from_legacy(cls, legacy: Any) -> "Transition":
        """Convert a legacy edit_spec Transition to the new format."""
        ttype = getattr(legacy, "type", None)
        if ttype is None:
            ttype = LegacyTransitionType.FADE
        if isinstance(ttype, LegacyTransitionType):
            ttype_value = ttype.value
        else:
            ttype_value = str(ttype)
        duration_val = getattr(legacy, "duration", 0.5)
        return cls(
            transition_type=ttype_value,
            duration=RationalTime.from_seconds(duration_val),
            parameters={"easing": getattr(legacy, "easing", "ease_in_out")},
        )


def map_transition_to_xfade(transition: Transition) -> str:
    """Map a Transition to its FFmpeg xfade filter name.

    Returns empty string for hard cuts or unsupported types.
    """
    if not transition.enabled:
        return ""
    name = XFADING_MAP.get(transition.transition_type, "")
    if name and name not in SUPPORTED_XFADE:
        return ""
    return name


def compute_xfade_offset(
    clip_a_duration: RationalTime,
    transition_duration: RationalTime,
    alignment: TransitionAlignment,
) -> RationalTime:
    """Compute the xfade offset parameter for a pair of clips.

    The offset is where the transition begins relative to clip A's timeline.
    """
    if alignment == TransitionAlignment.CENTER:
        return clip_a_duration - transition_duration / Fraction(2, 1)
    elif alignment == TransitionAlignment.START:
        return clip_a_duration - transition_duration
    else:
        return clip_a_duration


@dataclass
class TransitionSegment:
    """A resolved transition segment between two clips for FFmpeg rendering."""

    clip_a_index: int
    clip_b_index: int
    xfade_filter: str
    offset: RationalTime
    duration: RationalTime
    transition: Transition


class TransitionGraph:
    """Build a sequence of transitions for a timeline track's clips.

    Given a list of clips on a track and a default transition, this produces
    the xfade filter chain needed to merge them sequentially.
    """

    def __init__(
        self,
        default_transition: Optional[Transition] = None,
        max_transition_duration: Optional[RationalTime] = None,
    ) -> None:
        self._default = default_transition or Transition(
            transition_type="fade",
            duration=RationalTime(1, 2),
        )
        self._max_dur = max_transition_duration or RationalTime(3, 1)

    def build_segments(
        self,
        clip_durations: List[RationalTime],
        transitions: Optional[List[Optional[Transition]]] = None,
    ) -> List[TransitionSegment]:
        """Build transition segments for a sequence of clips.

        Args:
            clip_durations: Duration of each clip (on timeline, after speed).
            transitions: Optional per-pair transition overrides. Length should be
                         len(clip_durations) - 1. None entries use the default.

        Returns:
            List of TransitionSegment, one per adjacent clip pair.
        """
        if len(clip_durations) < 2:
            return []

        segments: List[TransitionSegment] = []
        cumulative_offset = RationalTime.zero()

        for i in range(len(clip_durations) - 1):
            trans = (
                transitions[i]
                if transitions and i < len(transitions) and transitions[i]
                else self._default
            )
            xfade_name = map_transition_to_xfade(trans)

            if not xfade_name or trans.duration <= RationalTime.zero():
                cumulative_offset = cumulative_offset + clip_durations[i]
                continue

            dur = trans.duration
            if dur > self._max_dur:
                dur = self._max_dur
            if dur > clip_durations[i]:
                dur = clip_durations[i]

            offset = compute_xfade_offset(
                clip_durations[i], dur, trans.alignment
            )

            segments.append(TransitionSegment(
                clip_a_index=i,
                clip_b_index=i + 1,
                xfade_filter=xfade_name,
                offset=cumulative_offset + offset,
                duration=dur,
                transition=trans,
            ))

            effective_duration = clip_durations[i] - dur
            cumulative_offset = cumulative_offset + effective_duration

        return segments

    def build_from_timeline(
        self,
        timeline: Timeline,
        track_id: str,
    ) -> List[TransitionSegment]:
        """Build transitions from a real timeline track."""
        track = timeline.get_track(track_id)
        if track.track_type != TrackType.VIDEO:
            return []

        sorted_clips = sorted(
            track.clips, key=lambda c: c.record_range.start.value
        )
        durations = [c.record_range.duration for c in sorted_clips]
        clip_ids = [c.clip_id for c in sorted_clips]

        segments = self.build_segments(durations)

        for seg in segments:
            seg.transition.clip_a_id = clip_ids[seg.clip_a_index]
            seg.transition.clip_b_id = clip_ids[seg.clip_b_index]

        return segments


def build_xfade_filter_complex(
    input_labels: List[str],
    segments: List[TransitionSegment],
    audio_labels: Optional[List[str]] = None,
) -> str:
    """Build an FFmpeg filter_complex string for sequential xfade merges.

    Args:
        input_labels: FFmpeg input labels like ["0:v", "1:v", "2:v"].
        segments: Transition segments from TransitionGraph.
        audio_labels: Optional audio labels for acrossfade.

    Returns:
        FFmpeg filter_complex string content.
    """
    if not segments or len(input_labels) < 2:
        return ""

    video_parts: List[str] = []
    audio_parts: List[str] = []

    prev_video = input_labels[0]
    prev_audio = audio_labels[0] if audio_labels else None

    used_inputs = {0}

    for i, seg in enumerate(segments):
        b_idx = seg.clip_b_index
        used_inputs.add(b_idx)
        b_label = input_labels[b_idx]

        out_video = f"xf{i}"
        out_audio = f"af{i}" if audio_labels else None

        video_parts.append(
            f"[{prev_video}][{b_label}]"
            f"xfade=transition={seg.xfade_filter}"
            f":duration={seg.duration.to_seconds():.6f}"
            f":offset={seg.offset.to_seconds():.6f}"
            f"[{out_video}]"
        )

        if prev_audio and audio_labels:
            b_audio = audio_labels[b_idx]
            audio_parts.append(
                f"[{prev_audio}][{b_audio}]"
                f"acrossfade=d={seg.duration.to_seconds():.6f}"
                f"[{out_audio}]"
            )
            prev_audio = out_audio

        prev_video = out_video

    last_video = prev_video

    unused = [
        input_labels[i]
        for i in range(len(input_labels))
        if i not in used_inputs
    ]
    for j, unused_label in enumerate(unused):
        temp = f"unused{j}"
        video_parts.append(
            f"[{last_video}][{unused_label}]"
            f"xfade=transition=fade:duration=0:offset=999999"
            f"[{temp}]"
        )
        last_video = temp

    all_parts = video_parts + audio_parts
    return ";".join(all_parts)


def legacy_to_xfade_filter(
    transition_type: str,
    duration: float,
    offset: float,
) -> str:
    """Quick conversion from legacy transition params to xfade filter string."""
    xfade_name = XFADING_MAP.get(transition_type, "fade")
    if not xfade_name:
        xfade_name = "fade"
    return (
        f"xfade=transition={xfade_name}"
        f":duration={duration:.6f}"
        f":offset={offset:.6f}"
    )


TRANSITION_PRESETS: Dict[str, Dict[str, Any]] = {
    "quick_cut": {
        "transition_type": "cut",
        "duration_seconds": 0.0,
        "description": "Hard cut with no transition",
    },
    "standard_fade": {
        "transition_type": "fade",
        "duration_seconds": 0.5,
        "description": "Classic cross-fade (0.5s)",
    },
    "smooth_dissolve": {
        "transition_type": "dissolve",
        "duration_seconds": 1.0,
        "description": "Smooth dissolve (1s)",
    },
    "wipe_left": {
        "transition_type": "wipe_left",
        "duration_seconds": 0.75,
        "description": "Left wipe transition (0.75s)",
    },
    "slide_transition": {
        "transition_type": "slide_left",
        "duration_seconds": 0.5,
        "description": "Slide left (0.5s)",
    },
    "fade_to_black": {
        "transition_type": "fade_black",
        "duration_seconds": 1.0,
        "description": "Fade through black (1s)",
    },
    "cinematic_dissolve": {
        "transition_type": "cross_dissolve",
        "duration_seconds": 1.5,
        "description": "Long cinematic dissolve (1.5s)",
    },
    "flash_transition": {
        "transition_type": "fade_white",
        "duration_seconds": 0.3,
        "description": "Flash white (0.3s)",
    },
}


def get_preset(name: str) -> Optional[Transition]:
    """Get a named transition preset as a Transition object."""
    preset = TRANSITION_PRESETS.get(name)
    if not preset:
        return None
    return Transition(
        name=name,
        transition_type=preset["transition_type"],
        duration=RationalTime.from_seconds(preset["duration_seconds"]),
    )
