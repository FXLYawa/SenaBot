import json
from dataclasses import fields
from datetime import datetime, timezone

import pytest

from core.memory.materialization import LLMMemoryMaterializer
from core.memory.models import (
    Entity,
    Experience,
    Fact,
    Knowledge,
    MemoryCandidate,
    MemoryDomain,
    MemoryItem,
    MemoryMaterializationInput,
    MemoryPayload,
    MemoryScopeKind,
    MemoryScopeRef,
    MemoryWriteEnvelope,
    Provenance,
    Understanding,
)
from core.memory.protocols import MemoryMaterializerProtocol


PROVENANCE = (Provenance("event", "event-001"),)


def create_candidate(
    content: str = "用户喜欢跑步",
) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-001",
        content=content,
        provenance=PROVENANCE,
        source_message_ids=("message-001",),
    )


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


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompt: str | None = None

    async def generate(self, prompt: str) -> str:
        self.prompt = prompt
        return self.response


def create_fact() -> Fact:
    return Fact(
        content="用户喜欢跑步",
        provenance=PROVENANCE,
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


def materialization_input(
    *,
    related_items: tuple[MemoryItem, ...] = (),
) -> MemoryMaterializationInput:
    return MemoryMaterializationInput(
        candidate=create_candidate("用户最近开始玩 FF14"),
        recorded_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        related_items=related_items,
    )


def test_materialization_input_defaults_to_no_related_items():
    input_data = MemoryMaterializationInput(
        candidate=create_candidate(),
        recorded_at=datetime.now(timezone.utc),
    )

    assert input_data.related_items == ()


def test_candidate_requires_provenance():
    with pytest.raises(ValueError, match="provenance must not be empty"):
        MemoryCandidate(
            candidate_id="candidate-001",
            content="用户喜欢跑步",
            provenance=(),
            source_message_ids=("message-001",),
        )


@pytest.mark.asyncio
async def test_materializer_converts_candidate_to_typed_payload():
    payload = create_fact()
    materializer: MemoryMaterializerProtocol = FakeMemoryMaterializer(
        payload
    )
    input_data = MemoryMaterializationInput(
        candidate=create_candidate(),
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


@pytest.mark.asyncio
async def test_llm_materializer_builds_fact_with_trusted_fields():
    input_data = materialization_input()
    llm = FakeLLM(
        json.dumps(
            {
                "domain": "fact",
                "payload": {
                    "content": "  用户最近开始玩 FF14  ",
                    "valid_from": "2026-08-01T00:00:00Z",
                    "valid_to": None,
                },
            },
            ensure_ascii=False,
        )
    )

    result = await LLMMemoryMaterializer(llm).materialize(input_data)

    assert result == Fact(
        content="用户最近开始玩 FF14",
        provenance=input_data.candidate.provenance,
        recorded_at=input_data.recorded_at,
        valid_from=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valid_to=None,
    )


@pytest.mark.asyncio
async def test_llm_materializer_builds_experience():
    llm = FakeLLM(
        json.dumps(
            {
                "domain": "experience",
                "payload": {
                    "summary": "Sena 和用户一起制定了健身计划",
                    "participants": [
                        {
                            "entity_type": "user",
                            "entity_id": "user-001",
                        },
                        {
                            "entity_type": "agent",
                            "entity_id": "sena",
                        },
                    ],
                    "occurred_from": "2026-08-24T10:00:00+08:00",
                    "occurred_to": None,
                },
            },
            ensure_ascii=False,
        )
    )
    input_data = materialization_input()

    result = await LLMMemoryMaterializer(llm).materialize(input_data)

    assert isinstance(result, Experience)
    assert result.participants == (
        Entity("user", "user-001"),
        Entity("agent", "sena"),
    )
    assert result.provenance == input_data.candidate.provenance
    assert result.recorded_at == input_data.recorded_at


@pytest.mark.asyncio
async def test_llm_materializer_builds_understanding_from_related_evidence():
    related_item = create_item()
    input_data = materialization_input(related_items=(related_item,))
    llm = FakeLLM(
        json.dumps(
            {
                "domain": "understanding",
                "payload": {
                    "content": "用户倾向于通过运动维持健康",
                    "evidence_item_ids": [related_item.item_id],
                },
            },
            ensure_ascii=False,
        )
    )

    result = await LLMMemoryMaterializer(llm).materialize(input_data)

    assert result == Understanding(
        content="用户倾向于通过运动维持健康",
        provenance=input_data.candidate.provenance,
        evidence_item_ids=(related_item.item_id,),
        recorded_at=input_data.recorded_at,
    )


@pytest.mark.asyncio
async def test_llm_materializer_rejects_unknown_evidence_item():
    llm = FakeLLM(
        json.dumps(
            {
                "domain": "understanding",
                "payload": {
                    "content": "用户喜欢运动",
                    "evidence_item_ids": ["invented-item"],
                },
            },
            ensure_ascii=False,
        )
    )

    with pytest.raises(ValueError, match="must reference related items"):
        await LLMMemoryMaterializer(llm).materialize(
            materialization_input(related_items=(create_item(),))
        )


@pytest.mark.asyncio
async def test_llm_materializer_builds_knowledge():
    input_data = materialization_input()
    llm = FakeLLM(
        json.dumps(
            {
                "domain": "knowledge",
                "payload": {
                    "content": "  Python dataclass 可以生成基础数据模型  "
                },
            },
            ensure_ascii=False,
        )
    )

    result = await LLMMemoryMaterializer(llm).materialize(input_data)

    assert result == Knowledge(
        content="Python dataclass 可以生成基础数据模型",
        provenance=input_data.candidate.provenance,
        recorded_at=input_data.recorded_at,
    )


@pytest.mark.asyncio
async def test_materialization_prompt_limits_related_memory_to_context():
    related_item = create_item()
    llm = FakeLLM(
        '{"domain":"fact","payload":'
        '{"content":"用户喜欢跑步",'
        '"valid_from":null,"valid_to":null}}'
    )

    await LLMMemoryMaterializer(llm).materialize(
        materialization_input(related_items=(related_item,))
    )

    assert llm.prompt is not None
    assert "候选记忆是本次要成形的唯一新信息来源" in llm.prompt
    assert "不得把旧记忆中本次候选未表达的信息" in llm.prompt
    assert "不得在本阶段决定新增、更新、删除或替代记忆" in llm.prompt
    assert "item_id: item-001" in llm.prompt
    assert "domain: fact" in llm.prompt
    assert "本次候选记忆：\n用户最近开始玩 FF14" in llm.prompt


@pytest.mark.asyncio
async def test_llm_materializer_rejects_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        await LLMMemoryMaterializer(FakeLLM("not-json")).materialize(
            materialization_input()
        )


@pytest.mark.asyncio
async def test_llm_materializer_rejects_non_object_top_level():
    with pytest.raises(ValueError, match="must be a JSON object"):
        await LLMMemoryMaterializer(FakeLLM("[]")).materialize(
            materialization_input()
        )


@pytest.mark.asyncio
async def test_llm_materializer_rejects_invalid_domain():
    response = '{"domain":"invalid","payload":{}}'

    with pytest.raises(ValueError, match="invalid memory materialization domain"):
        await LLMMemoryMaterializer(FakeLLM(response)).materialize(
            materialization_input()
        )


@pytest.mark.asyncio
async def test_llm_materializer_rejects_invalid_datetime():
    response = (
        '{"domain":"fact","payload":'
        '{"content":"用户喜欢跑步",'
        '"valid_from":"not-a-date","valid_to":null}}'
    )

    with pytest.raises(ValueError, match="must be an ISO 8601 string"):
        await LLMMemoryMaterializer(FakeLLM(response)).materialize(
            materialization_input()
        )
