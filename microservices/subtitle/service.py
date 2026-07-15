"""
Subtitle Microservice
──────────────────────
Subscribes to TRANSCRIPT_READY → generates SRT → optionally burns in →
publishes SUBTITLE_READY.

Replaces the monolithic services/subtitle_service.py with an event-driven
microservice that plugs into the EventBus pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import EventType, SystemEvent

logger = logging.getLogger("subtitle_service")

SUBTITLES_DIR = Path("data/subtitles")
SUBTITLES_DIR.mkdir(parents=True, exist_ok=True)

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


class SubtitleMicroservice:
    """
    Event-driven subtitle generator.

    Listens for TRANSCRIPT_READY events (from TranscriptionService),
    produces SRT files, and optionally burns them into the video.
    Publishes SUBTITLE_READY when done.
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        burn_in: bool = False,
        style: Optional[str] = None,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.burn_in = burn_in
        self.style = style or (
            "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,Outline=2,Shadow=1,"
            "MarginV=30"
        )

        # Metrics
        self._srt_generated = 0
        self._burn_in_count = 0
        self._failed = 0

        # Subscribe to TRANSCRIPT_READY
        self.event_bus.subscribe(
            EventType.TRANSCRIPT_READY.value,
            self._on_transcript_ready,
        )

        logger.info("SubtitleMicroservice initialized (burn_in=%s)", burn_in)

    async def _on_transcript_ready(self, event: SystemEvent):
        """Handle transcript ready — generate SRT and optionally burn in."""
        payload = event.payload
        clip_path = payload.get("clip_path", "")
        segments = payload.get("segments", [])
        language = payload.get("language", "")
        clip_id = payload.get("clip_id", "")

        if not segments:
            logger.warning("No segments in transcript for %s", clip_path)
            return

        try:
            # 1. Generate SRT
            srt_path = await self._generate_srt(
                segments=segments,
                clip_id=clip_id or Path(clip_path).stem,
            )

            if not srt_path:
                self._failed += 1
                return

            self._srt_generated += 1
            subtitled_video_path = None

            # 2. Optionally burn-in
            if self.burn_in and clip_path and os.path.exists(clip_path):
                subtitled_video_path = await self._burn_subtitles(
                    clip_path, srt_path
                )
                if subtitled_video_path:
                    self._burn_in_count += 1

            # 3. Publish SUBTITLE_READY
            await self.event_bus.publish_quick(
                EventType.SUBTITLE_READY,
                payload={
                    "clip_id": clip_id,
                    "clip_path": subtitled_video_path or clip_path,
                    "srt_path": srt_path,
                    "language": language,
                    "segment_count": len(segments),
                    "burned_in": subtitled_video_path is not None,
                },
                source_service="subtitle",
                stream_id=event.stream_id,
                causation_id=event.event_id,
            )

            logger.info(
                "Subtitle ready: %s (%d segments, burn=%s)",
                clip_id, len(segments), subtitled_video_path is not None,
            )

        except Exception as e:
            self._failed += 1
            logger.error("Subtitle generation failed: %s", e, exc_info=True)

    async def _generate_srt(
        self,
        segments: list[dict],
        clip_id: str,
    ) -> Optional[str]:
        """Generate an SRT file from transcript segments."""
        output_path = str(SUBTITLES_DIR / f"{clip_id}.srt")

        lines = []
        for i, seg in enumerate(segments, 1):
            start = self._format_srt_time(seg.get("start", 0.0))
            end = self._format_srt_time(seg.get("end", 0.0))
            text = seg.get("text", "").strip()
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")

        try:
            Path(output_path).write_text("\n".join(lines), encoding="utf-8")
            logger.debug("SRT written: %s", output_path)
            return output_path
        except Exception as e:
            logger.error("SRT write error: %s", e)
            return None

    async def _burn_subtitles(
        self,
        video_path: str,
        srt_path: str,
    ) -> Optional[str]:
        """Burn SRT subtitles into video via FFmpeg."""
        output_path = str(
            EXPORTS_DIR / f"{Path(video_path).stem}_subtitled.mp4"
        )

        # Windows path escaping for FFmpeg subtitles filter
        srt_escaped = srt_path.replace("\\", "/").replace(":", "\\:")

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vf", f"subtitles={srt_escaped}:force_style='{self.style}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            output_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode == 0:
                logger.info("Subtitles burned: %s", output_path)
                return output_path
            else:
                logger.error("Burn-in error: %s", stderr.decode()[:500])
                return None

        except asyncio.TimeoutError:
            logger.error("Burn-in timeout")
            return None
        except Exception as e:
            logger.error("Burn-in error: %s", e)
            return None

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """Convert seconds to SRT time format (HH:MM:SS,mmm)."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    def get_status(self) -> dict:
        return {
            "srt_generated": self._srt_generated,
            "burn_in_count": self._burn_in_count,
            "failed": self._failed,
            "burn_in_enabled": self.burn_in,
        }
