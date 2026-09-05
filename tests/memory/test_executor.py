from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core.memory.change_plan import (
    AddMemoryItem,
    EndFactValidity,
    MemoryChangePlan,
    NoMemoryChange,
    SupersedeMemoryItem,
)
from core.memory.executor import (
    MemoryChangeExecutionInput,
    MemoryChangeExecutor,
)
from core.memory.models import (
    Fact,
    MemoryIndexEmbedding,
    MemoryItem,
    MemoryScopeKind,
    MemoryScopeRef,
    MemorySupersedeResult,
    MemoryWriteEnvelope,
    Provenance,
    Understanding,
)


RECORDED_AT = datetime(2026, 8, 25, tzinfo=timezone.utc)
USER_SCOPE = MemoryScopeRef(MemoryScopeKind.USER, "user-001")
SCOPES = frozenset({USER_SCOPE})
PROVENANCE = (Provenance("event", "event-001"),)


def create_fact(content: str = "用户喜欢跑步") -> Fact:
    return Fact(
        content=content,
        provenance=PROVENANCE,
        recorded_at=RECORDED_AT,
    )


def create_item(item_id: str, payload) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        memory_space_id="space-001",
        scopes=SCOPES,
        payload=payload,
    )


def create_input(
    plan: MemoryChangePlan,
    *,
    related_items: tuple[MemoryItem, ...] = (),
) -> MemoryChangeExecutionInput:
    return MemoryChangeExecutionInput(
        plan=plan,
        related_items=related_items,
        memory_space_id="space-001",
        scopes=SCOPES,
        operation_id="operation-001",
    )


class RecordingRepository:
    def __init__(self, related_items: tuple[MemoryItem, ...] = ()) -> None:
        self.items = {item.item_id: item for item in related_items}
        self.calls: list[tuple] = []

    async def add(self, envelope: MemoryWriteEnvelope) -> MemoryItem:
        self.calls.append(("add", envelope))
        self.items[envelope.item.item_id] = envelope.item
        return envelope.item

    async def end_fact_validity(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        valid_to: datetime,
    ) -> MemoryItem:
        self.calls.append(
            (
                "end_fact_validity",
                operation_id,
                target_item_id,
                valid_to,
            )
        )
        target = self.items[target_item_id]
        updated = replace(
            target,
            payload=replace(target.payload, valid_to=valid_to),
        )
        self.items[target_item_id] = updated
        return updated

    async def supersede(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        replacement: MemoryWriteEnvelope,
    ) -> MemorySupersedeResult:
        self.calls.append(
            (
                "supersede",
                operation_id,
                target_item_id,
                replacement,
            )
        )
        return MemorySupersedeResult(
            previous_item=self.items[target_item_id],
            replacement_item=replacement.item,
        )


class RecordingIndexer:
    async def embed_item(self, item: MemoryItem) -> MemoryIndexEmbedding:
        return MemoryIndexEmbedding((1.0, 0.0), "test-model")


@pytest.mark.asyncio
async def test_add_builds_envelope_and_calls_repository():
    repository = RecordingRepository()
    payload = create_fact()
    executor = MemoryChangeExecutor(
        repository,
        lambda: "item-001",
        indexer=RecordingIndexer(),
    )

    result = await executor.execute(
        create_input(
            MemoryChangePlan(
                operations=(AddMemoryItem(payload=payload),)
            )
        )
    )

    assert result.updated_items == ()
    assert result.added_items == (repository.items["item-001"],)
    _, envelope = repository.calls[0]
    assert envelope.operation_id == "operation-001"
    assert envelope.item.item_id == "item-001"
    assert envelope.item.memory_space_id == "space-001"
    assert envelope.item.scopes == SCOPES
    assert envelope.item.payload is payload
    assert envelope.embedding == MemoryIndexEmbedding((1.0, 0.0), "test-model")


