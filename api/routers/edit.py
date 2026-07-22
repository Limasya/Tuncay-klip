"""
Otomatik edit API endpoint'leri.
Edit spec oluşturma, render, montaj, müzik/SFX kütüphanesi.
Gelişmiş: sahne algılama, beat-sync, split-screen, end-screen,
lower-third, sticker, emotion-arc, word-timing, karaoke endpoint'leri.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from utils.auth_compat import Principal, Scope, require_scope

from models.schemas import (
    EditSpecRequest, EditSpecResponse, RenderJobCreate, RenderJobResponse,
    MontageCreate, MusicLibraryResponse, SFXLibraryResponse,
    AudioDuckingRequest, AudioDuckingResponse,
    BeatSyncRequest, BeatSyncResponse,
    SceneDetectionRequest, SceneDetectionResponse, SceneInfo,
    SplitScreenRequest, EndScreenRequest, LowerThirdRequest,
    StickerOverlayRequest, EmotionArcRequest, AdvancedRenderRequest,
    WordTimingRequest, WordTimingResponse, WordTimingInfo,
    SceneAutoEffectsRequest, SceneAutoEffectsResponse,
)
from services.auto_editor import auto_editor
from services.render_pipeline import render_pipeline
from services.music_service import music_service
from services.edit_spec import (
    AspectRatio, ClipSpec, TimeRange, VisualEffect, ColorGrading,
    BeatSyncConfig, WordHighlightConfig, StickerOverlayConfig,
    LowerThirdConfig, LowerThirdEntry, EndScreenConfig,
    EmotionArcConfig, EmotionSegment, SceneDetectionConfig,
)

EXPORTS_DIR = Path("data/exports")
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR = Path("data/temp")
TEMP_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/edit",
    tags=["auto-edit"],
    dependencies=[Depends(require_scope(Scope.CLIPS_WRITE))],
)

# Geçici job depolama (production'da Redis/DB olmalı)
_render_jobs: Dict[str, Dict] = {}


@router.post("/spec", response_model=EditSpecResponse)
async def create_edit_spec(request: EditSpecRequest):
    """
    Kaynak videodan analiz sinyalleriyle edit spec üretir.
    Henüz render yapmaz, sadece edit talimatlarını döndürür.
    """
    try:
        # Basit analiz simülasyonu (gerçek kullanımda pipeline'dan gelir)
        analysis = {
            "emotion": {"dominant": "neutral", "confidence": 0.5},
            "motion": {"level": "medium"},
            "audio": {"energy_level": "medium", "is_spike": False},
            "chat": {},
            "composite_score": 0.5,
        }

        ar = AspectRatio(request.aspect_ratio) if request.aspect_ratio in [
            a.value for a in AspectRatio
        ] else AspectRatio.PORTRAIT_9_16

        spec = auto_editor.generate_edit_spec(
            source_path=request.source_path,
            analysis=analysis,
            category=request.category.value,
            aspect_ratio=ar,
            resolution=request.resolution,
            custom_overrides=None,
        )

        return EditSpecResponse(
            version=spec.version,
            source_path=spec.source_path,
            aspect_ratio=spec.aspect_ratio.value,
            resolution=spec.resolution,
            color_preset=spec.color_grading.preset.value,
            subtitle_style=spec.subtitles[0].style.value if spec.subtitles else "classic",
            speed_segments_count=len(spec.speed_segments),
            has_watermark=spec.watermark is not None,
            has_music=any(t.path for t in spec.audio_tracks),
            category=spec.category,
            composite_score=spec.composite_score,
        )
    except Exception as e:
        logger.error("Edit spec oluşturma hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/render", response_model=RenderJobResponse)
async def start_render(request: RenderJobCreate, background_tasks: BackgroundTasks):
    """
    Yeni bir render işi başlatır. Arka planda çalışır.
    """
    job_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)

    job = {
        "job_id": job_id,
        "status": "pending",
        "source_path": request.source_path,
        "output_path": None,
        "edit_spec": None,
        "created_at": now,
        "completed_at": None,
        "error": None,
    }
    _render_jobs[job_id] = job

    background_tasks.add_task(
        _execute_render_job, job_id, request
    )

    return RenderJobResponse(**job)


@router.get("/render/{job_id}", response_model=RenderJobResponse)
async def get_render_status(job_id: str):
    """Render işinin durumunu sorgular."""
    job = _render_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job bulunamadı")
    return RenderJobResponse(**job)


@router.get("/render", response_model=list[RenderJobResponse])
async def list_render_jobs(status: Optional[str] = None, limit: int = 20):
    """Render işlerini listeler."""
    jobs = list(_render_jobs.values())
    if status:
        jobs = [j for j in jobs if j["status"] == status]
    jobs.sort(key=lambda x: x["created_at"], reverse=True)
    return [RenderJobResponse(**j) for j in jobs[:limit]]


@router.post("/montage")
async def create_montage(request: MontageCreate, background_tasks: BackgroundTasks):
    """
    Birden fazla klibi montaj olarak birleştirir.
    """
    job_id = str(uuid.uuid4())[:8]

    background_tasks.add_task(
        _execute_montage_job, job_id, request
    )

    return {
        "job_id": job_id,
        "status": "processing",
        "clip_count": len(request.clip_paths),
        "transition": request.transition_type,
    }


@router.get("/music/library", response_model=MusicLibraryResponse)
async def get_music_library():
    """Müzik kütüphanesini listeler."""
    tracks = music_service.get_available_music()
    return MusicLibraryResponse(tracks=tracks, total=len(tracks))


@router.get("/sfx/library", response_model=SFXLibraryResponse)
async def get_sfx_library():
    """SFX kütüphanesini listeler."""
    clips = music_service.get_available_sfx()
    return SFXLibraryResponse(clips=clips, total=len(clips))


@router.post("/audio/ducking", response_model=AudioDuckingResponse)
async def calculate_ducking(request: AudioDuckingRequest):
    """
    Speech-music ducking parametrelerini hesaplar.
    FFmpeg sidechaincompress parametrelerini döndürür.
    """
    params = music_service.calculate_ducking_params(
        speech_level=request.speech_level,
        music_level=request.music_level,
        target_ratio=request.target_ratio,
    )

    filter_str = music_service.build_ducking_filter(
        music_volume=request.music_level,
        duck_params=params,
    )

    return AudioDuckingResponse(
        threshold=params["threshold"],
        ratio=params["ratio"],
        attack=params["attack"],
        release=params["release"],
        filter_string=filter_str,
    )


@router.post("/analyze/music")
async def analyze_for_music(audio_features: Dict):
    """
    Ses özelliklerinden müzik seçim bilgileri üretir.
    """
    result = music_service.analyze_audio_for_music_selection(audio_features)
    return result


@router.post("/quick-render")
async def quick_render(
    source_path: str,
    category: str = "other",
    aspect_ratio: str = "9:16",
):
    """
    Hızlı render - minimum parametre ile edit spec üretip render eder.
    """
    analysis = {
        "emotion": {"dominant": "neutral", "confidence": 0.5},
        "motion": {"level": "medium"},
        "audio": {"energy_level": "medium", "is_spike": False},
        "chat": {},
        "composite_score": 0.5,
    }

    ar = AspectRatio(aspect_ratio) if aspect_ratio in [
        a.value for a in AspectRatio
    ] else AspectRatio.PORTRAIT_9_16

    spec = auto_editor.generate_edit_spec(
        source_path=source_path,
        analysis=analysis,
        category=category,
        aspect_ratio=ar,
    )

    output_path = await render_pipeline.render(spec)

    if not output_path:
        raise HTTPException(status_code=500, detail="Render başarısız")

    return {
        "status": "completed",
        "output_path": output_path,
        "category": category,
        "aspect_ratio": aspect_ratio,
        "color_preset": spec.color_grading.preset.value,
    }


# --- Arka plan görevleri ---

async def _execute_render_job(job_id: str, request: RenderJobCreate):
    """Arka planda render işini yürütür."""
    job = _render_jobs.get(job_id)
    if not job:
        return

    try:
        job["status"] = "processing"

        # Edit spec üret
        analysis = {
            "emotion": {"dominant": "neutral", "confidence": 0.5},
            "motion": {"level": "medium"},
            "audio": {"energy_level": "medium", "is_spike": False},
            "chat": {},
            "composite_score": 0.5,
        }

        ar = AspectRatio(request.aspect_ratio) if request.aspect_ratio in [
            a.value for a in AspectRatio
        ] else AspectRatio.PORTRAIT_9_16

        spec = auto_editor.generate_edit_spec(
            source_path=request.source_path,
            analysis=analysis,
            category=request.category.value,
            aspect_ratio=ar,
            resolution=request.resolution,
            custom_overrides=None,
        )

        # Render
        output_path = await render_pipeline.render(spec)

        if output_path:
            job["status"] = "completed"
            job["output_path"] = output_path
            job["completed_at"] = datetime.now(timezone.utc)
        else:
            job["status"] = "failed"
            job["error"] = "Render başarısız"

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        logger.error("Render job hatası (%s): %s", job_id, e)


async def _execute_montage_job(job_id: str, request: MontageCreate):
    """Arka planda montaj işini yürütür."""
    try:
        from services.edit_spec import MontageSpec, Transition, TransitionType

        # Her klibi basit spec ile render et
        clip_specs = []
        for path in request.clip_paths:
            spec = ClipSpec(source_path=path)
            clip_specs.append(spec)

        transition_type = TransitionType(request.transition_type) \
            if request.transition_type in [t.value for t in TransitionType] \
            else TransitionType.FADE

        montage = MontageSpec(
            clips=clip_specs,
            transition=Transition(
                type=transition_type,
                duration=request.transition_duration,
            ),
            background_music=None,
            output_path=request.output_path or f"data/exports/montage_{job_id}.mp4",
        )

        result = await render_pipeline.render_montage(montage)
        logger.info("Montaj tamamlandı: %s", result)

    except Exception as e:
        logger.error("Montaj job hatası (%s): %s", job_id, e)


# --- Sahne Algilama ---

@router.post("/scene-detect", response_model=SceneDetectionResponse)
async def detect_scenes(request: SceneDetectionRequest):
    """
    Video dosyasından sahneleri algılar.
    FFmpeg scene filter ile sahne değişimlerini tespit eder.
    """
    from services.scene_detection import scene_detection

    try:
        result = await scene_detection.detect_scenes(
            request.source_path,
            threshold=request.threshold,
            min_scene_duration=request.min_scene_duration,
        )

        scenes = [
            SceneInfo(
                index=s.index, start=s.start,
                end=s.end, duration=s.duration,
            )
            for s in result.scenes
        ]

        highlight = None
        if request.highlight_reel:
            highlight = scene_detection.generate_highlight_reel(
                result.scenes,
                max_duration=request.max_highlight_duration,
            )

        return SceneDetectionResponse(
            total_scenes=result.total_scenes,
            total_duration=result.total_duration,
            average_scene_duration=result.average_scene_duration,
            scenes=scenes,
            highlight_reel=highlight,
        )
    except Exception as e:
        logger.error("Sahne algılama hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Beat-Senkronize Duzenleme ---

@router.post("/beat-sync", response_model=BeatSyncResponse)
async def analyze_beat_sync(request: BeatSyncRequest):
    """
    Ses dosyasından beat'leri algılar ve beat-senkronize filtreler üretir.
    """
    from services.beat_sync import beat_sync

    try:
        audio_path = request.audio_path or request.source_path
        beat_grid = await beat_sync.detect_beats(audio_path, request.bpm or 0.8)

        # BPM override
        if request.bpm:
            from services.beat_sync import BeatGrid, BeatInfo
            interval = 60.0 / request.bpm
            beats = []
            t = 0.0
            beat_num = 0
            while t < beat_grid.duration:
                is_downbeat = (beat_num % 4 == 0)
                beats.append(BeatInfo(
                    time=t,
                    strength=1.0 if is_downbeat else 0.6,
                    bpm=request.bpm,
                    beat_number=beat_num % 4,
                    is_downbeat=is_downbeat,
                ))
                t += interval
                beat_num += 1
            beat_grid = BeatGrid(
                bpm=request.bpm, beats=beats,
                total_bars=beat_num // 4,
                time_signature="4/4",
                duration=beat_grid.duration,
            )

        filters_count = 0
        if request.zoom_on_beat:
            f = beat_sync.generate_beat_zoom_filter(beat_grid, request.zoom_level, request.downbeats_only)
            if f and f != "null":
                filters_count += 1
        if request.flash_on_beat:
            f = beat_sync.generate_beat_flash_filter(beat_grid)
            if f and f != "null":
                filters_count += 1
        if request.shake_on_beat:
            f = beat_sync.generate_beat_shake_filter(beat_grid)
            if f and f != "null":
                filters_count += 1
        if request.speed_variation:
            f = beat_sync.generate_beat_speed_filter(beat_grid)
            if f and f != "null":
                filters_count += 1

        return BeatSyncResponse(
            bpm=beat_grid.bpm,
            total_beats=len(beat_grid.beats),
            total_bars=beat_grid.total_bars,
            duration=beat_grid.duration,
            filters_generated=filters_count,
        )
    except Exception as e:
        logger.error("Beat-sync hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Split Screen ---

@router.post("/split-screen")
async def render_split_screen(request: SplitScreenRequest):
    """
    Çoklu klibi split screen olarak render eder.
    """
    try:
        spec = ClipSpec(
            source_path=request.clip_paths[0],
            split_screen=SplitScreenConfig(
                enabled=True,
                layout=request.layout,
                clip_paths=request.clip_paths,
                gap=request.gap,
            ),
        )

        output_path = request.output_path
        result = await render_pipeline.render_split_screen(spec, output_path)

        if not result:
            raise HTTPException(status_code=500, detail="Split screen render başarısız")

        return {
            "status": "completed",
            "output_path": result,
            "layout": request.layout,
            "clip_count": len(request.clip_paths),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Split screen hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- End Screen ---

@router.post("/end-screen")
async def add_end_screen(request: EndScreenRequest):
    """
    Videoya end screen (outro) overlay ekler.
    """
    from services.end_screen import end_screen

    try:
        spec = ClipSpec(
            source_path=request.source_path,
            end_screen=EndScreenConfig(
                enabled=True,
                template=request.template,
                custom_text=request.custom_text,
                call_to_action=request.call_to_action,
                cta_position=request.cta_position,
            ),
        )

        result = await render_pipeline.render(spec)
        if not result:
            raise HTTPException(status_code=500, detail="End screen render başarısız")

        return {
            "status": "completed",
            "output_path": result,
            "template": request.template,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("End screen hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Lower Third ---

@router.post("/lower-third")
async def add_lower_third(request: LowerThirdRequest):
    """
    Videoya lower third grafik ekler.
    """
    try:
        spec = ClipSpec(
            source_path=request.source_path,
            lower_thirds=LowerThirdConfig(
                enabled=True,
                entries=[
                    LowerThirdEntry(
                        name=request.name,
                        title=request.title,
                        style=request.style,
                        start_time=request.start_time,
                        duration=request.duration,
                        position=request.position,
                        animated=request.animated,
                    )
                ],
            ),
        )

        result = await render_pipeline.render(spec)
        if not result:
            raise HTTPException(status_code=500, detail="Lower third render başarısız")

        return {
            "status": "completed",
            "output_path": result,
            "name": request.name,
            "style": request.style,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Lower third hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Sticker/Emoji Overlay ---

@router.post("/sticker")
async def add_sticker_overlay(request: StickerOverlayRequest):
    """
    Videoya sticker/emoji overlay ekler.
    Reaksiyon, emoji yağmuru veya konfeti.
    """
    try:
        spec = ClipSpec(
            source_path=request.source_path,
            stickers=StickerOverlayConfig(
                enabled=True,
                reaction_type=request.reaction_type,
                reaction_start=request.reaction_start,
                reaction_duration=request.reaction_duration,
                emoji_rain=request.emoji_rain,
                emoji_rain_emoji=request.emoji_rain_emoji,
                confetti=request.confetti,
            ),
        )

        result = await render_pipeline.render(spec)
        if not result:
            raise HTTPException(status_code=500, detail="Sticker render başarısız")

        return {
            "status": "completed",
            "output_path": result,
            "reaction_type": request.reaction_type,
            "emoji_rain": request.emoji_rain,
            "confetti": request.confetti,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sticker hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Emotion Arc ---

@router.post("/emotion-arc")
async def apply_emotion_arc(request: EmotionArcRequest):
    """
    Videoya emotion arc efektleri uygular.
    Duygu değişimlerini renk, hız ve vignette efektlerine çevirir.
    """
    try:
        segments = [
            EmotionSegment(
                start=s.get("start", 0),
                end=s.get("end", 1),
                emotion=s.get("emotion", "neutral"),
                intensity=s.get("intensity", 0.5),
            )
            for s in request.segments
        ]

        spec = ClipSpec(
            source_path=request.source_path,
            emotion_arc=EmotionArcConfig(
                enabled=True,
                segments=segments,
                apply_color=request.apply_color,
                apply_speed=request.apply_speed,
                apply_vignette=request.apply_vignette,
            ),
        )

        result = await render_pipeline.render(spec)
        if not result:
            raise HTTPException(status_code=500, detail="Emotion arc render başarısız")

        return {
            "status": "completed",
            "output_path": result,
            "segments_count": len(segments),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Emotion arc hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Tam Gelistirilmis Render ---

@router.post("/advanced-render", response_model=RenderJobResponse)
async def advanced_render(request: AdvancedRenderRequest, background_tasks: BackgroundTasks):
    """
    Tüm gelişmiş özellikleri tek seferde uygulayarak render eder.
    Beat-sync, word-highlight, sticker, lower-third, end-screen,
    emotion-arc, scene-detection dahil.
    """
    job_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)

    job = {
        "job_id": job_id,
        "status": "pending",
        "source_path": request.source_path,
        "output_path": None,
        "edit_spec": None,
        "created_at": now,
        "completed_at": None,
        "error": None,
    }
    _render_jobs[job_id] = job

    background_tasks.add_task(_execute_advanced_render, job_id, request)

    return RenderJobResponse(**job)


async def _execute_advanced_render(job_id: str, request: AdvancedRenderRequest):
    """Arka planda gelişmiş render işini yürütür."""
    job = _render_jobs.get(job_id)
    if not job:
        return

    try:
        job["status"] = "processing"

        # Aspect ratio
        ar = AspectRatio(request.aspect_ratio) if request.aspect_ratio in [
            a.value for a in AspectRatio
        ] else AspectRatio.PORTRAIT_9_16

        # ClipSpec oluştur
        spec = ClipSpec(
            source_path=request.source_path,
            aspect_ratio=ar,
            resolution=request.resolution,
            crf=request.crf,
            category=request.category,
            # Beat sync
            beat_sync=BeatSyncConfig(
                enabled=request.beat_sync_enabled,
                bpm=request.beat_sync_bpm,
                zoom_on_beat=request.beat_sync_zoom,
            ) if request.beat_sync_enabled else BeatSyncConfig(),
            # Word highlight
            word_highlight=WordHighlightConfig(
                enabled=request.word_highlight_enabled,
                words=request.word_highlight_words,
                palette=request.word_highlight_palette,
            ) if request.word_highlight_enabled else WordHighlightConfig(),
            # Stickers
            stickers=StickerOverlayConfig(
                enabled=request.stickers_enabled,
                reaction_type=request.sticker_reaction,
                emoji_rain=request.sticker_emoji_rain,
                confetti=request.sticker_confetti,
            ) if request.stickers_enabled else StickerOverlayConfig(),
            # Lower thirds
            lower_thirds=LowerThirdConfig(
                enabled=request.lower_thirds_enabled,
                entries=[
                    LowerThirdEntry(
                        name=request.lower_thirds_name,
                        title=request.lower_thirds_title,
                        style=request.lower_thirds_style,
                    )
                ] if request.lower_thirds_enabled else [],
            ) if request.lower_thirds_enabled else LowerThirdConfig(),
            # End screen
            end_screen=EndScreenConfig(
                enabled=request.end_screen_enabled,
                template=request.end_screen_template,
            ) if request.end_screen_enabled else EndScreenConfig(),
            # Emotion arc
            emotion_arc=EmotionArcConfig(
                enabled=request.emotion_arc_enabled,
                segments=[
                    EmotionSegment(
                        start=s.get("start", 0),
                        end=s.get("end", 1),
                        emotion=s.get("emotion", "neutral"),
                        intensity=s.get("intensity", 0.5),
                    )
                    for s in request.emotion_arc_segments
                ] if request.emotion_arc_enabled else [],
            ) if request.emotion_arc_enabled else EmotionArcConfig(),
            # Scene detection
            scene_detection=SceneDetectionConfig(
                enabled=request.scene_detection_enabled,
                threshold=request.scene_detection_threshold,
            ) if request.scene_detection_enabled else SceneDetectionConfig(),
        )

        # Render
        output_path = await render_pipeline.render(spec)

        if output_path:
            job["status"] = "completed"
            job["output_path"] = output_path
            job["completed_at"] = datetime.now(timezone.utc)
        else:
            job["status"] = "failed"
            job["error"] = "Render başarısız"

    except Exception as e:
        job["status"] = "failed"
        job["error"] = str(e)
        logger.error("Advanced render job hatası (%s): %s", job_id, e)


# --- Kelime Zamanlama ---

@router.post("/word-timing", response_model=WordTimingResponse)
async def extract_word_timing(request: WordTimingRequest):
    """
    Video/ses dosyasından kelime kelime zamanlama çıkarır.
    Whisper word_timestamps kullanır (mevcut değilse segment bazlı tahmin).
    Karaoke/word-highlight için gerekli.
    """
    from services.word_highlight import word_highlight

    try:
        words = await word_highlight.extract_timings_from_video(
            request.source_path, request.language
        )

        word_infos = [
            WordTimingInfo(
                word=w.word, start=w.start,
                end=w.end, confidence=w.confidence,
            )
            for w in words
        ]

        method = "segment_based"
        if word_highlight._whisper_model is not None:
            method = "whisper"

        return WordTimingResponse(
            source_path=request.source_path,
            language=request.language,
            total_words=len(word_infos),
            words=word_infos,
            method=method,
        )
    except Exception as e:
        logger.error("Kelime zamanlama hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Sahne Bazlı Otomatik Efekt ---

@router.post("/scene-auto-effects", response_model=SceneAutoEffectsResponse)
async def scene_auto_effects(request: SceneAutoEffectsRequest):
    """
    Videoyu sahne analiz edip otomatik efekt üretir.
    Kısa sahneler -> hızlı zoom/flash, uzun sahneler -> yavaş zoom/vignette,
    hareketli sahneler -> shake, sakin sahneler -> slow-mo/cool ton.
    """
    from services.scene_detection import scene_detection

    try:
        result = await scene_detection.auto_generate_edit_spec(
            request.source_path,
            threshold=request.threshold,
            min_scene_duration=request.min_scene_duration,
        )

        if not result:
            raise HTTPException(status_code=400, detail="Sahne bulunamadı")

        return SceneAutoEffectsResponse(
            scene_count=result["scene_count"],
            average_scene_duration=result["average_scene_duration"],
            total_duration=result["total_duration"],
            speed_segments=result["speed_segments"],
            color_preset=result["color_preset"],
            visual_effects=result["visual_effects"],
            scene_transitions=result["scene_transitions"],
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Sahne otomatik efekt hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


# --- Kelime Zamanlama ile Hızlı Karaoke Render ---

@router.post("/karaoke-render")
async def karaoke_render(
    source_path: str,
    language: str = "tr",
    palette: str = "neon",
):
    """
    Videoyu Whisper ile analiz edip kelime vurgulu karaoke render üretir.
    1. Whisper ile kelime zamanlaması çıkar
    2. ASS karaoke dosyası üret
    3. Videoya burn-in yap
    """
    from services.word_highlight import word_highlight

    try:
        words = await word_highlight.extract_timings_from_video(
            source_path, language
        )

        if not words:
            raise HTTPException(
                status_code=400,
                detail="Kelime zamanlama çıkarılamadı"
            )

        ass_content = word_highlight.generate_karaoke_ass(
            words=words,
            palette=palette,
        )

        ass_path = str(TEMP_DIR / f"karaoke_{Path(source_path).stem}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        output_path = str(EXPORTS_DIR / f"karaoke_{Path(source_path).stem}.mp4")
        cmd = [
            "ffmpeg", "-y",
            "-i", source_path,
            "-vf", f"ass={ass_path}",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "copy",
            output_path,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

        if proc.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"FFmpeg hatası: {stderr.decode()[:500]}"
            )

        return {
            "status": "completed",
            "output_path": output_path,
            "ass_path": ass_path,
            "word_count": len(words),
            "palette": palette,
            "method": "whisper" if word_highlight._whisper_model else "segment_based",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Karaoke render hatası: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
