import json

import pytest

from core.memory.extractor import LLMMemoryExtractor
from core.memory.models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    Provenance,
)
from core.memory.service import MemoryService


PROVENANCE = (Provenance("event", "event-001"),)


def create_candidate(
    content: str = "用户喜欢跑步",
    *,
    candidate_id: str = "candidate-001",
    source_message_ids: tuple[str, ...] = ("message-001",),
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id=candidate_id,
        content=content,
        provenance=PROVENANCE,
        source_message_ids=source_message_ids,
    )


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

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        self.context = context
        return [create_candidate()]


def extraction_context() -> MemoryExtractionContext:
    return MemoryExtractionContext(
        new_messages=[
            MemoryExtractionMessage("message-001", "user", "今天有点累"),
            MemoryExtractionMessage(
                "message-002",
                "assistant",
                "你可能最近工作太多了",
            ),
        ],
        summary="用户喜欢跑步",
        recent_messages=[
            MemoryExtractionMessage(
                "history-001",
                "user",
                "我上周去了杭州",
            )
        ],
        provenance=PROVENANCE,
    )


@pytest.mark.asyncio
async def test_extract_returns_multiple_trimmed_candidates() -> None:
    llm = FakeLLM(
        json.dumps(
            {
                "memories": [
                    {
                        "content": "  用户喜欢跑步  ",
                        "source_message_ids": ["message-001"],
                    },
                    {
                        "content": "用户养了一只猫",
                        "source_message_ids": ["message-001", "message-002"],
                    },
                ]
            },
            ensure_ascii=False,
        )
    )

    candidate_ids = iter(["candidate-001", "candidate-002"])
    candidates = await LLMMemoryExtractor(
        llm,
        candidate_id_factory=candidate_ids.__next__,
    ).extract(extraction_context())

    assert [candidate.content for candidate in candidates] == [
        "用户喜欢跑步",
        "用户养了一只猫",
    ]
    assert [candidate.candidate_id for candidate in candidates] == [
        "candidate-001",
        "candidate-002",
    ]
    assert candidates[0].provenance == PROVENANCE
    assert candidates[0].source_message_ids == ("message-001",)
    assert candidates[1].source_message_ids == (
        "message-001",
        "message-002",
    )


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
                {"content": "缺少来源"},
                {"content": "空来源", "source_message_ids": []},
                {
                    "content": "  有效记忆  ",
                    "source_message_ids": ["message-001"],
                },
            ]
        },
        ensure_ascii=False,
    )

    candidates = await LLMMemoryExtractor(
        FakeLLM(response),
        candidate_id_factory=lambda: "candidate-001",
    ).extract(extraction_context())

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
async def test_extract_rejects_non_array_memories() -> None:
    with pytest.raises(ValueError, match="must be a JSON array"):
        await LLMMemoryExtractor(
            FakeLLM('{"memories": {}}')
        ).extract(extraction_context())


@pytest.mark.asyncio
async def test_extract_rejects_source_outside_new_messages() -> None:
    response = json.dumps(
        {
            "memories": [
                {
                    "content": "用户上周去了杭州",
                    "source_message_ids": ["history-001"],
                }
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="must reference new messages"):
        await LLMMemoryExtractor(FakeLLM(response)).extract(
            extraction_context()
        )


@pytest.mark.asyncio
async def test_prompt_limits_context_and_assistant_to_supporting_information(
) -> None:
    llm = FakeLLM('{"memories": []}')

    await LLMMemoryExtractor(llm).extract(extraction_context())

    assert llm.prompt is not None
    assert "历史摘要和最近消息只用于帮助理解当前消息" in llm.prompt
    assert "不能直接作为本次新记忆的来源" in llm.prompt
    assert (
        "不得把 Assistant 的推测、建议或未经用户确认的信息"
        "作为用户事实提取"
        in llm.prompt
    )
    assert "历史摘要：\n用户喜欢跑步" in llm.prompt
    assert (
        "最近消息：\n[history-001] user: 我上周去了杭州"
        in llm.prompt
    )
    assert (
        "当前新消息：\n[message-001] user: 今天有点累"
        in llm.prompt
    )
    assert (
        "[message-002] assistant: 你可能最近工作太多了"
        in llm.prompt
    )
    assert '"source_message_ids": ["message-001"]' in llm.prompt


@pytest.mark.asyncio
async def test_service_builds_context_and_delegates_to_extractor() -> None:
    extractor = RecordingExtractor()
    unused_dependency = object()
    service = MemoryService(
        extractor=extractor,
        embedder=unused_dependency,
        retriever=unused_dependency,
        reranker=unused_dependency,
        materializer=unused_dependency,
        reviewer=unused_dependency,
        executor=unused_dependency,
    )
    input_data = MemoryExtractionInput(
        messages=[
            MemoryExtractionMessage(
                "message-001",
                "user",
                "我喜欢跑步",
            )
        ],
        provenance=PROVENANCE,
    )
    recent_messages = [
        MemoryExtractionMessage(
            "history-001",
            "assistant",
            "你之前提到过运动",
        )
    ]

    candidates = await service.extract(
        input_data,
        summary="用户在制定运动计划",
        recent_messages=recent_messages,
    )

    assert candidates == [create_candidate()]
    assert extractor.context == MemoryExtractionContext(
        new_messages=input_data.messages,
        summary="用户在制定运动计划",
        recent_messages=recent_messages,
        provenance=PROVENANCE,
    )


@pytest.mark.asyncio
async def test_service_requires_configured_extractor() -> None:
    unused_dependency = object()
    service = MemoryService(
        extractor=None,
        embedder=unused_dependency,
        retriever=unused_dependency,
        reranker=unused_dependency,
        materializer=unused_dependency,
        reviewer=unused_dependency,
        executor=unused_dependency,
    )

    with pytest.raises(RuntimeError, match="memory extractor is not configured"):
        await service.extract(
            MemoryExtractionInput(
                messages=[],
                provenance=PROVENANCE,
            ),
            summary=None,
            recent_messages=[],
        )
