from datetime import datetime, timezone

import pytest

from core.memory.contracts import MemoryQueryRequest
from core.memory.embedding import SimpleMemoryEmbedder
from core.memory.models import (
    Fact,
    Memory,
    MemoryItem,
    MemoryRecallContext,
    MemoryQueryCriteria,
    MemoryRetrievalCandidate,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
)
from core.memory.reranker import SimpleMemoryReranker
from core.memory.retriever import (
    SimpleMemoryRetriever,
    is_scope_accessible,
)
from core.memory.service import MemoryService


def create_memory(
    memory_id: str,
    content: str,
    *,
    user_id: str = "user-001",
    session_id: str = "session-001",
    group_id: str = "group-001",
) -> Memory:
    current_time = datetime.now(timezone.utc)
    return Memory(
        memory_id=memory_id,
        content=content,
        created_at=current_time,
        updated_at=current_time,
        operation_id=f"operation-{memory_id}",
        user_id=user_id,
        session_id=session_id,
        group_id=group_id,
        source_event_id=f"event-{memory_id}",
        metadata={},
    )


def create_memory_item(
    item_id: str,
    scopes: frozenset[MemoryScopeRef],
    *,
    memory_space_id: str = "space-001",
) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        memory_space_id=memory_space_id,
        scopes=scopes,
        payload=Fact(
            content="用户喜欢跑步",
            provenance=(Provenance("event", "event-001"),),
            recorded_at=datetime.now(timezone.utc),
        ),
    )


class RecordingEmbedder:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def embed(self, query: str) -> list[float]:
        self.calls.append(("embed", query))
        return [1.0, 2.0]


class RecordingRetriever:
    def __init__(
        self,
        calls: list[object],
        candidates: list[MemoryRetrievalCandidate],
    ) -> None:
        self.calls = calls
        self.candidates = candidates

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]:
        self.calls.append(
            (
                "retrieve",
                query_embedding,
                context,
            )
        )
        return self.candidates


class RecordingReranker:
    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    async def rerank(
        self,
        query: str,
        candidates: list[MemoryRetrievalCandidate],
    ) -> list[MemoryRetrievalCandidate]:
        self.calls.append(("rerank", query, candidates))
        return list(reversed(candidates))


class RecordingRepository:
    def __init__(self, memories: list[Memory]) -> None:
        self.memories = memories
        self.criteria: MemoryQueryCriteria | None = None

    async def query(
        self,
        criteria: MemoryQueryCriteria,
    ) -> list[Memory]:
        self.criteria = criteria
        return self.memories


@pytest.mark.asyncio
async def test_query_runs_complete_retrieval_pipeline():
    calls: list[object] = []
    first_memory = create_memory("memory-001", "用户喜欢跑步")
    second_memory = create_memory("memory-002", "用户喜欢游泳")
    candidates = [
        MemoryRetrievalCandidate(first_memory, score=0.2),
        MemoryRetrievalCandidate(second_memory, score=0.8),
    ]
    repository = RecordingRepository([])
    service = MemoryService(
        repository=repository,
        embedder=RecordingEmbedder(calls),
        retriever=RecordingRetriever(calls, candidates),
        reranker=RecordingReranker(calls),
    )

    result = await service.query(
        MemoryQueryRequest(
            query_id="query-001",
            user_id="user-001",
            session_id="session-001",
            group_id="group-001",
            query_text="用户喜欢什么运动",
        )
    )

    assert calls == [
        ("embed", "用户喜欢什么运动"),
        (
            "retrieve",
            [1.0, 2.0],
            MemoryRecallContext(
                scopes=frozenset(
                    {
                        MemoryScopeRef(
                            MemoryScopeKind.USER,
                            "user-001",
                        ),
                        MemoryScopeRef(
                            MemoryScopeKind.SESSION,
                            "session-001",
                        ),
                        MemoryScopeRef(
                            MemoryScopeKind.GROUP,
                            "group-001",
                        ),
                    }
                )
            ),
        ),
        ("rerank", "用户喜欢什么运动", candidates),
    ]
    assert result.query_id == "query-001"
    assert result.user_id == "user-001"
    assert result.session_id == "session-001"
    assert result.group_id == "group-001"
    assert result.memories == [second_memory, first_memory]


