"""Tests for NLE Phase 6: Compositor, Transitions, Audio Mixer, Title Renderer."""
import pytest
from fractions import Fraction

from services.timeline_engine import (
    RationalTime,
    TimeRange,
    Timeline,
    TimelineClip,
    Track,
    TrackType,
)
from services.compositor import (
    AlphaMode,
    BlendMode,
    CompositeLayer,
    CompositorConfig,
    DirtyRegion,
    GapInfo,
    LayerCompositor,
    Transform2D,
    analyze_gaps,
    fill_gaps_with_color,
    has_gaps,
)
from services.transitions import (
    EasingType,
    Transition,
    TransitionAlignment,
    TransitionGraph,
    TransitionSegment,
    build_xfade_filter_complex,
    get_preset,
    legacy_to_xfade_filter,
    map_transition_to_xfade,
)
from services.audio_mixer import (
    AudioTrackType,
    ChannelLayout,
    DuckingCurve,
    DuckingMode,
    DuckingProfile,
    DuckingRule,
    LoudnessStandard,
    LoudnessTarget,
    PanKeyframe,
    TimelineAudioClip,
    TimelineAudioMixer,
    VolumeKeyframe,
)
from services.title_renderer import (
    SubtitleEntry,
    SubtitleFormat,
    SubtitleRenderer,
    TitlePosition,
    TitleStyle,
    get_title_preset,
)


# ──────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────

def _make_timeline_with_video_clips():
    tl = Timeline(
        timeline_id="tl1",
        name="test",
        fps=Fraction(30, 1),
        width=1920,
        height=1080,
    )
    tl.add_track(TrackType.VIDEO, "V1")
    v1 = tl.tracks[0]
    for i in range(3):
        clip = TimelineClip.create(
            asset_path=f"clip{i}.mp4",
            source_range=TimeRange(RationalTime(0), RationalTime(5, 1)),
            record_start=RationalTime(i * 5, 1),
            name=f"clip{i}",
        )
        v1.insert_clip(clip, RationalTime(i * 5, 1), "insert")
    return tl


def _make_timeline_with_gap():
    tl = Timeline(
        timeline_id="tl-gap",
        name="gap_test",
        fps=Fraction(30, 1),
        width=1920,
        height=1080,
    )
    tl.add_track(TrackType.VIDEO, "V1")
    v1 = tl.tracks[0]
    clip_a = TimelineClip.create(
        asset_path="a.mp4",
        source_range=TimeRange(RationalTime(0), RationalTime(3, 1)),
        record_start=RationalTime(0),
    )
    v1.insert_clip(clip_a, RationalTime(0), "insert")
    clip_b = TimelineClip.create(
        asset_path="b.mp4",
        source_range=TimeRange(RationalTime(0), RationalTime(3, 1)),
        record_start=RationalTime(5, 1),
    )
    v1.insert_clip(clip_b, RationalTime(5, 1), "insert")
    return tl


# ══════════════════════════════════════════════════════════
# 1. Compositor Tests
# ══════════════════════════════════════════════════════════

class TestTransform2D:
    def test_identity(self):
        t = Transform2D()
        assert t.is_identity()

    def test_non_identity(self):
        t = Transform2D(x=10, y=20)
        assert not t.is_identity()

    def test_overlay_str(self):
        t = Transform2D(x=100, y=50)
        assert "overlay=100:50" in t.to_ffmpeg_overlay()

    def test_scale(self):
        t = Transform2D(scale_x=0.5, scale_y=0.5)
        s = t.to_ffmpeg_scale(1920, 1080)
        assert "scale=960:540" in s


