from core.embedding import EmbeddingProvider, EmbeddingRequest
from core.memory.models import Experience, MemoryIndexEmbedding, MemoryItem


class ProviderMemoryEmbedder:
    """把共享 EmbeddingProvider 适配为 Memory 查询向量端口。"""

    def __init__(self, provider: EmbeddingProvider) -> None:
        self._provider = provider

    async def embed(self, query: str) -> list[float]:
        response = await self._provider.embed(EmbeddingRequest(query))
        return list(response.vector)

    async def embed_item(self, item: MemoryItem) -> MemoryIndexEmbedding:
        """由 Memory 决定领域对象对应的检索文本。"""

        payload = item.payload
        text = payload.summary if isinstance(payload, Experience) else payload.content
        response = await self._provider.embed(EmbeddingRequest(text))
        return MemoryIndexEmbedding(response.vector, response.model)


class SimpleMemoryEmbedder:
    """MVP 阶段的占位 Embedding 实现。"""

    async def embed(
        self,
        query: str,
    ) -> list[float]:
        if not query.strip():
            return [0.0]

        return [float(len(query))]
