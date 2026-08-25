from .contracts import (
    MemoryQueryRequest,
    MemoryQueryResult,
)
from .executor import (
    MemoryChangeExecutionInput,
    MemoryChangeExecutionResult,
)
from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryFormationInput,
    MemoryMaterializationInput,
    MemoryRecallContext,
    MemoryReviewInput,
    MemoryScopeKind,
    MemoryScopeRef,
)
from .protocols import (
    MemoryChangeExecutorProtocol,
    MemoryEmbeddingProtocol,
    MemoryExtractorProtocol,
    MemoryMaterializerProtocol,
    MemoryRerankerProtocol,
    MemoryRetrieverProtocol,
    MemoryReviewerProtocol,
)


class MemoryService:
    """Memory 的业务处理类。"""

    def __init__(
        self,
        extractor: MemoryExtractorProtocol | None = None,
        embedder: MemoryEmbeddingProtocol | None = None,
        retriever: MemoryRetrieverProtocol | None = None,
        reranker: MemoryRerankerProtocol | None = None,
        materializer: MemoryMaterializerProtocol | None = None,
        reviewer: MemoryReviewerProtocol | None = None,
        executor: MemoryChangeExecutorProtocol | None = None,
    ) -> None:
        self.extractor = extractor
        self.embedder = embedder
        self.retriever = retriever
        self.reranker = reranker
        self.materializer = materializer
        self.reviewer = reviewer
        self.executor = executor

    async def query(
        self,
        request: MemoryQueryRequest,
    ) -> MemoryQueryResult:
        """执行向量化、检索和重排，返回最终记忆列表。"""

        if self.embedder is None:
            raise RuntimeError("memory embedder is not configured")

        if self.retriever is None:
            raise RuntimeError("memory retriever is not configured")

        if self.reranker is None:
            raise RuntimeError("memory reranker is not configured")

        query_embedding = await self.embedder.embed(request.query_text)
        query_context = MemoryRecallContext(
            scopes=frozenset(
                {
                    MemoryScopeRef(
                        kind=MemoryScopeKind.USER,
                        scope_id=request.user_id,
                    ),
                    MemoryScopeRef(
                        kind=MemoryScopeKind.SESSION,
                        scope_id=request.session_id,
                    ),
                    MemoryScopeRef(
                        kind=MemoryScopeKind.GROUP,
                        scope_id=request.group_id,
                    ),
                }
            )
        )
        candidates = await self.retriever.retrieve(
            query_embedding,
            context=query_context,
        )

        candidates = await self.reranker.rerank(
            request.query_text,
            candidates,
        )

        memories = [candidate.memory for candidate in candidates]

        return MemoryQueryResult(
            query_id=request.query_id,
            user_id=request.user_id,
            session_id=request.session_id,
            group_id=request.group_id,
            memories=memories,
        )

    async def form(
        self,
        input_data: MemoryFormationInput,
    ) -> MemoryChangeExecutionResult:
        """将候选召回、成形、审查并执行为正式 Memory 变更。"""

        if self.embedder is None:
            raise RuntimeError("memory embedder is not configured")

        if self.retriever is None:
            raise RuntimeError("memory retriever is not configured")

        if self.materializer is None:
            raise RuntimeError("memory materializer is not configured")

        if self.reviewer is None:
            raise RuntimeError("memory reviewer is not configured")

        if self.executor is None:
            raise RuntimeError("memory executor is not configured")

        query_embedding = await self.embedder.embed(
            input_data.candidate.content
        )

        retrieval_candidates = await self.retriever.retrieve(
            query_embedding,
            context=input_data.recall_context,
        )

        related_items = tuple(
            candidate.memory
            for candidate in retrieval_candidates
        )

        payload = await self.materializer.materialize(
            MemoryMaterializationInput(
                candidate=input_data.candidate,
                provenance=input_data.provenance,
                recorded_at=input_data.recorded_at,
                related_items=related_items,
            )
        )

        plan = await self.reviewer.review(
            MemoryReviewInput(
                payload=payload,
                related_items=related_items,
            )
        )

        return await self.executor.execute(
            MemoryChangeExecutionInput(
                plan=plan,
                related_items=related_items,
                memory_space_id=input_data.memory_space_id,
                scopes=input_data.scopes,
                operation_id=input_data.operation_id,
            )
        )

    async def extract(
        self,
        input_data: MemoryExtractionInput,
        *,
        summary: str | None,
        recent_messages: list[MemoryExtractionMessage],
    ) -> list[MemoryCandidate]:
        """组装提取上下文并提取长期记忆候选。"""

        if self.extractor is None:
            raise RuntimeError("memory extractor is not configured")

        context = MemoryExtractionContext(
            new_messages=input_data.messages,
            recent_messages=recent_messages,
            summary=summary,
        )

        return await self.extractor.extract(context)
