"""
AI Pipeline Integration Hub (IP_PART7)

Coordinates all AI services into a unified pipeline:

  Clip Created → [Parallel AI Analysis]
    ├── Video Analysis: Face → Emotion → Pose → Scene → Objects → Gestures
    ├── Audio Analysis: Energy → Spike → Speech Emotion → Events → Crowd → Music
    ├── Chat Analysis: NLP Sentiment → Toxicity → Hype → Language → Trends
    ├── AI Generator: LLM Title → Description → Hashtags → Thumbnail concept
    ├── Recommendation: Similar clips → Content ranking → Personalized feed
    └── Smart Editor: Cut suggestions → Beat sync → Platform optimization

All results published to event bus for downstream consumption.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

logger = logging.getLogger("ai_pipeline")


class AIPipelineHub:
    """
    Central coordinator for all AI services.

    Orchestrates:
    - Frame analysis (Vision AI)
    - Audio chunk processing (Audio AI)
    - Chat message processing (Chat AI)
    - Clip metadata generation (LLM Engine)
    - Recommendation updates
    - Smart editing suggestions

    All services run in the same process (local mode) or via
    event bus subscribers (distributed mode).
    """

    def __init__(self):
        self._started = False
        self._services: dict[str, Any] = {}
        self._metrics = {
            "frames_processed": 0,
            "audio_chunks_processed": 0,
            "chat_messages_processed": 0,
            "clips_analyzed": 0,
            "metadata_generated": 0,
            "total_pipeline_runs": 0,
        }
        self._init_services()

    def _init_services(self):
        """Initialize all AI services with fallback where needed."""
        # Video Analysis
        try:
            from microservices.video_analysis.service import VideoAnalysisService
            self._services["video_analysis"] = VideoAnalysisService()
            logger.info("Video Analysis service initialized")
        except Exception as e:
            logger.warning("Video Analysis unavailable: %s", e)
            self._services["video_analysis"] = None

        # Audio Analysis
        try:
            from microservices.audio_analysis.service import AudioAnalysisService
            self._services["audio_analysis"] = AudioAnalysisService()
            logger.info("Audio Analysis service initialized")
        except Exception as e:
            logger.warning("Audio Analysis unavailable: %s", e)
            self._services["audio_analysis"] = None

        # Chat Analysis
        try:
            from microservices.chat_analysis.service import ChatAnalysisService
            self._services["chat_analysis"] = ChatAnalysisService()
            logger.info("Chat Analysis service initialized")
        except Exception as e:
            logger.warning("Chat Analysis unavailable: %s", e)
            self._services["chat_analysis"] = None

        # AI Generator
        try:
            from microservices.ai_generator.service import AIGeneratorMicroservice
            self._services["ai_generator"] = AIGeneratorMicroservice()
            logger.info("AI Generator service initialized")
        except Exception as e:
            logger.warning("AI Generator unavailable: %s", e)
            self._services["ai_generator"] = None

        # LLM Engine (always available via template fallback)
        try:
            from services.llm_engine import llm_engine
            self._services["llm_engine"] = llm_engine
            logger.info("LLM Engine connected (%d providers)", llm_engine._provider_count)
        except Exception as e:
            logger.warning("LLM Engine unavailable: %s", e)
            self._services["llm_engine"] = None

        # Social Media AI
        try:
            from services.social_media_ai import social_media_ai
            self._services["social_media_ai"] = social_media_ai
            logger.info("Social Media AI initialized for viral content generation")
        except Exception as e:
            logger.warning("Social Media AI unavailable: %s", e)
            self._services["social_media_ai"] = None

        # Social Video Generator (Viral Tiktok/Reels Editor)
        try:
            from services.social_video_generator import social_video_gen
            self._services["social_video_generator"] = social_video_gen
            logger.info("Social Video Generator connected for automatic 9:16 edits")
        except Exception as e:
            logger.warning("Social Video Generator unavailable: %s", e)
            self._services["social_video_generator"] = None

        # Recommendation Engine
        try:
            from services.recommendation_engine import (
                ClipSimilarityEngine, UserPreferenceLearner, ClipRanker)
            self._services["similarity_engine"] = ClipSimilarityEngine()
            self._services["preference_learner"] = UserPreferenceLearner()
            self._services["clip_ranker"] = ClipRanker()
            logger.info("Recommendation Engine initialized")
        except Exception as e:
            logger.warning("Recommendation Engine unavailable: %s", e)

        # Smart Editor
        try:
            from services.smart_editor import (
                ClipContentAnalyzer, AutoTrimSuggestor, BeatSyncAnalyzer)
            self._services["content_analyzer"] = ClipContentAnalyzer()
            self._services["auto_trim"] = AutoTrimSuggestor()
            self._services["beat_sync"] = BeatSyncAnalyzer()
            logger.info("Smart Editor initialized")
        except Exception as e:
            logger.warning("Smart Editor unavailable: %s", e)

    async def start(self):
        """Start the AI pipeline."""
        if self._started:
            return
        self._started = True
        logger.info("AI Pipeline Hub started with %d services",
                     sum(1 for s in self._services.values() if s is not None))

    async def stop(self):
        """Stop the AI pipeline."""
        self._started = False
        logger.info("AI Pipeline Hub stopped")

    async def process_frame(self, frame_image: np.ndarray, frame_id: str = "") -> dict:
        """Process a single frame through Vision AI."""
        svc = self._services.get("video_analysis")
        if svc is None:
            return {"error": "video_analysis_unavailable"}

        try:
            import numpy as np
            if not isinstance(frame_image, np.ndarray):
                return {"error": "invalid_frame_format"}
            result = await svc.analyze_frame(frame_image, frame_id)
            self._metrics["frames_processed"] += 1
            return result.model_dump(mode="json") if hasattr(result, 'model_dump') else {"ok": True}
        except Exception as e:
            logger.error("Frame processing failed: %s", e)
            return {"error": str(e)}

    async def process_audio_chunk(self, audio_data: np.ndarray) -> dict:
        """Process an audio chunk through Audio AI."""
        svc = self._services.get("audio_analysis")
        if svc is None:
            return {"error": "audio_analysis_unavailable"}

        try:
            import numpy as np
            if not isinstance(audio_data, np.ndarray):
                return {"error": "invalid_audio_format"}
            result = await svc.analyze_chunk(audio_data)
            self._metrics["audio_chunks_processed"] += 1
            return result.model_dump(mode="json") if hasattr(result, 'model_dump') else {"ok": True}
        except Exception as e:
            logger.error("Audio processing failed: %s", e)
            return {"error": str(e)}

    async def process_chat_message(self, text: str, user: str = "") -> dict:
        """Process a chat message through Chat AI."""
        svc = self._services.get("chat_analysis")
        if svc is None:
            return {"error": "chat_analysis_unavailable"}

        try:
            result = await svc.process_message(text, user)
            self._metrics["chat_messages_processed"] += 1
            return result.model_dump(mode="json") if hasattr(result, 'model_dump') else {
                "label": result.label, "score": result.score, "confidence": result.confidence}
        except Exception as e:
            logger.error("Chat processing failed: %s", e)
            return {"error": str(e)}

    async def generate_clip_metadata(
        self,
        clip_id: str,
        category: str,
        emotion: str,
        streamer: str = "Tuncay",
        tags: list[str] | None = None,
        platform: str = "youtube",
    ) -> dict:
        """Generate full AI metadata for a clip."""
        self._metrics["clips_analyzed"] += 1

        llm = self._services.get("llm_engine")
        if llm is None:
            return {"error": "llm_engine_unavailable"}

        try:
            titles = await llm.generate_titles(
                streamer_name=streamer, category=category,
                emotion=emotion, platform=platform, tags=tags or [])
            description = await llm.generate_description(
                title=titles[0] if titles else "", streamer_name=streamer,
                category=category, emotion=emotion, platform=platform)
            hashtags = await llm.generate_hashtags(
                category=category, game_name="", streamer_name=streamer,
                emotion=emotion, platform=platform, count=15)
            thumbnail = await llm.suggest_thumbnail(
                title=titles[0] if titles else "", streamer_name=streamer,
                category=category, emotion=emotion, platform=platform)

            # Viral Sosyal Medya İçeriği (SocialMediaAI)
            viral_package = {}
            social_media = self._services.get("social_media_ai")
            if social_media is not None:
                viral_package = await social_media.generate_viral_package(
                    transcript="[Otomatik olarak sağlanan klip metni]",
                    metadata={"emotion": emotion, "game": category, "streamer": streamer}
                )

            self._metrics["metadata_generated"] += 1
            return {
                "clip_id": clip_id,
                "titles": titles[:5],
                "description": description,
                "hashtags": hashtags[:15],
                "thumbnail_concept": thumbnail,
                "viral_package": viral_package,
                "source": "ai_pipeline_v2",
                "generated_at": time.time(),
            }
        except Exception as e:
            logger.error("Metadata generation failed: %s", e)
            return {"error": str(e), "clip_id": clip_id}

    async def analyze_full_clip(
        self,
        clip_id: str,
        category: str,
        emotion: str,
        highlight_scores: list[dict] | None = None,
        audio_spikes: list[dict] | None = None,
        chat_spikes: list[dict] | None = None,
        chat_highlights: list[str] | None = None,
        duration: float = 30.0,
        platform: str = "youtube",
        streamer: str = "Tuncay",
        key_frame_idx: int | None = None,
    ) -> dict:
        """Full pipeline analysis of a completed clip."""
        self._metrics["total_pipeline_runs"] += 1
        start = time.time()

        tasks = []

        # Task 1: LLM metadata generation
        llm = self._services.get("llm_engine")
        metadata_task = None
        if llm is not None:
            metadata_task = asyncio.create_task(self.generate_clip_metadata(
                clip_id, category, emotion, streamer, platform=platform))
            tasks.append(metadata_task)

        # Task 2: Smart editing suggestions
        content_analyzer = self._services.get("content_analyzer")
        auto_trim = self._services.get("auto_trim")
        if content_analyzer is not None and auto_trim is not None:
            edit_recs = content_analyzer.analyze(
                highlight_scores or [], [], audio_spikes or [],
                chat_spikes or [], duration, platform)
            trim_recs = auto_trim.suggest_trims(
                duration, highlight_scores or [], audio_spikes or [], platform)
        else:
            edit_recs = {}
            trim_recs = {}

        # Task 3: Recommendation updates
        similarity_engine = self._services.get("similarity_engine")
        if similarity_engine is not None:
            try:
                from services.recommendation_engine import ClipProfile
                profile = ClipProfile(
                    clip_id=clip_id, category=category, emotion=emotion,
                    duration=duration, highlight_score=0.7,
                    tags=[], platform=platform, streamer=streamer,
                    created_at=time.time())
                similarity_engine.add_clip(profile)
            except Exception as e:
                logger.debug("Recommendation update skipped: %s", e)

        # Wait for async tasks
        ai_metadata = {}
        if tasks:
            done, _ = await asyncio.wait(tasks, timeout=30)
            for task_result in done:
                try:
                    result = task_result.result()
                    if isinstance(result, dict) and "titles" in result:
                        ai_metadata = result
                except Exception as e:
                    logger.debug("Subtask failed: %s", e)

        elapsed = (time.time() - start) * 1000

        return {
            "clip_id": clip_id,
            "ai_metadata": ai_metadata,
            "edit_recommendations": edit_recs,
            "trim_recommendations": trim_recs,
            "pipeline_elapsed_ms": round(elapsed, 1),
            "pipeline_version": "v2_ai",
            "services_used": [k for k, v in self._services.items() if v is not None],
        }

    def get_status(self) -> dict:
        """Get comprehensive AI pipeline status."""
        status = dict(self._metrics)
        for name, svc in self._services.items():
            if svc is not None and hasattr(svc, 'get_status'):
                try:
                    status[f"service_{name}"] = svc.get_status()
                except Exception as e:
                    logger.debug("%s servis durumu alınamadı: %s", name, e)
        return status

    @property
    def is_running(self) -> bool:
        return self._started


# Singleton
ai_pipeline = AIPipelineHub()