from datetime import datetime, timezone

import pytest

from core.memory.contracts import MemoryQueryRequest
from core.memory.embedding import SimpleMemoryEmbedder
from core.memory.models import (
    Fact,
    MemoryItem,
    MemoryRecallContext,
    MemoryRetrievalCandidate,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
)
from core.memory.reranker import SimpleMemoryReranker
from core.memory.retriever import (
    SimpleMemoryRetriever,
    SimpleMemorySpaceRouter,
)
from core.memory.service import MemoryService


def create_memory(
    item_id: str,
    content: str,
    *,
    user_id: str = "user-001",
    session_id: str = "session-001",
    group_id: str = "group-001",
) -> MemoryItem:
    return MemoryItem(
        item_id=item_id,
        memory_space_id="space-001",
        scopes=frozenset(
            {
                MemoryScopeRef(MemoryScopeKind.USER, user_id),
                MemoryScopeRef(MemoryScopeKind.SESSION, session_id),
                MemoryScopeRef(MemoryScopeKind.GROUP, group_id),
            }
        ),
        payload=Fact(
            content=content,
            provenance=(Provenance("event", f"event-{item_id}"),),
            recorded_at=datetime.now(timezone.utc),
        ),
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


class RecordingMemorySpaceRouter:
    def __init__(
        self,
        calls: list[object],
        retriever: RecordingRetriever,
    ) -> None:
        self.calls = calls
        self.retriever = retriever

    def for_space(
        self,
        memory_space_id: str,
    ) -> RecordingRetriever:
        self.calls.append(("for_space", memory_space_id))
        return self.retriever


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


@pytest.mark.parametrize(
    "missing_dependency",
    [
        "extractor",
        "embedder",
        "memory_spaces",
        "reranker",
        "materializer",
        "reviewer",
        "executor",
    ],
)
def test_service_requires_every_dependency_at_construction(
    missing_dependency: str,
) -> None:
    dependencies = {
        "extractor": object(),
        "embedder": object(),
        "memory_spaces": object(),
        "reranker": object(),
        "materializer": object(),
        "reviewer": object(),
        "executor": object(),
    }
    del dependencies[missing_dependency]

    with pytest.raises(TypeError, match=missing_dependency):
        MemoryService(**dependencies)


@pytest.mark.asyncio
async def test_query_runs_complete_retrieval_pipeline():
    calls: list[object] = []
    first_memory = create_memory("memory-001", "用户喜欢跑步")
    second_memory = create_memory("memory-002", "用户喜欢游泳")
    candidates = [
        MemoryRetrievalCandidate(first_memory, score=0.2),
        MemoryRetrievalCandidate(second_memory, score=0.8),
    ]
    service = MemoryService(
        extractor=object(),
        embedder=RecordingEmbedder(calls),
        memory_spaces=RecordingMemorySpaceRouter(
            calls,
            RecordingRetriever(calls, candidates),
        ),
        reranker=RecordingReranker(calls),
        materializer=object(),
        reviewer=object(),
        executor=object(),
    )

    result = await service.query(
        MemoryQueryRequest(
            query_id="query-001",
            memory_space_id="space-001",
            user_id="user-001",
            session_id="session-001",
            group_id="group-001",
            query_text="用户喜欢什么运动",
        )
    )

    assert calls == [
        ("embed", "用户喜欢什么运动"),
        ("for_space", "space-001"),
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
    service = MemoryService(
        extractor=object(),
        embedder=RecordingEmbedder(calls),
        memory_spaces=RecordingMemorySpaceRouter(
            calls,
            RecordingRetriever(calls, []),
        ),
        reranker=RecordingReranker(calls),
        materializer=object(),
        reviewer=object(),
        executor=object(),
    )

    result = await service.query(
        MemoryQueryRequest(
            query_id="query-empty",
            memory_space_id="space-001",
            user_id="user-001",
            session_id="session-001",
            group_id="group-001",
            query_text="没有匹配的记忆",
        )
    )

    assert result.memories == []
    assert calls[-1] == ("rerank", "没有匹配的记忆", [])


@pytest.mark.asyncio
async def test_simple_embedder_returns_placeholder_vector():
    embedder = SimpleMemoryEmbedder()

    assert await embedder.embed("跑步") == [2.0]
    assert await embedder.embed("   ") == [0.0]


@pytest.mark.asyncio
async def test_simple_retriever_filters_scope_and_wraps_items():
    memory = create_memory("memory-001", "用户喜欢跑步")
    retriever = SimpleMemoryRetriever([memory])

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

    assert candidates == [
        MemoryRetrievalCandidate(memory=memory, score=0.0)
    ]


@pytest.mark.asyncio
async def test_simple_retriever_filters_inaccessible_items():
    memory = create_memory(
        "memory-001",
        "用户喜欢跑步",
        user_id="user-002",
    )
    retriever = SimpleMemoryRetriever([memory])
    context = MemoryRecallContext(
        scopes=frozenset(
            {
                MemoryScopeRef(MemoryScopeKind.USER, "user-001"),
            }
        )
    )

    assert await retriever.retrieve([2.0], context=context) == []


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


def test_recall_context_matches_same_user_scope():
    user_scope = MemoryScopeRef(
        MemoryScopeKind.USER,
        "user-001",
    )
    item = create_memory_item(
        "item-001",
        frozenset({user_scope}),
    )

    context = MemoryRecallContext(
        scopes=frozenset({user_scope}),
    )

    assert context.matches(item)


def test_recall_context_rejects_different_user_scope():
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
        scopes=frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.USER,
                    "user-002",
                )
            }
        )
    )

    assert not context.matches(item)


