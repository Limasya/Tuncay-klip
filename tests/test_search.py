"""
REST semantic search endpoint testleri.

`/api/search/semantic` endpoint'i ChromaDB üzerinden semantik
klip aramasını REST üzerinden sağlar. VectorStore.search, testte
monkeypatch ile sahte sonuç döndürecek şekilde değiştirilir.
"""
import json

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from main import app
from services.vector_store import vector_store


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_semantic_search_success(monkeypatch, client):
    """Başarılı arama: VectorStore.search sonuçları JSON olarak dönmeli."""

    async def _fake_search(self, query, top_k=10, filters=None):
        assert query == "rage moment"
        assert top_k == 2
        assert filters == {"category": "funny"}
        return [
            {
                "clip_id": "abc-1",
                "similarity_score": 0.95,
                "metadata": {"title": "İlk", "category": "funny"},
            },
            {
                "clip_id": "abc-2",
                "similarity_score": 0.75,
                "metadata": {"title": "İkinci", "category": "funny"},
            },
        ]

    monkeypatch.setattr(vector_store, "search", _fake_search)

    response = await client.get(
        "/api/search/semantic",
        params={
            "q": "rage moment",
            "top_k": 2,
            "filters": json.dumps({"category": "funny"}),
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["query"] == "rage moment"
    assert payload["top_k"] == 2
    assert payload["count"] == 2
    assert payload["filters"] == {"category": "funny"}
    assert payload["results"][0]["clip_id"] == "abc-1"
    assert payload["results"][0]["similarity_score"] == pytest.approx(0.95)


@pytest.mark.asyncio
async def test_semantic_search_invalid_filters(client):
    """Geçersiz JSON filtresi için 400 dönmeli."""
    response = await client.get(
        "/api/search/semantic",
        params={"q": "anything", "filters": "{not json}"},
    )
    assert response.status_code == 400
    detail = response.json().get("detail", "")
    assert "Geçersiz filters JSON" in detail


@pytest.mark.asyncio
async def test_semantic_search_empty_results(monkeypatch, client):
    """Hiç sonuç yoksa boş liste dönmeli."""

    async def _fake_empty(self, query, top_k=10, filters=None):
        return []

    monkeypatch.setattr(vector_store, "search", _fake_empty)

    resp = await client.get("/api/search/semantic", params={"q": "no-match"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["results"] == []
