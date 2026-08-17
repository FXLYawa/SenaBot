from datetime import datetime, timezone

import pytest

from core.memory.models import (
    Memory,
    MemoryCandidate,
    MemoryQueryCriteria,
    MemoryUpdateAction,
    MemoryUpdateDecision,
    MemoryUpdateInput,
)
from core.memory.repository import FileMemoryRepository
from core.memory.service import MemoryService


class RecordingRepository:
    def __init__(self, memories: list[Memory] | None = None) -> None:
        self.memories = list(memories or [])
        self.criteria: MemoryQueryCriteria | None = None
        self.saved: list[Memory] = []
        self.updated: list[Memory] = []
        self.deleted: list[str] = []

    async def query(self, criteria: MemoryQueryCriteria) -> list[Memory]:
        self.criteria = criteria
        return list(self.memories)

    async def save(self, memory: Memory) -> Memory:
        self.saved.append(memory)
        return memory

    async def update(self, memory: Memory) -> Memory:
        self.updated.append(memory)
        return memory

    async def delete(self, memory_id: str) -> None:
        self.deleted.append(memory_id)


class FixedUpdater:
    def __init__(self, decision: MemoryUpdateDecision) -> None:
        self.decision = decision
        self.candidate: MemoryCandidate | None = None
        self.existing_memories: list[Memory] | None = None

    async def decide(
        self,
        candidate: MemoryCandidate,
        existing_memories: list[Memory],
    ) -> MemoryUpdateDecision:
        self.candidate = candidate
        self.existing_memories = existing_memories
        return self.decision


def update_input(candidate: MemoryCandidate | None = None) -> MemoryUpdateInput:
    return MemoryUpdateInput(
        candidate=candidate or MemoryCandidate(
            content="用户每周跑步三次",
            metadata={"candidate": "new", "shared": "candidate"},
        ),
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
        source_event_id="event-002",
        operation_id="operation-002",
    )


def existing_memory() -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(
        memory_id="memory-001",
        content="用户喜欢跑步",
        created_at=now,
        updated_at=now,
        operation_id="operation-001",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
        source_event_id="event-001",
        metadata={"existing": "old", "shared": "existing"},
    )


@pytest.mark.asyncio
async def test_review_and_update_adds_memory() -> None:
    input_data = update_input()
    decision = MemoryUpdateDecision(
        action=MemoryUpdateAction.ADD,
        candidate=input_data.candidate,
        content="用户每周跑步三次",
    )
    repository = RecordingRepository()
    updater = FixedUpdater(decision)
    service = MemoryService(repository=repository, updater=updater)

    result = await service.review_and_update(input_data)

    assert result is decision
    assert updater.candidate is input_data.candidate
    assert updater.existing_memories == []
    assert repository.criteria == MemoryQueryCriteria(
        query_text="",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
    )
    assert len(repository.saved) == 1
    saved = repository.saved[0]
    assert saved.content == "用户每周跑步三次"
    assert saved.operation_id == "operation-002"
    assert saved.source_event_id == "event-002"
    assert saved.metadata == input_data.candidate.metadata
    assert saved.metadata is not input_data.candidate.metadata


@pytest.mark.asyncio
async def test_review_and_update_updates_memory_and_merges_metadata() -> None:
    target = existing_memory()
    input_data = update_input()
    decision = MemoryUpdateDecision(
        action=MemoryUpdateAction.UPDATE,
        candidate=input_data.candidate,
        target_memory_id=target.memory_id,
        content="用户每周跑步三次",
    )
    repository = RecordingRepository([target])
    updater = FixedUpdater(decision)
    service = MemoryService(repository=repository, updater=updater)

    result = await service.review_and_update(input_data)

    assert result is decision
    assert updater.existing_memories == [target]
    assert len(repository.updated) == 1
    updated = repository.updated[0]
    assert updated.memory_id == target.memory_id
    assert updated.created_at == target.created_at
    assert updated.updated_at >= target.updated_at
    assert updated.content == "用户每周跑步三次"
    assert updated.metadata == {
        "existing": "old",
        "candidate": "new",
        "shared": "candidate",
    }


@pytest.mark.asyncio
async def test_review_and_update_deletes_memory() -> None:
    target = existing_memory()
    input_data = update_input()
    decision = MemoryUpdateDecision(
        action=MemoryUpdateAction.DELETE,
        candidate=input_data.candidate,
        target_memory_id=target.memory_id,
    )
    repository = RecordingRepository([target])
    service = MemoryService(
        repository=repository,
        updater=FixedUpdater(decision),
    )

    result = await service.review_and_update(input_data)

    assert result is decision
    assert repository.deleted == [target.memory_id]
    assert repository.saved == []
    assert repository.updated == []


@pytest.mark.asyncio
async def test_review_and_update_none_does_not_persist() -> None:
    target = existing_memory()
    input_data = update_input()
    decision = MemoryUpdateDecision(
        action=MemoryUpdateAction.NONE,
        candidate=input_data.candidate,
    )
    repository = RecordingRepository([target])
    service = MemoryService(
        repository=repository,
        updater=FixedUpdater(decision),
    )

    result = await service.review_and_update(input_data)

    assert result is decision
    assert repository.saved == []
    assert repository.updated == []
    assert repository.deleted == []


@pytest.mark.asyncio
async def test_review_and_update_requires_configured_updater() -> None:
    service = MemoryService(repository=RecordingRepository())

    with pytest.raises(RuntimeError, match="memory updater is not configured"):
        await service.review_and_update(update_input())


@pytest.mark.asyncio
async def test_review_and_update_rejects_missing_update_target() -> None:
    input_data = update_input()
    decision = MemoryUpdateDecision(
        action=MemoryUpdateAction.UPDATE,
        candidate=input_data.candidate,
        target_memory_id="missing-memory",
        content="更新内容",
    )
    service = MemoryService(
        repository=RecordingRepository(),
        updater=FixedUpdater(decision),
    )

    with pytest.raises(ValueError, match="target memory not found for UPDATE"):
        await service.review_and_update(input_data)


@pytest.mark.asyncio
async def test_review_and_update_loads_all_memories_in_same_scope(tmp_path) -> None:
    repository = FileMemoryRepository(tmp_path / "memories.json")
    same_scope = existing_memory()
    other_scope = Memory(
        memory_id="memory-002",
        content="用户喜欢游泳",
        created_at=same_scope.created_at,
        updated_at=same_scope.updated_at,
        operation_id="operation-other",
        user_id="user-other",
        session_id=same_scope.session_id,
        group_id=same_scope.group_id,
        source_event_id="event-other",
        metadata={},
    )
    await repository.save(same_scope)
    await repository.save(other_scope)
    candidate = MemoryCandidate(content="用户不喜欢跑步")
    input_data = update_input(candidate)
    decision = MemoryUpdateDecision(
        action=MemoryUpdateAction.NONE,
        candidate=candidate,
    )
    updater = FixedUpdater(decision)
    service = MemoryService(repository=repository, updater=updater)

    await service.review_and_update(input_data)

    assert updater.existing_memories == [same_scope]
