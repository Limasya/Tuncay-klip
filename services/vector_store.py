"""
Vector Store — ChromaDB ile Semantik Arama
─────────────────────────────────────────
Klipleri vektör veritabanında sakla ve semantik arama yap.

Özellikler:
  - ChromaDB local vektör veritabanı (ücretsiz, açık kaynak)
  - sentence-transformers ile yerel embedding (ücretsiz)
  - Semantik klip arama ("en eğlenceli clipler", "rage anları" gibi)
  - Benzer klip bulma
  - Tag/kategori tabanlı filtreleme
  - HuggingFace embedding fallback

Kullanım:
    from services.vector_store import vector_store
    await vector_store.add_clip(clip_id, metadata)
    results = await vector_store.search("rage moment", top_k=5)
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("vector_store")


class ClipVectorStore:
    """
    ChromaDB tabanlı klip semantik arama motoru.

    İlk başlatmada ChromaDB ve embedding modeli yüklenir.
    Tüm çağrılar non-blocking (asyncio.to_thread) çalışır.
    """

    COLLECTION_NAME = "tuncay_klip_clips"
    DB_DIR = "data/vector_db"

    def __init__(self):
        self._client = None
        self._collection = None
        self._embedder = None
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _ensure_initialized(self):
        """Lazy initialization — ilk kullanımda yükle."""
        if self._initialized:
            return
        async with self._init_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._init_sync)
            self._initialized = True

    def _init_sync(self):
        """Senkron başlatma (thread'de çalışır)."""
        os.makedirs(self.DB_DIR, exist_ok=True)

        # ── ChromaDB ──
        try:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=self.DB_DIR,
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=self.COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "ChromaDB initialized at %s (collection=%s, count=%d)",
                self.DB_DIR, self.COLLECTION_NAME, self._collection.count(),
            )
        except ImportError:
            logger.warning("chromadb not installed — vector search disabled")
            return
        except Exception as e:
            logger.warning("ChromaDB init failed: %s", e)
            return

        # ── Embedding Modeli ──
        self._embedder = self._load_embedder()

    def _load_embedder(self):
        """Embedding modeli yükle (sentence-transformers veya fallback)."""
        # Önce sentence-transformers dene (yerel, ücretsiz)
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.environ.get(
                "EMBEDDING_MODEL",
                "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            )
            embedder = SentenceTransformer(model_name)
            logger.info("sentence-transformers embedding loaded: %s", model_name)
            return ("sentence_transformers", embedder)
        except ImportError:
            pass
        except Exception as e:
            logger.warning("sentence-transformers failed: %s", e)

        # Fallback: transformers kütüphanesi
        try:
            from transformers import AutoTokenizer, AutoModel
            import torch

            model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModel.from_pretrained(model_name)
            model.eval()
            logger.info("HuggingFace transformers embedding loaded (fallback)")
            return ("transformers", (tokenizer, model))
        except Exception as e:
            logger.warning("Transformers embedding failed: %s — using hash fallback", e)

        return ("hash", None)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Metinleri embedding vektörlerine dönüştür."""
        if self._embedder is None:
            return self._hash_embed(texts)

        kind, model = self._embedder

        if kind == "sentence_transformers":
            try:
                embeddings = model.encode(texts, convert_to_numpy=True)
                return embeddings.tolist()
            except Exception as e:
                logger.warning("ST embed failed: %s", e)

        if kind == "transformers":
            try:
                import torch
                tokenizer, m = model
                encoded = tokenizer(texts, padding=True, truncation=True,
                                    max_length=128, return_tensors="pt")
                with torch.no_grad():
                    output = m(**encoded)
                embeddings = output.last_hidden_state[:, 0, :].numpy()
                return embeddings.tolist()
            except Exception as e:
                logger.warning("Transformers embed failed: %s", e)

        return self._hash_embed(texts)

    @staticmethod
    def _hash_embed(texts: list[str]) -> list[list[float]]:
        """Hash tabanlı basit embedding (son çare, 128 boyut)."""
        import hashlib
        result = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = [(b / 255.0 - 0.5) * 2 for b in h]
            # 128 boyuta pad
            while len(vec) < 128:
                vec.extend(vec[:min(len(vec), 128 - len(vec))])
            result.append(vec[:128])
        return result

    def _build_clip_text(self, clip_id: str, metadata: dict) -> str:
        """Klip metadata'sından arama metni oluştur."""
        parts = [
            metadata.get("title", ""),
            metadata.get("category", ""),
            metadata.get("emotion", ""),
            metadata.get("game", ""),
            metadata.get("streamer", ""),
            " ".join(metadata.get("tags", [])),
            metadata.get("description", ""),
        ]
        return " | ".join(p for p in parts if p)

    # ─── Public API ──────────────────────────────────────────────────────────

    async def add_clip(self, clip_id: str, metadata: dict) -> bool:
        """Klip'i vektör veritabanına ekle."""
        await self._ensure_initialized()
        if self._collection is None:
            return False

        try:
            text = self._build_clip_text(clip_id, metadata)
            embeddings = await asyncio.to_thread(self._embed, [text])

            await asyncio.to_thread(
                self._collection.upsert,
                ids=[str(clip_id)],
                embeddings=embeddings,
                documents=[text],
                metadatas=[{
                    "clip_id": str(clip_id),
                    "title": metadata.get("title", "")[:200],
                    "category": metadata.get("category", ""),
                    "emotion": metadata.get("emotion", ""),
                    "game": metadata.get("game", ""),
                    "streamer": metadata.get("streamer", ""),
                    "duration": str(metadata.get("duration", 0)),
                    "virality_score": str(metadata.get("virality_score", 0)),
                    "platform": metadata.get("platform", ""),
                    "created_at": metadata.get("created_at", ""),
                }],
            )
            logger.debug("Vector store: added clip %s", clip_id)
            return True
        except Exception as e:
            logger.warning("Vector store add failed for %s: %s", clip_id, e)
            return False

    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Semantik arama yap.

        Args:
            query: Arama metni (örn: "en komik rage anları")
            top_k: Kaç sonuç döndürülsün
            filters: ChromaDB where filtresi (örn: {"category": "exciting"})

        Returns:
            [{"clip_id": ..., "score": ..., "metadata": {...}}, ...]
        """
        await self._ensure_initialized()
        if self._collection is None:
            return []

        try:
            query_embeddings = await asyncio.to_thread(self._embed, [query])

            kwargs: dict[str, Any] = {
                "query_embeddings": query_embeddings,
                "n_results": min(top_k, max(1, self._collection.count())),
                "include": ["distances", "metadatas", "documents"],
            }
            if filters:
                kwargs["where"] = filters

            results = await asyncio.to_thread(self._collection.query, **kwargs)

            output = []
            if results["ids"] and results["ids"][0]:
                for i, clip_id in enumerate(results["ids"][0]):
                    distance = results["distances"][0][i] if results.get("distances") else 1.0
                    similarity = 1.0 - distance  # cosine distance → similarity
                    output.append({
                        "clip_id": clip_id,
                        "similarity_score": round(similarity, 4),
                        "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                        "document": results["documents"][0][i] if results.get("documents") else "",
                    })

            logger.debug("Vector search '%s': %d results", query[:50], len(output))
            return output

        except Exception as e:
            logger.warning("Vector search failed for '%s': %s", query[:50], e)
            return []

    async def find_similar(self, clip_id: str, top_k: int = 5) -> list[dict]:
        """Bir klipe benzer klipleri bul."""
        await self._ensure_initialized()
        if self._collection is None:
            return []

        try:
            # Önce mevcut klibi bul
            result = await asyncio.to_thread(
                self._collection.get,
                ids=[str(clip_id)],
                include=["documents"],
            )
            if not result["documents"]:
                return []

            clip_text = result["documents"][0]
            return await self.search(clip_text, top_k=top_k + 1)

        except Exception as e:
            logger.warning("find_similar failed for %s: %s", clip_id, e)
            return []

    async def delete_clip(self, clip_id: str) -> bool:
        """Klip'i vektör veritabanından sil."""
        await self._ensure_initialized()
        if self._collection is None:
            return False
        try:
            await asyncio.to_thread(self._collection.delete, ids=[str(clip_id)])
            return True
        except Exception as e:
            logger.warning("Vector delete failed for %s: %s", clip_id, e)
            return False

    async def get_stats(self) -> dict:
        """Vektör store istatistikleri."""
        await self._ensure_initialized()
        count = 0
        embedder_type = "none"

        if self._collection is not None:
            try:
                count = await asyncio.to_thread(self._collection.count)
            except Exception as e:
                logger.debug("Vector store count alınamadı: %s", e)

        if self._embedder:
            embedder_type = self._embedder[0]

        return {
            "initialized": self._initialized,
            "db_dir": self.DB_DIR,
            "collection": self.COLLECTION_NAME,
            "total_clips": count,
            "embedder": embedder_type,
            "model": os.environ.get(
                "EMBEDDING_MODEL",
                "paraphrase-multilingual-MiniLM-L12-v2",
            ),
        }

    async def rebuild_index(self, clips: list[dict]) -> dict:
        """Tüm klipleri yeniden indeksle."""
        added = 0
        failed = 0
        for clip in clips:
            clip_id = clip.get("id") or clip.get("clip_id")
            if not clip_id:
                continue
            ok = await self.add_clip(clip_id, clip)
            if ok:
                added += 1
            else:
                failed += 1

        return {"added": added, "failed": failed, "total": len(clips)}


# Singleton
vector_store = ClipVectorStore()
