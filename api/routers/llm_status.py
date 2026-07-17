"""
LLM Status API Router
─────────────────────
LLM provider durumu, sağlık metrikleri ve yönlendirme API'si.

Endpoint'ler:
  GET  /api/llm/status          — Tüm provider'ların durumu
  GET  /api/llm/providers       — Ücretsiz provider önerileri
  GET  /api/llm/health          — Hızlı sağlık kontrolü
  POST /api/llm/test            — Belirli provider'ı test et
  POST /api/llm/route           — Akıllı yönlendirme ile generate
  GET  /api/llm/stats           — İstatistikler
  POST /api/llm/reset-cooldowns — Cooldown'ları sıfırla
  GET  /api/llm/vector/stats    — Vektör DB istatistikleri
  POST /api/llm/vector/search   — Semantik klip araması
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("llm_status_router")

router = APIRouter(prefix="/api/llm", tags=["LLM"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class RouteRequest(BaseModel):
    prompt: str
    strategy: str = "cost_optimized"  # cost_optimized / speed_first / quality_first / balanced
    max_tokens: int = 512
    temperature: float = 0.7
    system_prompt: Optional[str] = None


class TestProviderRequest(BaseModel):
    provider: str
    prompt: str = "Say hello in Turkish, one sentence only."
    max_tokens: int = 100


class VectorSearchRequest(BaseModel):
    query: str
    top_k: int = 10
    filters: Optional[dict] = None


class VectorAddRequest(BaseModel):
    clip_id: str
    metadata: dict


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/status", summary="Tüm LLM provider durumu")
async def get_llm_status():
    """
    Tüm LLM provider'larının durumunu, istatistiklerini ve sağlık bilgisini döndürür.
    Smart router'daki tier sistemi ve cooldown durumunu da içerir.
    """
    try:
        from services.llm_engine import llm_engine
        from services.smart_llm_router import smart_router, PROVIDER_TIERS, PROVIDER_SPEED_TPS

        # Engine'deki provider listesi
        engine_providers = [
            {
                "name": name,
                "tier": PROVIDER_TIERS.get(name, 99),
                "speed_tps": PROVIDER_SPEED_TPS.get(name, 30.0),
            }
            for name, _ in llm_engine._providers
        ]

        # Router istatistikleri
        router_status = smart_router.get_status()

        return {
            "engine": {
                "total_providers": llm_engine._provider_count,
                "providers": engine_providers,
                "stats": llm_engine._stats,
                "cache_size": len(llm_engine._cache),
            },
            "router": router_status,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error("LLM status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/providers", summary="Ücretsiz LLM provider önerileri")
async def get_free_providers():
    """
    Ücretsiz LLM provider'larının listesini, kayıt linkleri ve özelliklerini döndürür.
    """
    try:
        from services.smart_llm_router import smart_router
        return {
            "free_providers": smart_router.get_recommended_free_providers(),
            "note": "Bu provider'ların tümü ücretsiz tier veya ücretsiz başlangıç kredisi sunar.",
            "setup_guide": {
                "step1": "provider'ı seç ve kayıt ol",
                "step2": "API key al",
                "step3": ".env dosyasına ekle (örn: GROQ_API_KEY=gsk_...)",
                "step4": "sunucuyu yeniden başlat",
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health", summary="LLM sağlık kontrolü")
async def llm_health():
    """Hızlı LLM sağlık kontrolü — tüm provider'ların erişilebilirlik durumu."""
    try:
        from services.llm_engine import llm_engine
        health = await llm_engine.health_check()
        return health
    except Exception as e:
        return {"healthy": False, "error": str(e)}


