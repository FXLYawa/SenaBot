"""SQLite Memory Repository 与 Retriever 的真实集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.data import SQLiteDatabase, SQLiteMemoryRepository, SQLiteMemorySpaceRouter
from core.embedding import EmbeddingRequest, EmbeddingResponse
from core.memory.models import (
    Fact, Knowledge, MemoryItem, MemoryRecallContext, MemoryScopeKind,
    MemoryScopeRef, MemoryWriteEnvelope, Provenance,
)


RECORDED_AT = datetime(2026, 9, 3, tzinfo=UTC)
PROVENANCE = (Provenance("event", "event_1"),)
USER_SCOPE = MemoryScopeRef(MemoryScopeKind.USER, "user_1")


class StubEmbeddingProvider:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        vectors = {
            "用户喜欢咖啡": (1.0, 0.0, 0.0),
            "用户喜欢茶": (0.0, 1.0, 0.0),
        }
        return EmbeddingResponse(vectors[request.text], "stub-embedding")

    async def close(self) -> None:
        pass


def _item(
    item_id: str,
    *,
    content: str = "用户喜欢咖啡",
    memory_space_id: str = "sena",
) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        memory_space_id=memory_space_id,
        scopes=frozenset({USER_SCOPE}),
        payload=Fact(content=content, provenance=PROVENANCE, recorded_at=RECORDED_AT),
    )


def _context(user_id: str = "user_1") -> MemoryRecallContext:
    return MemoryRecallContext(
        frozenset({MemoryScopeRef(MemoryScopeKind.USER, user_id)})
    )


@pytest.mark.asyncio
async def test_repository_persists_item_and_retriever_uses_vector_scope_and_space():
    with SQLiteDatabase(":memory:") as database:
        repository = SQLiteMemoryRepository(database, StubEmbeddingProvider())
        router = SQLiteMemorySpaceRouter(database)
        coffee = _item("memory_1")
        tea = _item("memory_2", content="用户喜欢茶")
        other_space = _item("memory_3", memory_space_id="other")

        for number, item in enumerate((coffee, tea, other_space), 1):
            await repository.add(MemoryWriteEnvelope(f"operation_{number}", item))

        candidates = await router.for_space("sena").retrieve(
            [1.0, 0.0, 0.0], context=_context()
        )
        hidden = await router.for_space("sena").retrieve(
            [1.0, 0.0, 0.0], context=_context("someone_else")
        )

        assert [value.memory for value in candidates] == [coffee, tea]
        assert candidates[0].score > candidates[1].score
        assert hidden == []
        provenance_row = database.connection.execute(
            "SELECT source_type, source_id FROM memory_provenances"
        ).fetchone()
        assert tuple(provenance_row) == ("event", "event_1")


@pytest.mark.asyncio
async def test_end_fact_validity_removes_fact_from_current_retrieval():
    with SQLiteDatabase(":memory:") as database:
        repository = SQLiteMemoryRepository(database, StubEmbeddingProvider())
        router = SQLiteMemorySpaceRouter(database)
        await repository.add(MemoryWriteEnvelope("operation_1", _item("memory_1")))

        updated = await repository.end_fact_validity(
            operation_id="operation_2",
            target_item_id="memory_1",
            valid_to=datetime(2026, 9, 4, tzinfo=UTC),
        )

        assert updated.payload.valid_to == datetime(2026, 9, 4, tzinfo=UTC)
        assert await router.for_space("sena").retrieve(
            [1.0, 0.0, 0.0], context=_context()
        ) == []


@pytest.mark.asyncio
async def test_supersede_is_atomic_and_only_retrieves_replacement():
    with SQLiteDatabase(":memory:") as database:
        repository = SQLiteMemoryRepository(database, StubEmbeddingProvider())
        router = SQLiteMemorySpaceRouter(database)
        previous = _item("memory_1")
        replacement = MemoryItem(
            "memory_2",
            "sena",
            frozenset({USER_SCOPE}),
            Knowledge("用户喜欢茶", PROVENANCE, RECORDED_AT),
        )
        await repository.add(MemoryWriteEnvelope("operation_1", previous))

        result = await repository.supersede(
            operation_id="operation_2",
            target_item_id=previous.item_id,
            replacement=MemoryWriteEnvelope("operation_2", replacement),
        )
        candidates = await router.for_space("sena").retrieve(
            [0.0, 1.0, 0.0], context=_context()
        )

        assert result.previous_item == previous
        assert result.replacement_item == replacement
        assert [value.memory for value in candidates] == [replacement]
        assert database.connection.execute(
            "SELECT operation_id FROM memory_replacements"
        ).fetchone()[0] == "operation_2"


@pytest.mark.asyncio
async def test_item_and_vector_can_be_retrieved_after_database_reopens():
    with TemporaryDirectory() as directory:
        path = Path(directory) / "sena.db"
        item = _item("memory_1")
        with SQLiteDatabase(path) as database:
            repository = SQLiteMemoryRepository(database, StubEmbeddingProvider())
            await repository.add(MemoryWriteEnvelope("operation_1", item))

        with SQLiteDatabase(path) as database:
            candidates = await SQLiteMemorySpaceRouter(database).for_space(
                "sena"
            ).retrieve([1.0, 0.0, 0.0], context=_context())

        assert [value.memory for value in candidates] == [item]
