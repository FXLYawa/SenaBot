from datetime import datetime, timezone

import pytest

from core.memory.errors import MemoryPersistenceError
from core.memory.models import Memory, MemoryQueryCriteria
from core.memory.repository import FileMemoryRepository


def memory(content: str = "用户喜欢跑步") -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(
        memory_id="memory-001",
        content=content,
        created_at=now,
        updated_at=now,
        operation_id="operation-001",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
        source_event_id="event-001",
        metadata={"source": "test"},
    )


def criteria() -> MemoryQueryCriteria:
    return MemoryQueryCriteria(
        query_text="",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
    )


@pytest.mark.asyncio
async def test_update_replaces_persisted_memory(tmp_path) -> None:
    repository = FileMemoryRepository(tmp_path / "memories.json")
    original = memory()
    await repository.save(original)
    updated = Memory(
        memory_id=original.memory_id,
        content="用户每周跑步三次",
        created_at=original.created_at,
        updated_at=datetime.now(timezone.utc),
        operation_id="operation-002",
        user_id=original.user_id,
        session_id=original.session_id,
        group_id=original.group_id,
        source_event_id="event-002",
        metadata={"source": "updated"},
    )

    result = await repository.update(updated)
    stored = await repository.query(criteria())

    assert result is updated
    assert stored == [updated]


@pytest.mark.asyncio
async def test_update_rejects_unknown_memory(tmp_path) -> None:
    repository = FileMemoryRepository(tmp_path / "memories.json")

    with pytest.raises(MemoryPersistenceError, match="未找到需要更新的记忆"):
        await repository.update(memory())


@pytest.mark.asyncio
async def test_delete_removes_persisted_memory(tmp_path) -> None:
    repository = FileMemoryRepository(tmp_path / "memories.json")
    await repository.save(memory())

    result = await repository.delete("memory-001")

    assert result is None
    assert await repository.query(criteria()) == []


@pytest.mark.asyncio
async def test_delete_rejects_unknown_memory(tmp_path) -> None:
    repository = FileMemoryRepository(tmp_path / "memories.json")

    with pytest.raises(MemoryPersistenceError, match="未找到需要删除的记忆"):
        await repository.delete("missing-memory")
