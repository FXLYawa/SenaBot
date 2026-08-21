from datetime import datetime, timezone
from uuid import uuid4

from . import models
from .contracts import (
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from .models import (
    Memory,
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryQueryCriteria,
    MemoryUpdateAction,
    MemoryUpdateDecision,
    MemoryUpdateInput,
)
from .protocols import (
    MemoryExtractorProtocol,
    MemoryRepositoryProtocol,
    MemoryUpdaterProtocol,
)


class MemoryService:
    """Memory的业务处理类"""

    def __init__(
      self,
      repository: MemoryRepositoryProtocol,
      extractor: MemoryExtractorProtocol | None = None,
      updater: MemoryUpdaterProtocol | None = None,
      embedder: MemoryEmbeddingProtocol | None = None,
      retriever: MemoryRetrieverProtocol | None = None,
      reranker: MemoryRerankerProtocol | None = None,
    ) -> None:
      self.repository = repository
      self.extractor = extractor
      self.updater = updater
      self.embedder = embedder
      self.retriever = retriever
      self.reranker = reranker

    async def query(
      self,
      request: MemoryQueryRequest,
    ) ->  MemoryQueryResult:
      """
      负责查询的主链路，即向量化 -> 检索 -> 重排 -> 选出最终结果。
      """
      if self.embedder is None:
          raise RuntimeError("memory embedder is not configured")

      if self.retriever is None:
          raise RuntimeError("memory retriever is not configured")

      if self.reranker is None:
          raise RuntimeError("memory reranker is not configured")

      query_embedding = await self.embedder.embed(request.query_text)

      candidates = await self.retriever.retrieve(
          query_embedding,
          user_id=request.user_id,
          session_id=request.session_id,
          group_id=request.group_id,
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

    async def write(
        self,
        request: MemoryWriteRequest,
    ) -> MemoryWriteResult:
      """写入长期记忆并保证来源事件与操作的幂等性."""

     existing_memory = await self.repository.find_by_operation_id(
         request.operation_id
      )

        if existing_memory is not None:
            return MemoryWriteResult(
                operation_id=request.operation_id,
                group_id=request.group_id,
                session_id=request.session_id,
                user_id=request.user_id,
                memory_id=existing_memory.memory_id,
            )

          existing_memory = await self.repository.find_by_source_event_id(
            request.source_event_id
        )

          if existing_memory is not None:
            return MemoryWriteResult(
                operation_id=request.operation_id,
                group_id=request.group_id,
                session_id=request.session_id,
                user_id=request.user_id,
                memory_id=existing_memory.memory_id,
            )

          memory_id = str(uuid4())
          current_time = datetime.now(timezone.utc)

          memory = models.Memory(
            memory_id=memory_id,
            content=request.write_text,
            created_at=current_time,
            updated_at=current_time,
            user_id=request.user_id,
            session_id=request.session_id,
            group_id=request.group_id,
            source_event_id=request.source_event_id,
            operation_id=request.operation_id,
            metadata={},
          )

          saved_memory = await self.repository.save(memory)

          return MemoryWriteResult(
            operation_id=request.operation_id,
            group_id=request.group_id,
            session_id=request.session_id,
            user_id=request.user_id,
            memory_id=saved_memory.memory_id,
          )

    async def extract(
        self,
        input_data: MemoryExtractionInput,
        *,
        summary: str | None,
        recent_messages: list[MemoryExtractionMessage],
    ) -> list[MemoryCandidate]:
        """
        提取记忆阶段的主链路实现
        """
        if self.extractor is None:
            raise RuntimeError("memory extractor is not configured")

        context = MemoryExtractionContext(
            new_messages=input_data.messages,
            recent_messages=recent_messages,
            summary=summary,
        )

        return await self.extractor.extract(context)

    async def _apply_decision(
        self,
        input_data: MemoryUpdateInput,
        decision: MemoryUpdateDecision,
        existing_memories: list[Memory],
    ) -> Memory | None:
        """根据更新决策执行持久化操作。"""

        if decision.action is MemoryUpdateAction.ADD:
            current_time = datetime.now(timezone.utc)

            memory = Memory(
                memory_id=str(uuid4()),
                content=decision.content,
                created_at=current_time,
                updated_at=current_time,
                operation_id=input_data.operation_id,
                user_id=input_data.user_id,
                session_id=input_data.session_id,
                group_id=input_data.group_id,
                source_event_id=input_data.source_event_id,
                metadata=input_data.candidate.metadata.copy(),
            )

            return await self.repository.save(memory)

        if decision.action is MemoryUpdateAction.UPDATE:
            target = next(
                (
                    memory
                    for memory in existing_memories
                    if memory.memory_id == decision.target_memory_id
                ),
                None,
            )

            if target is None:
                raise ValueError("target memory not found for UPDATE")

            updated_memory = Memory(
                memory_id=target.memory_id,
                content=decision.content,
                created_at=target.created_at,
                updated_at=datetime.now(timezone.utc),
                operation_id=input_data.operation_id,
                user_id=input_data.user_id,
                session_id=input_data.session_id,
                group_id=input_data.group_id,
                source_event_id=input_data.source_event_id,
                metadata={
                    **target.metadata,
                    **input_data.candidate.metadata,
                },
            )

            return await self.repository.update(updated_memory)

        if decision.action is MemoryUpdateAction.DELETE:
            await self.repository.delete(decision.target_memory_id)
            return None

        if decision.action is MemoryUpdateAction.NONE:
            return None

        raise ValueError("unsupported memory update action")

    async def review_and_update(
        self,
        input_data: MemoryUpdateInput,
    ) -> MemoryUpdateDecision:
        """审查候选记忆并执行更新决策。

        MVP 中 operation_id 仅作为操作来源标识；本流程暂不保证重试幂等。
        """
        if self.updater is None:
            raise RuntimeError("memory updater is not configured")

        criteria = MemoryQueryCriteria(
            # TODO: 正式 Repository 接入后使用显式 scope 查询或语义 Top-K，
            # 不再依赖空 query_text 的包含语义。
            query_text="",
            user_id=input_data.user_id,
            session_id=input_data.session_id,
            group_id=input_data.group_id,
        )

        existing_memories = await self.repository.query(criteria)

        decision = await self.updater.decide(
            input_data.candidate,
            existing_memories,
        )

        await self._apply_decision(
            input_data,
            decision,
            existing_memories,
        )

        return decision
