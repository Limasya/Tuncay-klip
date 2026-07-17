"""
GraphQL endpoint testleri.

`/graphql` üzerinden semantik klip aramasının (ChromaDB) çalıştığını doğrular.
VectorStore.search, testte monkeypatch ile sahte sonuç döndürecek şekilde
değiştirilir; böylece harici bağımlılıklar yüklenmeden test çalışabilir.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from main import app
from services.vector_store import vector_store


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as _client:
        yield _client


@pytest.mark.asyncio
async def test_graphql_search(monkeypatch, client):
    """`search` alanının sonuçları başarılı şekilde döndürdüğünü doğrular."""

    async def _fake_search(query, top_k=10, filters=None):
        return [
            {
                "clip_id": "clip-1",
                "similarity_score": 0.92,
                "metadata": {"title": "İlk klip", "category": "funny"},
            },
            {
                "clip_id": "clip-2",
                "similarity_score": 0.81,
                "metadata": {"title": "İkinci klip", "category": "rage"},
            },
        ]

    monkeypatch.setattr(vector_store, "search", _fake_search)

    query = """
        query Search($q: String!, $k: Int!) {
            search(query: $q, topK: $k) {
                clipId
                similarityScore
                metadata
            }
        }
    """
    variables = {"q": "en komik rage anları", "k": 2}

    response = await client.post(
        "/graphql",
        json={"query": query, "variables": variables},
    )

    assert response.status_code == 200, response.text
    payload = response.json()

    # Hata yoksa 'data' dönmeli
    assert "errors" not in payload or not payload["errors"], payload
    assert "data" in payload, payload

    results = payload["data"]["search"]
    assert isinstance(results, list)
    assert len(results) == 2
    assert results[0]["clipId"] == "clip-1"
    assert results[0]["similarityScore"] == pytest.approx(0.92)
    assert results[0]["metadata"]["title"] == "İlk klip"
    assert results[1]["clipId"] == "clip-2"
    assert results[1]["metadata"]["category"] == "rage"


@pytest.mark.asyncio
async def test_graphql_vector_stats(monkeypatch, client):
    """`vectorStats` sorgusu, vector_store.get_stats () çıktısını döndürür."""

    async def _fake_stats():
        return {
            "initialized": True,
            "total_clips": 42,
            "embedder": "sentence_transformers",
            "model": "paraphrase-multilingual-MiniLM-L12-v2",
            "db_dir": "data/vector_db",
        }

    monkeypatch.setattr(vector_store, "get_stats", _fake_stats)

    query = """
        query {
            vectorStats {
                initialized
                totalClips
                embedder
                model
                dbDir
            }
        }
    """
    response = await client.post("/graphql", json={"query": query})
    assert response.status_code == 200, response.text
    payload = response.json()

    assert "errors" not in payload or not payload["errors"], payload
    stats = payload["data"]["vectorStats"]
    assert stats["initialized"] is True
    assert stats["totalClips"] == 42
    assert stats["embedder"] == "sentence_transformers"
    assert stats["model"].endswith("MiniLM-L12-v2")
    assert stats["dbDir"] == "data/vector_db"
