"""Compile a validated NLE timeline into the existing FFmpeg render pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

from services.edit_spec import AspectRatio, ClipSpec, MontageSpec, SpeedSegment, TimeRange, Transition, TransitionType
from services.project_store import Project
from services.timeline_engine import TimelineClip, TrackType


class TimelineCompilationError(ValueError):
    """The timeline is valid edit state but exceeds the current renderer."""


@dataclass(frozen=True)
class TimelineRenderPlan:
    project_id: str
    project_revision: int
    montage: MontageSpec


class TimelineRenderer:
    """First production vertical slice from NLE state to FFmpeg ClipSpecs.

    The compositor is intentionally not faked.  This compiler supports one
    visible, non-overlapping video track with contiguous enabled clips.  It
    rejects layered compositing and gaps until the layer compositor is wired
    into the GPU/filter-graph renderer.
    """

    def compile(
        self,
        project: Project,
        *,
        output_path: str,
        aspect_ratio: AspectRatio,
        resolution: str,
        crf: int,
    ) -> TimelineRenderPlan:
        active_video_tracks = [
            track for track in project.timeline.tracks
            if track.track_type == TrackType.VIDEO
            and track.visible
            and any(clip.enabled for clip in track.clips)
        ]
        if not active_video_tracks:
            raise TimelineCompilationError("Timeline has no enabled video clips")
        if len(active_video_tracks) > 1:
            raise TimelineCompilationError(
                "Layered video rendering is not enabled yet; use one active video track"
            )

        clips = sorted(
            (clip for clip in active_video_tracks[0].clips if clip.enabled),
            key=lambda clip: clip.record_range.start.value,
        )
        self._validate_contiguous(clips)

        specs = [
            self._compile_clip(clip, aspect_ratio=aspect_ratio, resolution=resolution, crf=crf)
            for clip in clips
        ]
        return TimelineRenderPlan(
            project_id=project.project_id,
            project_revision=project.revision,
            montage=MontageSpec(
                clips=specs,
                transition=Transition(type=TransitionType.NONE),
                output_path=output_path,
            ),
        )

    @staticmethod
    def _validate_contiguous(clips: List[TimelineClip]) -> None:
        expected_start = None
        for clip in clips:
            if not Path(clip.asset_path).is_file():
                raise FileNotFoundError(clip.asset_path)
            if expected_start is None:
                if clip.record_range.start.to_seconds() != 0:
                    raise TimelineCompilationError(
                        "Timeline render currently requires the first video clip at 0"
                    )
            elif clip.record_range.start != expected_start:
                raise TimelineCompilationError(
                    "Timeline render currently does not support gaps; close gaps or use a gap generator"
                )
            expected_start = clip.record_range.end

    @staticmethod
    def _compile_clip(
        clip: TimelineClip,
        *,
        aspect_ratio: AspectRatio,
        resolution: str,
        crf: int,
    ) -> ClipSpec:
        if clip.reverse:
            raise TimelineCompilationError("Reverse playback is not enabled in the timeline compiler yet")
        if clip.opacity != 1.0:
            raise TimelineCompilationError("Per-clip opacity requires the layer compositor")
        source_start = clip.source_range.start.to_seconds()
        source_end = clip.source_range.end.to_seconds()
        speed_segments = []
        if clip.speed != 1:
            speed_segments.append(SpeedSegment(
                time_range=TimeRange(start=0.0, end=clip.source_range.duration.to_seconds()),
                speed=float(clip.speed),
            ))
        return ClipSpec(
            source_path=clip.asset_path,
            time_range=TimeRange(start=source_start, end=source_end),
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            crf=crf,
            speed_segments=speed_segments,
            music_volume=clip.volume,
        )


timeline_renderer = TimelineRenderer()