@pytest.mark.asyncio
async def test_query_returns_empty_result_when_retriever_has_no_candidates():
    calls: list[object] = []
    repository = RecordingRepository([])
    service = MemoryService(
        repository=repository,
        embedder=RecordingEmbedder(calls),
        retriever=RecordingRetriever(calls, []),
        reranker=RecordingReranker(calls),
    )

    result = await service.query(
        MemoryQueryRequest(
            query_id="query-empty",
            user_id="user-001",
            session_id="session-001",
            group_id="group-001",
            query_text="没有匹配的记忆",
        )
    )

    assert result.memories == []
    assert calls[-1] == ("rerank", "没有匹配的记忆", [])


@pytest.mark.asyncio
async def test_query_requires_embedder():
    service = MemoryService(
        repository=RecordingRepository([]),
        retriever=RecordingRetriever([], []),
    )

    with pytest.raises(
        RuntimeError,
        match="memory embedder is not configured",
    ):
        await service.query(
            MemoryQueryRequest(
                query_id="query-001",
                user_id="user-001",
                session_id="session-001",
                group_id="group-001",
                query_text="跑步",
            )
        )


@pytest.mark.asyncio
async def test_query_requires_retriever():
    service = MemoryService(
        repository=RecordingRepository([]),
        embedder=RecordingEmbedder([]),
    )

    with pytest.raises(
        RuntimeError,
        match="memory retriever is not configured",
    ):
        await service.query(
            MemoryQueryRequest(
                query_id="query-001",
                user_id="user-001",
                session_id="session-001",
                group_id="group-001",
                query_text="跑步",
            )
        )


@pytest.mark.asyncio
async def test_query_requires_reranker():
    calls: list[object] = []
    service = MemoryService(
        repository=RecordingRepository([]),
        embedder=RecordingEmbedder(calls),
        retriever=RecordingRetriever(calls, []),
    )

    with pytest.raises(
        RuntimeError,
        match="memory reranker is not configured",
    ):
        await service.query(
            MemoryQueryRequest(
                query_id="query-001",
                user_id="user-001",
                session_id="session-001",
                group_id="group-001",
                query_text="跑步",
            )
        )

    assert calls == []


@pytest.mark.asyncio
async def test_simple_embedder_returns_placeholder_vector():
    embedder = SimpleMemoryEmbedder()

    assert await embedder.embed("跑步") == [2.0]
    assert await embedder.embed("   ") == [0.0]


@pytest.mark.asyncio
async def test_simple_retriever_queries_scope_and_wraps_memories():
    memory = create_memory("memory-001", "用户喜欢跑步")
    repository = RecordingRepository([memory])
    retriever = SimpleMemoryRetriever(repository)

    candidates = await retriever.retrieve(
        [2.0],
        context=MemoryRecallContext(
            scopes=frozenset(
                {
                    MemoryScopeRef(
                        MemoryScopeKind.USER,
                        "user-001",
                    ),
                    MemoryScopeRef(
                        MemoryScopeKind.SESSION,
                        "session-001",
                    ),
                    MemoryScopeRef(
                        MemoryScopeKind.GROUP,
                        "group-001",
                    ),
                }
            )
        ),
    )

    assert repository.criteria == MemoryQueryCriteria(
        query_text="",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
    )
    assert candidates == [
        MemoryRetrievalCandidate(memory=memory, score=0.0)
    ]


@pytest.mark.asyncio
async def test_simple_retriever_requires_all_legacy_scope_dimensions():
    retriever = SimpleMemoryRetriever(RecordingRepository([]))
    context = MemoryRecallContext(
        scopes=frozenset(
            {
                MemoryScopeRef(MemoryScopeKind.USER, "user-001"),
                MemoryScopeRef(
                    MemoryScopeKind.SESSION,
                    "session-001",
                ),
            }
        )
    )

    with pytest.raises(
        ValueError,
        match="legacy retriever requires exactly one group scope",
    ):
        await retriever.retrieve([2.0], context=context)


