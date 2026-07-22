from pathlib import Path

from services.compositor import CompositeLayer, CompositorConfig, LayerCompositor
from services.smart_crop import (
    apply_cinematic_lut,
    generate_smart_crop_filter,
    generate_zoompan_filter,
)


def test_zoompan_is_aspect_safe_and_does_not_duplicate_frames():
    result = generate_zoompan_filter(
        source_w=1920,
        source_h=1080,
        target_w=1080,
        target_h=1920,
        duration_s=10,
        fps=30,
    )

    assert result.startswith("crop=606:1080:")
    assert ":d=1:" in result
    assert "setsar=1" in result
    assert "on/300" in result


def test_smart_crop_clamps_focus_inside_frame():
    result = generate_smart_crop_filter(
        source_w=1920,
        source_h=1080,
        focus_point=(1.5, -0.5),
    )

    assert result == "crop=606:1080:1314:0,scale=1080:1920,setsar=1"


def test_lut_requires_an_existing_cube_file(tmp_path: Path):
    invalid = tmp_path / "grade.txt"
    invalid.write_text("not a lut", encoding="ascii")
    assert apply_cinematic_lut(str(invalid)) == ""

    lut = tmp_path / "grade.cube"
    lut.write_text("LUT_3D_SIZE 2\n", encoding="ascii")
    assert apply_cinematic_lut(str(lut)).startswith("lut3d=file='")


def test_compositor_applies_lut_once_to_final_output(tmp_path: Path):
    lut = tmp_path / "grade.cube"
    lut.write_text("LUT_3D_SIZE 2\n", encoding="ascii")
    compositor = LayerCompositor(CompositorConfig(lut_path=str(lut)))
    compositor.add_layer(CompositeLayer(source_clip_id="base"))
    compositor.add_layer(CompositeLayer(source_clip_id="overlay"))

    graph = compositor.build_filter_graph()

    assert graph.count("lut3d=") == 1
    assert graph.count("[vout]") == 1
    assert "[vout_pre]" in graph
    assert graph.startswith("[0:v][1:v]overlay=")


def test_compositor_single_layer_lut_has_valid_first_filter(tmp_path: Path):
    lut = tmp_path / "grade.cube"
    lut.write_text("LUT_3D_SIZE 2\n", encoding="ascii")
    compositor = LayerCompositor(CompositorConfig(lut_path=str(lut)))
    compositor.add_layer(CompositeLayer(source_clip_id="base"))

    graph = compositor.build_filter_graph()

    assert graph.startswith("[0:v]lut3d=")
    assert not graph.startswith(";")
