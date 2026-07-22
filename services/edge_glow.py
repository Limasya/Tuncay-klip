"""
Edge Glow Efekti Ureteci
opensource-clipping edge_glow.py'den adaptasyon.
Cerceve kenarlarinda yavas hareket eden gradient isik efekti uretir.
"""
import asyncio
import logging
import math
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import cv2
    import numpy as np
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


@dataclass
class EdgeGlowConfig:
    """Edge glow konfigurasyonu."""
    edge_thickness: int = 0
    glow_speed: float = 0.15
    opacity: float = 0.45
    fps: int = 30
    seamless_loop: bool = True


def generate_edge_glow_video(
    output_path: str,
    width: int,
    height: int,
    duration: float = 10.0,
    config: Optional[EdgeGlowConfig] = None,
) -> str:
    """
    Kenar glow overlay video uretir (siyah arka plan, screen blend ile ustuste binilir).

    Args:
        output_path: Cikis video dosya yolu.
        width: Frame genisligi.
        height: Frame yuksekligi.
        duration: Süre (saniye).
        config: Edge glow parametreleri.

    Returns:
        Olusturulan video dosya yolu.
    """
    if not _AVAILABLE:
        raise RuntimeError("OpenCV/NumPy yuklenemedi")

    if config is None:
        config = EdgeGlowConfig()

    fps = config.fps
    glow_speed = config.glow_speed
    opacity = config.opacity

    if config.seamless_loop and duration > 0:
        raw_rotations = duration * glow_speed
        n_rotations = max(1, round(raw_rotations))
        adjusted_speed = n_rotations / duration
        if abs(adjusted_speed - glow_speed) > 1e-6:
            logger.info("Edge glow: hiz ayarlandi %.3f -> %.3f (seamless loop)", glow_speed, adjusted_speed)
        glow_speed = adjusted_speed

    edge_thickness = config.edge_thickness
    if edge_thickness <= 0:
        edge_thickness = max(40, int(min(width, height) * 0.10))

    total_frames = int(duration * fps)

    ys = np.arange(height).reshape(-1, 1).astype(np.float32)
    xs = np.arange(width).reshape(1, -1).astype(np.float32)

    d_top = ys
    d_bottom = (height - 1) - ys
    d_left = xs
    d_right = (width - 1) - xs

    d_edge = np.minimum(np.minimum(d_top, d_bottom), np.minimum(d_left, d_right))
    alpha = np.clip(1.0 - d_edge / edge_thickness, 0, 1)
    alpha = alpha * alpha
    alpha = (alpha * opacity * 255).astype(np.uint8)

    perimeter = float(2 * (width + height))
    p_top = xs.copy()
    p_right = np.full_like(ys, width, dtype=np.float32) + ys
    p_bottom = np.full_like(xs, width + height, dtype=np.float32) + ((width - 1) - xs)
    p_left = np.full_like(ys, 2 * width + height, dtype=np.float32) + ((height - 1) - ys)

    d_top_b = np.broadcast_to(d_top, (height, width))
    d_bottom_b = np.broadcast_to(d_bottom, (height, width))
    d_left_b = np.broadcast_to(d_left, (height, width))
    d_right_b = np.broadcast_to(d_right, (height, width))

    p_top_b = np.broadcast_to(p_top, (height, width))
    p_right_b = np.broadcast_to(p_right, (height, width))
    p_bottom_b = np.broadcast_to(p_bottom, (height, width))
    p_left_b = np.broadcast_to(p_left, (height, width))

    dists = np.stack([d_top_b, d_right_b, d_bottom_b, d_left_b], axis=-1)
    positions = np.stack([p_top_b, p_right_b, p_bottom_b, p_left_b], axis=-1)
    nearest_idx = np.argmin(dists, axis=-1)
    pos_map = np.take_along_axis(positions, nearest_idx[..., np.newaxis], axis=-1).squeeze(-1)
    pos_map = pos_map / perimeter

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        output_path,
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    hsv_frame = np.zeros((height, width, 3), dtype=np.uint8)
    hsv_frame[:, :, 1] = 200

    for fi in range(total_frames):
        t = fi / fps
        hue_offset = t * glow_speed
        hue = ((pos_map + hue_offset) % 1.0 * 180).astype(np.uint8)
        hsv_frame[:, :, 0] = hue
        hsv_frame[:, :, 2] = alpha
        bgr = cv2.cvtColor(hsv_frame, cv2.COLOR_HSV2BGR)
        proc.stdin.write(bgr.tobytes())

    proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", errors="ignore")
    rc = proc.wait()
    if rc != 0:
        logger.warning("Edge glow uretim hatasi: %s", stderr[-500:])

    logger.info("Edge glow video uretildi: %s (%d frame)", output_path, total_frames)
    return output_path


async def generate_edge_glow_async(
    output_path: str,
    width: int,
    height: int,
    duration: float = 10.0,
    config: Optional[EdgeGlowConfig] = None,
) -> str:
    """Async wrapper for edge glow generation."""
    return await asyncio.to_thread(
        generate_edge_glow_video, output_path, width, height, duration, config
    )
