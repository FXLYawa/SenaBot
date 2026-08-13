import json

import pytest

from core.memory.extractor import LLMMemoryExtractor
from core.memory.models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionInput,
    MemoryExtractionMessage,
)
from core.memory.service import MemoryService


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt: str | None = None

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


class RecordingExtractor:
    def __init__(self) -> None:
        self.context: MemoryExtractionContext | None = None

    async def extract(self, context: MemoryExtractionContext) -> list[MemoryCandidate]:
        self.context = context
        return [MemoryCandidate(content="用户喜欢跑步")]


def extraction_context() -> MemoryExtractionContext:
    return MemoryExtractionContext(
        new_messages=[
            MemoryExtractionMessage("user", "今天有点累"),
            MemoryExtractionMessage("assistant", "你可能最近工作太多了"),
        ],
        summary="用户喜欢跑步",
        recent_messages=[MemoryExtractionMessage("user", "我上周去了杭州")],
    )


@pytest.mark.asyncio
async def test_extract_returns_multiple_trimmed_candidates() -> None:
    llm = FakeLLM(
        json.dumps(
            {
                "memories": [
                    {"content": "  用户喜欢跑步  "},
                    {"content": "用户养了一只猫"},
                ]
            },
            ensure_ascii=False,
        )
    )

    candidates = await LLMMemoryExtractor(llm).extract(extraction_context())

    assert [candidate.content for candidate in candidates] == ["用户喜欢跑步", "用户养了一只猫"]


@pytest.mark.asyncio
async def test_extract_returns_empty_candidates() -> None:
    candidates = await LLMMemoryExtractor(FakeLLM('{"memories": []}')).extract(
        extraction_context()
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_extract_filters_invalid_candidates() -> None:
    response = json.dumps(
        {
            "memories": [
                None,
                {"missing": "content"},
                {"content": 42},
                {"content": "   "},
                {"content": "  有效记忆  "},
            ]
        },
        ensure_ascii=False,
    )

    candidates = await LLMMemoryExtractor(FakeLLM(response)).extract(extraction_context())

    assert [candidate.content for candidate in candidates] == ["有效记忆"]


@pytest.mark.asyncio
async def test_extract_rejects_invalid_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        await LLMMemoryExtractor(FakeLLM("not-json")).extract(extraction_context())


@pytest.mark.asyncio
async def test_extract_rejects_non_object_top_level() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        await LLMMemoryExtractor(FakeLLM("[]")).extract(extraction_context())


@pytest.mark.asyncio
async def test_prompt_limits_context_and_assistant_to_supporting_information() -> None:
    llm = FakeLLM('{"memories": []}')

    await LLMMemoryExtractor(llm).extract(extraction_context())

    assert llm.prompt is not None
    assert "历史摘要和最近消息只用于帮助理解当前消息" in llm.prompt
    assert "不能直接作为本次新记忆的来源" in llm.prompt
    assert "不得把 Assistant 的推测、建议或未经用户确认的信息作为用户事实提取" in llm.prompt
    assert "历史摘要：\n用户喜欢跑步" in llm.prompt
    assert "最近消息：\nuser: 我上周去了杭州" in llm.prompt
    assert "当前新消息：\nuser: 今天有点累" in llm.prompt
    assert "assistant: 你可能最近工作太多了" in llm.prompt


@pytest.mark.asyncio
async def test_service_builds_context_and_delegates_to_extractor() -> None:
    extractor = RecordingExtractor()
    service = MemoryService(repository=object(), extractor=extractor)  # type: ignore[arg-type]
    input_data = MemoryExtractionInput(
        messages=[MemoryExtractionMessage("user", "我喜欢跑步")],
        metadata={"source_event_id": "event-001"},
    )
    recent_messages = [MemoryExtractionMessage("assistant", "你之前提到过运动")]

    candidates = await service.extract(
        input_data,
        summary="用户在制定运动计划",
        recent_messages=recent_messages,
    )

    assert candidates == [MemoryCandidate(content="用户喜欢跑步")]
    assert extractor.context == MemoryExtractionContext(
        new_messages=input_data.messages,
        summary="用户在制定运动计划",
        recent_messages=recent_messages,
    )


@pytest.mark.asyncio
async def test_service_requires_configured_extractor() -> None:
    service = MemoryService(repository=object())  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="memory extractor is not configured"):
        await service.extract(
            MemoryExtractionInput(messages=[]),
            summary=None,
            recent_messages=[],
        )
