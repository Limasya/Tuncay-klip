"""
LLM Status API Router
─────────────────────
LLM provider durumu, sağlık metrikleri ve yönlendirme API'si.

Endpoint'ler:
    GET  /api/llm/status          — Tüm provider'ların durumu
    GET  /api/llm/health          — Hızlı sağlık kontrolü
    POST /api/llm/test            — Belirli provider'ı test et
    GET  /api/llm/stats           — İstatistikler
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
        from services import llm_client

        # Facade durumu
        facade_status = llm_client.get_router_status()
        facade_health = await llm_client.health_check()

        return {
            "facade": facade_status,
            "health": facade_health,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.error("LLM status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/health", summary="LLM sağlık kontrolü")
async def llm_health():
    """Hızlı LLM sağlık kontrolü — tüm provider'ların erişilebilirlik durumu."""
    try:
        from services import llm_client
        health = await llm_client.health_check()
        return health
    except Exception as e:
        return {"healthy": False, "error": str(e)}


@router.post("/test", summary="Provider test et")
async def test_provider(req: TestProviderRequest):
    """Belirli bir provider'ı test prompt ile dene ve yanıt süresini ölç."""
    from services import llm_client
    import asyncio

    # Provider testi facade üzerinden (flag-off: llm_engine providers, flag-on: router)
    provider_name = req.provider
    start = time.time()
    try:
        result = await llm_client.generate(
            req.prompt,
            language="tr",
            max_tokens=req.max_tokens,
            temperature=0.5,
        )
        elapsed_ms = round((time.time() - start) * 1000, 1)
        return {
            "provider": provider_name,
            "success": True,
            "response": result,
            "latency_ms": elapsed_ms,
            "chars": len(result),
        }
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"Provider '{provider_name}' 30s'de yanıt vermedi")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Provider hata: {str(e)}")



@router.get("/stats", summary="Detaylı istatistikler")
async def get_stats():
    """LLM engine ve router istatistiklerini döndürür."""
    try:
        from services import llm_client

        engine_stats = llm_client.get_stats()
        # Cache hit rate hesapla
        total = engine_stats.get("total_requests", 0)
        hits = engine_stats.get("cache_hits", 0)
        engine_stats["cache_hit_rate"] = round((hits / total * 100) if total > 0 else 0, 1)

        return {
            "engine_stats": engine_stats,
            "facade": llm_client.get_router_status(),
            "timestamp": time.time(),
        }
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
