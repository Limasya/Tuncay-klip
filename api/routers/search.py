"""
Semantic Search API Router
─────────────────────────
Vector store (ChromaDB) üzerinden REST üzerinden semantik arama yapar.

Endpoint: GET /api/search/semantic?q=<sorgu>&top_k=10&filters=<json>
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from services.vector_store import vector_store
from utils.auth_compat import Principal, Scope, require_scope

logger = logging.getLogger("search_api")

router = APIRouter(prefix="/api/search", tags=["Search"])


def _resolve_scope_guard():
    """Devre dışı bırakılmış auth ortamlarında da çalışabilen guard döndürür."""
    return require_scope(Scope.ANALYTICS_READ)


@router.get("/semantic")
async def semantic_search(
    q: str = Query(..., min_length=1, description="Arama sorgusu metni"),
    top_k: int = Query(
        10,
        ge=1,
        le=50,
        description="Maksimum sonuç sayısı (1-50)",
    ),
    filters: Optional[str] = Query(
        None,
        description="JSON formatında ChromaDB 'where' filtresi (örn: {\"category\":\"funny\"})",
    ),
    _principal: Principal = Depends(_resolve_scope_guard()),
):
    """ChromaDB üzerinden semantik klip araması.

    Query parametreleri:
      - q: arama metni (zorunlu)
      - top_k: kaç sonuç (1-50, varsayılan 10)
      - filters: JSON string olarak extra metadata filtreleri

    Response: {"query": "...", "top_k": 10, "results": [...]}
    """
    parsed_filters: Optional[dict[str, Any]] = None
    if filters:
        try:
            parsed_filters = json.loads(filters)
            if not isinstance(parsed_filters, dict):
                raise ValueError("filters JSON bir nesne olmalı")
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid filters payload: %s", exc)
            raise HTTPException(
                status_code=400,
                detail=f"Geçersiz filters JSON: {exc}",
            )

    try:
        results = await vector_store.search(
            query=q,
            top_k=top_k,
            filters=parsed_filters,
        )
    except Exception as exc:  # pragma: no cover – beklenmeyen hata
        logger.exception("Search failed for query=%s: %s", q, exc)
        raise HTTPException(
            status_code=500,
            detail=f"Arama sırasında hata oluştu: {exc}",
        )

    return {
        "query": q,
        "top_k": top_k,
        "filters": parsed_filters,
        "count": len(results),
        "results": results,
    }
