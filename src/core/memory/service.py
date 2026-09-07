from core.common import utc_now
import math
from dataclasses import dataclass, replace

from core.context import ContextReadView

from .contracts import (
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryExtractionResult,
)
from .converters import (
    context_entry_provenance,
    extraction_scopes,
    to_extraction_messages,
    to_extraction_summary,
)
from .executor import (
    MemoryChangeExecutionInput,
    MemoryChangeExecutionResult,
)
from .models import (
    MemoryExtractionContext,
    MemoryFormationInput,
    MemoryMaterializationInput,
    MemoryRecallContext,
    MemoryRetrievalCandidate,
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

    scopes = {
        MemoryScopeRef(MemoryScopeKind.USER, request.user_id),
        MemoryScopeRef(MemoryScopeKind.SESSION, request.session_id),
    }
    if request.group_id.strip():
        scopes.add(MemoryScopeRef(MemoryScopeKind.GROUP, request.group_id))
    return MemoryRecallContext(scopes=frozenset(scopes))


@dataclass(frozen=True, slots=True)
class MemoryRecallPolicy:
    """普通查询与 Formation 查重各自的候选过滤策略。"""

    query_min_score: float = 0.25
    query_limit: int = 5
    formation_min_score: float = 0.4
    formation_limit: int = 20

    def __post_init__(self) -> None:
        if self.query_limit <= 0 or self.formation_limit <= 0:
            raise ValueError("memory recall limits must be positive")
        for score in (self.query_min_score, self.formation_min_score):
            if (
                isinstance(score, bool)
                or not math.isfinite(score)
                or not -1 <= score <= 1
            ):
                raise ValueError("memory recall minimum scores must be between -1 and 1")


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
        recall_policy: MemoryRecallPolicy | None = None,
    ) -> None:
        self.extractor = extractor
        self.embedder = embedder
        self.memory_spaces = memory_spaces
        self.reranker = reranker
        self.materializer = materializer
        self.reviewer = reviewer
        self.executor = executor
        self.recall_policy = recall_policy or MemoryRecallPolicy()

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
        candidates = self._filter_candidates(
            candidates,
            min_score=self.recall_policy.query_min_score,
            limit=self.recall_policy.query_limit,
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
        retrieval_candidates = self._filter_candidates(
            retrieval_candidates,
            min_score=self.recall_policy.formation_min_score,
            limit=self.recall_policy.formation_limit,
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

    @staticmethod
    def _filter_candidates(
        candidates: list[MemoryRetrievalCandidate],
        *,
        min_score: float,
        limit: int,
    ) -> list[MemoryRetrievalCandidate]:
        return [candidate for candidate in candidates if candidate.score >= min_score][
            :limit
        ]

    async def extract_and_store(
        self,
        *,
        operation_id: str,
        memory_space_id: str,
        user_id: str,
        context: ContextReadView,
    ) -> MemoryExtractionResult:
        """完整处理一个原始范围；所有触发来源共用提取、形成和落库流程。"""

        # 将目标原文转换为待提取消息，将前置摘要和原文作为背景，一起交给提取器。
        candidates = await self.extractor.extract(
            MemoryExtractionContext(
                new_messages=to_extraction_messages(context.entries),
                provenance=context_entry_provenance(context.entries),
                summary=to_extraction_summary(context.summaries),
                recent_messages=to_extraction_messages(context.preceding_entries),
            ),
        )
        # 根据候选引用的消息 ID 查回目标条目，为每个候选构造对应的条目和事件来源。
        entries_by_id = {entry.entry_id: entry for entry in context.entries}
        candidates = [
            replace(
                candidate,
                provenance=context_entry_provenance(tuple(
                    entries_by_id[entry_id] for entry_id in candidate.source_message_ids
                )),
            )
            for candidate in candidates
        ]
        # 为本批候选准备形成阶段的召回范围、记忆归属和统一记录时间。
        scopes = extraction_scopes(user_id, context.session)
        recall_context = MemoryRecallContext(scopes=scopes)
        recorded_at = utc_now()
        execution_results: list[MemoryChangeExecutionResult] = []

        # 逐个形成候选记忆：召回相关记忆、确定类型与变更计划，再执行写入。
        for candidate in candidates:
            execution_results.append(
                await self.form(
                    MemoryFormationInput(
                        candidate=candidate,
                        recorded_at=recorded_at,
                        recall_context=recall_context,
                        memory_space_id=memory_space_id,
                        scopes=scopes,
                        operation_id=operation_id,
                    )
                )
            )

        # 汇总新增和更新的记忆 ID，连同本批完成边界返回给协调流程保存进度。
        return MemoryExtractionResult(
            operation_id=operation_id,
            memory_space_id=memory_space_id,
            session_id=context.session.session_id,
            processed_through_sequence=context.through_sequence,
            added_item_ids=tuple(
                item.item_id for result in execution_results for item in result.added_items
            ),
            updated_item_ids=tuple(
                item.item_id for result in execution_results for item in result.updated_items
            ),
        )
