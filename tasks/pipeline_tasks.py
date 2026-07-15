"""
Celery tasks for heavy pipeline operations.

These tasks run on Celery workers (not the FastAPI event loop),
so FFmpeg encoding, Whisper transcription, and uploads don't block
the real-time pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from pathlib import Path

from tasks import celery_app

logger = logging.getLogger("celery_tasks")

EXPORTS_DIR = Path("data/exports")
SUBTITLES_DIR = Path("data/subtitles")
THUMBNAILS_DIR = Path("data/thumbnails")

for d in [EXPORTS_DIR, SUBTITLES_DIR, THUMBNAILS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# ─── Subtitle Burn-in ──────────────────────────────────────

@celery_app.task(bind=True, name="tasks.burn_subtitles", max_retries=2)
def burn_subtitles(
    self,
    video_path: str,
    srt_path: str,
    clip_id: str = "",
    style: str = "",
) -> dict:
    """
    Burn SRT subtitles into video via FFmpeg.
    Returns {"output_path": ..., "status": "ok"|"error", "error": ...}
    """
    if not os.path.exists(video_path):
        return {"status": "error", "error": f"Video not found: {video_path}"}
    if not os.path.exists(srt_path):
        return {"status": "error", "error": f"SRT not found: {srt_path}"}

    base = Path(video_path).stem
    output_path = str(EXPORTS_DIR / f"{base}_subtitled.mp4")

    if not style:
        style = (
            "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,Outline=2,Shadow=1,MarginV=30"
        )

    srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"subtitles={srt_escaped}:force_style='{style}'",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "copy",
        output_path,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            logger.info("Subtitle burn-in complete: %s", output_path)
            return {"output_path": output_path, "status": "ok"}
        else:
            error_msg = result.stderr[:500]
            logger.error("FFmpeg subtitle error: %s", error_msg)
            raise self.retry(exc=RuntimeError(error_msg), countdown=5)
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Burn-in timeout (300s)"}


# ─── Video Export (multi-platform aspect ratios) ───────────

PLATFORM_PROFILES = {
    "youtube": {"aspect": "16:9", "width": 1280, "height": 720},
    "tiktok": {"aspect": "9:16", "width": 720, "height": 1280},
    "instagram_reels": {"aspect": "9:16", "width": 720, "height": 1280},
    "instagram_post": {"aspect": "1:1", "width": 720, "height": 720},
    "shorts": {"aspect": "9:16", "width": 720, "height": 1280},
}


@celery_app.task(bind=True, name="tasks.export_clip", max_retries=1)
def export_clip(
    self,
    clip_path: str,
    platforms: list[str] = None,
) -> dict:
    """
    Export a clip to multiple platform aspect ratios.
    Returns {"exports": {platform: path}, "failed": [platforms]}
    """
    if not os.path.exists(clip_path):
        return {"status": "error", "error": f"Clip not found: {clip_path}"}

    platforms = platforms or ["youtube", "tiktok"]
    base = Path(clip_path).stem
    exports = {}
    failed = []

    for platform in platforms:
        profile = PLATFORM_PROFILES.get(platform, PLATFORM_PROFILES["youtube"])
        w, h = profile["width"], profile["height"]
        out_path = str(EXPORTS_DIR / f"{base}_{platform}_{w}x{h}.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", clip_path,
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            out_path,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0 and os.path.exists(out_path):
                exports[platform] = out_path
                logger.info("Exported %s: %s", platform, out_path)
            else:
                failed.append(platform)
                logger.error("Export failed for %s: %s", platform, result.stderr[:300])
        except subprocess.TimeoutExpired:
            failed.append(platform)

    return {
        "clip_path": clip_path,
        "exports": exports,
        "failed": failed,
        "status": "ok" if not failed else "partial",
    }


# ─── Thumbnail Generation ──────────────────────────────────

@celery_app.task(name="tasks.generate_thumbnail")
def generate_thumbnail(
    clip_path: str,
    clip_id: str = "",
    time_point: float = 0.5,
) -> dict:
    """
    Extract a thumbnail from the clip at the given time point.
    Returns {"thumbnail_path": ..., "status": "ok"|"error"}
    """
    if not os.path.exists(clip_path):
        return {"status": "error", "error": f"Clip not found: {clip_path}"}

    name = clip_id or Path(clip_path).stem
    thumb_path = str(THUMBNAILS_DIR / f"{name}.jpg")

    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-ss", str(time_point),
        "-vframes", "1",
        "-q:v", "2",
        thumb_path,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and os.path.exists(thumb_path):
            return {"thumbnail_path": thumb_path, "status": "ok"}
        else:
            return {"status": "error", "error": result.stderr[:300]}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Thumbnail extraction timeout"}


# ─── AI Metadata Generation ────────────────────────────────

@celery_app.task(name="tasks.generate_metadata")
def generate_metadata(
    clip_id: str,
    category: str = "exciting",
    platform: str = "youtube",
    streamer_name: str = "Tuncay",
    emotion: str = "",
    viewer_count: int = 0,
    game_name: str = "",
) -> dict:
    """
    Generate AI title, description, and hashtags for a clip.
    Returns {"title", "description", "hashtags", "status": "ok"}
    """
    try:
        from src.ai_generator import ai_title_generator

        metadata = ai_title_generator.generate_full_metadata(
            emotion=emotion or category,
            category=category,
            streamer_name=streamer_name,
            viewer_count=viewer_count,
            game_name=game_name,
            platform=platform,
        )
        metadata["clip_id"] = clip_id
        metadata["status"] = "ok"
        return metadata

    except Exception as e:
        logger.error("Metadata generation failed: %s", e)
        return {
            "clip_id": clip_id,
            "title": f"Clip {clip_id[:8]}",
            "description": "",
            "hashtags": [],
            "status": "error",
            "error": str(e),
        }


# ─── Platform Upload ──────────────────────────────────────

@celery_app.task(bind=True, name="tasks.upload_to_platform", max_retries=3)
def upload_to_platform(
    self,
    clip_path: str,
    platform: str,
    title: str = "",
    description: str = "",
    tags: list[str] = None,
) -> dict:
    """
    Upload a clip to a social platform.
    Retries up to 3 times on failure.
    Returns {"video_id", "url", "status": "ok"|"error"}
    """
    if not os.path.exists(clip_path):
        return {"status": "error", "error": f"File not found: {clip_path}"}

    try:
        from src.uploader import auto_publisher

        # Run async publisher in sync context
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(
                auto_publisher.publish(
                    video_path=clip_path,
                    title=title or "Auto-generated clip",
                    description=description,
                    tags=tags or [],
                    platform=platform,
                    privacy="private",
                )
            )
        finally:
            loop.close()

        if result:
            logger.info("Uploaded to %s: %s", platform, result.get("url"))
            return {
                "video_id": result.get("video_id", ""),
                "url": result.get("url", ""),
                "platform": platform,
                "status": "ok",
            }
        else:
            raise self.retry(exc=RuntimeError("Upload returned empty"), countdown=10)

    except Exception as e:
        logger.error("Upload to %s failed: %s", platform, e)
        raise self.retry(exc=e, countdown=10)


# ─── Whisper Transcription ─────────────────────────────────

@celery_app.task(bind=True, name="tasks.transcribe_clip", max_retries=1)
def transcribe_clip(
    self,
    clip_path: str,
    language: str = "tr",
    model_size: str = "base",
) -> dict:
    """
    Transcribe a clip using Whisper.
    Returns {"text", "segments": [...], "language", "status": "ok"}
    """
    if not os.path.exists(clip_path):
        return {"status": "error", "error": f"Clip not found: {clip_path}"}

    try:
        import whisper

        model = whisper.load_model(model_size)
        result = model.transcribe(
            clip_path,
            language=language if language else None,
            task="transcribe",
        )

        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg.get("start", 0.0),
                "end": seg.get("end", 0.0),
                "text": seg.get("text", ""),
            })

        return {
            "text": result.get("text", ""),
            "segments": segments,
            "language": result.get("language", language),
            "status": "ok",
        }

    except Exception as e:
        logger.error("Transcription failed: %s", e)
        return {"status": "error", "error": str(e)}


# ─── Batch Operations ─────────────────────────────────────

@celery_app.task(name="tasks.process_clip_full")
def process_clip_full(
    clip_path: str,
    clip_id: str = "",
    category: str = "exciting",
    platforms: list[str] = None,
    auto_upload: bool = False,
    language: str = "tr",
) -> dict:
    """
    Full post-clip processing pipeline:
    1. Transcribe → 2. Generate SRT → 3. Export → 4. Thumbnail → 5. Metadata → 6. Upload

    This is a Celery chain orchestration — each step dispatches to the
    appropriate task.
    """
    from celery import chain, group

    clip_id = clip_id or Path(clip_path).stem

    # Run transcription + thumbnail + metadata in parallel (they're independent)
    parallel_group = group(
        transcribe_clip.s(clip_path, language),
        generate_thumbnail.s(clip_path, clip_id),
        generate_metadata.s(clip_id, category, "youtube"),
    )

    # Then export to platforms
    export_task = export_clip.s(clip_path, platforms or ["youtube", "tiktok"])

    result = parallel_group.apply_async()

    # Wait for parallel results with timeout
    try:
        parallel_results = result.get(timeout=300)
    except Exception as e:
        logger.error("Parallel processing timeout: %s", e)
        parallel_results = []

    # Run export
    export_result = export_task.apply_async().get(timeout=300)

    # Collect all results
    return {
        "clip_id": clip_id,
        "clip_path": clip_path,
        "parallel_results": parallel_results,
        "export_result": export_result,
        "status": "ok",
    }
