"""
Otomatik edit API endpoint'leri.
Edit spec oluşturma, render, montaj, müzik/SFX kütüphanesi.
"""
import logging
import uuid
from datetime import datetime
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from models.schemas import (
    EditSpecRequest, EditSpecResponse, RenderJobCreate, RenderJobResponse,
    MontageCreate, MusicLibraryResponse, SFXLibraryResponse,
    AudioDuckingRequest, AudioDuckingResponse,
)
from services.auto_editor import auto_editor
from services.render_pipeline import render_pipeline
from services.music_service import music_service
from services.edit_spec import AspectRatio, ClipSpec

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/edit", tags=["auto-edit"])

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
            custom_overrides=request.custom_overrides,
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
    now = datetime.utcnow()

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
            custom_overrides=request.custom_overrides,
        )

        # Render
        output_path = await render_pipeline.render(spec)

        if output_path:
            job["status"] = "completed"
            job["output_path"] = output_path
            job["completed_at"] = datetime.utcnow()
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
