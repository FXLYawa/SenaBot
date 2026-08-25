from collections.abc import Iterable

from .models import (
    MemoryItem,
    MemoryRecallContext,
    MemoryRetrievalCandidate,
    MemoryScopeKind,
)


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


class SimpleMemoryRetriever:
    """基于内存快照和 Scope 过滤的占位检索器。

    该实现只用于本地测试和 MVP 编排验证；它接收 query embedding，
    但不计算语义相关性，也不代表正式 Data 层检索能力。
    """

    def __init__(
        self,
        items: Iterable[MemoryItem] = (),
    ) -> None:
        self._items = tuple(items)

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]:
        """按 Scope 过滤内存快照并包装为零分候选。"""
        return [
            MemoryRetrievalCandidate(
                memory=item,
                score=0.0,
            )
            for item in self._items
            if is_scope_accessible(item, context)
        ]
