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
    判断记忆的长期归属是否命中当前召回主体。

    GLOBAL 记忆始终可以进入粗候选集；其他记忆只需有一个归属
    Scope 与当前上下文匹配。这里不判断语义相关性、敏感度或是否
    适合向当前参与者披露。
    """

    has_global_scope = any(
        scope.kind is MemoryScopeKind.GLOBAL
        for scope in item.scopes
    )
    if has_global_scope:
        return True

    return not item.scopes.isdisjoint(context.scopes)


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
        """到向量数据库中检索对应向量"""

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
