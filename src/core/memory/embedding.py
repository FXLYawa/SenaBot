class SimpleMemoryEmbedder:
    """MVP 阶段的占位 Embedding 实现。"""

    async def embed(
        self,
        query: str,
    ) -> list[float]:
        if not query.strip():
            return [0.0]

        return [float(len(query))]
