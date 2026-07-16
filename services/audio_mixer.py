"""Audio mixer integration for the NLE timeline.

Provides:
- Audio track and bus models compatible with the timeline
- Volume/pan keyframe data for automation
- FFmpeg filter graph generation for multi-track audio mixing
- Sidechain ducking filter generation
- Loudness measurement target specs

This module is intentionally independent from numpy/scipy to stay
testable without heavy dependencies. The actual audio processing
(digital signal processing) happens in the render pipeline via FFmpeg.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from services.timeline_engine import RationalTime, TimeRange, Timeline, TrackType


class AudioTrackType(Enum):
    DIALOGUE = "dialogue"
    MUSIC = "music"
    EFFECTS = "effects"
    AMBIENCE = "ambience"


class DuckingMode(Enum):
    SIDECHAIN = "sidechain"
    THRESHOLD = "threshold"
    MANUAL = "manual"


class DuckingCurve(Enum):
    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    LOGARITHMIC = "logarithmic"
    S_CURVE = "s_curve"


class ChannelLayout(Enum):
    MONO = 1
    STEREO = 2


class LoudnessStandard(Enum):
    ITU_BS1770_4 = "itu_bs1770_4"
    EBU_R128 = "ebu_r128"
    PLATFORM_SOCIAL = "platform_social"


@dataclass
class VolumeKeyframe:
    """A volume automation keyframe."""

    time: RationalTime
    volume_db: float = 0.0
    curve: str = "linear"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time": self.time.to_dict(),
            "volume_db": self.volume_db,
            "curve": self.curve,
        }


@dataclass
class PanKeyframe:
    """A pan automation keyframe."""

    time: RationalTime
    pan_lr: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time": self.time.to_dict(),
            "pan_lr": self.pan_lr,
        }


@dataclass
class TimelineAudioClip:
    """An audio clip placed on a timeline audio track."""

    clip_id: str = field(default_factory=lambda: str(uuid4()))
    asset_path: str = ""
    source_range: TimeRange = field(
        default_factory=lambda: TimeRange(
            RationalTime.zero(), RationalTime(1, 1)
        )
    )
    record_range: TimeRange = field(
        default_factory=lambda: TimeRange(
            RationalTime.zero(), RationalTime(1, 1)
        )
    )
    gain_db: float = 0.0
    pan: float = 0.0
    fade_in: RationalTime = field(
        default_factory=lambda: RationalTime.zero()
    )
    fade_out: RationalTime = field(
        default_factory=lambda: RationalTime.zero()
    )
    volume_keyframes: List[VolumeKeyframe] = field(default_factory=list)
    pan_keyframes: List[PanKeyframe] = field(default_factory=list)
    enabled: bool = True
    name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "asset_path": self.asset_path,
            "source_range": self.source_range.to_dict(),
            "record_range": self.record_range.to_dict(),
            "gain_db": self.gain_db,
            "pan": self.pan,
            "fade_in": self.fade_in.to_dict(),
            "fade_out": self.fade_out.to_dict(),
            "enabled": self.enabled,
            "name": self.name,
        }


@dataclass
class DuckingProfile:
    """Configuration for audio ducking between tracks."""

    profile_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "default"
    mode: DuckingMode = DuckingMode.SIDECHAIN
    threshold_db: float = -30.0
    range_db: float = -12.0
    attack_ms: float = 50.0
    hold_ms: float = 200.0
    release_ms: float = 500.0
    curve: DuckingCurve = DuckingCurve.EXPONENTIAL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "name": self.name,
            "mode": self.mode.value,
            "threshold_db": self.threshold_db,
            "range_db": self.range_db,
            "attack_ms": self.attack_ms,
            "hold_ms": self.hold_ms,
            "release_ms": self.release_ms,
            "curve": self.curve.value,
        }


@dataclass
class DuckingRule:
    """A ducking rule: when source tracks are active, duck target tracks."""

    rule_id: str = field(default_factory=lambda: str(uuid4()))
    source_track_ids: List[str] = field(default_factory=list)
    target_track_ids: List[str] = field(default_factory=list)
    profile: DuckingProfile = field(default_factory=DuckingProfile)
    priority: int = 0
    enabled: bool = True


@dataclass
class LoudnessTarget:
    """Loudness normalization target for the final output."""

    target_lufs: float = -14.0
    tolerance_lu: float = 1.0
    max_true_peak_dbtp: float = -1.0
    standard: LoudnessStandard = LoudnessStandard.PLATFORM_SOCIAL

    @classmethod
    def youtube(cls) -> "LoudnessTarget":
        return cls(target_lufs=-14.0, max_true_peak_dbtp=-1.0)

    @classmethod
    def tiktok(cls) -> "LoudnessTarget":
        return cls(target_lufs=-14.0, max_true_peak_dbtp=-1.0)

    @classmethod
    def broadcast_ebu(cls) -> "LoudnessTarget":
        return cls(
            target_lufs=-23.0,
            tolerance_lu=0.5,
            max_true_peak_dbtp=-1.0,
            standard=LoudnessStandard.EBU_R128,
        )

    @classmethod
    def twitch(cls) -> "LoudnessTarget":
        return cls(target_lufs=-14.0, max_true_peak_dbtp=-0.5)


class TimelineAudioMixer:
    """Manages audio tracks, ducking, and generates FFmpeg audio filter graphs.

    This is the timeline-level audio mixer that operates on rational time
    and produces FFmpeg filter strings for the render pipeline.
    """

    def __init__(self) -> None:
        self._tracks: Dict[str, TimelineAudioClip] = {}
        self._ducking_rules: List[DuckingRule] = []
        self._loudness_target: Optional[LoudnessTarget] = None
        self._music_volume: float = 1.0
        self._sfx_volume: float = 1.0

    @property
    def loudness_target(self) -> Optional[LoudnessTarget]:
        return self._loudness_target

    @loudness_target.setter
    def loudness_target(self, target: LoudnessTarget) -> None:
        self._loudness_target = target

    @property
    def music_volume(self) -> float:
        return self._music_volume

    @music_volume.setter
    def music_volume(self, vol: float) -> None:
        if not 0.0 <= vol <= 2.0:
            raise ValueError("Volume must be between 0.0 and 2.0")
        self._music_volume = vol

    @property
    def sfx_volume(self) -> float:
        return self._sfx_volume

    @sfx_volume.setter
    def sfx_volume(self, vol: float) -> None:
        if not 0.0 <= vol <= 2.0:
            raise ValueError("Volume must be between 0.0 and 2.0")
        self._sfx_volume = vol

    def add_clip(self, clip: TimelineAudioClip) -> None:
        self._tracks[clip.clip_id] = clip

    def remove_clip(self, clip_id: str) -> bool:
        return self._tracks.pop(clip_id, None) is not None

    def get_clip(self, clip_id: str) -> Optional[TimelineAudioClip]:
        return self._tracks.get(clip_id)

    @property
    def clips(self) -> List[TimelineAudioClip]:
        return list(self._tracks.values())

    def add_ducking_rule(self, rule: DuckingRule) -> None:
        self._ducking_rules.append(rule)

    def remove_ducking_rule(self, rule_id: str) -> bool:
        for i, r in enumerate(self._ducking_rules):
            if r.rule_id == rule_id:
                self._ducking_rules.pop(i)
                return True
        return False

    @property
    def ducking_rules(self) -> List[DuckingRule]:
        return list(self._ducking_rules)

    def build_amix_filter(
        self,
        input_labels: List[str],
        input_volumes: Optional[List[float]] = None,
        duration: str = "first",
    ) -> str:
        """Build an FFmpeg amix filter from multiple audio inputs.

        Args:
            input_labels: e.g. ["0:a", "1:a", "2:a"]
            input_volumes: Optional per-input volume multipliers
            duration: "first", "longest", or "shortest"

        Returns:
            amix filter string like "[0:a][1:a]amix=inputs=2:duration=first[out]"
        """
        n = len(input_labels)
        if n == 0:
            return ""
        if n == 1:
            return f"acopy"

        vol_parts: List[str] = []
        for i, label in enumerate(input_labels):
            vol = input_volumes[i] if input_volumes and i < len(input_volumes) else 1.0
            if vol != 1.0:
                vol_parts.append(f"[{label}]volume={vol:.3f}[a{i}]")
                input_labels_effective = f"[a{i}]"
            else:
                input_labels_effective = f"[{label}]"

        filter_str = "".join(vol_parts)
        mix_inputs = "".join(
            f"[a{i}]" if (input_volumes and i < len(input_volumes) and input_volumes[i] != 1.0)
            else f"[{input_labels[i]}]"
            for i in range(n)
        )
        out_label = "amix_out"
        filter_str += f"{mix_inputs}amix=inputs={n}:duration={duration}:dropout_transition=3[{out_label}]"
        return filter_str

    def build_ducking_filter(
        self,
        music_label: str,
        voice_label: str,
        rule: DuckingRule,
    ) -> str:
        """Build an FFmpeg sidechaincompress filter for ducking.

        The music track is compressed based on the voice track's level.
        """
        p = rule.profile
        threshold_linear = 10 ** (p.threshold_db / 20.0)
        return (
            f"[{music_label}][{voice_label}]"
            f"sidechaincompress="
            f"threshold={threshold_linear:.6f}:"
            f"ratio={10 ** (abs(p.range_db) / 20.0):.2f}:"
            f"attack={p.attack_ms:.1f}:"
            f"release={p.release_ms:.1f}"
            f"[ducked]"
        )

    def build_fade_filter(
        self,
        input_label: str,
        fade_in: Optional[RationalTime] = None,
        fade_out: Optional[RationalTime] = None,
        total_duration: Optional[RationalTime] = None,
    ) -> str:
        """Build afade filters for a clip."""
        parts: List[str] = []
        current = input_label

        if fade_in and fade_in > RationalTime.zero():
            d = fade_in.to_seconds()
            parts.append(f"[{current}]afade=t=in:d={d:.6f}[fi]")
            current = "fi"

        if fade_out and fade_out > RationalTime.zero() and total_duration:
            d = fade_out.to_seconds()
            st = (total_duration - fade_out).to_seconds()
            parts.append(f"[{current}]afade=t=out:st={st:.6f}:d={d:.6f}[fo]")
            current = "fo"

        if not parts:
            return ""
        return ";".join(parts)

    def build_loudness_filter(
        self,
        input_label: str,
        target: Optional[LoudnessTarget] = None,
    ) -> str:
        """Build an FFmpeg loudnorm filter for loudness normalization."""
        t = target or self._loudness_target or LoudnessTarget()
        return (
            f"[{input_label}]loudnorm="
            f"I={t.target_lufs}:"
            f"TP={t.max_true_peak_dbtp}:"
            f"LRA={t.tolerance_lu * 2}"
            f"[lnorm]"
        )

    def build_full_audio_graph(
        self,
        timeline: Timeline,
    ) -> str:
        """Build a complete audio filter graph from timeline audio tracks.

        Returns the filter_complex string for all audio processing.
        """
        audio_tracks = [
            t for t in timeline.tracks
            if t.track_type == TrackType.AUDIO and not t.muted
        ]
        if not audio_tracks:
            return ""

        input_labels: List[str] = []
        vol_adjusts: List[str] = []
        idx = 0

        for track in audio_tracks:
            for clip in track.clips:
                if not clip.enabled:
                    continue
                label = f"{idx}:a"
                current_label = f"a{idx}"

                if clip.volume != 1.0:
                    vol_adjusts.append(
                        f"[{label}]volume={clip.volume:.3f}[{current_label}]"
                    )
                else:
                    current_label = label

                input_labels.append(current_label)
                idx += 1

        if not input_labels:
            return ""

        parts = list(vol_adjusts)

        if len(input_labels) == 1:
            parts.append(f"[{input_labels[0]}]anull[aout]")
            return ";".join(parts)

        mix = self.build_amix_filter(list(input_labels))
        if mix:
            parts.append(mix)

        if self._loudness_target:
            parts.append(self.build_loudness_filter("amix_out"))

        return ";".join(parts) if parts else ""
