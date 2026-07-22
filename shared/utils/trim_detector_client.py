"""
Rust trim-detector binary wrapper — native silence + freeze detection.
Returns keep segments as JSON, Python handles the actual FFmpeg trimming.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Optional

logger = logging.getLogger("trim_detector_client")

TRIM_DETECTOR_PATH: Optional[str] = None


def _find_trim_detector() -> Optional[str]:
    candidates = [
        "tools/trim-detector/target/release/tuncay-trim-detector.exe",
        "tools/trim-detector/target/release/tuncay-trim-detector",
        "../tools/trim-detector/target/release/tuncay-trim-detector.exe",
        "../tools/trim-detector/target/release/tuncay-trim-detector",
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return None


def get_trim_detector() -> Optional[str]:
    global TRIM_DETECTOR_PATH
    if TRIM_DETECTOR_PATH is None:
        TRIM_DETECTOR_PATH = _find_trim_detector()
    return TRIM_DETECTOR_PATH


def is_available() -> bool:
    return get_trim_detector() is not None


async def detect_segments(
    video_path: str,
    noise_threshold_db: float = -28.0,
    min_silence_duration: float = 0.5,
    freeze_noise: float = 0.001,
    min_freeze_duration: float = 0.6,
    min_segment_duration: float = 1.5,
    merge_gap: float = 0.3,
    max_duration: float = 60.0,
) -> dict[str, Any]:
    """
    Run Rust trim-detector on a video file.

    Returns dict with:
      - total_duration (float)
      - kept_duration (float)
      - removed_duration (float)
      - removed_pct (float)
      - active_segments (list of [start, end])
      - boring_segments (list of [start, end])

    Returns empty-ish dict on failure (caller falls back to FFmpeg).
    """
    detector = get_trim_detector()
    if not detector:
        logger.debug("Rust trim-detector not found")
        return {}

    spec = {
        "video": os.path.abspath(video_path),
        "noise_threshold_db": noise_threshold_db,
        "min_silence_duration": min_silence_duration,
        "freeze_noise": freeze_noise,
        "min_freeze_duration": min_freeze_duration,
        "min_segment_duration": min_segment_duration,
        "merge_gap": merge_gap,
        "max_duration": max_duration,
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(spec, f, indent=2)
        spec_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            detector,
            "--spec", spec_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode()[:300]
            logger.warning("Rust trim-detector failed (%d): %s", proc.returncode, err)
            return {}

        result = json.loads(stdout.decode())
        logger.info(
            "Rust trim-detector: %.1fs -> %.1fs (%.0f%% removed, %d segments)",
            result.get("total_duration", 0),
            result.get("kept_duration", 0),
            result.get("removed_pct", 0),
            len(result.get("active_segments", [])),
        )
        return result

    except Exception as e:
        logger.debug("Rust trim-detector exception: %s", e)
        return {}

    finally:
        try:
            os.unlink(spec_path)
        except OSError:
            pass