@pytest.mark.asyncio
async def test_simple_retriever_rejects_duplicate_scope_kind():
    retriever = SimpleMemoryRetriever(RecordingRepository([]))
    context = MemoryRecallContext(
        scopes=frozenset(
            {
                MemoryScopeRef(MemoryScopeKind.USER, "user-001"),
                MemoryScopeRef(MemoryScopeKind.USER, "user-002"),
                MemoryScopeRef(
                    MemoryScopeKind.SESSION,
                    "session-001",
                ),
                MemoryScopeRef(MemoryScopeKind.GROUP, "group-001"),
            }
        )
    )

    with pytest.raises(
        ValueError,
        match="legacy retriever requires exactly one user scope",
    ):
        await retriever.retrieve([2.0], context=context)


@pytest.mark.asyncio
async def test_simple_reranker_sorts_candidates_by_score_descending():
    low_score = MemoryRetrievalCandidate(
        memory=create_memory("memory-low", "低相关记忆"),
        score=0.1,
    )
    high_score = MemoryRetrievalCandidate(
        memory=create_memory("memory-high", "高相关记忆"),
        score=0.9,
    )
    candidates = [low_score, high_score]

    result = await SimpleMemoryReranker().rerank("查询", candidates)

    assert result == [high_score, low_score]
    assert candidates == [low_score, high_score]


def test_scope_filter_matches_same_user_scope():
    user_scope = MemoryScopeRef(
        MemoryScopeKind.USER,
        "user-001",
    )
    item = create_memory_item(
        "item-001",
        frozenset({user_scope}),
    )

    assert is_scope_accessible(
        item,
        MemoryRecallContext(frozenset({user_scope})),
    )


def test_scope_filter_rejects_different_user_scope():
    item = create_memory_item(
        "item-001",
        frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    "user-001",
                )
            }
        ),
    )
    context = MemoryRecallContext(
        frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    "user-002",
                )
            }
        )
    )

    assert not is_scope_accessible(item, context)


def test_scope_filter_requires_all_item_scopes():
    user_scope = MemoryScopeRef(
        MemoryScopeKind.USER,
        "user-001",
    )
    group_scope = MemoryScopeRef(
        MemoryScopeKind.GROUP,
        "group-001",
    )
    session_scope = MemoryScopeRef(
        MemoryScopeKind.SESSION,
        "session-001",
    )
    item = create_memory_item(
        "item-001",
        frozenset({user_scope, group_scope}),
    )

    assert not is_scope_accessible(
        item,
        MemoryRecallContext(frozenset({user_scope})),
    )
    assert is_scope_accessible(
        item,
        MemoryRecallContext(
            frozenset({user_scope, group_scope})
        ),
    )
    assert is_scope_accessible(
        item,
        MemoryRecallContext(
            frozenset({user_scope, group_scope, session_scope})
        ),
    )


def test_global_item_is_visible_in_empty_context():
    item = create_memory_item(
        "item-global",
        frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.GLOBAL,
                    None,
                )
            }
        ),
    )

    assert is_scope_accessible(
        item,
        MemoryRecallContext(frozenset()),
    )


def test_global_query_scope_does_not_grant_user_scope_access():
    item = create_memory_item(
        "item-user",
        frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    "user-001",
                )
            }
        ),
    )
    context = MemoryRecallContext(
        frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.GLOBAL,
                    None,
                )
            }
        )
    )

    assert not is_scope_accessible(item, context)


def test_memory_space_does_not_affect_scope_access():
    user_scope = MemoryScopeRef(
        MemoryScopeKind.USER,
        "user-001",
    )
    first_item = create_memory_item(
        "item-001",
        frozenset({user_scope}),
        memory_space_id="space-001",
    )
    second_item = create_memory_item(
        "item-002",
        frozenset({user_scope}),
        memory_space_id="space-002",
    )
    context = MemoryRecallContext(frozenset({user_scope}))

    assert is_scope_accessible(first_item, context)
    assert is_scope_accessible(second_item, context)
