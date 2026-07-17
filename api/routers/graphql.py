"""
GraphQL endpoint — semantik klip araması ve vektör store istatistikleri.

Özellikler:
  - ``search`` sorgusu: ChromaDB üzerinden semantik benzerlik araması
  - ``vectorStats`` sorgusu: Vektör veritabanı sağlık bilgilerini getirir
  - Tüm resolver çağrıları OpenTelemetry span'ı ile izlenebilir
    (otel_enabled + paketler mevcutsa).
"""
import logging
from contextlib import contextmanager
from typing import Optional, List

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON

from services.vector_store import vector_store

try:
    from platform_eng.observability import start_span as _otel_start_span
    _OTEL_AVAILABLE = True
except Exception:  # pragma: no cover - telemetry bağımlılığı opsiyonel
    _OTEL_AVAILABLE = False


@contextmanager
def _maybe_span(name: str, **attrs):
    """OpenTelemetry span oluştur; bağımlılık yoksa noop."""
    if _OTEL_AVAILABLE:
        with _otel_start_span(name, **attrs) as span:
            yield span
    else:
        yield None


logger = logging.getLogger("graphql_api")


@strawberry.type
class SearchResult:
    clip_id: str
    similarity_score: float
    metadata: JSON


@strawberry.type
class VectorStoreStatus:
    """Vector store (ChromaDB) çalışma durumu."""
    initialized: bool
    total_clips: int
    embedder: str
    model: str
    db_dir: str


@strawberry.type
class Query:
    @strawberry.field
    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[JSON] = None,
    ) -> List[SearchResult]:
        """ChromaDB üzerinden semantik klip araması."""
        with _maybe_span(
            "graphql.search",
            query=query,
            top_k=top_k,
        ):
            results = await vector_store.search(
                query=query, top_k=top_k, filters=filters,
            )
            return [SearchResult(**res) for res in results]

    @strawberry.field
    async def vector_stats(self) -> VectorStoreStatus:
        """Vector store istatistikleri — izleme/dashboard için."""
        stats = await vector_store.get_stats()
        return VectorStoreStatus(
            initialized=bool(stats.get("initialized")),
            total_clips=int(stats.get("total_clips", 0)),
            embedder=str(stats.get("embedder", "")),
            model=str(stats.get("model", "")),
            db_dir=str(stats.get("db_dir", "")),
        )


schema = strawberry.Schema(query=Query)


async def get_context() -> dict:
    return {}


def get_context_sync() -> dict:
    return {}


router = GraphQLRouter(schema, path="/graphql", context_getter=get_context_sync)