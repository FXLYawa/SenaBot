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
    MemoryReviewerProtocol,
    MemorySpaceRouterProtocol,
)


def _build_query_recall_context(
    request: MemoryQueryRequest,
) -> MemoryRecallContext:
    """根据查询请求构造当前可召回的 Scope 边界。"""

    return MemoryRecallContext(
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


class MemoryService:
    """Memory 的业务处理类。"""

    def __init__(
        self,
        extractor: MemoryExtractorProtocol,
        embedder: MemoryEmbeddingProtocol,
        memory_spaces: MemorySpaceRouterProtocol,
        reranker: MemoryRerankerProtocol,
        materializer: MemoryMaterializerProtocol,
        reviewer: MemoryReviewerProtocol,
        executor: MemoryChangeExecutorProtocol,
    ) -> None:
        self.extractor = extractor
        self.embedder = embedder
        self.memory_spaces = memory_spaces
        self.reranker = reranker
        self.materializer = materializer
        self.reviewer = reviewer
        self.executor = executor

    async def query(
        self,
        request: MemoryQueryRequest,
    ) -> MemoryQueryResult:
        """执行向量化、检索和重排，返回最终记忆列表。"""

        # 向量化输入
        query_embedding = await self.embedder.embed(request.query_text)

        # 得到允许召回的边界
        query_context = _build_query_recall_context(request)

        # 根据 Memory Space 路由到对应的记忆空间后检索。
        retriever = self.memory_spaces.for_space(request.memory_space_id)
        candidates = await retriever.retrieve(
            query_embedding,
            context=query_context,
        )

        # 进行精度更高的重排序,得到最终结果
        candidates = await self.reranker.rerank(
            request.query_text,
            candidates,
        )

        memories = [candidate.memory for candidate in candidates]

        # 返回最终查询结果
        return MemoryQueryResult(
            query_id=request.query_id,
            memory_space_id=request.memory_space_id,
            user_id=request.user_id,
            session_id=request.session_id,
            group_id=request.group_id,
            memories=memories,
        )

    async def form(
        self,
        input_data: MemoryFormationInput,
    ) -> MemoryChangeExecutionResult:
        """
        接收Extraction,即记忆提取阶段的记忆
        召回相关记忆
        将相关记忆和候选交给materialize,得到Payload,即记忆的类型
        根据Payload和相关记忆决定执行什么决策
        正式入库
        """

        # 向量化输入
        query_embedding = await self.embedder.embed(input_data.candidate.content)

        # 根据 Memory Space 路由到对应的记忆空间后检索相关记忆。
        retriever = self.memory_spaces.for_space(input_data.memory_space_id)
        retrieval_candidates = await retriever.retrieve(
            query_embedding,
            context=input_data.recall_context,
        )

        # 得到相关记忆集合
        related_items = tuple(candidate.memory for candidate in retrieval_candidates)

        # 得到 payload
        payload = await self.materializer.materialize(
            MemoryMaterializationInput(
                candidate=input_data.candidate,
                recorded_at=input_data.recorded_at,
                related_items=related_items,
            )
        )

        # 确定执行计划
        plan = await self.reviewer.review(
            MemoryReviewInput(
                payload=payload,
                related_items=related_items,
            )
        )

        # 执行正式入库
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

        # 得到组装后的上下文
        context = MemoryExtractionContext(
            new_messages=input_data.messages,
            recent_messages=recent_messages,
            summary=summary,
            provenance=input_data.provenance,
        )

        return await self.extractor.extract(context)
