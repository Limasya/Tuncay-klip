"""
Transcription Microservice
───────────────────────────
Subscribes to CLIP_CREATED events, extracts audio via FFmpeg,
runs Whisper transcription, and publishes TRANSCRIPT_READY events.

Flow: CLIP_CREATED → Extract Audio (FFmpeg) → Whisper → TRANSCRIPT_READY
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

from shared.event_bus import EventBus, get_event_bus
from shared.event_schemas import (
    EventType, SystemEvent, TranscriptResult,
)

logger = logging.getLogger("transcription")


class TranscriptionService:
    """
    Whisper-based transcription service.

    Subscribes to CLIP_CREATED events.
    For each new clip:
      1. Extract audio from video file using FFmpeg
      2. Run Whisper ASR (lazy-loaded)
      3. Publish TRANSCRIPT_READY event with text + segments
    """

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        model_size: str = "base",
        language: Optional[str] = None,
    ):
        self.event_bus = event_bus or get_event_bus()
        self.model_size = model_size
        self.language = language

        self._whisper_model = None
        self._clips_transcribed = 0
        self._clips_failed = 0

        # Subscribe to clip created events
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

    def _load_whisper(self):
        """Lazy-load Whisper model (downloads on first use)."""
        if self._whisper_model is not None:
            return

        try:
            import whisper
            logger.info(f"Loading Whisper model: {self.model_size}")
            self._whisper_model = whisper.load_model(self.model_size)
            logger.info("Whisper model loaded successfully")
        except ImportError:
            logger.error(
                "openai-whisper not installed. "
                "Install with: pip install openai-whisper"
            )
        except Exception as e:
            logger.error(f"Whisper model load failed: {e}")

    async def _on_clip_created(self, event: SystemEvent):
        """Handle a new clip — transcribe it."""
        clip_data = event.payload
        file_path = clip_data.get("file_path", "")

        if not file_path or not os.path.exists(file_path):
            logger.warning(f"Clip file not found: {file_path}")
            self._clips_failed += 1
            return

        logger.info(f"Transcribing clip: {file_path}")

        try:
            # 1. Extract audio
            audio_path = await self._extract_audio(file_path)
            if not audio_path:
                logger.warning("Audio extraction failed, skipping transcription")
                self._clips_failed += 1
                return

            # 2. Run Whisper
            result = await self.transcribe(audio_path)

            # 3. Publish TRANSCRIPT_READY
            transcript = TranscriptResult(
                text=result.get("text", ""),
                language=result.get("language", self.language or ""),
                language_probability=result.get("language_probability", 0.0),
                words=[
                    {"start": s["start"], "end": s["end"], "text": s["text"]}
                    for s in result.get("segments", [])
                ],
            )

            self._clips_transcribed += 1

            await self.event_bus.publish_quick(
                EventType.TRANSCRIPT_READY,
                {
                    "clip_file_path": file_path,
                    "transcript": transcript.model_dump(mode="json"),
                    "segments": result.get("segments", []),
                },
                source_service="transcription",
                stream_id=event.stream_id,
                causation_id=event.event_id,
            )

            # 4. Cleanup temp audio
            if audio_path and os.path.exists(audio_path):
                os.remove(audio_path)

            logger.info(
                f"Transcription complete: {len(result.get('segments', []))} segments, "
                f"lang={result.get('language', 'unknown')}"
            )

        except Exception as e:
            logger.error(f"Transcription pipeline error: {e}", exc_info=True)
            self._clips_failed += 1

    async def _extract_audio(self, video_path: str) -> Optional[str]:
        """Extract WAV audio from video using FFmpeg."""
        audio_path = video_path.rsplit(".", 1)[0] + "_transcript.wav"

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-v", "quiet",
            audio_path,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=120)

            if proc.returncode == 0 and os.path.exists(audio_path):
                return audio_path

        except asyncio.TimeoutError:
            logger.error("Audio extraction timed out")
        except Exception as e:
            logger.error(f"Audio extraction error: {e}")

        return None

    async def transcribe(self, audio_path: str) -> dict:
        """Run Whisper transcription on an audio file."""
        self._load_whisper()

        if self._whisper_model is None:
            return {"text": "", "segments": [], "language": ""}

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._whisper_model.transcribe(
                audio_path,
                language=self.language,
                task="transcribe",
                verbose=False,
            ),
        )

        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"].strip(),
            })

        return {
            "text": result.get("text", "").strip(),
            "segments": segments,
            "language": result.get("language", ""),
            "language_probability": result.get("language_probability", 0.0),
        }

    def get_status(self) -> dict:
        return {
            "model_size": self.model_size,
            "model_loaded": self._whisper_model is not None,
            "language": self.language,
            "clips_transcribed": self._clips_transcribed,
            "clips_failed": self._clips_failed,
        }
