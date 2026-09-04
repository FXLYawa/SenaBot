"""Data 层对 Memory Repository 和 Retriever 协议的 MVP 支撑测试。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.data import (
    InMemoryDataStore,
    InMemoryMemoryRepository,
    InMemoryMemorySpaceRouter,
)
from core.memory.models import (
    Fact,
    MemoryItem,
    MemoryRecallContext,
    MemoryScopeKind,
    MemoryScopeRef,
    MemoryWriteEnvelope,
    Provenance,
)


RECORDED_AT = datetime(2026, 9, 3, tzinfo=UTC)
PROVENANCE = (Provenance("event", "event_1"),)


def _fact(content: str = "用户喜欢咖啡") -> Fact:
    return Fact(
        content=content,
        provenance=PROVENANCE,
        recorded_at=RECORDED_AT,
    )


def _item(
    item_id: str,
    *,
    memory_space_id: str = "sena",
    user_id: str = "user_1",
) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        memory_space_id=memory_space_id,
        scopes=frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    user_id,
                )
            }
        ),
        payload=_fact(),
    )


@pytest.mark.asyncio
async def test_repository_add_can_be_retrieved_from_same_memory_space():
    store = InMemoryDataStore()
    repository = InMemoryMemoryRepository(store)
    router = InMemoryMemorySpaceRouter(store)
    item = _item("memory_1")

    added = await repository.add(
        MemoryWriteEnvelope(
            operation_id="operation_1",
            item=item,
        )
    )
    candidates = await router.for_space("sena").retrieve(
        [0.0],
        context=MemoryRecallContext(
            scopes=frozenset(
                {
                    MemoryScopeRef(
                        MemoryScopeKind.USER,
                        "user_1",
                    )
                }
            )
        ),
    )

    assert added is item
    assert [candidate.memory for candidate in candidates] == [item]


@pytest.mark.asyncio
async def test_retriever_is_isolated_by_memory_space():
    store = InMemoryDataStore()
    repository = InMemoryMemoryRepository(store)
    router = InMemoryMemorySpaceRouter(store)
    item = _item("memory_1", memory_space_id="sena")

    await repository.add(MemoryWriteEnvelope("operation_1", item))

    candidates = await router.for_space("other_bot").retrieve(
        [0.0],
        context=MemoryRecallContext(
            scopes=frozenset(
                {
                    MemoryScopeRef(
                        MemoryScopeKind.USER,
                        "user_1",
                    )
                }
            )
        ),
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_repository_can_end_fact_validity():
    store = InMemoryDataStore()
    repository = InMemoryMemoryRepository(store)
    item = _item("memory_1")
    valid_to = datetime(2026, 9, 4, tzinfo=UTC)

    await repository.add(MemoryWriteEnvelope("operation_1", item))
    updated = await repository.end_fact_validity(
        operation_id="operation_2",
        target_item_id="memory_1",
        valid_to=valid_to,
    )

    assert isinstance(updated.payload, Fact)
    assert updated.payload.valid_to == valid_to
    assert store.get_memory_item("memory_1") == updated
