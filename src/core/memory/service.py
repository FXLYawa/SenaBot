from datetime import datetime, timezone
from uuid import uuid4

from . import models
from .contracts import MemoryQueryRequest, MemoryQueryResult, MemoryWriteRequest, MemoryWriteResult
from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryQueryCriteria,
)
from .protocols import MemoryExtractorProtocol, MemoryRepositoryProtocol


class MemoryService:
    """Memory的业务处理类"""

    def __init__(
        self,
        repository: MemoryRepositoryProtocol,
        extractor: MemoryExtractorProtocol | None = None,
    ):
        self.repository = repository
        self.extractor = extractor

    async def query(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        """Memory查询记忆的函数,当前为简单实现,并不包含向量数据库查询"""

        criteria = MemoryQueryCriteria(
            query_text=request.query_text,
            user_id=request.user_id,
            session_id=request.session_id,
            group_id=request.group_id,
        )

        memories = await self.repository.query(criteria)

        return MemoryQueryResult(
            query_id=request.query_id,
            user_id=request.user_id,
            session_id=request.session_id,
            group_id=request.group_id,
            memories=memories,
        )

    async def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Memory写入记忆,当前为简单写入JSON,并不包含向量数据库写入"""

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
