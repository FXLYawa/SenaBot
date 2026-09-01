from datetime import datetime, timedelta, timezone

import pytest

from core.memory.change_plan import (
    AddMemoryItem,
    EndFactValidity,
    MemoryChangePlan,
    NoMemoryChange,
    SupersedeMemoryItem,
    validate_memory_change_plan,
)
from core.memory.models import (
    Experience,
    Fact,
    Knowledge,
    MemoryItem,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
    Understanding,
)


RECORDED_AT = datetime(2026, 8, 25, tzinfo=timezone.utc)
PROVENANCE = (Provenance("event", "event-001"),)


def create_item(item_id: str, payload) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        memory_space_id="space-001",
        scopes=frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    "user-001",
                )
            }
        ),
        payload=payload,
    )


def create_fact(*, valid_from: datetime | None = None) -> Fact:
    return Fact(
        content="用户喜欢跑步",
        provenance=PROVENANCE,
        recorded_at=RECORDED_AT,
        valid_from=valid_from,
    )


def create_understanding(content: str = "用户注重健康") -> Understanding:
    return Understanding(
        content=content,
        provenance=PROVENANCE,
        evidence_item_ids=("evidence-001",),
        recorded_at=RECORDED_AT,
    )


def create_knowledge(content: str = "运动有助于健康") -> Knowledge:
    return Knowledge(
        content=content,
        provenance=PROVENANCE,
        recorded_at=RECORDED_AT,
    )


def create_experience() -> Experience:
    return Experience(
        summary="用户参加了马拉松",
        provenance=PROVENANCE,
        participants=(),
        occurred_from=None,
        occurred_to=None,
        recorded_at=RECORDED_AT,
    )


def test_change_plan_requires_operations():
    with pytest.raises(ValueError, match="must not be empty"):
        MemoryChangePlan(operations=())


def test_no_change_must_not_be_combined_with_other_operations():
    with pytest.raises(ValueError, match="cannot be combined"):
        MemoryChangePlan(
            operations=(
                NoMemoryChange(reason="已有记忆覆盖"),
                AddMemoryItem(payload=create_fact()),
            )
        )


def test_no_change_accepts_a_non_blank_reason():
    plan = MemoryChangePlan(
        operations=(NoMemoryChange(reason="已有记忆覆盖"),)
    )

    validate_memory_change_plan(plan, ())


def test_no_change_rejects_blank_reason():
    with pytest.raises(ValueError, match="reason must not be blank"):
        NoMemoryChange(reason=" ")


@pytest.mark.parametrize(
    "operation_factory",
    [
        lambda: EndFactValidity(" ", RECORDED_AT),
        lambda: SupersedeMemoryItem(" ", create_understanding()),
    ],
)
def test_targeted_operations_reject_blank_target_id(
    operation_factory,
):
    with pytest.raises(ValueError, match="target_item_id must not be blank"):
        operation_factory()


def test_end_fact_validity_requires_datetime():
    with pytest.raises(ValueError, match="valid_to must be a datetime"):
        EndFactValidity("item-001", "2026-08-25")  # type: ignore[arg-type]


def test_fact_can_end_and_add_a_replacement_fact():
    old_fact = create_item(
        "fact-001",
        create_fact(valid_from=RECORDED_AT - timedelta(days=10)),
    )
    plan = MemoryChangePlan(
        operations=(
            EndFactValidity("fact-001", RECORDED_AT),
            AddMemoryItem(
                payload=Fact(
                    content="用户现在不喜欢跑步",
                    provenance=PROVENANCE,
                    recorded_at=RECORDED_AT,
                )
            ),
        )
    )

    validate_memory_change_plan(plan, (old_fact,))


def test_targeted_operation_requires_related_item():
    plan = MemoryChangePlan(
        operations=(EndFactValidity("missing-item", RECORDED_AT),)
    )

    with pytest.raises(ValueError, match="must reference a related item"):
        validate_memory_change_plan(plan, ())


def test_end_fact_validity_rejects_non_fact_target():
    experience = create_item("experience-001", create_experience())
    plan = MemoryChangePlan(
        operations=(
            EndFactValidity("experience-001", RECORDED_AT),
        )
    )

    with pytest.raises(ValueError, match="target must be a Fact"):
        validate_memory_change_plan(plan, (experience,))


def test_end_fact_validity_rejects_time_before_valid_from():
    fact = create_item(
        "fact-001",
        create_fact(valid_from=RECORDED_AT),
    )
    plan = MemoryChangePlan(
        operations=(
            EndFactValidity(
                "fact-001",
                RECORDED_AT - timedelta(seconds=1),
            ),
        )
    )

    with pytest.raises(ValueError, match="must not precede"):
        validate_memory_change_plan(plan, (fact,))


@pytest.mark.parametrize(
    ("old_payload", "replacement"),
    [
        (
            create_understanding(),
            create_understanding("用户更偏好户外运动"),
        ),
        (
            create_knowledge(),
            create_knowledge("规律运动有助于健康"),
        ),
    ],
)
def test_understanding_and_knowledge_can_be_superseded(
    old_payload,
    replacement,
):
    target = create_item("item-001", old_payload)
    plan = MemoryChangePlan(
        operations=(
            SupersedeMemoryItem("item-001", replacement),
        )
    )

    validate_memory_change_plan(plan, (target,))


def test_experience_cannot_be_superseded():
    target = create_item("experience-001", create_experience())
    plan = MemoryChangePlan(
        operations=(
            SupersedeMemoryItem(
                "experience-001",
                create_understanding(),
            ),
        )
    )

    with pytest.raises(
        ValueError,
        match="target must be an Understanding or Knowledge",
    ):
        validate_memory_change_plan(plan, (target,))


def test_supersede_requires_same_domain():
    target = create_item("understanding-001", create_understanding())
    plan = MemoryChangePlan(
        operations=(
            SupersedeMemoryItem(
                "understanding-001",
                create_knowledge(),
            ),
        )
    )

    with pytest.raises(ValueError, match="same domain"):
        validate_memory_change_plan(plan, (target,))


def test_change_plan_rejects_duplicate_target_operations():
    with pytest.raises(ValueError, match="same target more than once"):
        MemoryChangePlan(
            operations=(
                EndFactValidity("fact-001", RECORDED_AT),
                EndFactValidity(
                    "fact-001",
                    RECORDED_AT + timedelta(seconds=1),
                ),
            )
        )
