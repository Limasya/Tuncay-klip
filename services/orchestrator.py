"""
Ana orkestratör servisi.
Tüm alt servisleri birleştirerek otomatik klip yakalama
ve analiz sistemini yönetir.
"""
import asyncio
import logging
import time
from datetime import datetime
from typing import Dict, Optional
from pathlib import Path
from config import get_settings
from services.kick_api import kick_service
from services.stream_capture import stream_capture
from services.analysis.pipeline import analysis_pipeline
from services.analysis.audio_analysis import audio_analyzer
from services.clip_service import (
    clip_classifier, clip_metadata, storage_service,
)
from services.subtitle_service import subtitle_service
from services.video_editor import video_editor
from services.chat_sentiment import chat_sentiment

logger = logging.getLogger(__name__)
settings = get_settings()


class Orchestrator:
    """
    Ana sistem orkestratörü.
    - Yayını izler
    - Akışı yakalar
    - Analiz pipeline'ını çalıştırır
    - Olay tespit edildiğinde klip oluşturur
    - Altyazı, sınıflandırma ve meta veri ekler
    """

    def __init__(self):
        self.is_monitoring = False
        self.is_stream_active = False
        self._current_stream_info: Dict = {}
        self._stream_url: Optional[str] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._clips_today = 0
        self._start_time: Optional[datetime] = None

    async def start(self):
        """Sistemi başlatır ve yayın izlemeyi başlar."""
        self.is_monitoring = True
        self._start_time = datetime.utcnow()

        # Klip tetikleme callback'i kaydet
        analysis_pipeline.on_clip_trigger(self._on_event_detected)

        # Yayını izle
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info("Orkestratör başladı. Hedef kanal: %s",
                     settings.kick_channel_slug)

    async def stop(self):
        """Sistemi durdurur."""
        self.is_monitoring = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        await analysis_pipeline.stop()
        await stream_capture.stop_capture()
        await audio_analyzer.stop()
        await kick_service.close()

        logger.info("Orkestratör durdu. Bugün %d klip oluşturuldu.",
                     self._clips_today)

    async def _monitor_loop(self):
        """Kick API'yi periyodik olarak yoklayarak yayın durumunu izler."""
        while self.is_monitoring:
            try:
                info = await kick_service.get_livestream_info()
                is_live = info.get("is_live", False)

                if is_live and not self.is_stream_active:
                    await self._on_stream_start(info)
                elif not is_live and self.is_stream_active:
                    await self._on_stream_end()

                self._current_stream_info = info

            except Exception as e:
                logger.error("İzleme döngüsü hatası: %s", e)

            await asyncio.sleep(30)

    async def _on_stream_start(self, stream_info: Dict):
        """Yayın başladığında çağrılır."""
        logger.info("YAYIN BAŞLADI: %s", stream_info.get("title", ""))
        self.is_stream_active = True
        self._current_stream_info = stream_info

        # Stream URL al
        self._stream_url = await kick_service.get_stream_url()
        if not self._stream_url:
            logger.error("Stream URL alınamadı!")
            return

        # Stream yakalamayı başlat
        await stream_capture.start_capture(self._stream_url)

        # Analiz pipeline'ını başlat
        stream_capture.on_frame(analysis_pipeline.process_frame)
        await analysis_pipeline.start()

        # Ses analizini başlat
        await audio_analyzer.start_audio_capture(self._stream_url)

    async def _on_stream_end(self):
        """Yayın bittiğinde çağrılır."""
        logger.info("YAYIN BİTTİ.")
        self.is_stream_active = False

        await analysis_pipeline.stop()
        await stream_capture.stop_capture()
        await audio_analyzer.stop()

    async def _on_event_detected(self, event: Dict):
        """
        Analiz pipeline'ından olay tespit edildiğinde çağrılır.
        Otomatik klip oluşturma + edit sürecini başlatır.
        """
        timestamp = event.get("timestamp", time.time())
        trigger_type = event.get("trigger_type", "composite")
        composite_score = event.get("composite_score", 0)

        logger.info(
            "OLAY -> KLİP: score=%.2f, type=%s",
            composite_score, trigger_type
        )

        try:
            # 1. Buffer'dan klip çıkar (sesli)
            clip_path = await stream_capture.capture_clip_with_audio(
                event_time=timestamp,
                pre_seconds=settings.clip_pre_seconds,
                post_seconds=settings.clip_post_seconds,
            )

            if not clip_path:
                logger.warning("Klip oluşturulamadı (buffer yetersiz)")
                return

            # 2. Sinyalleri topla
            emotion_result = event.get("emotion", {})
            motion_result = event.get("motion", {})
            audio_result = event.get("audio", {})
            chat_result = event.get("chat", {})

            analysis = {
                "emotion": emotion_result,
                "motion": motion_result,
                "audio": audio_result,
                "chat": chat_result,
                "composite_score": composite_score,
            }

            # 3. Sınıflandır
            category = clip_classifier.determine_category(
                emotion_result, motion_result, audio_result
            )
            tags = clip_classifier.generate_tags(
                emotion_result, motion_result, audio_result
            )

            # 4. Otomatik edit spec üret
            from services.auto_editor import auto_editor
            from services.edit_spec import AspectRatio
            edit_spec = auto_editor.generate_edit_spec(
                source_path=clip_path,
                analysis=analysis,
                category=category,
                aspect_ratio=AspectRatio.PORTRAIT_9_16,
            )

            # 5. Altyazı üret (Whisper)
            subtitle_result = await subtitle_service.process_clip_subtitles(
                clip_path,
                language="tr",
                burn_in=False,
            )
            whisper_segments = subtitle_result.get("segments", [])

            # 6. Müzik ve SFX seç
            from services.music_service import music_service
            selected_music = music_service.select_music_for_clip(
                emotion=emotion_result.get("dominant", "neutral"),
                category=category,
                duration=settings.clip_pre_seconds + settings.clip_post_seconds,
            )
            selected_sfx = None
            if audio_result.get("is_spike"):
                selected_sfx = music_service.select_sfx_for_event(
                    event_type="clip_trigger",
                    emotion=emotion_result.get("dominant", "neutral"),
                    audio_energy=audio_result.get("energy_level", "medium"),
                )

            # 7. Edit spec'i zenginleştir
            edit_spec = auto_editor.merge_analysis_into_edit_spec(
                base_spec=edit_spec,
                analysis=analysis,
                whisper_segments=whisper_segments,
                music_path=selected_sfx.path if selected_sfx else None,
            )

            # 8. Render pipeline ile uygula
            from services.render_pipeline import render_pipeline
            rendered_path = await render_pipeline.render(edit_spec)

            if not rendered_path:
                logger.warning("Render başarısız, ham klip kullanılıyor")
                rendered_path = clip_path

            # 9. Meta veri topla
            metadata = await clip_metadata.build_clip_metadata(
                emotion_result, motion_result, audio_result
            )

            # 10. S3'e yükle
            s3_url = await storage_service.upload_clip(rendered_path)

            # 11. Veritabanına kaydet
            await self._save_clip_to_db(
                clip_path=rendered_path,
                thumb_path=None,
                subtitle_path=subtitle_result.get("srt_path"),
                s3_url=s3_url,
                category=category,
                trigger_type=trigger_type,
                tags=tags,
                emotion_result=emotion_result,
                motion_result=motion_result,
                audio_result=audio_result,
                metadata=metadata,
            )

            self._clips_today += 1
            logger.info(
                "Klip #%d oluşturuldu ve render edildi: %s [%s] "
                "(edit: color=%s, music=%s)",
                self._clips_today,
                Path(rendered_path).name,
                category,
                edit_spec.color_grading.preset.value,
                "yes" if selected_sfx else "no",
            )

        except Exception as e:
            logger.error("Klip oluşturma pipeline hatası: %s", e, exc_info=True)

    async def _save_clip_to_db(
        self,
        clip_path: str,
        thumb_path: Optional[str],
        subtitle_path: Optional[str],
        s3_url: Optional[str],
        category: str,
        trigger_type: str,
        tags: list,
        emotion_result: Dict,
        motion_result: Dict,
        audio_result: Dict,
        metadata: Dict,
    ):
        """Klip bilgilerini veritabanına kaydeder."""
        from services.database import async_session
        from models.database import Clip, Broadcaster
        from sqlalchemy import select

        async with async_session() as session:
            # Broadcaster bul veya oluştur
            result = await session.execute(
                select(Broadcaster).where(
                    Broadcaster.kick_user_id == settings.kick_broadcaster_user_id
                )
            )
            broadcaster = result.scalar_one_or_none()

            if not broadcaster:
                broadcaster = Broadcaster(
                    kick_user_id=settings.kick_broadcaster_user_id,
                    channel_slug=settings.kick_channel_slug,
                )
                session.add(broadcaster)
                await session.flush()

            stream_meta = metadata.get("stream", {})
            analysis_meta = metadata.get("analysis", {})

            clip = Clip(
                broadcaster_id=broadcaster.id,
                title=f"Klip {self._clips_today} - {category}",
                category=category,
                status="ready",
                trigger_type=trigger_type,
                clip_start_time=datetime.utcnow(),
                duration_seconds=settings.clip_pre_seconds + settings.clip_post_seconds,
                video_path=clip_path,
                thumbnail_path=thumb_path,
                subtitle_path=subtitle_path,
                s3_url=s3_url,
                viewer_count=stream_meta.get("viewer_count"),
                stream_title=stream_meta.get("title"),
                category_name=stream_meta.get("category"),
                dominant_emotion=analysis_meta.get("dominant_emotion"),
                emotion_score=analysis_meta.get("emotion_confidence"),
                motion_score=analysis_meta.get("motion_score"),
                audio_energy=analysis_meta.get("audio_energy"),
                tags=tags,
            )

            session.add(clip)
            await session.commit()

    def get_status(self) -> Dict:
        """Sistem durumunu döndürür."""
        import psutil
        try:
            import torch
            gpu_available = torch.cuda.is_available()
        except ImportError:
            gpu_available = False

        return {
            "is_monitoring": self.is_monitoring,
            "target_channel": settings.kick_channel_slug,
            "stream_active": self.is_stream_active,
            "stream_info": self._current_stream_info,
            "clips_today": self._clips_today,
            "buffer_frames": stream_capture.frame_buffer.frame_count,
            "analysis_stats": analysis_pipeline.stats,
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
            "gpu_available": gpu_available,
            "uptime_seconds": (
                (datetime.utcnow() - self._start_time).total_seconds()
                if self._start_time else 0
            ),
        }


# Singleton
orchestrator = Orchestrator()
