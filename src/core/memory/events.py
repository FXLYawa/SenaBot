"""Memory 接入 EventBus 的声明与装配入口。"""

from __future__ import annotations

from core.event import EventFlow, ModuleEventAPI
from core.memory.extraction_flow import MemoryExtractionFlow
from core.memory.contracts import (
    MemoryErrorInfo,
    MemoryQueryFailedEventData,
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryExtractionFailedEventData,
    MemoryExtractionResult,
)
from core.memory.service import MemoryService


class MemoryModule:
    """组装 Memory 公开事件处理器，不暴露内部记忆形成流程。"""

    def __init__(
        self, service: MemoryService, extraction: MemoryExtractionFlow | None = None,
        *,
        extraction_handler_timeout: float | None = None,
    ) -> None:
        self._service = service
        self._extraction = extraction
        self._extraction_handler_timeout = extraction_handler_timeout

    def register(self, events: ModuleEventAPI) -> None:
        """声明查询与提取结果事件，并接入查询入口及内部提取触发器。"""

        event_definitions = (
            ("memory.query.requested", MemoryQueryRequest),
            ("memory.query.completed", MemoryQueryResult),
            ("memory.query.failed", MemoryQueryFailedEventData),
            ("memory.extraction.completed", MemoryExtractionResult),
            ("memory.extraction.failed", MemoryExtractionFailedEventData),
        )
        subscriptions = (
            (
                "memory.query.requested",
                self._handle_query_requested,
                "memory.query_requested",
            ),
        )

        if self._extraction is not None:
            # 上下文变化进入触发判断，读取结果接续当前批次的提取与落库。
            subscriptions += (
                (
                    "context.state.changed",
                    self._extraction.handle_context_changed,
                    "memory.extraction_context_changed",
                ),
                (
                    "context.read.resolved",
                    self._extraction.handle_context_read,
                    "memory.extraction_context_read",
                    self._extraction_handler_timeout,
                ),
            )

        for event_type, payload_type in event_definitions:
            events.register(event_type, payload_type=payload_type)
        for subscription in subscriptions:
            events.subscribe(*subscription)

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
