from datetime import datetime, timezone

import pytest

from core.memory.change_plan import AddMemoryItem, MemoryChangePlan
from core.memory.executor import (
    MemoryChangeExecutionInput,
    MemoryChangeExecutionResult,
)
from core.memory.models import (
    Fact,
    MemoryCandidate,
    MemoryFormationInput,
    MemoryItem,
    MemoryMaterializationInput,
    MemoryRecallContext,
    MemoryRetrievalCandidate,
    MemoryReviewInput,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
)
from core.memory.service import MemoryService


RECORDED_AT = datetime(2026, 8, 25, tzinfo=timezone.utc)
PROVENANCE = (Provenance("event", "event-001"),)
USER_SCOPE = MemoryScopeRef(MemoryScopeKind.USER, "user-001")
SCOPES = frozenset({USER_SCOPE})


def create_fact(content: str) -> Fact:
    return Fact(
        content=content,
        provenance=PROVENANCE,
        recorded_at=RECORDED_AT,
    )


class RecordingEmbedder:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.query: str | None = None

    async def embed(self, query: str) -> list[float]:
        self.calls.append("embed")
        self.query = query
        return [0.25, 0.75]


class RecordingRetriever:
    def __init__(
        self,
        calls: list[str],
        candidates: list[MemoryRetrievalCandidate],
    ) -> None:
        self.calls = calls
        self.candidates = candidates
        self.embedding: list[float] | None = None
        self.context: MemoryRecallContext | None = None

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]:
        self.calls.append("retrieve")
        self.embedding = query_embedding
        self.context = context
        return self.candidates


class RecordingMaterializer:
    def __init__(self, calls: list[str], payload: Fact) -> None:
        self.calls = calls
        self.payload = payload
        self.input_data: MemoryMaterializationInput | None = None

    async def materialize(
        self,
        input_data: MemoryMaterializationInput,
    ) -> Fact:
        self.calls.append("materialize")
        self.input_data = input_data
        return self.payload


class RecordingReviewer:
    def __init__(self, calls: list[str], plan: MemoryChangePlan) -> None:
        self.calls = calls
        self.plan = plan
        self.input_data: MemoryReviewInput | None = None

    async def review(
        self,
        input_data: MemoryReviewInput,
    ) -> MemoryChangePlan:
        self.calls.append("review")
        self.input_data = input_data
        return self.plan


