from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timedelta, timezone

import pytest

from core.memory.models import (
    Experience,
    Fact,
    Knowledge,
    MemoryDomain,
    MemoryItem,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
    Understanding,
)


def create_payloads():
    recorded_at = datetime.now(timezone.utc)
    provenance = (Provenance("event", "event-001"),)

    return [
        (
            Fact(
                content="用户喜欢跑步",
                provenance=provenance,
                recorded_at=recorded_at,
            ),
            MemoryDomain.FACT,
        ),
        (
            Experience(
                summary="用户和 Sena 一起制定了跑步计划",
                provenance=provenance,
                participants=(),
                occurred_from=None,
                occurred_to=None,
                recorded_at=recorded_at,
            ),
            MemoryDomain.EXPERIENCE,
        ),
        (
            Understanding(
                content="用户更容易坚持有计划的运动",
                provenance=provenance,
                evidence_item_ids=("item-001",),
                recorded_at=recorded_at,
            ),
            MemoryDomain.UNDERSTANDING,
        ),
        (
            Knowledge(
                content="循序渐进可以降低运动损伤风险",
                provenance=provenance,
                recorded_at=recorded_at,
            ),
            MemoryDomain.KNOWLEDGE,
        ),
    ]


@pytest.mark.parametrize(("payload", "expected_domain"), create_payloads())
def test_memory_item_domain_is_derived_from_payload(
    payload,
    expected_domain,
):
    item = MemoryItem(
        item_id="item-001",
        memory_space_id="space-001",
        scopes=frozenset(
            {
                MemoryScopeRef(
                    kind=MemoryScopeKind.USER,
                    scope_id="user-001",
                )
            }
        ),
        payload=payload,
    )

    assert item.domain is expected_domain


def test_memory_item_domain_is_not_a_stored_field():
    assert "domain" not in {
        field.name
        for field in fields(MemoryItem)
    }


def test_memory_domains_are_distinct():
    assert MemoryDomain.FACT is not MemoryDomain.EXPERIENCE
    assert MemoryDomain.UNDERSTANDING is not MemoryDomain.KNOWLEDGE


@pytest.mark.parametrize(("payload", "expected_domain"), create_payloads())
def test_memory_payloads_are_immutable(payload, expected_domain):
    with pytest.raises(FrozenInstanceError):
        payload.recorded_at = datetime.now(timezone.utc)


def test_fact_rejects_reversed_validity_range():
    current_time = datetime.now(timezone.utc)

    with pytest.raises(
        ValueError,
        match="fact validity end must not precede start",
    ):
        Fact(
            content="用户喜欢跑步",
            provenance=(Provenance("event", "event-001"),),
            recorded_at=current_time,
            valid_from=current_time,
            valid_to=current_time - timedelta(days=1),
        )


def test_experience_requires_summary_and_valid_occurrence_range():
    current_time = datetime.now(timezone.utc)
    provenance = (Provenance("event", "event-001"),)

    with pytest.raises(
        ValueError,
        match="experience summary must not be blank",
    ):
        Experience(
            summary="  ",
            provenance=provenance,
            participants=(),
            occurred_from=None,
            occurred_to=None,
            recorded_at=current_time,
        )

    with pytest.raises(
        ValueError,
        match="experience occurrence end must not precede start",
    ):
        Experience(
            summary="用户参加了跑步活动",
            provenance=provenance,
            participants=(),
            occurred_from=current_time,
            occurred_to=current_time - timedelta(hours=1),
            recorded_at=current_time,
        )


def test_understanding_requires_evidence():
    with pytest.raises(
        ValueError,
        match="evidence_item_ids must not be empty",
    ):
        Understanding(
            content="用户喜欢有计划的运动",
            provenance=(Provenance("event", "event-001"),),
            evidence_item_ids=(),
            recorded_at=datetime.now(timezone.utc),
        )


def test_payload_requires_non_empty_content_and_provenance():
    current_time = datetime.now(timezone.utc)

    with pytest.raises(ValueError, match="fact content must not be blank"):
        Fact(
            content=" ",
            provenance=(Provenance("event", "event-001"),),
            recorded_at=current_time,
        )

    with pytest.raises(ValueError, match="provenance must not be empty"):
        Knowledge(
            content="有效知识",
            provenance=(),
            recorded_at=current_time,
        )


def test_scope_ref_enforces_scope_id_semantics():
    with pytest.raises(ValueError, match="global scope_id must be None"):
        MemoryScopeRef(
            kind=MemoryScopeKind.GLOBAL,
            scope_id="global-001",
        )

    with pytest.raises(ValueError, match="user scope_id must not be blank"):
        MemoryScopeRef(
            kind=MemoryScopeKind.USER,
            scope_id=" ",
        )


def test_memory_item_requires_valid_scope_combination():
    payload = create_payloads()[0][0]

    with pytest.raises(ValueError, match="memory scopes must not be empty"):
        MemoryItem(
            item_id="item-001",
            memory_space_id="space-001",
            scopes=frozenset(),
            payload=payload,
        )

    with pytest.raises(
        ValueError,
        match="global scope cannot be combined with other scopes",
    ):
        MemoryItem(
            item_id="item-001",
            memory_space_id="space-001",
            scopes=frozenset(
                {
                    MemoryScopeRef(MemoryScopeKind.GLOBAL, None),
                    MemoryScopeRef(MemoryScopeKind.USER, "user-001"),
                }
            ),
            payload=payload,
        )
