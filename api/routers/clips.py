"""
Klip yönetim API router'ı.
Klipleri listeleme, silme, dışa aktarma, favori ekleme.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from typing import Optional, List
from datetime import datetime

from models.schemas import (
    ClipResponse, ClipListResponse, ClipCreate,
    ClipCategoryEnum, ClipStatusEnum,
)
from models.database import Clip, ClipCategory, ClipStatus, TriggerType
from services.database import get_db
from utils.auth_compat import Principal, Scope, get_current_principal, require_scope

router = APIRouter(prefix="/api/clips", tags=["clips"])


@router.get("/", response_model=ClipListResponse)
async def list_clips(
    _principal: Principal = Depends(require_scope(Scope.CLIPS_READ)),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    status: Optional[str] = None,
    trigger_type: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: AsyncSession = Depends(get_db),
):
    """Klipleri filtreleyerek listeler."""
    query = select(Clip)

    if category:
        query = query.where(Clip.category == category)
    if status:
        query = query.where(Clip.status == status)
    if trigger_type:
        query = query.where(Clip.trigger_type == trigger_type)

    # Toplam sayı
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Sıralama
    sort_col = getattr(Clip, sort_by, Clip.created_at)
    if sort_order == "desc":
        query = query.order_by(desc(sort_col))
    else:
        query = query.order_by(sort_col)

    # Sayfalama
    query = query.offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    clips = result.scalars().all()

    return ClipListResponse(
        clips=[ClipResponse.model_validate(c) for c in clips],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{clip_id}", response_model=ClipResponse)
async def get_clip(
    clip_id: int,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Tek bir klibin detaylarını döndürür."""
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(404, "Klip bulunamadı")
    return ClipResponse.model_validate(clip)


@router.post("/", response_model=ClipResponse)
async def create_manual_clip(
    data: ClipCreate,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
    db: AsyncSession = Depends(get_db),
):
    """Manuel klip kaydı oluşturur (kullanıcı tarafından yüklenen)."""
    clip = Clip(
        broadcaster_id=1,  # Varsayılan - gerçek projede auth'dan gelir
        title=data.title,
        description=data.description,
        category=data.category.value if data.category else ClipCategory.OTHER,
        status=ClipStatus.PENDING,
        trigger_type=data.trigger_type.value if data.trigger_type else TriggerType.MANUAL,
        is_manual=data.is_manual,
    )
    db.add(clip)
    await db.commit()
    await db.refresh(clip)
    return ClipResponse.model_validate(clip)


@router.post("/{clip_id}/upload")
async def upload_clip_file(
    clip_id: int,
    file: UploadFile = File(...),
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
    db: AsyncSession = Depends(get_db),
):
    """Manuel klip için video dosyası yükler."""
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(404, "Klip bulunamadı")

    # Dosyayı kaydet
    import aiofiles
    from pathlib import Path
    clips_dir = Path("data/clips")
    clips_dir.mkdir(parents=True, exist_ok=True)

    file_path = clips_dir / f"manual_{clip_id}_{file.filename}"
    async with aiofiles.open(file_path, "wb") as f:
        content = await file.read()
        await f.write(content)

    clip.video_path = str(file_path)
    clip.status = ClipStatus.PROCESSING
    await db.commit()

    # Arka planda analiz ve altyazı başlat
    import asyncio
    asyncio.create_task(_process_uploaded_clip(clip_id, str(file_path)))

    return {"message": "Dosya yüklendi, işleniyor.", "path": str(file_path)}


@router.patch("/{clip_id}/favorite")
async def toggle_favorite(
    clip_id: int,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
    db: AsyncSession = Depends(get_db),
):
    """Klibi favori olarak işaretle/kaldır."""
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(404, "Klip bulunamadı")

    clip.is_favorite = not clip.is_favorite
    await db.commit()
    return {"is_favorite": clip.is_favorite}


@router.post("/{clip_id}/export")
async def export_clip(
    clip_id: int,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
    resolution: str = "720p",
    platform: Optional[str] = None,
    output_format: str = "mp4",
    add_subtitle: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Klibi sosyal medya format\u0131nda d\u0131\u015fa aktar\u0131r.
    platform: youtube, reels, instagram_post, instagram_vertical (platform secilirse resolution yerine bu kullanilir)
    resolution: 1440p, 1080p, 720p, 480p, 360p, 240p
    output_format: mp4, mov, mkv, webm, avi, wmv
    """
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip or not clip.video_path:
        raise HTTPException(404, "Klip veya video dosyası bulunamadı")

    from services.video_editor import video_editor

    # Platform secildiyse, onun resolution'unu kullan
    actual_resolution = resolution
    if platform and platform in video_editor.PLATFORM_SIZES:
        actual_resolution = video_editor.PLATFORM_SIZES[platform]["resolution"]

    # Boyutlandir + format donustur
    output = await video_editor.export_clip(
        clip.video_path,
        resolution=actual_resolution,
        output_format=output_format,
    )

    # Altyazı ekle
    if add_subtitle and clip.subtitle_path and output:
        from services.subtitle_service import subtitle_service
        output = await subtitle_service.burn_subtitles(output, clip.subtitle_path)

    if output:
        clip.is_exported = True
        await db.commit()
        return {"export_path": output, "message": "Dışa aktarma başarılı"}

    raise HTTPException(500, "Dışa aktarma başarısız")


@router.delete("/{clip_id}")
async def delete_clip(
    clip_id: int,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_DELETE)),
    db: AsyncSession = Depends(get_db),
):
    """Klibi siler."""
    result = await db.execute(select(Clip).where(Clip.id == clip_id))
    clip = result.scalar_one_or_none()
    if not clip:
        raise HTTPException(404, "Klip bulunamadı")

    # Dosyaları sil
    import os
    for path in [clip.video_path, clip.thumbnail_path, clip.subtitle_path]:
        if path and os.path.exists(path):
            os.remove(path)

    await db.delete(clip)
    await db.commit()
    return {"message": "Klip silindi"}


@router.get("/stats/summary")
async def clip_stats(
    _principal: Principal = Depends(require_scope(Scope.CLIPS_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Klip istatistiklerini döndürür."""
    total = await db.execute(select(func.count(Clip.id)))
    by_category = await db.execute(
        select(Clip.category, func.count(Clip.id)).group_by(Clip.category)
    )
    today = await db.execute(
        select(func.count(Clip.id)).where(
            func.date(Clip.created_at) == func.current_date()
        )
    )

    return {
        "total_clips": total.scalar() or 0,
        "today_clips": today.scalar() or 0,
        "by_category": {
            str(cat): count for cat, count in by_category.all()
        },
    }


async def _process_uploaded_clip(clip_id: int, file_path: str):
    """Yüklenen klip için arka plan işleme."""
    from services.subtitle_service import subtitle_service

    try:
        result = await subtitle_service.process_clip_subtitles(
            file_path, language="tr"
        )

        from services.database import async_session
        async with async_session() as db:
            res = await db.execute(select(Clip).where(Clip.id == clip_id))
            clip = res.scalar_one_or_none()
            if clip:
                clip.subtitle_path = result.get("srt_path")
                clip.status = ClipStatus.READY
                await db.commit()

    except Exception as e:
        import logging
        logging.getLogger(__name__).error("Klip işleme hatası: %s", e)