class TestDirtyRegion:
    def test_area(self):
        r = DirtyRegion(0, 0, 100, 50)
        assert r.area == 5000

    def test_intersects(self):
        a = DirtyRegion(0, 0, 100, 100)
        b = DirtyRegion(50, 50, 100, 100)
        assert a.intersects(b)

    def test_no_intersect(self):
        a = DirtyRegion(0, 0, 10, 10)
        b = DirtyRegion(100, 100, 10, 10)
        assert not a.intersects(b)

    def test_merge(self):
        a = DirtyRegion(0, 0, 100, 100)
        b = DirtyRegion(50, 50, 100, 100)
        m = a.merge(b)
        assert m.x == 0 and m.y == 0
        assert m.width == 150 and m.height == 150


class TestLayerCompositor:
    def test_add_remove_layer(self):
        comp = LayerCompositor()
        layer = CompositeLayer(source_clip_id="c1")
        comp.add_layer(layer)
        assert len(comp.layers) == 1
        assert comp.remove_layer(layer.layer_id)
        assert len(comp.layers) == 0

    def test_remove_nonexistent(self):
        comp = LayerCompositor()
        assert not comp.remove_layer("nope")

    def test_clear(self):
        comp = LayerCompositor()
        comp.add_layer(CompositeLayer())
        comp.add_layer(CompositeLayer())
        comp.clear()
        assert len(comp.layers) == 0
        assert len(comp.dirty_regions) == 0

    def test_mark_clean(self):
        comp = LayerCompositor()
        comp.add_layer(CompositeLayer(source_clip_id="c1"))
        assert len(comp.dirty_regions) > 0
        comp.mark_clean()
        assert len(comp.dirty_regions) == 0

    def test_layer_limit(self):
        comp = LayerCompositor(CompositorConfig(max_layers=2))
        comp.add_layer(CompositeLayer())
        comp.add_layer(CompositeLayer())
        with pytest.raises(ValueError, match="Layer limit"):
            comp.add_layer(CompositeLayer())

    def test_build_filter_graph_empty(self):
        comp = LayerCompositor()
        assert comp.build_filter_graph() == ""

    def test_build_filter_graph_single_layer(self):
        comp = LayerCompositor()
        comp.add_layer(CompositeLayer(source_clip_id="c1"))
        assert comp.build_filter_graph() == ""

    def test_build_filter_graph_multi_layer(self):
        comp = LayerCompositor()
        comp.add_layer(CompositeLayer(source_clip_id="c1"))
        comp.add_layer(CompositeLayer(source_clip_id="c2"))
        fg = comp.build_filter_graph()
        assert "overlay" in fg

    def test_build_filter_graph_from_timeline(self):
        tl = _make_timeline_with_video_clips()
        comp = LayerCompositor()
        fg = comp.build_filter_graph(timeline=tl)
        assert fg == ""

    def test_get_composite_count(self):
        tl = _make_timeline_with_video_clips()
        comp = LayerCompositor()
        assert comp.get_composite_count(tl) == 1


# ══════════════════════════════════════════════════════════
# 2. Gap Analysis Tests
# ══════════════════════════════════════════════════════════

class TestGapAnalysis:
    def test_no_gaps(self):
        tl = _make_timeline_with_video_clips()
        gaps = analyze_gaps(tl)
        assert len(gaps) == 0

    def test_has_gaps(self):
        tl = _make_timeline_with_gap()
        assert has_gaps(tl)

    def test_no_gaps_empty_timeline(self):
        tl = Timeline("t", "t", Fraction(30), 1920, 1080)
        assert not has_gaps(tl)

    def test_gap_detection(self):
        tl = _make_timeline_with_gap()
        gaps = analyze_gaps(tl)
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.duration == RationalTime(2, 1)

    def test_gap_dict(self):
        tl = _make_timeline_with_gap()
        gaps = analyze_gaps(tl)
        d = gaps[0].to_dict()
        assert "duration" in d
        assert "gap_start" in d

    def test_fill_gaps(self):
        tl = _make_timeline_with_gap()
        specs = fill_gaps_with_color(tl)
        assert len(specs) == 1
        assert "filter" in specs[0]
        assert "color=c=0x000000" in specs[0]["filter"]


