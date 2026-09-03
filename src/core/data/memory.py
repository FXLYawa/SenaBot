"""Memory 模块所需的 MVP Data 适配器。"""

from __future__ import annotations

from datetime import datetime

from core.data.store import InMemoryDataStore
from core.memory.models import (
    MemoryItem,
    MemoryRecallContext,
    MemoryRetrievalCandidate,
    MemorySupersedeResult,
    MemoryWriteEnvelope,
)
from core.memory.protocols import MemoryRetrieverProtocol


class InMemoryMemoryRepository:
    """MemoryRepositoryProtocol 的进程内 MVP 实现。"""

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def add(
        self,
        envelope: MemoryWriteEnvelope,
    ) -> MemoryItem:
        """保存新增 MemoryItem。"""

        return self._store.add_memory(envelope.item)

    async def end_fact_validity(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        valid_to: datetime,
    ) -> MemoryItem:
        """结束旧 Fact 的有效期。"""

        return self._store.end_fact_validity(target_item_id, valid_to)

    async def supersede(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        replacement: MemoryWriteEnvelope,
    ) -> MemorySupersedeResult:
        """保存替代版本并返回新旧 MemoryItem。"""

        previous = self._store.get_memory_item(target_item_id)
        replacement_item = self._store.add_memory(replacement.item)
        return MemorySupersedeResult(
            previous_item=previous,
            replacement_item=replacement_item,
        )


class InMemoryMemoryRetriever:
    """按 Memory Space 和 Scope 从进程内 Store 召回候选。"""

    def __init__(
        self,
        store: InMemoryDataStore,
        memory_space_id: str,
    ) -> None:
        self._store = store
        self._memory_space_id = memory_space_id

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]:
        """返回当前 Memory Space 内命中 Scope 的全部候选。"""

        return [
            MemoryRetrievalCandidate(memory=item, score=0.0)
            for item in self._store.memory_items(self._memory_space_id)
            if context.matches(item)
        ]


class InMemoryMemorySpaceRouter:
    """MemorySpaceRouterProtocol 的进程内 MVP 实现。"""

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    def for_space(
        self,
        memory_space_id: str,
    ) -> MemoryRetrieverProtocol:
        """为指定 Memory Space 创建 Retriever。"""

        return InMemoryMemoryRetriever(self._store, memory_space_id)
