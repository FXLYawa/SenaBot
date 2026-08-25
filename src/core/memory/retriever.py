from .models import (
    MemoryItem,
    MemoryQueryContext,
    MemoryQueryCriteria,
    MemoryRetrievalCandidate,
    MemoryScopeKind,
)
from .protocols import MemoryRepositoryProtocol


def is_scope_accessible(
    item: MemoryItem,
    context: MemoryQueryContext,
) -> bool:
    """
    当前仅作为MVP实现,review时可以跳过
    判断一条记忆是否允许在当前作用域参与召回。
    后续建立数据库后实现变为根据传入记忆的Scope检索相应区域的MemoryItem
    """

    has_global_scope = any(
        scope.kind is MemoryScopeKind.GLOBAL
        for scope in item.scopes
    )
    if has_global_scope:
        return True

    return item.scopes.issubset(context.scopes)


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
