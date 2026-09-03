"""Memory 接入 EventBus 的声明与装配入口。"""

from __future__ import annotations

from core.event import EventFlow, ModuleEventAPI
from core.memory.contracts import (
    MemoryErrorInfo,
    MemoryQueryFailedEventData,
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryWriteFailedEventData,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from core.memory.service import MemoryService


class MemoryModule:
    """组装 Memory 公开事件处理器，不暴露内部记忆形成流程。"""

    def __init__(self, service: MemoryService) -> None:
        self._service = service

    def register(self, events: ModuleEventAPI) -> None:
        """声明 Memory 拥有的事件，并订阅查询入口事件。"""

        event_definitions = (
            ("memory.query.requested", MemoryQueryRequest),
            ("memory.query.completed", MemoryQueryResult),
            ("memory.query.failed", MemoryQueryFailedEventData),
            ("memory.write.requested", MemoryWriteRequest),
            ("memory.write.completed", MemoryWriteResult),
            ("memory.write.failed", MemoryWriteFailedEventData),
        )
        subscriptions = (
            (
                "memory.query.requested",
                self._handle_query_requested,
                "memory.query_requested",
            ),
            (
                "memory.write.requested",
                self._handle_write_requested,
                "memory.write_requested",
            ),
        )

        for event_type, payload_type in event_definitions:
            events.register(event_type, payload_type=payload_type)
        for event_pattern, handler, handler_id in subscriptions:
            events.subscribe(event_pattern, handler, handler_id=handler_id)

    async def _handle_query_requested(self, flow: EventFlow) -> None:
        """把公开查询事件适配到 MemoryService.query。"""

        request: MemoryQueryRequest = flow.payload
        try:
            result = await self._service.query(request)
        except Exception as error:
            flow.emit(
                "memory.query.failed",
                MemoryQueryFailedEventData(
                    query_id=request.query_id,
                    memory_space_id=request.memory_space_id,
                    error=MemoryErrorInfo(
                        code=type(error).__name__,
                        message=str(error),
                    ),
                ),
            )
            return

        flow.emit("memory.query.completed", result)

    async def _handle_write_requested(self, flow: EventFlow) -> None:
        """把公开写入事件适配到 MemoryService.write。"""

        request: MemoryWriteRequest = flow.payload
        try:
            result = await self._service.write(request)
        except Exception as error:
            flow.emit(
                "memory.write.failed",
                MemoryWriteFailedEventData(
                    operation_id=request.operation_id,
                    memory_space_id=request.memory_space_id,
                    error=MemoryErrorInfo(
                        code=type(error).__name__,
                        message=str(error),
                    ),
                ),
            )
            return

        flow.emit("memory.write.completed", result)
