"""
Pipeline Orchestrator
──────────────────────
Wires all microservices together into a running pipeline.

Architecture:
┌─────────────────────────────────────────────────────────────────────┐
│                          EVENT BUS                                    │
│   (in-memory / Redis Streams)                                         │
└──────┬───────┬───────┬───────┬───────┬───────┬───────┬───────┬──────┘
       │       │       │       │       │       │       │       │
  ┌────▼───┐ ┌─▼────┐ ┌▼─────┐ ┌▼─────┐ ┌▼──────┐ ┌▼─────┐ ┌▼─────┐ ┌▼────────┐
  │ Stream │ │Video │ │Audio │ │ Chat │ │ Event │ │Trans │ │Sub-  │ │Thumb/AI │
  │Capture │ │Anal. │ │Anal. │ │ Anal │ │Detect │ │cript │ │title │ │Editor   │
  └────┬───┘ └──────┘ └──────┘ └──────┘ └───┬───┘ └──────┘ └──────┘ └─────────┘
       │                                      │
       │         ┌────────────┐               │
       └────────►│  Decision  │◄──────────────┘
                 │  Engine    │
                 └─────┬──────┘
                       │
                 ┌─────▼──────┐    ┌──────────┐    ┌──────────┐
                 │    Clip    │───►│  Upload  │───►│ Publish  │
                 │ Generator  │    │  (opt)   │    │          │
                 └────────────┘    └──────────┘    └──────────┘
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import numpy as np

from shared.event_bus import EventBus, init_event_bus
from shared.event_schemas import EventType, SystemEvent

from microservices.stream_capture.service import StreamCaptureService, Frame
from microservices.video_analysis.service import VideoAnalysisService
from microservices.audio_analysis.service import AudioAnalysisService
from microservices.chat_analysis.service import ChatAnalysisService
from microservices.event_detector.service import EventDetectorService
from microservices.decision_engine.service import DecisionEngineService
from microservices.clip_generator.service import ClipGeneratorService
from microservices.chat_source import KickChatSource
from microservices.transcription.service import TranscriptionService
from microservices.subtitle.service import SubtitleMicroservice
from microservices.video_editor.service import VideoEditorMicroservice
from microservices.ai_generator.service import AIGeneratorMicroservice
from microservices.uploader.service import UploaderMicroservice
from microservices.thumbnail.service import ThumbnailMicroservice
from microservices.notification.service import NotificationService
from services.ai_pipeline import ai_pipeline as ai_pipeline_hub
from config import get_settings

logger = logging.getLogger("orchestrator")


class PipelineOrchestrator:
    """
    Manages the full event-driven pipeline lifecycle.

    1. Initializes event bus
    2. Creates all microservices
    3. Wires them together via event subscriptions
    4. Starts stream capture
    5. Routes frames to analysis services
    """

    def __init__(self):
        self.event_bus: Optional[EventBus] = None

        # Services
        self.stream_capture: Optional[StreamCaptureService] = None
        self.video_analysis: Optional[VideoAnalysisService] = None
        self.audio_analysis: Optional[AudioAnalysisService] = None
        self.chat_analysis: Optional[ChatAnalysisService] = None
        self.event_detector: Optional[EventDetectorService] = None
        self.decision_engine: Optional[DecisionEngineService] = None
        self.clip_generator: Optional[ClipGeneratorService] = None
        self.chat_source: Optional[KickChatSource] = None
        self.transcription: Optional[TranscriptionService] = None
        self.subtitle: Optional[SubtitleMicroservice] = None
        self.video_editor: Optional[VideoEditorMicroservice] = None
        self.ai_generator: Optional[AIGeneratorMicroservice] = None
        self.uploader: Optional[UploaderMicroservice] = None
        self.thumbnail: Optional[ThumbnailMicroservice] = None
        self.notification_service: Optional[NotificationService] = None
        self.ai_pipeline_hub = None

        self._is_running = False
        self._start_time: Optional[datetime] = None
        self._analysis_task: Optional[asyncio.Task] = None

        # Analysis throttle
        self._last_analysis_time = 0.0
        self._analysis_interval = 0.5  # Analyze every 0.5s (2 FPS)

    async def initialize(self):
        """Initialize event bus and lightweight services.
        Video analysis is initialized lazily (downloads ML models)."""
        logger.info("Initializing pipeline orchestrator...")
        settings = get_settings()

        # Start event bus
        self.event_bus = await init_event_bus()

        # Create lightweight services
        self.audio_analysis = AudioAnalysisService(self.event_bus)
        self.chat_analysis = ChatAnalysisService(self.event_bus)
        self.event_detector = EventDetectorService(
            event_bus=self.event_bus,
            score_threshold=settings.emotion_threshold,
            score_interval=settings.decision_score_interval,
            decay_halflife=settings.decision_decay_halflife,
        )
        self.decision_engine = DecisionEngineService(
            event_bus=self.event_bus,
            clip_threshold=settings.decision_clip_threshold,
            cooldown_seconds=settings.decision_cooldown_seconds,
            min_evidence_signals=settings.decision_min_evidence,
            confirmation_window=settings.decision_confirmation_window,
            confirmation_required=settings.decision_confirmation_required,
            threshold_floor=settings.decision_threshold_floor,
            evidence_threshold=settings.decision_evidence_threshold,
        )

        # Subscribe to clip creation for logging
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

        # Start transcription service (subscribes to CLIP_CREATED)
        self.transcription = TranscriptionService(event_bus=self.event_bus)

        # Start post-clip pipeline services
        self.subtitle = SubtitleMicroservice(event_bus=self.event_bus)
        self.video_editor = VideoEditorMicroservice(event_bus=self.event_bus)
        self.ai_generator = AIGeneratorMicroservice(event_bus=self.event_bus)
        self.uploader = UploaderMicroservice(event_bus=self.event_bus)
        self.thumbnail = ThumbnailMicroservice(event_bus=self.event_bus)

        # Notification service (webhooks)
        self.notification_service = NotificationService(event_bus=self.event_bus)
        self.notification_service.auto_configure_from_settings()

        # AI Pipeline Hub — aggregates Vision AI, Audio AI, Chat AI,
        # LLM, Recommendation Engine, and Smart Editor.
        self.ai_pipeline_hub = ai_pipeline_hub
        try:
            await self.ai_pipeline_hub.start()
        except Exception as e:
            logger.warning("AI Pipeline Hub start failed (non-fatal): %s", e)

        # AI_METADATA_READY subscriber — log enrichment events.
        async def _on_ai_metadata_ready(event: SystemEvent):
            logger.info(
                "AI_METADATA_READY: clip_id=%s",
                event.payload.get("clip_id", "?"),
            )

        self.event_bus.subscribe(
            EventType.AI_METADATA_READY.value,
            _on_ai_metadata_ready,
        )

        logger.info("All microservices initialized")

    async def _ensure_video_analysis(self):
        """Lazily initialize video analysis (downloads ML models)."""
        if not self.event_bus:
            await self.initialize()
        if not self.video_analysis:
            logger.info("Loading video analysis models...")
            self.video_analysis = VideoAnalysisService(self.event_bus)
            logger.info("Video analysis ready")

    async def start_stream(
        self,
        stream_url: str,
        target_fps: int = 2,
        buffer_seconds: int = 30,
    ):
        """Start capturing a stream and processing frames."""
        if self._is_running:
            logger.warning("Pipeline already running")
            return

        if not self.event_bus:
            await self.initialize()

        # Create capture service
        self.stream_capture = StreamCaptureService(
            stream_url=stream_url,
            target_fps=target_fps,
            buffer_seconds=buffer_seconds,
            event_bus=self.event_bus,
        )

        # Create clip generator (needs capture reference)
        self.clip_generator = ClipGeneratorService(
            event_bus=self.event_bus,
            capture_service=self.stream_capture,
        )

        # Register frame callback
        self.stream_capture.on_frame(self._on_new_frame)

        # Register audio callback
        self.stream_capture.on_audio_chunk(self._on_new_audio)

        # Start capture
        await self.stream_capture.start()

        # Start chat source (if Kick API is available)
        if self.chat_analysis:
            self.chat_source = KickChatSource(
                event_bus=self.event_bus,
                chat_analysis=self.chat_analysis,
            )
            await self.chat_source.start()

        self._is_running = True
        self._start_time = datetime.utcnow()

        logger.info(f"Pipeline started: {stream_url}")

    async def stop(self):
        """Stop the pipeline gracefully."""
        self._is_running = False

        if self.chat_source:
            try:
                await self.chat_source.stop()
            except Exception as e:
                logger.error("Chat source stop error: %s", e)

        if self.stream_capture:
            try:
                await self.stream_capture.stop()
            except Exception as e:
                logger.error("Stream capture stop error: %s", e)

        if self.event_bus:
            try:
                await self.event_bus.stop()
            except Exception as e:
                logger.error("Event bus stop error: %s", e)

        if self.ai_pipeline_hub:
            try:
                await self.ai_pipeline_hub.stop()
            except Exception as e:
                logger.error("AI pipeline hub stop error: %s", e)

        logger.info("Pipeline stopped")

    async def _on_new_frame(self, frame: Frame):
        """
        Called for each new frame from stream capture.

        This is where the event-driven pipeline kicks in:
        Frame → Video Analysis → Events → Event Detector → Decision → Clip
        """
        now = time.time()

        # Throttle: only analyze at target rate
        if now - self._last_analysis_time < self._analysis_interval:
            return
        self._last_analysis_time = now

        try:
            # Run video analysis (lazy init)
            await self._ensure_video_analysis()
            if self.video_analysis:
                result = await self.video_analysis.analyze_frame(
                    frame.image, frame.frame_id
                )
        except Exception as e:
            logger.error("Frame analysis error (non-fatal): %s", e)

    async def _on_new_audio(self, samples: np.ndarray, stream_time: float):
        """
        Called for each 1-second audio chunk from stream capture.

        Real audio replaces the synthetic random-noise path.
        """
        try:
            if self.audio_analysis:
                await self.audio_analysis.analyze_chunk(samples)
        except Exception as e:
            logger.error("Audio analysis error (non-fatal): %s", e)

    async def _on_clip_created(self, event: SystemEvent):
        """Handle clip creation events — run AI Critic, save to DB, enrich with AI."""
        clip_data = event.payload
        logger.info(
            f"CLIP CREATED! "
            f"Score: {clip_data.get('highlight_score', 0):.3f} "
            f"Category: {clip_data.get('category', 'unknown')} "
            f"Path: {clip_data.get('file_path', 'unknown')}"
        )

        # Run AI Critic on the rendered clip so critic_score persists to DB.
        file_path = clip_data.get("file_path", "")
        if file_path:
            try:
                from services.ai_critic import ai_critic
                report = await ai_critic.critique(video_path=file_path)
                clip_data["critique"] = report.to_dict()
                logger.info(
                    "AI Critic: score=%.2f passed=%s for %s",
                    report.score, report.passed, file_path,
                )
            except Exception as e:
                logger.warning("AI Critic failed for %s (non-critical): %s", file_path, e)

        # Save to database
        try:
            from api.routers.pipeline import save_pipeline_clip_to_db
            await save_pipeline_clip_to_db(clip_data)
        except Exception as e:
            logger.warning(f"DB clip save failed (non-critical): {e}")

        # Run full AI enrichment pipeline (fired-and-forgotten).
        if self.ai_pipeline_hub and clip_data.get("clip_id"):
            try:
                clip_id = str(clip_data.get("clip_id"))
                asyncio.create_task(self._ai_enrich_clip(clip_id, clip_data))
            except Exception as e:
                logger.debug(f"AI enrichment trigger skipped: {e}")

    async def _ai_enrich_clip(self, clip_id: str, clip_data: dict):
        """Run AI Pipeline Hub enrichment on a new clip.

        Generates LLM titles/descriptions/hashtags, smart editing
        recommendations and updates the recommendation engine.
        """
        if not self.ai_pipeline_hub:
            return
        try:
            result = await self.ai_pipeline_hub.analyze_full_clip(
                clip_id=clip_id,
                category=clip_data.get("category", "other"),
                emotion=(clip_data.get("emotion", {}) or {}).get(
                    "dominant", "neutral"
                ),
                duration=clip_data.get("duration", 30.0),
                platform=clip_data.get("platform", "youtube"),
                streamer=clip_data.get("streamer", "Tuncay"),
            )
            await self.event_bus.publish_quick(
                EventType.AI_METADATA_READY,
                {
                    "clip_id": clip_id,
                    "pipeline_elapsed_ms": result.get(
                        "pipeline_elapsed_ms", 0
                    ),
                    "services_used": result.get("services_used", []),
                    "source": "ai_pipeline_hub",
                },
                source_service="ai_pipeline",
                stream_id=clip_data.get("stream_id", ""),
            )
        except Exception as e:
            logger.warning(
                "AI enrichment failed for clip %s: %s", clip_id, e
            )

    # ─── Manual Trigger Methods ───────────────────────────────

    async def inject_chat_message(self, text: str, user: str = ""):
        """Manually inject a chat message for testing."""
        if not self.event_bus:
            await self.initialize()
        if self.chat_analysis:
            return await self.chat_analysis.process_message(text, user)

    async def inject_audio_chunk(self, audio_data: np.ndarray):
        """Manually inject audio for testing."""
        if not self.event_bus:
            await self.initialize()
        if self.audio_analysis:
            return await self.audio_analysis.analyze_chunk(audio_data)

    async def analyze_single_frame(self, frame_image: np.ndarray):
        """Analyze a single frame without stream capture."""
        await self._ensure_video_analysis()
        return await self.video_analysis.analyze_frame(frame_image, "manual_001")

    # ─── Status & Metrics ─────────────────────────────────────

    def get_full_status(self) -> dict:
        """Get status of all services."""
        status = {
            "pipeline": {
                "is_running": self._is_running,
                "start_time": self._start_time.isoformat() if self._start_time else None,
            },
            "event_bus": self.event_bus.metrics if self.event_bus else {},
        }

        if self.stream_capture:
            status["stream_capture"] = self.stream_capture.get_status()
        if self.video_analysis:
            status["video_analysis"] = self.video_analysis.get_status()
        if self.audio_analysis:
            status["audio_analysis"] = self.audio_analysis.get_status()
        if self.chat_analysis:
            status["chat_analysis"] = self.chat_analysis.get_status()
        if self.event_detector:
            status["event_detector"] = self.event_detector.get_status()
        if self.decision_engine:
            status["decision_engine"] = self.decision_engine.get_status()
        if self.clip_generator:
            status["clip_generator"] = self.clip_generator.get_status()
        if self.transcription:
            status["transcription"] = self.transcription.get_status()
        if self.chat_source:
            status["chat_source"] = self.chat_source.get_status()
        if self.subtitle:
            status["subtitle"] = self.subtitle.get_status()
        if self.video_editor:
            status["video_editor"] = self.video_editor.get_status()
        if self.ai_generator:
            status["ai_generator"] = self.ai_generator.get_status()
        if self.uploader:
            status["uploader"] = self.uploader.get_status()
        if self.thumbnail:
            status["thumbnail"] = self.thumbnail.get_status()
        if self.notification_service:
            status["notification"] = self.notification_service.get_status()
        if self.ai_pipeline_hub:
            status["ai_pipeline"] = self.ai_pipeline_hub.get_status()

        return status


# ─── Global Singleton ─────────────────────────────────────────

orchestrator = PipelineOrchestrator()
