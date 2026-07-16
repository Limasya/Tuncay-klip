"""
Kullanıcı tercihleri API router'ı.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models.schemas import UserPreferencesUpdate, UserPreferencesResponse
from models.database import UserPreferences, Broadcaster
from services.database import get_db
from utils.auth_compat import Principal, Scope, get_current_principal, require_scope

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


@router.get("/", response_model=UserPreferencesResponse)
async def get_preferences(
    _principal: Principal = Depends(get_current_principal),
    db: AsyncSession = Depends(get_db),
):
    """Mevcut kullanıcı tercihlerini döndürür."""
    result = await db.execute(
        select(UserPreferences).join(Broadcaster).limit(1)
    )
    prefs = result.scalar_one_or_none()
    if not prefs:
        # Varsayılan tercihler döndür
        return UserPreferencesResponse(
            broadcaster_id=0,
            preferred_categories=[],
            min_clip_duration=10,
            max_clip_duration=60,
            auto_subtitle=True,
            subtitle_language="tr",
            subtitle_style="default",
            emotion_sensitivity=0.7,
            motion_sensitivity=0.6,
            audio_trigger_enabled=True,
            chat_trigger_enabled=True,
            auto_export=False,
            export_format="mp4",
            export_resolution="1080p",
            add_watermark=False,
            watermark_text=None,
            priority_tags=[],
            excluded_tags=[],
            sort_by="created_at",
        )
    return UserPreferencesResponse.model_validate(prefs)


@router.put("/", response_model=UserPreferencesResponse)
async def update_preferences(
    data: UserPreferencesUpdate,
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
    db: AsyncSession = Depends(get_db),
):
    """Kullanıcı tercihlerini günceller."""
    result = await db.execute(
        select(UserPreferences).join(Broadcaster).limit(1)
    )
    prefs = result.scalar_one_or_none()

    if not prefs:
        # Yeni tercih kaydı oluştur
        bc_result = await db.execute(select(Broadcaster).limit(1))
        broadcaster = bc_result.scalar_one_or_none()
        if not broadcaster:
            raise HTTPException(400, "Önce bir yayıncı ekleyin")

        prefs = UserPreferences(broadcaster_id=broadcaster.id)
        db.add(prefs)

    # Güncelleme
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prefs, key, value)

    await db.commit()
    await db.refresh(prefs)
    return UserPreferencesResponse.model_validate(prefs)


@router.post("/reset")
async def reset_preferences(
    _principal: Principal = Depends(require_scope(Scope.CLIPS_WRITE)),
    db: AsyncSession = Depends(get_db),
):
    """Tercihleri varsayılan değerlere sıfırlar."""
    result = await db.execute(
        select(UserPreferences).join(Broadcaster).limit(1)
    )
    prefs = result.scalar_one_or_none()
    if prefs:
        prefs.preferred_categories = []
        prefs.min_clip_duration = 10
        prefs.max_clip_duration = 60
        prefs.auto_subtitle = True
        prefs.subtitle_language = "tr"
        prefs.subtitle_style = "default"
        prefs.emotion_sensitivity = 0.7
        prefs.motion_sensitivity = 0.6
        prefs.audio_trigger_enabled = True
        prefs.chat_trigger_enabled = True
        prefs.auto_export = False
        prefs.export_format = "mp4"
        prefs.export_resolution = "1080p"
        prefs.add_watermark = False
        prefs.watermark_text = None
        prefs.priority_tags = []
        prefs.excluded_tags = []
        prefs.sort_by = "created_at"
        await db.commit()

    return {"message": "Tercihler sıfırlandı"}