def test_recall_context_matches_any_item_ownership_scope():
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

    assert (
        MemoryRecallContext(
            scopes=frozenset(
                {
                    user_scope,
                    MemoryScopeRef(
                        MemoryScopeKind.GROUP,
                        "another-group",
                    ),
                }
            )
        ).matches(item)
    )
    assert (
        MemoryRecallContext(
            scopes=frozenset({user_scope, group_scope}),
        ).matches(item)
    )
    assert (
        MemoryRecallContext(
            scopes=frozenset({user_scope, group_scope, session_scope}),
        ).matches(item)
    )


def test_recall_context_rejects_context_without_matching_owner():
    item = create_memory_item(
        "item-001",
        frozenset(
            {
                MemoryScopeRef(MemoryScopeKind.USER, "user-001"),
                MemoryScopeRef(MemoryScopeKind.GROUP, "group-001"),
            }
        ),
    )
    context = MemoryRecallContext(
        scopes=frozenset(
            {
                MemoryScopeRef(MemoryScopeKind.USER, "user-002"),
                MemoryScopeRef(MemoryScopeKind.GROUP, "group-002"),
            }
        )
    )

    assert not context.matches(item)


def test_recall_context_allows_global_item_in_empty_context():
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

    context = MemoryRecallContext(
        scopes=frozenset(),
    )

    assert context.matches(item)


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
        scopes=frozenset(
            {
                MemoryScopeRef(
                    MemoryScopeKind.GLOBAL,
                    None,
                )
            }
        )
    )

    assert not context.matches(item)


def test_memory_space_does_not_affect_recall_context_match():
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
    context = MemoryRecallContext(
        scopes=frozenset({user_scope}),
    )

    assert context.matches(first_item)
    assert context.matches(second_item)


@pytest.mark.asyncio
async def test_memory_space_router_selects_one_memory_space():
    user_scope = MemoryScopeRef(
        MemoryScopeKind.USER,
        "user-001",
    )
    accessible_item = create_memory_item(
        "item-001",
        frozenset({user_scope}),
        memory_space_id="space-001",
    )
    other_space_item = create_memory_item(
        "item-002",
        frozenset({user_scope}),
        memory_space_id="space-002",
    )
    router = SimpleMemorySpaceRouter(
        {
            "space-001": SimpleMemoryRetriever([accessible_item]),
            "space-002": SimpleMemoryRetriever([other_space_item]),
        }
    )
    retriever = router.for_space("space-001")

    candidates = await retriever.retrieve(
        [1.0],
        context=MemoryRecallContext(
            scopes=frozenset({user_scope}),
        ),
    )

    assert candidates == [
        MemoryRetrievalCandidate(accessible_item, score=0.0)
    ]
