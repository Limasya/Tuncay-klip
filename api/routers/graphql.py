from typing import Optional, List
import strawberry
from strawberry.fastapi import GraphQLRouter
from services.vector_store import vector_store


@strawberry.type
class SearchResult:
    clip_id: str
    similarity_score: float
    metadata: dict


@strawberry.type
class Query:
    @strawberry.field
    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[dict] = None
    ) -> List[SearchResult]:
        """
        ChromaDB üzerinden semantik arama yapar.
        
        Args:
            query: Arama metni (örn: "en komik rage anları", "clutch kazanma sahneleri")
            top_k: Kaç sonuç döndürülsün (varsayılan 10)
            filters: ChromaDB where filtresi (örn: {"category": "exciting"})
        
        Returns:
            Benzerlik skoruna göre sıralı klip listesi
        """
        results = await vector_store.search(query=query, top_k=top_k, filters=filters)
        return [SearchResult(**res) for res in results]


schema = strawberry.Schema(query=Query)
router = GraphQLRouter(schema)