@pytest.mark.asyncio
async def test_no_change_does_not_call_repository():
    repository = RecordingRepository()
    executor = MemoryChangeExecutor(
        repository,
        lambda: "unused-item-id",
        indexer=RecordingIndexer(),
    )
    plan = MemoryChangePlan(
        operations=(NoMemoryChange(reason="已有记忆覆盖"),)
    )

    result = await executor.execute(create_input(plan))

    assert result.added_items == ()
    assert result.updated_items == ()
    assert repository.calls == []


@pytest.mark.asyncio
async def test_end_fact_validity_calls_repository_port():
    target = create_item("fact-001", create_fact())
    repository = RecordingRepository((target,))
    executor = MemoryChangeExecutor(
        repository,
        lambda: "unused-item-id",
        indexer=RecordingIndexer(),
    )
    plan = MemoryChangePlan(
        operations=(EndFactValidity("fact-001", RECORDED_AT),)
    )

    result = await executor.execute(
        create_input(plan, related_items=(target,))
    )

    assert result.added_items == ()
    assert result.updated_items[0].payload.valid_to == RECORDED_AT
    assert repository.calls == [
        (
            "end_fact_validity",
            "operation-001",
            "fact-001",
            RECORDED_AT,
        )
    ]


@pytest.mark.asyncio
async def test_supersede_calls_repository_port_with_replacement():
    old_payload = Understanding(
        content="用户注重健康",
        provenance=PROVENANCE,
        evidence_item_ids=("evidence-001",),
        recorded_at=RECORDED_AT,
    )
    replacement = replace(
        old_payload,
        content="用户更偏好户外运动",
    )
    target = create_item("understanding-001", old_payload)
    repository = RecordingRepository((target,))
    executor = MemoryChangeExecutor(
        repository,
        lambda: "item-002",
        indexer=RecordingIndexer(),
    )
    plan = MemoryChangePlan(
        operations=(
            SupersedeMemoryItem("understanding-001", replacement),
        )
    )

    result = await executor.execute(
        create_input(plan, related_items=(target,))
    )

    assert result.updated_items == (target,)
    assert result.added_items[0].item_id == "item-002"
    assert result.added_items[0].payload is replacement
    call = repository.calls[0]
    assert call[:3] == (
        "supersede",
        "operation-001",
        "understanding-001",
    )
    assert call[3].item is result.added_items[0]


@pytest.mark.asyncio
async def test_executor_validates_targets_before_repository_call():
    repository = RecordingRepository()
    executor = MemoryChangeExecutor(
        repository,
        lambda: "unused-item-id",
        indexer=RecordingIndexer(),
    )
    plan = MemoryChangePlan(
        operations=(EndFactValidity("missing-item", RECORDED_AT),)
    )

    with pytest.raises(ValueError, match="must reference a related item"):
        await executor.execute(create_input(plan))

    assert repository.calls == []


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("memory_space_id", " ", "memory_space_id must not be blank"),
        ("scopes", frozenset(), "memory scopes must not be empty"),
        ("operation_id", " ", "operation_id must not be blank"),
    ],
)
def test_execution_input_rejects_invalid_context(
    field_name,
    value,
    message,
):
    values = {
        "plan": MemoryChangePlan(
            operations=(NoMemoryChange(reason="无需写入"),)
        ),
        "related_items": (),
        "memory_space_id": "space-001",
        "scopes": SCOPES,
        "operation_id": "operation-001",
    }
    values[field_name] = value

    with pytest.raises(ValueError, match=message):
        MemoryChangeExecutionInput(**values)


def test_execution_input_rejects_global_scope_combination():
    with pytest.raises(ValueError, match="global scope cannot be combined"):
        MemoryChangeExecutionInput(
            plan=MemoryChangePlan(
                operations=(NoMemoryChange(reason="无需写入"),)
            ),
            related_items=(),
            memory_space_id="space-001",
            scopes=frozenset(
                {
                    MemoryScopeRef(MemoryScopeKind.GLOBAL, None),
                    USER_SCOPE,
                }
            ),
            operation_id="operation-001",
        )
