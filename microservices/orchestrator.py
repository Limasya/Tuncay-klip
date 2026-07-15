"""
Pipeline Orchestrator
──────────────────────
Wires all microservices together into a running pipeline.

Architecture:
┌─────────────────────────────────────────────────────────────┐
│                      EVENT BUS                               │
│  (in-memory pub/sub — swap to Redis Streams in production)  │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────┘
       │          │          │          │          │
  ┌────▼────┐ ┌──▼───┐ ┌───▼───┐ ┌───▼───┐ ┌───▼────┐
  │ Stream  │ │Video │ │Audio  │ │ Chat  │ │ Event  │
  │Capture  │ │Anal. │ │Anal.  │ │ Anal. │ │Detect  │
  └────┬────┘ └──────┘ └───────┘ └───────┘ └───┬────┘
       │                                        │
       │         ┌────────────┐                 │
       └────────►│  Decision  │◄────────────────┘
                 │  Engine    │
                 └─────┬──────┘
                       │
                 ┌─────▼──────┐
                 │    Clip    │
                 │ Generator  │
                 └────────────┘
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

        # Start event bus
        self.event_bus = await init_event_bus()

        # Create lightweight services
        self.audio_analysis = AudioAnalysisService(self.event_bus)
        self.chat_analysis = ChatAnalysisService(self.event_bus)
        self.event_detector = EventDetectorService(self.event_bus)
        self.decision_engine = DecisionEngineService(self.event_bus)

        # Subscribe to clip creation for logging
        self.event_bus.subscribe(
            EventType.CLIP_CREATED.value,
            self._on_clip_created,
        )

        logger.info("Lightweight services initialized")

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

        # Start capture
        await self.stream_capture.start()
        self._is_running = True
        self._start_time = datetime.utcnow()

        logger.info(f"Pipeline started: {stream_url}")

    async def stop(self):
        """Stop the pipeline gracefully."""
        self._is_running = False

        if self.stream_capture:
            await self.stream_capture.stop()

        if self.event_bus:
            await self.event_bus.stop()

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

        # Run video analysis (lazy init)
        await self._ensure_video_analysis()
        if self.video_analysis:
            result = await self.video_analysis.analyze_frame(
                frame.image, frame.frame_id
            )

        # Generate synthetic audio features (in production, real audio chunks)
        if self.audio_analysis:
            # Simulate audio: use frame motion as proxy
            audio_data = np.random.randn(16000).astype(np.float32) * 0.01
            await self.audio_analysis.analyze_chunk(audio_data)

    async def _on_clip_created(self, event: SystemEvent):
        """Handle clip creation events."""
        clip_data = event.payload
        logger.info(
            f"🎬 CLIP CREATED! "
            f"Score: {clip_data.get('highlight_score', 0):.3f} "
            f"Category: {clip_data.get('category', 'unknown')} "
            f"Path: {clip_data.get('file_path', 'unknown')}"
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

        return status


# ─── Global Singleton ─────────────────────────────────────────

orchestrator = PipelineOrchestrator()
