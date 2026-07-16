"""Frame-accurate non-linear editing primitives.

This module is deliberately independent from FFmpeg and FastAPI.  It owns the
project's edit decision state: rational time, tracks, clip instances, and the
core insert/overwrite/lift/extract/ripple operations.  Rendering is handled by
``services.timeline_renderer`` after this state has been validated.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from functools import total_ordering
from typing import Any, Dict, Iterable, List, Optional, Tuple
from uuid import uuid4


@total_ordering
@dataclass(frozen=True)
class RationalTime:
    """Canonical rational seconds; never use floating point for edit state."""

    numerator: int
    denominator: int = 1

    def __post_init__(self) -> None:
        if self.denominator == 0:
            raise ValueError("RationalTime denominator cannot be zero")
        value = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", value.numerator)
        object.__setattr__(self, "denominator", value.denominator)

    @property
    def value(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    @classmethod
    def zero(cls) -> "RationalTime":
        return cls(0, 1)

    @classmethod
    def from_fraction(cls, value: Fraction) -> "RationalTime":
        return cls(value.numerator, value.denominator)

    @classmethod
    def from_seconds(cls, value: float) -> "RationalTime":
        # str avoids inheriting a binary-float approximation into project data.
        return cls.from_fraction(Fraction(str(value)).limit_denominator(1_000_000))

    @classmethod
    def from_dict(cls, data: Dict[str, int]) -> "RationalTime":
        return cls(data["numerator"], data["denominator"])

    def to_dict(self) -> Dict[str, int]:
        return {"numerator": self.numerator, "denominator": self.denominator}

    def to_seconds(self) -> float:
        return float(self.value)

    def __add__(self, other: "RationalTime") -> "RationalTime":
        return self.from_fraction(self.value + other.value)

    def __sub__(self, other: "RationalTime") -> "RationalTime":
        return self.from_fraction(self.value - other.value)

    def __mul__(self, other: Fraction) -> "RationalTime":
        return self.from_fraction(self.value * other)

    def __truediv__(self, other: Fraction) -> "RationalTime":
        if other == 0:
            raise ValueError("Cannot divide time by zero")
        return self.from_fraction(self.value / other)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, RationalTime):
            return NotImplemented
        return self.value < other.value


@dataclass(frozen=True)
class TimeRange:
    """A half-open [start, end) range expressed with rational time."""

    start: RationalTime
    duration: RationalTime

    def __post_init__(self) -> None:
        if self.start < RationalTime.zero():
            raise ValueError("Time ranges cannot start before zero")
        if self.duration < RationalTime.zero():
            raise ValueError("Time range duration cannot be negative")

    @property
    def end(self) -> RationalTime:
        return self.start + self.duration

    def contains(self, point: RationalTime) -> bool:
        return self.start <= point < self.end

    def overlaps(self, other: "TimeRange") -> bool:
        return self.start < other.end and other.start < self.end

    def offset(self, delta: RationalTime) -> "TimeRange":
        return TimeRange(self.start + delta, self.duration)

    def intersection(self, other: "TimeRange") -> Optional["TimeRange"]:
        start = max(self.start, other.start)
        end = min(self.end, other.end)
        if start >= end:
            return None
        return TimeRange(start, end - start)

    def to_dict(self) -> Dict[str, Dict[str, int]]:
        return {"start": self.start.to_dict(), "duration": self.duration.to_dict()}

    @classmethod
    def from_dict(cls, data: Dict[str, Dict[str, int]]) -> "TimeRange":
        return cls(
            start=RationalTime.from_dict(data["start"]),
            duration=RationalTime.from_dict(data["duration"]),
        )


class TrackType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    TITLE = "title"
    ADJUSTMENT = "adjustment"
    DATA = "data"


class EditMode(str, Enum):
    INSERT = "insert"
    OVERWRITE = "overwrite"
    LIFT = "lift"
    EXTRACT = "extract"


@dataclass
class TimelineClip:
    """An immutable-media clip instance placed on a timeline track."""

    clip_id: str
    asset_path: str
    source_range: TimeRange
    record_range: TimeRange
    name: str = ""
    speed: Fraction = field(default_factory=lambda: Fraction(1, 1))
    reverse: bool = False
    enabled: bool = True
    locked: bool = False
    opacity: float = 1.0
    volume: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_path:
            raise ValueError("TimelineClip requires an asset_path")
        if self.source_range.duration == RationalTime.zero():
            raise ValueError("TimelineClip source range cannot be empty")
        if self.speed <= 0:
            raise ValueError("TimelineClip speed must be positive")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("TimelineClip opacity must be between 0 and 1")
        if self.volume < 0:
            raise ValueError("TimelineClip volume cannot be negative")

        expected_duration = self.source_range.duration / self.speed
        if self.record_range.duration != expected_duration:
            raise ValueError(
                "record_range.duration must equal source_range.duration / speed"
            )

    @classmethod
    def create(
        cls,
        *,
        asset_path: str,
        source_range: TimeRange,
        record_start: RationalTime,
        name: str = "",
        speed: Fraction = Fraction(1, 1),
        reverse: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "TimelineClip":
        if speed <= 0:
            raise ValueError("TimelineClip speed must be positive")
        return cls(
            clip_id=str(uuid4()),
            asset_path=asset_path,
            source_range=source_range,
            record_range=TimeRange(record_start, source_range.duration / speed),
            name=name or asset_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1],
            speed=speed,
            reverse=reverse,
            metadata=metadata or {},
        )

    def fragment(self, range_on_timeline: TimeRange) -> "TimelineClip":
        """Return a new clip instance for a selected subrange of this clip."""
        selected = self.record_range.intersection(range_on_timeline)
        if selected is None:
            raise ValueError("Cannot fragment a clip outside its record range")

        record_offset = selected.start - self.record_range.start
        source_duration = selected.duration * self.speed
        if self.reverse:
            source_start = self.source_range.end - (record_offset + selected.duration) * self.speed
        else:
            source_start = self.source_range.start + record_offset * self.speed

        return TimelineClip(
            clip_id=str(uuid4()),
            asset_path=self.asset_path,
            source_range=TimeRange(source_start, source_duration),
            record_range=selected,
            name=self.name,
            speed=self.speed,
            reverse=self.reverse,
            enabled=self.enabled,
            locked=self.locked,
            opacity=self.opacity,
            volume=self.volume,
            metadata=dict(self.metadata),
        )

    def move_to(self, start: RationalTime) -> None:
        self.record_range = TimeRange(start, self.record_range.duration)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "asset_path": self.asset_path,
            "source_range": self.source_range.to_dict(),
            "record_range": self.record_range.to_dict(),
            "name": self.name,
            "speed": {"numerator": self.speed.numerator, "denominator": self.speed.denominator},
            "reverse": self.reverse,
            "enabled": self.enabled,
            "locked": self.locked,
            "opacity": self.opacity,
            "volume": self.volume,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TimelineClip":
        speed = data.get("speed", {"numerator": 1, "denominator": 1})
        return cls(
            clip_id=data["clip_id"],
            asset_path=data["asset_path"],
            source_range=TimeRange.from_dict(data["source_range"]),
            record_range=TimeRange.from_dict(data["record_range"]),
            name=data.get("name", ""),
            speed=Fraction(speed["numerator"], speed["denominator"]),
            reverse=data.get("reverse", False),
            enabled=data.get("enabled", True),
            locked=data.get("locked", False),
            opacity=data.get("opacity", 1.0),
            volume=data.get("volume", 1.0),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Track:
    """A non-overlapping clip lane. Gaps are represented implicitly."""

    track_id: str
    name: str
    track_type: TrackType
    order: int
    clips: List[TimelineClip] = field(default_factory=list)
    locked: bool = False
    visible: bool = True
    muted: bool = False
    solo: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._sort_and_validate()

    def _sort_and_validate(self) -> None:
        self.clips.sort(key=lambda clip: clip.record_range.start.value)
        previous: Optional[TimelineClip] = None
        for clip in self.clips:
            if previous and previous.record_range.end > clip.record_range.start:
                raise ValueError(
                    f"Track {self.name} contains overlapping clips "
                    f"{previous.clip_id} and {clip.clip_id}"
                )
            previous = clip

    def get_clip(self, clip_id: str) -> TimelineClip:
        for clip in self.clips:
            if clip.clip_id == clip_id:
                return clip
        raise KeyError(f"Clip not found: {clip_id}")

    def clips_in_range(self, time_range: TimeRange) -> List[TimelineClip]:
        return [clip for clip in self.clips if clip.record_range.overlaps(time_range)]

    def _assert_editable(self, clips: Iterable[TimelineClip] = ()) -> None:
        if self.locked:
            raise PermissionError(f"Track is locked: {self.name}")
        locked = next((clip for clip in clips if clip.locked), None)
        if locked:
            raise PermissionError(f"Clip is locked: {locked.clip_id}")

    def _split_at(self, position: RationalTime) -> None:
        for index, clip in enumerate(list(self.clips)):
            if clip.record_range.start < position < clip.record_range.end:
                self._assert_editable([clip])
                left = clip.fragment(TimeRange(clip.record_range.start, position - clip.record_range.start))
                right = clip.fragment(TimeRange(position, clip.record_range.end - position))
                self.clips[index:index + 1] = [left, right]
                return

    def _shift_from(self, position: RationalTime, delta: RationalTime) -> None:
        if delta == RationalTime.zero():
            return
        candidates = [clip for clip in self.clips if clip.record_range.start >= position]
        self._assert_editable(candidates)
        for clip in candidates:
            clip.move_to(clip.record_range.start + delta)

    def _remove_range(self, range_to_remove: TimeRange) -> None:
        overlaps = self.clips_in_range(range_to_remove)
        self._assert_editable(overlaps)
        retained: List[TimelineClip] = []
        for clip in self.clips:
            if not clip.record_range.overlaps(range_to_remove):
                retained.append(clip)
                continue
            if clip.record_range.start < range_to_remove.start:
                retained.append(clip.fragment(TimeRange(
                    clip.record_range.start,
                    range_to_remove.start - clip.record_range.start,
                )))
            if clip.record_range.end > range_to_remove.end:
                retained.append(clip.fragment(TimeRange(
                    range_to_remove.end,
                    clip.record_range.end - range_to_remove.end,
                )))
        self.clips = retained
        self._sort_and_validate()

    def insert_clip(self, clip: TimelineClip, position: RationalTime, mode: EditMode) -> None:
        """Insert or overwrite a clip at an exact record time."""
        self._assert_editable()
        if mode == EditMode.INSERT:
            self._split_at(position)
            self._shift_from(position, clip.record_range.duration)
        elif mode == EditMode.OVERWRITE:
            self._remove_range(TimeRange(position, clip.record_range.duration))
        else:
            raise ValueError("insert_clip only accepts insert or overwrite mode")

        clip.move_to(position)
        self.clips.append(clip)
        self._sort_and_validate()

    def remove(self, time_range: TimeRange, mode: EditMode) -> None:
        """Lift leaves a gap; extract closes it by rippling later clips left."""
        if mode not in (EditMode.LIFT, EditMode.EXTRACT):
            raise ValueError("remove only accepts lift or extract mode")
        self._remove_range(time_range)
        if mode == EditMode.EXTRACT:
            self._shift_from(time_range.end, RationalTime.zero() - time_range.duration)
        self._sort_and_validate()

    def ripple_trim(self, clip_id: str, new_source_duration: RationalTime) -> None:
        """Trim clip out point and keep following material contiguous."""
        clip = self.get_clip(clip_id)
        self._assert_editable([clip])
        if new_source_duration <= RationalTime.zero():
            raise ValueError("New source duration must be positive")

        old_end = clip.record_range.end
        old_duration = clip.record_range.duration
        new_record_duration = new_source_duration / clip.speed
        delta = new_record_duration - old_duration
        clip.source_range = TimeRange(clip.source_range.start, new_source_duration)
        clip.record_range = TimeRange(clip.record_range.start, new_record_duration)
        self._shift_from(old_end, delta)
        self._sort_and_validate()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "name": self.name,
            "track_type": self.track_type.value,
            "order": self.order,
            "clips": [clip.to_dict() for clip in self.clips],
            "locked": self.locked,
            "visible": self.visible,
            "muted": self.muted,
            "solo": self.solo,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Track":
        return cls(
            track_id=data["track_id"],
            name=data["name"],
            track_type=TrackType(data["track_type"]),
            order=data["order"],
            clips=[TimelineClip.from_dict(clip) for clip in data.get("clips", [])],
            locked=data.get("locked", False),
            visible=data.get("visible", True),
            muted=data.get("muted", False),
            solo=data.get("solo", False),
            metadata=data.get("metadata", {}),
        )


@dataclass
class Timeline:
    """NLE timeline with independently editable video, audio and title lanes."""

    timeline_id: str
    name: str
    fps: Fraction
    width: int
    height: int
    tracks: List[Track] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.fps <= 0:
            raise ValueError("Timeline fps must be positive")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Timeline dimensions must be positive")

    @classmethod
    def create(
        cls,
        name: str,
        fps: Fraction = Fraction(30, 1),
        width: int = 1920,
        height: int = 1080,
    ) -> "Timeline":
        timeline = cls(str(uuid4()), name, fps, width, height)
        timeline.add_track(TrackType.VIDEO, "V1")
        timeline.add_track(TrackType.AUDIO, "A1")
        return timeline

    @property
    def duration(self) -> RationalTime:
        ends = [clip.record_range.end for track in self.tracks for clip in track.clips if clip.enabled]
        return max(ends) if ends else RationalTime.zero()

    def add_track(self, track_type: TrackType, name: Optional[str] = None) -> Track:
        matching = [track for track in self.tracks if track.track_type == track_type]
        order = len(matching)
        track = Track(
            track_id=str(uuid4()),
            name=name or f"{track_type.value.upper()[0]}{order + 1}",
            track_type=track_type,
            order=order,
        )
        self.tracks.append(track)
        return track

    def get_track(self, track_id: str) -> Track:
        for track in self.tracks:
            if track.track_id == track_id:
                return track
        raise KeyError(f"Track not found: {track_id}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timeline_id": self.timeline_id,
            "name": self.name,
            "fps": {"numerator": self.fps.numerator, "denominator": self.fps.denominator},
            "width": self.width,
            "height": self.height,
            "tracks": [track.to_dict() for track in self.tracks],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Timeline":
        fps = data["fps"]
        return cls(
            timeline_id=data["timeline_id"],
            name=data["name"],
            fps=Fraction(fps["numerator"], fps["denominator"]),
            width=data["width"],
            height=data["height"],
            tracks=[Track.from_dict(track) for track in data.get("tracks", [])],
            metadata=data.get("metadata", {}),
        )
