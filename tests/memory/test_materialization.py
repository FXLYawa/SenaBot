from dataclasses import fields
from datetime import datetime, timezone

import pytest

from core.memory.models import (
    Fact,
    MemoryCandidate,
    MemoryDomain,
    MemoryItem,
    MemoryMaterializationInput,
    MemoryPayload,
    MemoryScopeKind,
    MemoryScopeRef,
    MemoryWriteEnvelope,
    Provenance,
)
from core.memory.protocols import MemoryMaterializerProtocol


class FakeMemoryMaterializer:
    def __init__(self, payload: MemoryPayload) -> None:
        self.payload = payload
        self.received_input: MemoryMaterializationInput | None = None

    async def materialize(
        self,
        input_data: MemoryMaterializationInput,
    ) -> MemoryPayload:
        self.received_input = input_data
        return self.payload


def create_fact() -> Fact:
    return Fact(
        content="用户喜欢跑步",
        provenance=(Provenance("event", "event-001"),),
        recorded_at=datetime.now(timezone.utc),
    )


def create_item() -> MemoryItem:
    return MemoryItem(
        item_id="item-001",
        memory_space_id="space-001",
        scopes=frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    "user-001",
                )
            }
        ),
        payload=create_fact(),
    )


def test_materialization_input_defaults_to_no_related_items():
    input_data = MemoryMaterializationInput(
        candidate=MemoryCandidate(content="用户喜欢跑步"),
        provenance=(Provenance("event", "event-001"),),
        recorded_at=datetime.now(timezone.utc),
    )

    assert input_data.related_items == ()


def test_materialization_input_requires_provenance():
    with pytest.raises(ValueError, match="provenance must not be empty"):
        MemoryMaterializationInput(
            candidate=MemoryCandidate(content="用户喜欢跑步"),
            provenance=(),
            recorded_at=datetime.now(timezone.utc),
        )


@pytest.mark.asyncio
async def test_materializer_converts_candidate_to_typed_payload():
    payload = create_fact()
    materializer: MemoryMaterializerProtocol = FakeMemoryMaterializer(
        payload
    )
    input_data = MemoryMaterializationInput(
        candidate=MemoryCandidate(content="用户喜欢跑步"),
        provenance=(Provenance("event", "event-001"),),
        recorded_at=datetime.now(timezone.utc),
    )

    result = await materializer.materialize(input_data)

    assert result is payload
    assert result.DOMAIN is MemoryDomain.FACT


def test_write_envelope_keeps_operation_id_outside_memory_item():
    item = create_item()
    envelope = MemoryWriteEnvelope(
        operation_id="operation-001",
        item=item,
    )

    assert envelope.item is item
    assert envelope.operation_id == "operation-001"
    assert "operation_id" not in {
        field.name
        for field in fields(MemoryItem)
    }


def test_write_envelope_requires_operation_id():
    with pytest.raises(ValueError, match="operation_id must not be blank"):
        MemoryWriteEnvelope(
            operation_id=" ",
            item=create_item(),
        )
