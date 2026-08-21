from .models import (
    MemoryQueryCriteria,
    MemoryRetrievalCandidate,
)
from .protocols import MemoryRepositoryProtocol


class SimpleMemoryRetriever:
    """MVP 阶段的简单长期记忆检索器。"""

    def __init__(
        self,
        repository: MemoryRepositoryProtocol,
    ) -> None:
        self._repository = repository

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        user_id: str,
        session_id: str,
        group_id: str,
    ) -> list[MemoryRetrievalCandidate]:
        # MVP 仅按 scope 获取候选，后续替换为真实向量检索。
        criteria = MemoryQueryCriteria(
            query_text="",
            user_id=user_id,
            session_id=session_id,
            group_id=group_id,
        )
        # 简单占位实现，暂不根据 query_embedding 计算相关性分数。
        memories = await self._repository.query(criteria)

        return [
            MemoryRetrievalCandidate(
                memory=memory,
                score=0.0,
            )
            for memory in memories
        ]