# ══════════════════════════════════════════════════════════
# 3. Transitions Tests
# ══════════════════════════════════════════════════════════

class TestTransition:
    def test_default(self):
        t = Transition()
        assert t.transition_type == "fade"
        assert t.enabled is True

    def test_negative_duration(self):
        with pytest.raises(ValueError):
            Transition(duration=RationalTime(-1, 1))

    def test_dict_roundtrip(self):
        t = Transition(transition_type="dissolve")
        d = t.to_dict()
        t2 = Transition.from_dict(d)
        assert t2.transition_type == "dissolve"

    def test_alignment(self):
        t = Transition(alignment=TransitionAlignment.START)
        assert t.alignment == TransitionAlignment.START

    def test_overlap_duration(self):
        t = Transition(duration=RationalTime(1, 1))
        assert t.overlap_duration == RationalTime(1, 1)


class TestTransitionXfadeMapping:
    def test_fade(self):
        t = Transition(transition_type="fade")
        assert map_transition_to_xfade(t) == "fade"

    def test_dissolve(self):
        t = Transition(transition_type="dissolve")
        assert map_transition_to_xfade(t) == "dissolve"

    def test_wipe_left(self):
        t = Transition(transition_type="wipe_left")
        assert map_transition_to_xfade(t) == "wipeleft"

    def test_cut_returns_empty(self):
        t = Transition(transition_type="cut")
        assert map_transition_to_xfade(t) == ""

    def test_disabled_returns_empty(self):
        t = Transition(transition_type="fade", enabled=False)
        assert map_transition_to_xfade(t) == ""

    def test_slide_right(self):
        t = Transition(transition_type="slide_right")
        assert map_transition_to_xfade(t) == "slideright"

    def test_fade_black(self):
        t = Transition(transition_type="fade_black")
        assert map_transition_to_xfade(t) == "fadeblack"

    def test_iris(self):
        t = Transition(transition_type="iris")
        assert map_transition_to_xfade(t) == "circlecrop"


class TestXfadeOffset:
    def test_center(self):
        from services.transitions import compute_xfade_offset
        off = compute_xfade_offset(
            RationalTime(10, 1), RationalTime(2, 1), TransitionAlignment.CENTER
        )
        assert off == RationalTime(9, 1)

    def test_start(self):
        from services.transitions import compute_xfade_offset
        off = compute_xfade_offset(
            RationalTime(10, 1), RationalTime(2, 1), TransitionAlignment.START
        )
        assert off == RationalTime(9, 1)

    def test_compute_xfade_offset_center(self):
        from services.transitions import compute_xfade_offset
        off = compute_xfade_offset(
            RationalTime(10, 1), RationalTime(2, 1), TransitionAlignment.CENTER
        )
        assert off == RationalTime(9, 1)


class TestTransitionGraph:
    def test_empty_clips(self):
        graph = TransitionGraph()
        segs = graph.build_segments([])
        assert segs == []

    def test_single_clip(self):
        graph = TransitionGraph()
        segs = graph.build_segments([RationalTime(5, 1)])
        assert segs == []

    def test_two_clips_fade(self):
        graph = TransitionGraph()
        segs = graph.build_segments([
            RationalTime(5, 1),
            RationalTime(5, 1),
        ])
        assert len(segs) == 1
        assert segs[0].xfade_filter == "fade"

    def test_no_transition_on_cut(self):
        cut_trans = Transition(transition_type="cut")
        graph = TransitionGraph(default_transition=cut_trans)
        segs = graph.build_segments([
            RationalTime(5, 1),
            RationalTime(5, 1),
        ])
        assert len(segs) == 0

    def test_max_duration_cap(self):
        graph = TransitionGraph(
            max_transition_duration=RationalTime(1, 1)
        )
        segs = graph.build_segments([
            RationalTime(10, 1),
            RationalTime(10, 1),
        ])
        assert segs[0].duration == RationalTime(1, 1)

    def test_build_from_timeline(self):
        tl = _make_timeline_with_video_clips()
        v1 = tl.tracks[0]
        graph = TransitionGraph()
        segs = graph.build_from_timeline(tl, v1.track_id)
        assert len(segs) == 2

    def test_build_from_timeline_no_video(self):
        tl = Timeline("t", "t", Fraction(30), 1920, 1080)
        a1 = tl.add_track(TrackType.AUDIO, "A1")
        graph = TransitionGraph()
        segs = graph.build_from_timeline(tl, a1.track_id)
        assert segs == []


