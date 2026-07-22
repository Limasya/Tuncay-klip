"""
Rust audio-mixer binary wrapper — tek FFmpeg pasusu ile SFX + muzik + ducking.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("audio_mixer_client")

AUDIO_MIXER_PATH: Optional[str] = None


def _find_audio_mixer() -> Optional[str]:
    """Rust audio-mixer binary'ini bul."""
    candidates = [
        "tools/audio-mixer/target/release/tuncay-audio-mixer.exe",
        "tools/audio-mixer/target/release/tuncay-audio-mixer",
        "../tools/audio-mixer/target/release/tuncay-audio-mixer.exe",
        "../tools/audio-mixer/target/release/tuncay-audio-mixer",
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return None


def get_audio_mixer() -> Optional[str]:
    global AUDIO_MIXER_PATH
    if AUDIO_MIXER_PATH is None:
        AUDIO_MIXER_PATH = _find_audio_mixer()
    return AUDIO_MIXER_PATH


def is_available() -> bool:
    return get_audio_mixer() is not None


async def mix_audio(
    video_path: str,
    output_path: str,
    music_path: str = "",
    music_volume_db: float = -18.0,
    sfx_events: Optional[list[dict[str, Any]]] = None,
    enable_ducking: bool = True,
    video_bitrate: str = "copy",
    audio_bitrate: str = "192k",
) -> bool:
    """
    Rust audio-mixer ile tek FFmpeg pasusu ile mixing.
    Tum SFX + muzik + ducking tek FFmpeg cagrisinda.
    
    Returns:
        Basariliysa True, herhangi bir hata/eksiklikte False (fallback).
    """
    mixer = get_audio_mixer()
    if not mixer:
        logger.debug("Rust audio-mixer bulunamadi, FFmpeg fallback kullanilacak")
        return False

    sfx_events = sfx_events or []

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        spec = {
            "video": os.path.abspath(video_path),
            "output": os.path.abspath(output_path),
            "music": os.path.abspath(music_path) if music_path and os.path.exists(music_path) else None,
            "music_volume_db": music_volume_db,
            "sfx_events": [
                {
                    "file": os.path.abspath(s.get("file", s.get("sfx_path", ""))),
                    "timestamp": s.get("timestamp", 2.0),
                    "volume_db": s.get("volume_db", -8.0),
                    "mix_ratio": s.get("mix_ratio", 0.6),
                }
                for s in sfx_events
                if os.path.exists(s.get("file", s.get("sfx_path", "")))
            ],
            "enable_ducking": enable_ducking,
            "video_bitrate": video_bitrate,
            "audio_bitrate": audio_bitrate,
        }
        json.dump(spec, f, indent=2)
        spec_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            mixer,
            "--spec", spec_path,
            "--verbose",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode()[:300]
            logger.warning("Rust audio-mixer failed (%d): %s", proc.returncode, err)
            return False

        logger.info(
            "Rust audio-mixer: %d SFX + %s -> %s",
            len(spec["sfx_events"]),
            "muzik" if spec["music"] else "muziksiz",
            os.path.basename(output_path),
        )
        return True

    except Exception as e:
        logger.debug("Rust audio-mixer exception: %s", e)
        return False

    finally:
        try:
            os.unlink(spec_path)
        except OSError:
            pass