@router.post("/test", summary="Provider test et")
async def test_provider(req: TestProviderRequest):
    """Belirli bir provider'ı test prompt ile dene ve yanıt süresini ölç."""
    from services.llm_engine import llm_engine
    import asyncio

    provider_fn = None
    for name, fn in llm_engine._providers:
        if name == req.provider:
            provider_fn = fn
            break

    if provider_fn is None:
        raise HTTPException(
            status_code=404,
            detail=f"Provider '{req.provider}' bulunamadı. Mevcut: {[n for n, _ in llm_engine._providers]}",
        )

    start = time.time()
    try:
        result = await asyncio.wait_for(
            provider_fn(req.prompt, max_tokens=req.max_tokens, temperature=0.5),
            timeout=30.0,
        )
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {
            "provider": req.provider,
            "success": True,
            "response": result,
            "latency_ms": elapsed_ms,
            "chars": len(result),
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Provider '{req.provider}' 30s'de yanıt vermedi")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider hata: {str(e)}")


@router.post("/route", summary="Akıllı yönlendirme ile generate")
async def smart_route_generate(req: RouteRequest):
    """
    Smart router kullanarak LLM çağrısı yap.

    Stratejiler:
    - **cost_optimized**: Önce ücretsiz tier (Groq → Cohere → ...)
    - **speed_first**: En hızlı provider (Groq/Cerebras önce)
    - **quality_first**: En kaliteli model
    - **balanced**: Hız + kalite dengesi
    """
    from services.smart_llm_router import smart_router, sync_router_with_engine

    # Router'ı engine ile senkronize et
    sync_router_with_engine()

    start = time.time()
    try:
        result, provider_used = await smart_router.route(
            prompt=req.prompt,
            strategy=req.strategy,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            system_prompt=req.system_prompt,
        )
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {
            "result": result,
            "provider_used": provider_used,
            "strategy": req.strategy,
            "latency_ms": elapsed_ms,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", summary="Detaylı istatistikler")
async def get_stats():
    """LLM engine ve router istatistiklerini döndürür."""
    try:
        from services.llm_engine import llm_engine
        from services.smart_llm_router import smart_router

        engine_stats = llm_engine._stats.copy()
        # Cache hit rate hesapla
        total = engine_stats.get("total_requests", 0)
        hits = engine_stats.get("cache_hits", 0)
        engine_stats["cache_hit_rate"] = round((hits / total * 100) if total > 0 else 0, 1)

        return {
            "engine_stats": engine_stats,
            "router_stats": {
                name: stats.to_dict()
                for name, stats in smart_router._stats.items()
            },
            "timestamp": time.time(),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset-cooldowns", summary="Cooldown'ları sıfırla")
async def reset_cooldowns():
    """Tüm provider cooldown'larını sıfırla (hata sonrası kurtarma için)."""
    try:
        from services.smart_llm_router import smart_router
        smart_router.reset_cooldowns()
        return {"success": True, "message": "Tüm cooldown'lar sıfırlandı"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Vektör Store Endpoint'leri ───────────────────────────────────────────────

@router.get("/vector/stats", summary="Vektör DB istatistikleri")
async def vector_stats():
    """ChromaDB vektör veritabanı istatistiklerini döndürür."""
    try:
        from services.vector_store import vector_store
        return await vector_store.get_stats()
    except Exception as e:
        return {"error": str(e), "initialized": False}


@router.post("/vector/search", summary="Semantik klip araması")
async def vector_search(req: VectorSearchRequest):
    """
    Semantik anlama ile klip ara.

    Örnekler:
    - "en komik rage anları"
    - "clutch kazanma sahneleri"
    - "eğlenceli fail momentleri"
    """
    try:
        from services.vector_store import vector_store
        results = await vector_store.search(
            query=req.query,
            top_k=req.top_k,
            filters=req.filters,
        )
        return {
            "query": req.query,
            "results": results,
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/vector/add", summary="Klip vektör DB'ye ekle")
async def vector_add(req: VectorAddRequest):
    """Klip'i ChromaDB vektör veritabanına ekle (semantic search için)."""
    try:
        from services.vector_store import vector_store
        ok = await vector_store.add_clip(req.clip_id, req.metadata)
        return {"success": ok, "clip_id": req.clip_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vector/similar/{clip_id}", summary="Benzer klipleri bul")
async def vector_similar(clip_id: str, top_k: int = Query(5, ge=1, le=50)):
    """Bir kliple benzer içerikleri semantik olarak bul."""
    try:
        from services.vector_store import vector_store
        results = await vector_store.find_similar(clip_id, top_k=top_k)
        return {
            "clip_id": clip_id,
            "similar_clips": results,
            "count": len(results),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Faster Whisper Endpoint'leri ─────────────────────────────────────────────

@router.get("/whisper/status", summary="Whisper servisi durumu")
async def whisper_status():
    """faster-whisper servisinin durumunu ve kullanılan backend'i döndürür."""
    try:
        from services.faster_whisper_service import faster_whisper
        return await faster_whisper.get_status()
    except Exception as e:
        return {"error": str(e), "backend": "unavailable"}