class TestBuildXfadeFilterComplex:
    def test_empty(self):
        assert build_xfade_filter_complex([], []) == ""

    def test_two_clips_with_fade(self):
        segs = [
            TransitionSegment(
                clip_a_index=0,
                clip_b_index=1,
                xfade_filter="fade",
                offset=RationalTime(4, 1),
                duration=RationalTime(1, 1),
                transition=Transition(transition_type="fade"),
            )
        ]
        fc = build_xfade_filter_complex(["0:v", "1:v"], segs)
        assert "xfade=transition=fade" in fc
        assert "offset=4.0" in fc
        assert "duration=1.0" in fc

    def test_three_clips(self):
        segs = [
            TransitionSegment(
                clip_a_index=0, clip_b_index=1,
                xfade_filter="fade",
                offset=RationalTime(4, 1),
                duration=RationalTime(1, 1),
                transition=Transition(),
            ),
            TransitionSegment(
                clip_a_index=1, clip_b_index=2,
                xfade_filter="dissolve",
                offset=RationalTime(8, 1),
                duration=RationalTime(1, 1),
                transition=Transition(transition_type="dissolve"),
            ),
        ]
        fc = build_xfade_filter_complex(["0:v", "1:v", "2:v"], segs)
        assert "xfade=transition=fade" in fc
        assert "xfade=transition=dissolve" in fc

    def test_with_audio(self):
        segs = [
            TransitionSegment(
                clip_a_index=0, clip_b_index=1,
                xfade_filter="fade",
                offset=RationalTime(4, 1),
                duration=RationalTime(1, 1),
                transition=Transition(),
            )
        ]
        fc = build_xfade_filter_complex(
            ["0:v", "1:v"], segs, audio_labels=["0:a", "1:a"]
        )
        assert "acrossfade" in fc


class TestLegacyToXfade:
    def test_basic(self):
        f = legacy_to_xfade_filter("fade", 0.5, 4.0)
        assert "xfade=transition=fade" in f
        assert "duration=0.5" in f
        assert "offset=4.0" in f


class TestTransitionPresets:
    def test_quick_cut(self):
        p = get_preset("quick_cut")
        assert p is not None
        assert p.transition_type == "cut"

    def test_standard_fade(self):
        p = get_preset("standard_fade")
        assert p is not None
        assert p.duration == RationalTime(1, 2)

    def test_unknown(self):
        assert get_preset("nonexistent") is None


class TestTransitionPresetsDict:
    def test_all_presets_valid(self):
        from services.transitions import TRANSITION_PRESETS
        for name, preset in TRANSITION_PRESETS.items():
            t = Transition(
                transition_type=preset["transition_type"],
                duration=RationalTime.from_seconds(preset["duration_seconds"]),
            )
            assert isinstance(preset["description"], str)


# ══════════════════════════════════════════════════════════
# 4. Audio Mixer Tests
# ══════════════════════════════════════════════════════════

class TestAudioClip:
    def test_creation(self):
        clip = TimelineAudioClip(asset_path="music.mp3")
        assert clip.asset_path == "music.mp3"
        assert clip.enabled is True

    def test_dict(self):
        clip = TimelineAudioClip(asset_path="sfx.wav", gain_db=-6.0)
        d = clip.to_dict()
        assert d["gain_db"] == -6.0


