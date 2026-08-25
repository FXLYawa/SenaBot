from .models import (
    MemoryItem,
    MemoryRecallContext,
    MemoryQueryCriteria,
    MemoryRetrievalCandidate,
    MemoryScopeKind,
)
from .protocols import MemoryRepositoryProtocol


def is_scope_accessible(
    item: MemoryItem,
    context: MemoryRecallContext,
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

def _get_required_scope_id(
            context: MemoryRecallContext,
            kind: MemoryScopeKind,
    ) -> str:

        """临时转换兼容函数"""
        matching_ids = [
            scope.scope_id
            for scope in context.scopes
            if scope.kind is kind
        ]

        if len(matching_ids) != 1:
            raise ValueError(
                f"legacy retriever requires exactly one "
                f"{kind.value} scope"
            )

        scope_id = matching_ids[0]

        if scope_id is None:
            raise ValueError(
                f"legacy retriever requires a non-null "
                f"{kind.value} scope"
            )

        return scope_id

class SimpleMemoryRetriever:
    """MVP 阶段的简单长期记忆检索器。"""

    def __init__(
        self,
        repository: MemoryRepositoryProtocol,
    ) -> None:
        self._repository = repository

    # 兼容旧 FileMemoryRepository。
    # Repository 迁移到 MemoryItem 后删除此转换。
    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]:
        # MVP 仅按 scope 获取候选，后续替换为真实向量检索。
        criteria = MemoryQueryCriteria(
            query_text="",
            user_id=_get_required_scope_id(
                context,
                MemoryScopeKind.USER,
            ),
            session_id=_get_required_scope_id(
                context,
                MemoryScopeKind.SESSION,
            ),
            group_id=_get_required_scope_id(
                context,
                MemoryScopeKind.GROUP,
            ),
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
