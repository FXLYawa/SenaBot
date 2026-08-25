import json
from datetime import datetime, timezone

import pytest

from core.memory.change_plan import (
    AddMemoryItem,
    EndFactValidity,
    NoMemoryChange,
    SupersedeMemoryItem,
)
from core.memory.models import (
    Experience,
    Fact,
    Knowledge,
    MemoryItem,
    MemoryReviewInput,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
    Understanding,
)
from core.memory.reviewer import LLMMemoryReviewer


RECORDED_AT = datetime(2026, 8, 25, tzinfo=timezone.utc)
PROVENANCE = (Provenance("event", "event-001"),)


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt: str | None = None

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


def create_fact(
    content: str = "用户喜欢跑步",
    *,
    valid_from: datetime | None = None,
) -> Fact:
    return Fact(
        content=content,
        provenance=PROVENANCE,
        recorded_at=RECORDED_AT,
        valid_from=valid_from,
    )


def create_understanding(
    content: str = "用户喜欢户外运动",
) -> Understanding:
    return Understanding(
        content=content,
        provenance=PROVENANCE,
        evidence_item_ids=("evidence-001",),
        recorded_at=RECORDED_AT,
    )


def create_knowledge(
    content: str = "规律运动有助于健康",
) -> Knowledge:
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


def review_input(
    payload,
    *related_items: MemoryItem,
) -> MemoryReviewInput:
    return MemoryReviewInput(
        payload=payload,
        related_items=related_items,
    )


@pytest.mark.asyncio
async def test_reviewer_adds_new_fact():
    payload = create_fact()
    reviewer = LLMMemoryReviewer(FakeLLM('{"operations":[{"type":"add"}]}'))

    plan = await reviewer.review(review_input(payload))

    assert plan.operations == (AddMemoryItem(payload),)


@pytest.mark.asyncio
async def test_reviewer_ends_old_fact_and_adds_new_fact():
    valid_from = datetime(2026, 8, 20, tzinfo=timezone.utc)
    old_item = create_item("fact-001", create_fact())
    payload = create_fact("用户现在不喜欢跑步", valid_from=valid_from)
    reviewer = LLMMemoryReviewer(
        FakeLLM(
            json.dumps(
                {
                    "operations": [
                        {
                            "type": "end_fact_validity",
                            "target_item_id": "fact-001",
                        },
                        {"type": "add"},
                    ]
                }
            )
        )
    )

    plan = await reviewer.review(review_input(payload, old_item))

    assert plan.operations == (
        EndFactValidity("fact-001", valid_from),
        AddMemoryItem(payload),
    )


@pytest.mark.asyncio
async def test_reviewer_adds_experience():
    payload = create_experience()
    reviewer = LLMMemoryReviewer(FakeLLM('{"operations":[{"type":"add"}]}'))

    plan = await reviewer.review(review_input(payload))

    assert plan.operations == (AddMemoryItem(payload),)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload_factory",
    [create_understanding, create_knowledge],
)
async def test_reviewer_supersedes_same_domain_memory(payload_factory):
    old_payload = payload_factory("旧内容")
    new_payload = payload_factory("新内容")
    old_item = create_item("item-001", old_payload)
    reviewer = LLMMemoryReviewer(
        FakeLLM(
            '{"operations":['
            '{"type":"supersede","target_item_id":"item-001"}'
            ']}'
        )
    )

    plan = await reviewer.review(review_input(new_payload, old_item))

    assert plan.operations == (
        SupersedeMemoryItem("item-001", new_payload),
    )


@pytest.mark.asyncio
async def test_reviewer_returns_no_change():
    payload = create_fact()
    reviewer = LLMMemoryReviewer(
        FakeLLM(
            '{"operations":['
            '{"type":"no_change","reason":"已有记忆完整覆盖"}'
            ']}'
        )
    )

    plan = await reviewer.review(review_input(payload))

    assert plan.operations == (
        NoMemoryChange("已有记忆完整覆盖"),
    )


@pytest.mark.asyncio
async def test_reviewer_prompt_contains_payload_and_related_items():
    payload = create_fact("用户现在不喜欢跑步")
    old_item = create_item("fact-001", create_fact())
    llm = FakeLLM('{"operations":[{"type":"add"}]}')

    await LLMMemoryReviewer(llm).review(
        review_input(payload, old_item)
    )

    assert llm.prompt is not None
    assert "不得改写 Payload" in llm.prompt
    assert '"content": "用户现在不喜欢跑步"' in llm.prompt
    assert '"item_id": "fact-001"' in llm.prompt
    assert "Experience 只能 add 或 no_change" in llm.prompt


@pytest.mark.asyncio
async def test_reviewer_rejects_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        await LLMMemoryReviewer(FakeLLM("not-json")).review(
            review_input(create_fact())
        )


@pytest.mark.asyncio
async def test_reviewer_rejects_non_object_top_level():
    with pytest.raises(ValueError, match="must be a JSON object"):
        await LLMMemoryReviewer(FakeLLM("[]")).review(
            review_input(create_fact())
        )


@pytest.mark.asyncio
async def test_reviewer_requires_operations_list():
    with pytest.raises(ValueError, match="operations must be a list"):
        await LLMMemoryReviewer(FakeLLM('{"operations":{}}')).review(
            review_input(create_fact())
        )


@pytest.mark.asyncio
async def test_reviewer_rejects_invalid_operation_type():
    response = '{"operations":[{"type":"delete"}]}'

    with pytest.raises(ValueError, match="invalid memory review operation"):
        await LLMMemoryReviewer(FakeLLM(response)).review(
            review_input(create_fact())
        )


@pytest.mark.asyncio
async def test_reviewer_rejects_unknown_target_item():
    response = (
        '{"operations":['
        '{"type":"end_fact_validity","target_item_id":"missing"}'
        ']}'
    )

    with pytest.raises(ValueError, match="must reference a related item"):
        await LLMMemoryReviewer(FakeLLM(response)).review(
            review_input(create_fact())
        )


@pytest.mark.asyncio
async def test_reviewer_rejects_supersede_for_experience():
    payload = create_experience()
    old_item = create_item("experience-001", create_experience())
    response = (
        '{"operations":['
        '{"type":"supersede","target_item_id":"experience-001"}'
        ']}'
    )

    with pytest.raises(ValueError, match="not allowed for payload domain"):
        await LLMMemoryReviewer(FakeLLM(response)).review(
            review_input(payload, old_item)
        )


@pytest.mark.asyncio
async def test_reviewer_rejects_no_change_combined_with_add():
    response = (
        '{"operations":['
        '{"type":"no_change","reason":"重复"},'
        '{"type":"add"}'
        ']}'
    )

    with pytest.raises(ValueError, match="cannot be combined"):
        await LLMMemoryReviewer(FakeLLM(response)).review(
            review_input(create_fact())
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("forbidden_field", ["content", "payload", "replacement"])
async def test_reviewer_rejects_attempt_to_override_payload(
    forbidden_field,
):
    response = json.dumps(
        {
            "operations": [
                {
                    "type": "add",
                    forbidden_field: "LLM 伪造内容",
                }
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="unsupported fields"):
        await LLMMemoryReviewer(FakeLLM(response)).review(
            review_input(create_fact())
        )
