"""
Zero-Bandwidth Clip Engine — Clip Renderer
──────────────────────────────────────────
Onaylanan clip'leri HLS'den stream edip render etme.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Optional

from .alerting import FFMPEG_UA, FFMPEG_REFERER

logger = logging.getLogger("zero_bandwidth_clipper")


async def render_clip(
    vod_url: str,
    clip_start_time: float,
    clip_duration: float,
    clip_id: str,
    output_dir: Path,
    get_hls_source_fn=None,
    validate_mp4_fn=None,
    cloudflare_checker=None,
) -> dict[str, Any]:
    """Onaylanan bir clip'i indir ve render et.

    Sadece clip süresi kadar video segmenti indirilir (~2-5 MB per 30sn).
    Tam VOD indirilmez.

    Telif/Hak: Render her zaman vod_url'den (ana VOD HLS kaynağından) yapılır.
    Community clip URL'si asla render kaynağı olarak kullanılmaz.
    """
    if get_hls_source_fn is None:
        from .vod_metadata import get_hls_source as _get_hls_source
        get_hls_source_fn = _get_hls_source

    logger.info(
        "Clip render baslatiliyor: %s (%.0f-%.0f sn)",
        clip_id, clip_start_time, clip_start_time + clip_duration,
    )

    hls_url = await get_hls_source_fn(vod_url)
    if not hls_url:
        return {"success": False, "error": "HLS source URL alinamadi"}

    output_path = output_dir / f"{clip_id}.mp4"

    cmd = [
        "ffmpeg", "-y",
        "-headers", f"User-Agent: {FFMPEG_UA}\r\nReferer: {FFMPEG_REFERER}\r\n",
        "-ss", str(clip_start_time),
        "-i", hls_url,
        "-t", str(clip_duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.info(
        "FFmpeg ile clip segment indiriliyor ve render ediliyor (~%.1f MB)...",
        clip_duration * 64 / 8 / 1024,
    )
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace")[-500:] if stderr else "FFmpeg failed"
        logger.error("Clip render basarisiz: %s", error_msg[:200])

        # FFmpeg'in Kick'ten 403/404/410 almasi da Cloudflare engeli olarak sayilmali
        error_lower = error_msg.lower()
        if cloudflare_checker and any(code in error_lower for code in ["403", "410", "forbidden", "http error"]):
            cloudflare_checker(403, error_msg[:200])

        return {"success": False, "error": error_msg[:500]}

    if not output_path.exists() or output_path.stat().st_size < 1024:
        return {"success": False, "error": "Render edilen cok kucuk veya bos"}

    if validate_mp4_fn is None:
        validate_mp4_fn = _validate_mp4

    valid = await validate_mp4_fn(str(output_path))
    if not valid:
        output_path.unlink(missing_ok=True)
        return {"success": False, "error": "Render edilen clip bozuk"}

    file_mb = output_path.stat().st_size / 1024 / 1024
    logger.info("Clip render tamamlandi: %s (%.1f MB)", output_path.name, file_mb)

    return {
        "success": True,
        "clip_path": str(output_path),
        "clip_id": clip_id,
        "duration": clip_duration,
        "file_size_mb": round(file_mb, 2),
        "bandwidth_used_mb": round(file_mb, 2),
    }


async def _validate_mp4(path: str, timeout: float = 15) -> bool:
    """MP4 dosyasinin gecerli olup olmadigini kontrol et."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode != 0:
            return False
        data = json.loads(stdout.decode(errors="replace"))
        duration = float(data.get("format", {}).get("duration", 0))
        return duration > 0
    except Exception:
        return False