class RecordingExecutor:
    def __init__(
        self,
        calls: list[str],
        result: MemoryChangeExecutionResult,
    ) -> None:
        self.calls = calls
        self.result = result
        self.input_data: MemoryChangeExecutionInput | None = None

    async def execute(
        self,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryChangeExecutionResult:
        self.calls.append("execute")
        self.input_data = input_data
        return self.result


@pytest.mark.asyncio
async def test_formation_runs_complete_pipeline_with_shared_snapshot():
    calls: list[str] = []
    related_item = MemoryItem(
        item_id="fact-old",
        memory_space_id="space-001",
        scopes=SCOPES,
        payload=create_fact("用户住在北京"),
    )
    retrieval_candidates = [
        MemoryRetrievalCandidate(memory=related_item, score=0.9)
    ]
    candidate = MemoryCandidate(content="用户搬到上海了")
    payload = create_fact("用户居住在上海")
    plan = MemoryChangePlan(
        operations=(AddMemoryItem(payload=payload),)
    )
    execution = MemoryChangeExecutionResult(added_items=())

    embedder = RecordingEmbedder(calls)
    retriever = RecordingRetriever(calls, retrieval_candidates)
    materializer = RecordingMaterializer(calls, payload)
    reviewer = RecordingReviewer(calls, plan)
    executor = RecordingExecutor(calls, execution)
    recall_context = MemoryRecallContext(scopes=SCOPES)
    service = MemoryService(
        embedder=embedder,
        retriever=retriever,
        materializer=materializer,
        reviewer=reviewer,
        executor=executor,
    )

    result = await service.form(
        MemoryFormationInput(
            candidate=candidate,
            provenance=PROVENANCE,
            recorded_at=RECORDED_AT,
            recall_context=recall_context,
            memory_space_id="space-001",
            scopes=SCOPES,
            operation_id="operation-001",
        )
    )

    assert calls == [
        "embed",
        "retrieve",
        "materialize",
        "review",
        "execute",
    ]
    assert embedder.query == candidate.content
    assert retriever.embedding == [0.25, 0.75]
    assert retriever.context is recall_context

    related_items = (related_item,)
    assert materializer.input_data is not None
    assert materializer.input_data.related_items == related_items
    assert reviewer.input_data is not None
    assert reviewer.input_data.related_items == related_items
    assert executor.input_data is not None
    assert executor.input_data.related_items == related_items
    assert executor.input_data.plan is plan
    assert executor.input_data.memory_space_id == "space-001"
    assert executor.input_data.scopes == SCOPES
    assert executor.input_data.operation_id == "operation-001"

    assert result is execution


@pytest.mark.asyncio
async def test_formation_supports_no_related_items():
    calls: list[str] = []
    payload = create_fact("用户喜欢跑步")
    plan = MemoryChangePlan(
        operations=(AddMemoryItem(payload=payload),)
    )
    materializer = RecordingMaterializer(calls, payload)
    reviewer = RecordingReviewer(calls, plan)
    executor = RecordingExecutor(
        calls,
        MemoryChangeExecutionResult(),
    )
    service = MemoryService(
        embedder=RecordingEmbedder(calls),
        retriever=RecordingRetriever(calls, []),
        materializer=materializer,
        reviewer=reviewer,
        executor=executor,
    )

    result = await service.form(
        MemoryFormationInput(
            candidate=MemoryCandidate(content="用户喜欢跑步"),
            provenance=PROVENANCE,
            recorded_at=RECORDED_AT,
            recall_context=MemoryRecallContext(scopes=SCOPES),
            memory_space_id="space-001",
            scopes=SCOPES,
            operation_id="operation-001",
        )
    )

    assert result is executor.result
    assert materializer.input_data is not None
    assert materializer.input_data.related_items == ()
    assert reviewer.input_data is not None
    assert reviewer.input_data.related_items == ()
    assert executor.input_data is not None
    assert executor.input_data.related_items == ()


@pytest.mark.parametrize(
    ("missing_dependency", "message"),
    [
        ("embedder", "memory embedder is not configured"),
        ("retriever", "memory retriever is not configured"),
        ("materializer", "memory materializer is not configured"),
        ("reviewer", "memory reviewer is not configured"),
        ("executor", "memory executor is not configured"),
    ],
)
@pytest.mark.asyncio
async def test_formation_requires_every_pipeline_dependency(
    missing_dependency,
    message,
):
    calls: list[str] = []
    payload = create_fact("用户喜欢跑步")
    plan = MemoryChangePlan(
        operations=(AddMemoryItem(payload=payload),)
    )
    dependencies = {
        "embedder": RecordingEmbedder(calls),
        "retriever": RecordingRetriever(calls, []),
        "materializer": RecordingMaterializer(calls, payload),
        "reviewer": RecordingReviewer(calls, plan),
        "executor": RecordingExecutor(
            calls,
            MemoryChangeExecutionResult(),
        ),
    }
    dependencies[missing_dependency] = None
    service = MemoryService(
        **dependencies,
    )

    with pytest.raises(RuntimeError, match=message):
        await service.form(
            MemoryFormationInput(
                candidate=MemoryCandidate(content="用户喜欢跑步"),
                provenance=PROVENANCE,
                recorded_at=RECORDED_AT,
                recall_context=MemoryRecallContext(scopes=SCOPES),
                memory_space_id="space-001",
                scopes=SCOPES,
                operation_id="operation-001",
            )
        )

    assert calls == []


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("provenance", (), "provenance must not be empty"),
        ("memory_space_id", " ", "memory_space_id must not be blank"),
        ("scopes", frozenset(), "memory scopes must not be empty"),
        ("operation_id", " ", "operation_id must not be blank"),
    ],
)
def test_formation_input_rejects_invalid_context(
    field_name,
    value,
    message,
):
    values = {
        "candidate": MemoryCandidate(content="用户喜欢跑步"),
        "provenance": PROVENANCE,
        "recorded_at": RECORDED_AT,
        "recall_context": MemoryRecallContext(scopes=SCOPES),
        "memory_space_id": "space-001",
        "scopes": SCOPES,
        "operation_id": "operation-001",
    }
    values[field_name] = value

    with pytest.raises(ValueError, match=message):
        MemoryFormationInput(**values)
