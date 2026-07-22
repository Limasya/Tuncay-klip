"""Aspect-safe auto-reframe and color grading helpers for FFmpeg."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Tuple

logger = logging.getLogger(__name__)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def generate_zoompan_filter(
    source_w: int = 1920,
    source_h: int = 1080,
    target_w: int = 1080,
    target_h: int = 1920,
    duration_s: float = 5.0,
    fps: int = 30,
    zoom_start: float = 1.0,
    zoom_end: float = 1.08,
    focus_point: Tuple[float, float] = (0.5, 0.5),
) -> str:
    """Build an eased, aspect-safe Ken Burns filter for video.

    The input is first cropped to the target aspect ratio. ``zoompan`` then
    emits one frame for each input frame (``d=1``); using the total frame
    count for ``d`` would duplicate every video frame and inflate duration.
    """
    if min(source_w, source_h, target_w, target_h, fps) <= 0:
        raise ValueError("Dimensions and fps must be positive")

    frames = max(1, round(max(duration_s, 1 / fps) * fps))
    focus_x = _clamp(float(focus_point[0]), 0.0, 1.0)
    focus_y = _clamp(float(focus_point[1]), 0.0, 1.0)
    zoom_start = max(1.0, float(zoom_start))
    zoom_end = max(1.0, float(zoom_end))

    source_ratio = source_w / source_h
    target_ratio = target_w / target_h
    if source_ratio >= target_ratio:
        crop_h = source_h
        crop_w = max(2, int(source_h * target_ratio))
    else:
        crop_w = source_w
        crop_h = max(2, int(source_w / target_ratio))
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    crop_x = int(_clamp(source_w * focus_x - crop_w / 2, 0, source_w - crop_w))
    crop_y = int(_clamp(source_h * focus_y - crop_h / 2, 0, source_h - crop_h))

    # smoothstep(p) = p*p*(3-2*p), p clamped to the render duration.
    progress = f"min(on/{frames},1)"
    eased = f"({progress})*({progress})*(3-2*({progress}))"
    zoom_expr = f"{zoom_start:.5f}+({zoom_end:.5f}-{zoom_start:.5f})*({eased})"
    focus_local_x = _clamp((source_w * focus_x - crop_x) / crop_w, 0.0, 1.0)
    focus_local_y = _clamp((source_h * focus_y - crop_y) / crop_h, 0.0, 1.0)
    x_expr = f"max(0,min(iw-iw/zoom,{focus_local_x:.5f}*iw-iw/zoom/2))"
    y_expr = f"max(0,min(ih-ih/zoom,{focus_local_y:.5f}*ih-ih/zoom/2))"

    return (
        f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},"
        f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':"
        f"d=1:s={target_w}x{target_h}:fps={fps},setsar=1"
    )


def generate_smart_crop_filter(
    source_w: int = 1920,
    source_h: int = 1080,
    target_w: int = 1080,
    target_h: int = 1920,
    focus_point: Tuple[float, float] = (0.5, 0.5),
) -> str:
    """Build a static aspect-safe crop centered around a normalized focus."""
    if min(source_w, source_h, target_w, target_h) <= 0:
        raise ValueError("Dimensions must be positive")

    source_ratio = source_w / source_h
    target_ratio = target_w / target_h
    if source_ratio >= target_ratio:
        crop_h = source_h
        crop_w = int(source_h * target_ratio)
    else:
        crop_w = source_w
        crop_h = int(source_w / target_ratio)
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    focus_x = _clamp(float(focus_point[0]), 0.0, 1.0)
    focus_y = _clamp(float(focus_point[1]), 0.0, 1.0)
    x = int(_clamp(source_w * focus_x - crop_w / 2, 0, source_w - crop_w))
    y = int(_clamp(source_h * focus_y - crop_h / 2, 0, source_h - crop_h))
    return f"crop={crop_w}:{crop_h}:{x}:{y},scale={target_w}:{target_h},setsar=1"


def apply_cinematic_lut(lut_path: str) -> str:
    """Return a validated FFmpeg ``lut3d`` filter for a local .cube file."""
    path = Path(lut_path).expanduser().resolve()
    if path.suffix.lower() != ".cube" or not path.is_file():
        logger.warning("Valid .cube LUT not found: %s", lut_path)
        return ""

    safe_path = os.fspath(path).replace("\\", "/")
    safe_path = safe_path.replace(":", "\\:").replace("'", "\\'")
    return f"lut3d=file='{safe_path}'"
