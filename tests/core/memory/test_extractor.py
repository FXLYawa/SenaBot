import json
from datetime import UTC, datetime

import pytest

from core.model import ModelRequest, ModelResponse, ModelResponseError
from core.common import Content, Summary
from core.context import (
    ContextActorRef, ContextActorType, ContextEntryRecord, ContextReadView, SessionRecord,
)

from core.memory.extractor import LLMMemoryExtractor
from core.memory.models import (
    MemoryCandidate,
    MemoryExtractionContext,
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
    def __init__(self, response: str, *, finish_reason: str = "stop") -> None:
        self.response = ModelResponse(text=response, model="test-model", finish_reason=finish_reason)
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        assert isinstance(request, ModelRequest)
        self.requests.append(request)
        return self.response

    async def close(self) -> None:
        pass


class RecordingExtractor:
    def __init__(self) -> None:
        self.context: MemoryExtractionContext | None = None

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        self.context = context
        return []


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
@pytest.mark.parametrize("candidate", [
    None, {"missing": "content"}, {"content": 42}, {"content": "   "},
    {"content": "缺少来源"}, {"content": "空来源", "source_message_ids": []},
])
async def test_extract_rejects_invalid_candidate_instead_of_filtering(candidate):
    response = json.dumps({"memories": [
        {"content": "有效记忆", "source_message_ids": ["message-001"]}, candidate,
    ]})
    with pytest.raises(ValueError, match="candidate"):
        await LLMMemoryExtractor(FakeLLM(response)).extract(extraction_context())


@pytest.mark.asyncio
async def test_extract_rejects_invalid_json() -> None:
    with pytest.raises(ModelResponseError):
        await LLMMemoryExtractor(FakeLLM("not-json")).extract(extraction_context())


@pytest.mark.asyncio
async def test_extract_rejects_non_object_top_level() -> None:
    with pytest.raises(ValueError, match="must be a JSON object"):
        await LLMMemoryExtractor(FakeLLM("[]")).extract(extraction_context())


@pytest.mark.asyncio
async def test_extract_rejects_non_array_memories() -> None:
    with pytest.raises(ValueError, match="must be a JSON array"):
        await LLMMemoryExtractor(FakeLLM('{"memories": {}}')).extract(
            extraction_context()
        )


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
        await LLMMemoryExtractor(FakeLLM(response)).extract(extraction_context())


@pytest.mark.asyncio
async def test_prompt_limits_context_and_assistant_to_supporting_information() -> None:
    llm = FakeLLM('{"memories": []}')

    await LLMMemoryExtractor(llm).extract(extraction_context())

    assert len(llm.requests) == 1
    assert len(llm.requests[0].messages) == 1
    assert llm.requests[0].messages[0].role == "user"
    prompt = llm.requests[0].messages[0].content
    assert "历史摘要和最近消息只用于帮助理解当前消息" in prompt
    assert "不能直接作为本次新记忆的来源" in prompt
    assert (
        "不得把 Assistant 的推测、建议或未经用户确认的信息"
        "作为用户事实提取" in prompt
    )
    assert "历史摘要：\n用户喜欢跑步" in prompt
    assert "最近消息：\n[history-001] user: 我上周去了杭州" in prompt
    assert "当前新消息：\n[message-001] user: 今天有点累" in prompt
    assert "[message-002] assistant: 你可能最近工作太多了" in prompt
    assert '"source_message_ids": ["message-001"]' in prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["length", "content_filter", "unknown", ""])
async def test_incomplete_model_response_is_rejected(finish_reason):
    llm = FakeLLM('{"memories": []}', finish_reason=finish_reason)
    with pytest.raises(ModelResponseError, match="incomplete or empty"):
        await LLMMemoryExtractor(llm).extract(extraction_context())


@pytest.mark.asyncio
async def test_complete_fenced_model_response_is_accepted():
    llm = FakeLLM('```json\n{"memories": []}\n```')
    result = await LLMMemoryExtractor(llm).extract(extraction_context())
    assert result == []


@pytest.mark.asyncio
async def test_service_builds_context_from_read_view_and_handles_empty_candidates():
    now = datetime(2026, 9, 11, tzinfo=UTC)
    session = SessionRecord("session-001", now, now)
    history = ContextEntryRecord(
        "history-001", session.session_id, 2, "sena_message",
        ContextActorRef(ContextActorType.SENA, "sena", "Sena"),
        Content.from_text("你之前提到过运动"), "event-history", now,
    )
    entry = ContextEntryRecord(
        "message-001", session.session_id, 3, "user_message",
        ContextActorRef(ContextActorType.USER, "user-001", "Alice"),
        Content.from_text("我喜欢跑步"), "event-001", now,
    )
    view = ContextReadView(
        session=session, after_sequence=2, through_sequence=3, entries=(entry,),
        preceding_entries=(history,),
        summaries=(Summary("summary-001", session.session_id, 1, 1, 1,
                           "用户在制定运动计划", now),),
    )
    extractor = RecordingExtractor()
    service = MemoryService(
        extractor=extractor, embedder=object(), memory_spaces=object(), reranker=None,
        materializer=object(), reviewer=object(), executor=object(),
    )
    result = await service.extract_and_store(
        operation_id="extraction-001", memory_space_id="sena",
        user_id="user-001", context=view,
    )
    assert extractor.context == MemoryExtractionContext(
        new_messages=[MemoryExtractionMessage(
            "message-001", "user", "我喜欢跑步", "user-001", "Alice", now,
        )],
        recent_messages=[MemoryExtractionMessage(
            "history-001", "assistant", "你之前提到过运动", "sena", "Sena", now,
        )],
        summary="[level=1 range=1-1]\n用户在制定运动计划",
        provenance=(Provenance("context_entry", "message-001"), Provenance("event", "event-001")),
    )
    assert result.operation_id == "extraction-001"
    assert result.memory_space_id == "sena"
    assert result.session_id == session.session_id
    assert result.processed_through_sequence == 3
    assert result.added_item_ids == result.updated_item_ids == ()
