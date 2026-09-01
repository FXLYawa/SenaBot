from collections.abc import Iterable, Mapping

from .models import (
    MemoryItem,
    MemoryRecallContext,
    MemoryRetrievalCandidate,
)
from .protocols import MemoryRetrieverProtocol


class SimpleMemoryRetriever:
    """基于单个 Memory Space 内存快照和 Scope 过滤的占位检索器。

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
        """还没有具体实现。"""
        return [
            MemoryRetrievalCandidate(
                memory=item,
                score=0.0,
            )
            for item in self._items
            if context.matches(item)
        ]


class SimpleMemorySpaceRouter:
    """MVP 用的 Memory Space 路由壳。

    真实向量库实现可以把 memory_space_id 映射到 namespace、tenant、
    partition 或带 tenant 过滤的 collection。这里先映射到一个
    已经代表单个 Memory Space 的 retriever。
    """

    def __init__(
        self,
        spaces: Mapping[str, MemoryRetrieverProtocol],
    ) -> None:
        self._spaces = dict(spaces)

    def for_space(
        self,
        memory_space_id: str,
    ) -> MemoryRetrieverProtocol:
        try:
            return self._spaces[memory_space_id]
        except KeyError as error:
            raise ValueError(
                f"memory space not found: {memory_space_id}"
            ) from error
