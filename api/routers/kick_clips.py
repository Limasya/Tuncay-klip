"""
Kick Clips API — Collector verisini dashboard'a sunar.
Search, list, stats, score, edit, render endpoint'leri.
"""
from fastapi import APIRouter, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/api/kick-clips", tags=["kick-clips"])


@router.get("/")
async def list_kick_clips(
    sort_by: str = Query("recent", pattern="^(recent|views|likes)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Kick clip'lerini listele (JSON state'tan)."""
    from services.kick_clips_collector import kick_clips_collector
    state = await kick_clips_collector.read_state()
    clips = list(state.get("clips", {}).values())

    if sort_by == "views":
        clips.sort(key=lambda x: x.get("views", 0), reverse=True)
    elif sort_by == "likes":
        clips.sort(key=lambda x: x.get("likes", 0), reverse=True)
    else:
        clips.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    total = len(clips)
    clips = clips[offset:offset + limit]

    return {
        "clips": clips,
        "total": total,
        "offset": offset,
        "limit": limit,
        "sort_by": sort_by,
    }


@router.get("/search")
async def search_kick_clips(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
):
    """Kick clip'lerinde ara."""
    from services.kick_clips_collector import kick_clips_collector
    results = await kick_clips_collector.search_clips(q)
    return {
        "query": q,
        "results": results[:limit],
        "total": len(results),
    }


@router.get("/stats")
async def kick_clip_stats():
    """Kick clip istatistikleri."""
    from services.kick_clips_collector import kick_clips_collector
    return await kick_clips_collector.get_clip_stats()


@router.get("/top")
async def top_kick_clips(
    sort_by: str = Query("views", pattern="^(views|likes|recent)$"),
    limit: int = Query(20, ge=1, le=100),
):
    """En popüler clip'leri getir."""
    from services.kick_clips_collector import kick_clips_collector
    return await kick_clips_collector.get_top_clips(limit=limit, sort_by=sort_by)


@router.get("/status")
async def kick_clips_collector_status():
    """Collector durumu."""
    from services.kick_clips_collector import kick_clips_collector
    return await kick_clips_collector.get_status()


@router.post("/refresh")
async def refresh_kick_clips(limit: int = Query(100, ge=1, le=500)):
    """Clip'leri yeniden topla."""
    from services.kick_clips_collector import kick_clips_collector
    return await kick_clips_collector.collect_all(limit=limit)


@router.get("/scored")
async def get_scored_clips(
    min_score: float = Query(0, ge=0, le=100),
    limit: int = Query(50, ge=1, le=200),
):
    """Tüm klipleri AI ile puanlandırarak listele."""
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_scorer import clip_scorer

    state = await kick_clips_collector.read_state()
    clips = list(state.get("clips", {}).values())

    scored = await clip_scorer.score_batch(clips)

    if min_score > 0:
        scored = [c for c in scored if c.get("score", 0) >= min_score]

    return {
        "clips": scored[:limit],
        "total": len(scored),
        "edit_queue": len([c for c in scored if c.get("verdict") == "edit"]),
        "watch_queue": len([c for c in scored if c.get("verdict") == "watch"]),
    }


@router.get("/edit-queue")
async def get_edit_queue(
    min_score: float = Query(55, ge=0, le=100),
    limit: int = Query(20, ge=1, le=100),
):
    """Edit için uygun klipleri listele (yüksek puanlı)."""
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_scorer import clip_scorer

    state = await kick_clips_collector.read_state()
    clips = list(state.get("clips", {}).values())

    queue = clip_scorer.get_edit_queue(clips, min_score=min_score)

    return {
        "clips": queue[:limit],
        "total": len(queue),
        "min_score": min_score,
    }


@router.post("/edit")
async def edit_clips(
    background_tasks: BackgroundTasks,
    min_score: float = Query(55, ge=0, le=100),
    max_clips: int = Query(10, ge=1, le=50),
):
    """Yüksek puanlı klipleri otomatik düzenle (arka planda)."""
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_scorer import clip_scorer
    from services.auto_editor import auto_editor

    if auto_editor.is_processing():
        return {"status": "busy", "message": "Düzenleme devam ediyor, lütfen bekleyin."}

    state = await kick_clips_collector.read_state()
    clips = [c for c in state.get("clips", {}).values() if c.get("downloaded")]

    queue = clip_scorer.get_edit_queue(clips, min_score=min_score)[:max_clips]

    if not queue:
        return {"status": "empty", "message": f"min_score={min_score} üzeri klip bulunamadı."}

    # Arka planda düzenle
    background_tasks.add_task(auto_editor.edit_batch, queue)

    return {
        "status": "started",
        "message": f"{len(queue)} klip düzenleniyor...",
        "clips": [
            {"clip_id": c.get("clip_id"), "title": c.get("title"), "score": c.get("score")}
            for c in queue
        ],
    }


@router.post("/{clip_id}/download")
async def download_clip(clip_id: str):
    """Tek bir klibi manuel indir. Dosya data/edited_clips/raw_{clip_id}.mp4'e kaydedilir."""
    from services.kick_clips_collector import kick_clips_collector
    from services.auto_editor import auto_editor
    from pathlib import Path

    state = await kick_clips_collector.read_state()
    clip = state.get("clips", {}).get(clip_id)
    if not clip:
        return {"status": "error", "message": f"Clip {clip_id} bulunamadi."}

    clip_url = clip.get("clip_url", "")
    if not clip_url:
        return {"status": "error", "message": "clip_url yok."}

    out_path = str(Path("data/edited_clips") / f"raw_{clip_id}.mp4")
    ok = await auto_editor._download_clip(clip_url, out_path)
    if ok:
        clip["downloaded"] = True
        state["clips"][clip_id] = clip
        await kick_clips_collector._write_state(state)
        return {"status": "ok", "message": f"Indirildi: {out_path}", "file_path": out_path}
    return {"status": "error", "message": "Indirme basarisiz."}


@router.get("/edit-results")
async def get_edit_results():
    """Düzenleme sonuçlarını döndür."""
    from services.auto_editor import auto_editor
    return {
        "results": auto_editor.get_results(),
        "processing": auto_editor.is_processing(),
    }


# ── KickBot Endpoints ────────────────────────────────────────────

@router.get("/kickbot")
async def list_kickbot_clips(
    sort_by: str = Query("views", pattern="^(views|likes|recent|duration)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """KickBot clip'lerini listele."""
    from services.kickbot_collector import kickbot_collector
    clips = await kickbot_collector.get_all_clips(sort_by=sort_by, limit=limit, offset=offset)
    stats = await kickbot_collector.get_stats()
    return {"clips": clips, "stats": stats, "sort_by": sort_by}


@router.post("/kickbot/sync")
async def sync_kickbot_clips(limit: int = Query(100, ge=1, le=500)):
    """KickBot'tan clip'leri senkronize et."""
    from services.kickbot_collector import kickbot_collector
    return await kickbot_collector.sync_clips(limit=limit)


@router.get("/kickbot/{clip_id}")
async def get_kickbot_clip(clip_id: str):
    """Tek bir KickBot clip detayı."""
    from services.kickbot_collector import kickbot_collector
    clip = await kickbot_collector.get_clip(clip_id)
    if not clip:
        return {"error": "Clip bulunamadı", "clip_id": clip_id}
    return clip


# ── Clip Analiz Endpoints ────────────────────────────────────────

@router.get("/analyze/{clip_id}")
async def analyze_clip(clip_id: str):
    """Klibi LLM ile analiz et — hook tespiti + edit önerileri."""
    from services.kickbot_collector import kickbot_collector
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_analyzer import clip_analyzer

    clip = await kick_clips_collector.get_clip(clip_id)
    if not clip:
        clip = await kickbot_collector.get_clip(clip_id)
    if not clip:
        # Kick API'den çekmeyi dene
        clips = await kickbot_collector.fetch_clips_from_kick_api(limit=200)
        clip = next((c for c in clips if c.get("clip_id") == clip_id), None)
        if not clip:
            return {"error": "Clip bulunamadı", "clip_id": clip_id}

    analysis = await clip_analyzer.analyze_clip(clip)
    return {"clip": clip, "analysis": analysis}


class ClipChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@router.post("/{clip_id}/chat")
async def clip_chat(clip_id: str, body: ClipChatRequest):
    """Klib hakkinda kurgu/duzenleme sorusu sor — LLM streaming cevap doner."""
    from services.kickbot_collector import kickbot_collector
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_analyzer import clip_analyzer
    from services.llm_client import generate

    clip = await kick_clips_collector.get_clip(clip_id)
    if not clip:
        clip = await kickbot_collector.get_clip(clip_id)
    if not clip:
        clips = await kickbot_collector.fetch_clips_from_kick_api(limit=200)
        clip = next((c for c in clips if c.get("clip_id") == clip_id), None)
    if not clip:
        return {"error": "Clip bulunamadi"}

    analysis = await clip_analyzer.analyze_clip(clip)

    system_prompt = (
        "Sen bir video kurgu ve duzenleme asistanisin. "
        "Kullanici sana bir Kick klibi gosteriyor ve kurgu hakkinda soru soruyor. "
        "Klibin analiz sonuclarini, viral potansiyelini, hook onerilerini ve edit stratejilerini "
        "kullanarak kisa, net ve pratik cevaplar ver. "
        "Turkce konus. Eger bir efekt, alt yazi, ses, gecis veya timing onerisi varsa "
        "spesifik FFmpeg veya timeline talimatlari ver."
    )

    clip_context = (
        f"Klib Baslik: {clip.get('title', '—')}\n"
        f"Kanal: {clip.get('channel_slug', '—')}\n"
        f"Süre: {clip.get('duration', '—')}s\n"
        f"Goruntulenme: {clip.get('views', 0)}\n"
        f"Likes: {clip.get('likes', 0)}\n"
        f"Olusturulma: {clip.get('created_at', '—')}\n"
        f"Kategori: {clip.get('category', '—')}\n"
        f"Klip URL: {clip.get('clip_url', '—')}\n"
        f"Thumbnail: {clip.get('thumbnail_url', '—')}\n\n"
        f"--- AI Analiz Sonuclari ---\n"
        f"Viral Potansiyel: {analysis.get('viral_potential', '—')}/100\n"
        f"Hook Onerisi: {analysis.get('hook_suggestion', '—')}\n"
        f"Edit Onerileri: {analysis.get('edit_suggestions', [])}\n"
        f"Duygu Arc: {analysis.get('emotion_arc', [])}\n"
        f"Skor: {analysis.get('score', '—')}\n"
    )

    messages = [{"role": "system", "content": system_prompt + "\n\n" + clip_context}]
    for msg in body.history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": body.message})

    async def stream_tokens():
        try:
            from services.llm_engine import llm_engine
            for msg in messages:
                pass
            prompt = "\n".join(
                f"[{m['role'].upper()}]: {m['content']}" for m in messages
            )
            result = await generate(
                prompt,
                system_prompt=system_prompt,
                max_tokens=1024,
                temperature=0.7,
                use_cache=False,
            )
            yield result
        except Exception as e:
            yield f"[Hata: {e}]"

    return StreamingResponse(stream_tokens(), media_type="text/plain")


@router.post("/analyze-batch")
async def analyze_batch_clips(
    clip_ids: list[str] = Query(...),
):
    """Birden fazla klibi toplu analiz et."""
    from services.kickbot_collector import kickbot_collector
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_analyzer import clip_analyzer

    clips = []
    for cid in clip_ids:
        clip = await kick_clips_collector.get_clip(cid)
        if not clip:
            clip = await kickbot_collector.get_clip(cid)
        if clip:
            clips.append(clip)

    if not clips:
        return {"error": "Hiç clip bulunamadı", "requested": len(clip_ids)}

    analyses = await clip_analyzer.analyze_batch(clips)
    return {"analyses": analyses, "count": len(analyses)}


# ── Stok Video Endpoints ─────────────────────────────────────────

@router.get("/stock/search")
async def search_stock_videos(
    q: str = Query(..., min_length=1),
    category: str | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Stok video ara (Pexels + Pixabay)."""
    from services.stock_video_service import stock_video_service
    results = await stock_video_service.search_videos(q, category=category, limit=limit)
    return {"query": q, "results": results, "total": len(results)}


@router.get("/stock/category/{category}")
async def get_stock_category(
    category: str,
    limit: int = Query(5, ge=1, le=20),
):
    """Kategori bazlı stok videolar getir."""
    from services.stock_video_service import stock_video_service
    results = await stock_video_service.search_category(category, limit=limit)
    return {"category": category, "results": results}


@router.get("/stock/stats")
async def stock_video_stats():
    """Stok video istatistikleri."""
    from services.stock_video_service import stock_video_service
    return stock_video_service.get_stats()


# ── Otomatik Kancalama Endpoints ─────────────────────────────────

@router.post("/auto-hook/{clip_id}")
async def auto_hook(clip_id: str):
    """Klibe otomatik kancalama ekle — LLM + stok video."""
    from services.kickbot_collector import kickbot_collector
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_analyzer import clip_analyzer

    clip = await kick_clips_collector.get_clip(clip_id)
    if not clip:
        clip = await kickbot_collector.get_clip(clip_id)
    if not clip:
        return {"error": "Clip bulunamadı"}

    analysis = await clip_analyzer.analyze_clip(clip)
    return {
        "clip": clip,
        "analysis": analysis,
        "hook_suggestion": analysis.get("hook_suggestion", ""),
        "intro_suggestion": analysis.get("intro_suggestion", ""),
        "outro_suggestion": analysis.get("outro_suggestion", ""),
        "suggested_edits": analysis.get("suggested_edits", []),
    }


# ── Render (Multi-Platform Export) Endpoints ─────────────────────

@router.post("/render/{clip_id}")
async def render_clip(
    clip_id: str,
    platform: str = Query("tiktok", pattern="^(tiktok|instagram_reels|youtube_shorts|x)$"),
    background_tasks: BackgroundTasks = None,
):
    """Tek klibi belirli platform için render et (TikTok/Reels/Shorts/X)."""
    from services.kickbot_collector import kickbot_collector
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_analyzer import clip_analyzer
    from services.auto_editor import auto_editor

    clip = await kick_clips_collector.get_clip(clip_id)
    if not clip:
        clip = await kickbot_collector.get_clip(clip_id)
    if not clip:
        return {"error": "Clip bulunamadı", "clip_id": clip_id}

    # Analiz et (hook timestamp'leri + suggested_edits için)
    analysis = await clip_analyzer.analyze_clip(clip)
    clip["hook_timestamps"] = analysis.get("hook_timestamps", [])
    clip["hook_suggestion"] = analysis.get("hook_suggestion", "")

    # Arka planda render et
    if background_tasks:
        background_tasks.add_task(auto_editor.edit_clip, clip, platform=platform)
        return {
            "status": "started",
            "clip_id": clip_id,
            "platform": platform,
            "message": f"Render başladı: {platform} formatı",
        }

    result = await auto_editor.edit_clip(clip, platform=platform)
    return {
        "status": result.get("status", "unknown"),
        "clip_id": clip_id,
        "platform": platform,
        "result": result,
    }


@router.post("/render-multi/{clip_id}")
async def render_clip_multi_platform(
    clip_id: str,
    platforms: str = Query("tiktok,instagram_reels,youtube_shorts,x"),
):
    """Klibi birden fazla platform için render et."""
    from services.kickbot_collector import kickbot_collector
    from services.kick_clips_collector import kick_clips_collector
    from services.clip_analyzer import clip_analyzer
    from services.auto_editor import auto_editor

    clip = await kick_clips_collector.get_clip(clip_id)
    if not clip:
        clip = await kickbot_collector.get_clip(clip_id)
    if not clip:
        return {"error": "Clip bulunamadı", "clip_id": clip_id}

    # Analiz et
    analysis = await clip_analyzer.analyze_clip(clip)
    clip["hook_timestamps"] = analysis.get("hook_timestamps", [])
    clip["hook_suggestion"] = analysis.get("hook_suggestion", "")

    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]
    results = await auto_editor.edit_multi_platform(clip, platforms=platform_list)

    return {
        "status": "completed",
        "clip_id": clip_id,
        "platforms": platform_list,
        "results": results,
    }


@router.get("/render-results/{clip_id}")
async def get_render_results_for_clip(clip_id: str):
    """Belirli klip için render sonuçlarını listele."""
    from services.auto_editor import auto_editor
    results = auto_editor.get_results()
    return {
        "clip_id": clip_id,
        "results": [r for r in results if r.get("clip_id") == clip_id],
        "processing": auto_editor.is_processing(),
    }


@router.get("/render-status")
async def render_status():
    """Render pipeline durumu."""
    from services.auto_editor import auto_editor
    return {
        "processing": auto_editor.is_processing(),
        "results_count": len(auto_editor.get_results()),
    }


@router.get("/available-formats")
async def get_available_formats():
    """Render için mevcut tüm formatları listele (2026 spec)."""
    return {
        "formats": [
            {
                "id": "tiktok",
                "name": "TikTok",
                "resolution": "1080x1920",
                "aspect": "9:16",
                "max_bitrate": "10M",
                "audio": "192k AAC stereo",
                "fps": 30,
                "max_duration": "10:00",
                "max_size": "287.6 MB",
                "sweet_spot": "21-34s",
                "hook_window": "1-3s",
                "aesthetic": "Raw & Fast",
                "safe_zone": "top 15% + bottom 35%",
            },
            {
                "id": "instagram_reels",
                "name": "Instagram Reels",
                "resolution": "1080x1920",
                "aspect": "9:16",
                "max_bitrate": "12M",
                "audio": "192k AAC stereo",
                "fps": 30,
                "max_duration": "3:00",
                "max_size": "4 GB",
                "sweet_spot": "15-30s",
                "hook_window": "1-2s",
                "aesthetic": "Aesthetic & Curated",
                "safe_zone": "top 12% + bottom 30%",
                "dm_share_weighted": "3-5x",
            },
            {
                "id": "youtube_shorts",
                "name": "YouTube Shorts",
                "resolution": "1080x1920",
                "aspect": "9:16",
                "max_bitrate": "10M",
                "audio": "192k AAC stereo",
                "fps": 30,
                "max_duration": "3:00",
                "max_size": "256 MB",
                "sweet_spot": "15-60s",
                "hook_window": "1-3s",
                "aesthetic": "Utility & Search",
                "safe_zone": "top 10% + bottom 25%",
            },
            {
                "id": "x",
                "name": "X / Twitter",
                "resolution": "1280x720",
                "aspect": "16:9",
                "max_bitrate": "5M",
                "audio": "128k AAC",
                "fps": 30,
                "max_duration": "2:20",
                "max_size": "512 MB",
                "sweet_spot": "30-90s",
                "hook_window": "1-3s",
                "aesthetic": "Conversation Starter",
                "safe_zone": "top 5% + bottom 10%",
            },
        ]
    }