class TestTimelineAudioMixer:
    def test_add_remove(self):
        mixer = TimelineAudioMixer()
        clip = TimelineAudioClip(asset_path="bgm.mp3")
        mixer.add_clip(clip)
        assert len(mixer.clips) == 1
        assert mixer.remove_clip(clip.clip_id)
        assert len(mixer.clips) == 0

    def test_music_volume(self):
        mixer = TimelineAudioMixer()
        mixer.music_volume = 0.5
        assert mixer.music_volume == 0.5

    def test_music_volume_range(self):
        mixer = TimelineAudioMixer()
        with pytest.raises(ValueError):
            mixer.music_volume = 3.0

    def test_sfx_volume(self):
        mixer = TimelineAudioMixer()
        mixer.sfx_volume = 0.8
        assert mixer.sfx_volume == 0.8

    def test_amix_filter(self):
        mixer = TimelineAudioMixer()
        f = mixer.build_amix_filter(["0:a", "1:a"])
        assert "amix=inputs=2" in f

    def test_amix_single_input(self):
        mixer = TimelineAudioMixer()
        f = mixer.build_amix_filter(["0:a"])
        assert "acopy" in f

    def test_amix_with_volumes(self):
        mixer = TimelineAudioMixer()
        f = mixer.build_amix_filter(["0:a", "1:a"], [0.5, 1.0])
        assert "volume=0.500" in f
        assert "amix" in f

    def test_build_fade_filter(self):
        mixer = TimelineAudioMixer()
        f = mixer.build_fade_filter(
            "0:a",
            fade_in=RationalTime(1, 1),
            fade_out=RationalTime(1, 1),
            total_duration=RationalTime(10, 1),
        )
        assert "afade=t=in" in f
        assert "afade=t=out" in f

    def test_build_fade_no_fades(self):
        mixer = TimelineAudioMixer()
        f = mixer.build_fade_filter("0:a")
        assert f == ""

    def test_ducking_rule(self):
        mixer = TimelineAudioMixer()
        rule = DuckingRule(
            source_track_ids=["voice"],
            target_track_ids=["music"],
        )
        mixer.add_ducking_rule(rule)
        assert len(mixer.ducking_rules) == 1

    def test_ducking_filter(self):
        mixer = TimelineAudioMixer()
        rule = DuckingRule()
        f = mixer.build_ducking_filter("music", "voice", rule)
        assert "sidechaincompress" in f
        assert "threshold=" in f

    def test_loudness_filter(self):
        mixer = TimelineAudioMixer()
        f = mixer.build_loudness_filter("0:a")
        assert "loudnorm" in f

    def test_loudness_target_preset(self):
        yt = LoudnessTarget.youtube()
        assert yt.target_lufs == -14.0
        ebu = LoudnessTarget.broadcast_ebu()
        assert ebu.target_lufs == -23.0
        tk = LoudnessTarget.tiktok()
        assert tk.target_lufs == -14.0


class TestDuckingProfile:
    def test_dict(self):
        p = DuckingProfile(name="test", threshold_db=-20.0)
        d = p.to_dict()
        assert d["threshold_db"] == -20.0
        assert d["mode"] == "sidechain"


# ══════════════════════════════════════════════════════════
# 5. Title/Subtitle Renderer Tests
# ══════════════════════════════════════════════════════════

class TestSubtitleEntry:
    def test_duration(self):
        e = SubtitleEntry(
            start=RationalTime(1, 1),
            end=RationalTime(4, 1),
        )
        assert e.duration == RationalTime(3, 1)

    def test_srt_time(self):
        e = SubtitleEntry()
        assert e.to_srt_time(RationalTime(0)) == "00:00:00,000"
        assert e.to_srt_time(RationalTime(65, 1)) == "00:01:05,000"

    def test_ass_time(self):
        e = SubtitleEntry()
        assert e.to_ass_time(RationalTime(0)) == "0:00:00.00"

    def test_dict(self):
        e = SubtitleEntry(text="Hello", index=1)
        d = e.to_dict()
        assert d["text"] == "Hello"


