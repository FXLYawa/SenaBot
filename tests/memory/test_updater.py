import json
from datetime import datetime, timezone

import pytest

from core.memory.models import Memory, MemoryCandidate, MemoryUpdateAction
from core.memory.updater import LLMMemoryUpdater


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt: str | None = None

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


def existing_memory(memory_id: str = "memory-001") -> Memory:
    now = datetime.now(timezone.utc)
    return Memory(
        memory_id=memory_id,
        content="用户喜欢跑步",
        created_at=now,
        updated_at=now,
        operation_id="operation-001",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
        source_event_id="event-001",
        metadata={"source": "existing"},
    )


def test_memory_update_actions_are_distinct_and_hashable() -> None:
    actions = {
        MemoryUpdateAction.ADD,
        MemoryUpdateAction.UPDATE,
        MemoryUpdateAction.DELETE,
        MemoryUpdateAction.NONE,
    }

    assert len(actions) == 4
    assert MemoryUpdateAction.ADD != MemoryUpdateAction.UPDATE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected_action", "expected_target", "expected_content"),
    [
        (
            {
                "action": "add",
                "target_memory_id": None,
                "content": "  用户养了一只猫  ",
            },
            MemoryUpdateAction.ADD,
            None,
            "用户养了一只猫",
        ),
        (
            {
                "action": "update",
                "target_memory_id": "memory-001",
                "content": "  用户每周跑步三次  ",
            },
            MemoryUpdateAction.UPDATE,
            "memory-001",
            "用户每周跑步三次",
        ),
        (
            {
                "action": "delete",
                "target_memory_id": "memory-001",
                "content": None,
            },
            MemoryUpdateAction.DELETE,
            "memory-001",
            None,
        ),
        (
            {
                "action": "none",
                "target_memory_id": None,
                "content": None,
            },
            MemoryUpdateAction.NONE,
            None,
            None,
        ),
    ],
)
async def test_decide_parses_valid_actions(
    response: dict,
    expected_action: MemoryUpdateAction,
    expected_target: str | None,
    expected_content: str | None,
) -> None:
    candidate = MemoryCandidate(content="候选记忆")
    llm = FakeLLM(json.dumps(response, ensure_ascii=False))

    decision = await LLMMemoryUpdater(llm).decide(
        candidate,
        [existing_memory()],
    )

    assert decision.action is expected_action
    assert decision.candidate is candidate
    assert decision.target_memory_id == expected_target
    assert decision.content == expected_content


@pytest.mark.asyncio
async def test_decide_builds_prompt_with_candidate_and_existing_memories() -> None:
    llm = FakeLLM(
        '{"action":"none","target_memory_id":null,"content":null}'
    )

    await LLMMemoryUpdater(llm).decide(
        MemoryCandidate(content="用户每周跑步三次"),
        [existing_memory()],
    )

    assert llm.prompt is not None
    assert "候选记忆：\n用户每周跑步三次" in llm.prompt
    assert "memory_id: memory-001" in llm.prompt
    assert "content: 用户喜欢跑步" in llm.prompt
    assert "target_memory_id 只能使用已有相关记忆中提供的 memory_id" in llm.prompt


@pytest.mark.asyncio
async def test_decide_formats_empty_existing_memories_as_none() -> None:
    llm = FakeLLM(
        '{"action":"add","target_memory_id":null,"content":"新记忆"}'
    )

    await LLMMemoryUpdater(llm).decide(
        MemoryCandidate(content="新记忆"),
        [],
    )

    assert llm.prompt is not None
    assert "已有相关记忆：\n无" in llm.prompt


@pytest.mark.asyncio
async def test_decide_rejects_invalid_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        await LLMMemoryUpdater(FakeLLM("not-json")).decide(
            MemoryCandidate(content="候选记忆"),
            [],
        )


@pytest.mark.asyncio
async def test_decide_rejects_non_object_top_level() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        await LLMMemoryUpdater(FakeLLM("[]")).decide(
            MemoryCandidate(content="候选记忆"),
            [],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        ({"action": 1}, "action must be a string"),
        ({"action": "merge"}, "invalid memory update action"),
        (
            {"action": "add", "target_memory_id": "memory-001", "content": "内容"},
            "ADD target_memory_id must be null",
        ),
        (
            {"action": "add", "target_memory_id": None, "content": "   "},
            "ADD requires non-empty content",
        ),
        (
            {
                "action": "update",
                "target_memory_id": "unknown",
                "content": "内容",
            },
            "invalid target_memory_id for UPDATE",
        ),
        (
            {
                "action": "update",
                "target_memory_id": "memory-001",
                "content": None,
            },
            "UPDATE requires non-empty content",
        ),
        (
            {"action": "delete", "target_memory_id": "unknown", "content": None},
            "invalid target_memory_id for DELETE",
        ),
        (
            {
                "action": "delete",
                "target_memory_id": "memory-001",
                "content": "内容",
            },
            "DELETE content must be null",
        ),
        (
            {"action": "none", "target_memory_id": "memory-001", "content": None},
            "NONE requires null target_memory_id and content",
        ),
    ],
)
async def test_decide_rejects_invalid_decisions(response: dict, error: str) -> None:
    llm = FakeLLM(json.dumps(response, ensure_ascii=False))

    with pytest.raises(ValueError, match=error):
        await LLMMemoryUpdater(llm).decide(
            MemoryCandidate(content="候选记忆"),
            [existing_memory()],
        )
