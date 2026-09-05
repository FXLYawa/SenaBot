"""Data 接入 EventBus 的声明与装配入口。"""

from __future__ import annotations

from core.context.contracts import (
    ContextErrorInfo,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextRestoreStatus,
    ContextStateChangedEventData,
)
from core.data.context import ContextRepositoryProtocol
from core.event import EventFlow, ModuleEventAPI


class DataModule:
    """MVP Data 事件适配器。"""

    def __init__(self, context_repository: ContextRepositoryProtocol) -> None:
        self._context_repository = context_repository

    def register(self, events: ModuleEventAPI) -> None:
        """订阅 Context 的恢复请求和状态变化。"""

        events.subscribe(
            "context.restore.requested",
            self._handle_context_restore_requested,
            handler_id="data.context_restore_requested",
        )
        events.subscribe(
            "context.state.changed",
            self._handle_context_state_changed,
            handler_id="data.context_state_changed",
        )

    async def _handle_context_restore_requested(self, flow: EventFlow) -> None:
        """响应 Context 冷恢复请求。"""

        request: ContextRestoreRequestData = flow.payload
        try:
            snapshot = self._context_repository.load_context(request.session_id)
        except Exception as error:
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    session_id=request.session_id,
                    status=ContextRestoreStatus.FAILED,
                    error=ContextErrorInfo(
                        code="data_context_restore_failed",
                        message=str(error),
                    ),
                ),
            )
            return

        if snapshot is None:
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    session_id=request.session_id,
                    status=ContextRestoreStatus.NOT_FOUND,
                ),
            )
            return

        flow.emit(
            "context.restore.resolved",
            ContextRestoreResultEventData(
                session_id=request.session_id,
                status=ContextRestoreStatus.COMPLETED,
                snapshot=snapshot,
            ),
        )

    async def _handle_context_state_changed(self, flow: EventFlow) -> None:
        """持久化 Context 增量状态变化。"""

        change: ContextStateChangedEventData = flow.payload
        self._context_repository.save_context_change(change)
