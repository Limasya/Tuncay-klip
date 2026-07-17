from typing import Optional, List
import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from services.vector_store import vector_store


@strawberry.type
class SearchResult:
    clip_id: str
    similarity_score: float
    metadata: JSON


@strawberry.type
class Query:
    @strawberry.field
    async def search(
        self,
        query: str,
        top_k: int = 10,
        filters: Optional[JSON] = None
    ) -> List[SearchResult]:
        """ChromaDB üzerinden semantik klip araması."""
        results = await vector_store.search(query=query, top_k=top_k, filters=filters)
        return [SearchResult(**res) for res in results]


schema = strawberry.Schema(query=Query)


async def get_context() -> dict:
    return {}


def get_context_sync() -> dict:
    return {}


router = GraphQLRouter(schema, path="/graphql", context_getter=get_context_sync)