class TestSubtitleRenderer:
    def test_srt_rendering(self):
        r = SubtitleRenderer()
        r.add_entry(SubtitleEntry(
            text="Hello World",
            start=RationalTime(0),
            end=RationalTime(2, 1),
        ))
        srt = r.render_srt()
        assert "00:00:00,000 --> 00:00:02,000" in srt
        assert "Hello World" in srt
        assert srt.startswith("1\n")

    def test_srt_multiple_entries(self):
        r = SubtitleRenderer()
        r.add_entry(SubtitleEntry(text="First", start=RationalTime(0), end=RationalTime(1, 1)))
        r.add_entry(SubtitleEntry(text="Second", start=RationalTime(1, 1), end=RationalTime(2, 1)))
        srt = r.render_srt()
        assert "2\n" in srt

    def test_ass_rendering(self):
        r = SubtitleRenderer()
        r.add_entry(SubtitleEntry(text="Test", start=RationalTime(0), end=RationalTime(1, 1)))
        ass = r.render_ass()
        assert "[Script Info]" in ass
        assert "[V4+ Styles]" in ass
        assert "[Events]" in ass
        assert "Test" in ass

    def test_from_timeline(self):
        tl = Timeline("t", "t", Fraction(30), 1920, 1080)
        title_track = tl.add_track(TrackType.TITLE, "T1")
        clip = TimelineClip.create(
            asset_path="title",
            source_range=TimeRange(RationalTime(0), RationalTime(3, 1)),
            record_start=RationalTime(0),
            name="My Title",
            metadata={"text": "Hello"},
        )
        title_track.insert_clip(clip, RationalTime(0), "insert")

        r = SubtitleRenderer()
        count = r.from_timeline(tl)
        assert count == 1
        assert r.entries[0].text == "Hello"

    def test_drawtext_filters(self):
        r = SubtitleRenderer()
        r.add_entry(SubtitleEntry(text="Test", start=RationalTime(0), end=RationalTime(2, 1)))
        filters = r.build_drawtext_filters()
        assert len(filters) == 1
        assert "drawtext=text=" in filters[0]
        assert "between(t," in filters[0]

    def test_word_highlight_filters(self):
        r = SubtitleRenderer()
        entry = SubtitleEntry(
            text="Hello World",
            start=RationalTime(0),
            end=RationalTime(2, 1),
            word_timings=[
                ("Hello", RationalTime(0), RationalTime(1, 1)),
                ("World", RationalTime(1, 1), RationalTime(2, 1)),
            ],
        )
        filters = r.build_word_highlight_filters(entry)
        assert len(filters) == 3

    def test_clear(self):
        r = SubtitleRenderer()
        r.add_entry(SubtitleEntry(text="X"))
        r.clear()
        assert len(r.entries) == 0


class TestTitlePresets:
    def test_known_preset(self):
        p = get_title_preset("classic_bottom")
        assert p is not None
        assert p["position"] == "bottom"

    def test_unknown_preset(self):
        assert get_title_preset("nonexistent") is None

    def test_all_presets(self):
        from services.title_renderer import TITLE_PRESETS
        for name, preset in TITLE_PRESETS.items():
            assert "position" in preset
            assert "font_size" in preset
            assert "color" in preset


class TestSubtitleFormats:
    def test_enum_values(self):
        assert SubtitleFormat.SRT.value == "srt"
        assert SubtitleFormat.ASS.value == "ass"
        assert SubtitleFormat.WEBVTT.value == "webvtt"


class TestLoudnessTargets:
    def test_all_platforms(self):
        assert LoudnessTarget.youtube().target_lufs == -14.0
        assert LoudnessTarget.tiktok().target_lufs == -14.0
        assert LoudnessTarget.twitch().target_lufs == -14.0
        assert LoudnessTarget.broadcast_ebu().target_lufs == -23.0
