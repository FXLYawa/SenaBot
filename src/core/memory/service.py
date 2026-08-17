from datetime import datetime, timezone
from uuid import uuid4

from . import models
from .contracts import (
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from .protocols import (
    MemoryEmbeddingProtocol,
    MemoryRepositoryProtocol,
    MemoryRerankerProtocol,
    MemoryRetrieverProtocol,
)


class MemoryService:
    """Memory的业务处理类"""

    def __init__(
        self,
        repository: MemoryRepositoryProtocol,
        embedder: MemoryEmbeddingProtocol | None = None,
        retriever: MemoryRetrieverProtocol | None = None,
        reranker: MemoryRerankerProtocol | None = None,
    ) -> None:
        self.repository = repository
        self.embedder = embedder
        self.retriever = retriever
        self.reranker = reranker

    async def query(
        self,
        request: MemoryQueryRequest,
    ) -> MemoryQueryResult:
        """
        负责查询的主链路,即向量化->检索->重排->选出最终结果
        还未实现query rewrite,未来可加入
        """
        if self.embedder is None:
            raise RuntimeError("memory embedder is not configured")

        if self.retriever is None:
            raise RuntimeError("memory retriever is not configured")

        if self.reranker is None:
            raise RuntimeError("memory reranker is not configured")

        # 得到向量化结果
        query_embedding = await self.embedder.embed(request.query_text)

        # 得到候选结果
        candidates = await self.retriever.retrieve(
            query_embedding,
            user_id=request.user_id,
            session_id=request.session_id,
            group_id=request.group_id,
        )

        # 进行重排序
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
        # 检查相同操作是否已经执行
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

