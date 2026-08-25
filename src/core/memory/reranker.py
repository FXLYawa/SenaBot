from .models import MemoryRetrievalCandidate


class SimpleMemoryReranker:
    """MVP 阶段的简单重排实现。

    不调用真实 Rerank 模型，仅按检索阶段已有 score 降序排列。
    """

    async def rerank(
        self,
        query: str,
        candidates: list[MemoryRetrievalCandidate],
    ) -> list[MemoryRetrievalCandidate]:
        """对检索出的多个结果再做一次重排序"""

        return sorted(
            candidates,
            key=lambda candidate: candidate.score,
            reverse=True,
        )
