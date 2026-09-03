from datetime import datetime, timezone

import pytest

from core.memory.change_plan import AddMemoryItem, MemoryChangePlan
from core.memory.contracts import (
    MemoryWriteMessage,
    MemoryWriteRequest,
    MemoryWriteSummary,
)
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


def create_candidate(content: str) -> MemoryCandidate:
    return MemoryCandidate(
        candidate_id="candidate-001",
        content=content,
        provenance=PROVENANCE,
        source_message_ids=("message-001",),
    )


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


class RecordingMemorySpaceRouter:
    def __init__(
        self,
        calls: list[str],
        retriever: RecordingRetriever,
    ) -> None:
        self.calls = calls
        self.retriever = retriever
        self.memory_space_id: str | None = None

    def for_space(
        self,
        memory_space_id: str,
    ) -> RecordingRetriever:
        self.calls.append("for_space")
        self.memory_space_id = memory_space_id
        return self.retriever


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


class RecordingExtractor:
    def __init__(
        self,
        calls: list[str],
        candidates: list[MemoryCandidate],
    ) -> None:
        self.calls = calls
        self.candidates = candidates
        self.context = None

    async def extract(self, context):
        self.calls.append("extract")
        self.context = context
        return self.candidates


class SequentialExecutor:
    def __init__(
        self,
        calls: list[str],
        results: list[MemoryChangeExecutionResult],
    ) -> None:
        self.calls = calls
        self.results = list(results)
        self.inputs: list[MemoryChangeExecutionInput] = []

    async def execute(
        self,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryChangeExecutionResult:
        self.calls.append("execute")
        self.inputs.append(input_data)
        return self.results.pop(0)


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
    candidate = create_candidate("用户搬到上海了")
    payload = create_fact("用户居住在上海")
    plan = MemoryChangePlan(
        operations=(AddMemoryItem(payload=payload),)
    )
    execution = MemoryChangeExecutionResult(added_items=())

    embedder = RecordingEmbedder(calls)
    retriever = RecordingRetriever(calls, retrieval_candidates)
    memory_spaces = RecordingMemorySpaceRouter(calls, retriever)
    materializer = RecordingMaterializer(calls, payload)
    reviewer = RecordingReviewer(calls, plan)
    executor = RecordingExecutor(calls, execution)
    recall_context = MemoryRecallContext(
        scopes=SCOPES,
    )
    service = MemoryService(
        extractor=object(),
        embedder=embedder,
        memory_spaces=memory_spaces,
        reranker=object(),
        materializer=materializer,
        reviewer=reviewer,
        executor=executor,
    )

    result = await service.form(
        MemoryFormationInput(
            candidate=candidate,
            recorded_at=RECORDED_AT,
            recall_context=recall_context,
            memory_space_id="space-001",
            scopes=SCOPES,
            operation_id="operation-001",
        )
    )

    assert calls == [
        "embed",
        "for_space",
        "retrieve",
        "materialize",
        "review",
        "execute",
    ]
    assert embedder.query == candidate.content
    assert memory_spaces.memory_space_id == "space-001"
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
        extractor=object(),
        embedder=RecordingEmbedder(calls),
        memory_spaces=RecordingMemorySpaceRouter(
            calls,
            RecordingRetriever(calls, []),
        ),
        reranker=object(),
        materializer=materializer,
        reviewer=reviewer,
        executor=executor,
    )

    result = await service.form(
        MemoryFormationInput(
            candidate=create_candidate("用户喜欢跑步"),
            recorded_at=RECORDED_AT,
            recall_context=MemoryRecallContext(
                scopes=SCOPES,
            ),
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


@pytest.mark.asyncio
async def test_write_runs_extraction_then_forms_each_candidate():
    calls: list[str] = []
    first_candidate = MemoryCandidate(
        candidate_id="candidate-001",
        content="用户喜欢咖啡",
        provenance=PROVENANCE,
        source_message_ids=("message-001",),
    )
    second_candidate = MemoryCandidate(
        candidate_id="candidate-002",
        content="用户讨厌熬夜",
        provenance=PROVENANCE,
        source_message_ids=("message-002",),
    )
    first_item = MemoryItem(
        item_id="memory-001",
        memory_space_id="space-001",
        scopes=SCOPES,
        payload=create_fact("用户喜欢咖啡"),
    )
    second_item = MemoryItem(
        item_id="memory-002",
        memory_space_id="space-001",
        scopes=SCOPES,
        payload=create_fact("用户讨厌熬夜"),
    )
    extractor = RecordingExtractor(calls, [first_candidate, second_candidate])
    materializer = RecordingMaterializer(calls, create_fact("用户喜欢咖啡"))
    reviewer = RecordingReviewer(
        calls,
        MemoryChangePlan(
            operations=(AddMemoryItem(payload=create_fact("用户喜欢咖啡")),)
        ),
    )
    executor = SequentialExecutor(
        calls,
        [
            MemoryChangeExecutionResult(added_items=(first_item,)),
            MemoryChangeExecutionResult(added_items=(second_item,)),
        ],
    )
    service = MemoryService(
        extractor=extractor,
        embedder=RecordingEmbedder(calls),
        memory_spaces=RecordingMemorySpaceRouter(
            calls,
            RecordingRetriever(calls, []),
        ),
        reranker=object(),
        materializer=materializer,
        reviewer=reviewer,
        executor=executor,
    )

    result = await service.write(
        MemoryWriteRequest(
            operation_id="operation-001",
            memory_space_id="space-001",
            user_id="user-001",
            session_id="session-001",
            group_id="group-001",
            messages=(
                MemoryWriteMessage("message-001", "user", "用户喜欢咖啡"),
                MemoryWriteMessage("message-002", "assistant", "我记住了"),
            ),
            recent_messages=(
                MemoryWriteMessage("message-000", "user", "之前的消息"),
            ),
            summaries=(
                MemoryWriteSummary(
                    summary_id="summary-002",
                    level=2,
                    first_sequence=1,
                    last_sequence=16,
                    text="更早的历史摘要",
                ),
                MemoryWriteSummary(
                    summary_id="summary-001",
                    level=1,
                    first_sequence=17,
                    last_sequence=24,
                    text="较近的历史摘要",
                ),
            ),
            source_event_id="event-001",
            recorded_at=RECORDED_AT,
        )
    )

    assert calls == [
        "extract",
        "embed",
        "for_space",
        "retrieve",
        "materialize",
        "review",
        "execute",
        "embed",
        "for_space",
        "retrieve",
        "materialize",
        "review",
        "execute",
    ]
    assert extractor.context is not None
    assert [message.message_id for message in extractor.context.new_messages] == [
        "message-001",
        "message-002",
    ]
    assert [message.message_id for message in extractor.context.recent_messages] == [
        "message-000",
    ]
    assert extractor.context.summary == (
        "[level=2 range=1-16]\n"
        "更早的历史摘要\n\n"
        "[level=1 range=17-24]\n"
        "较近的历史摘要"
    )
    assert len(executor.inputs) == 2
    assert [item.memory_space_id for item in executor.inputs] == [
        "space-001",
        "space-001",
    ]
    assert [item.operation_id for item in executor.inputs] == [
        "operation-001",
        "operation-001",
    ]
    assert result.operation_id == "operation-001"
    assert result.memory_space_id == "space-001"
    assert result.added_item_ids == ("memory-001", "memory-002")
    assert result.updated_item_ids == ()


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
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
        "candidate": create_candidate("用户喜欢跑步"),
        "recorded_at": RECORDED_AT,
        "recall_context": MemoryRecallContext(
            scopes=SCOPES,
        ),
        "memory_space_id": "space-001",
        "scopes": SCOPES,
        "operation_id": "operation-001",
    }
    values[field_name] = value

    with pytest.raises(ValueError, match=message):
        MemoryFormationInput(**values)
