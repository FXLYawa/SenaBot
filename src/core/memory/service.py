from uuid import uuid4
from datetime import datetime, timezone

from . import models
from .models import MemoryQueryCriteria
from .contracts import MemoryWriteRequest,MemoryQueryRequest,MemoryQueryResult,MemoryWriteResult
from .protocols import MemoryRepositoryProtocol

class MemoryService:
    """Memory的业务处理类"""

    def __init__(self,repository: MemoryRepositoryProtocol,):
        self.repository = repository

    async def query(self,request:MemoryQueryRequest) -> MemoryQueryResult:

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

    async def write(self,request: MemoryWriteRequest) -> MemoryWriteResult:

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

        existing_memory = (
            await self.repository.find_by_source_event_id(
                request.source_event_id
            )
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

