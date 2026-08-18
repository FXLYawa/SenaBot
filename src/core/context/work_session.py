"""独立 Work Session 的解析与冷恢复流程。"""

from __future__ import annotations

from typing import cast

from core.context.common import new_id
from core.context.contracts import (
    ContextErrorInfo,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextRestoreStatus,
    ContextSnapshot,
    ContextStateChangedEventData,
    ContextWorkFailedEventData,
    ContextWorkReadyEventData,
    ContextWorkRequestData,
)
from core.context.identity import work_session_id
from core.context.store import ContextStateStore
from core.event import EventFlow


class WorkSessionFlow:
    """通过 Work 身份解析 Session, 在有需要时请求冷恢复并返回最终 Work Session 快照"""

    def __init__(self, store: ContextStateStore) -> None:
        self._store = store # 
        # restore operation_id 指向原始 Work 请求，业务关联仍使用请求自己的 operation_id。
        self._pending: dict[str, ContextWorkRequestData] = {}

    async def handle_request(self, flow: EventFlow) -> None:
        """解析 Work Session; 尚未加载时请求 Data 冷恢复"""

        request: ContextWorkRequestData = flow.payload
        # 解析 Work Session ID 并检查是否已加载
        try:
            session_id = work_session_id(request.purpose, request.work_id)
        except ValueError as exc:
            self._fail(flow, request, "work_identity_invalid", str(exc))
            return
        if self._store.is_loaded(session_id):
            # 直接返回已加载的 Work Session 快照
            self._ready(flow, request)
            return

        # 还未加载的 Work Session 需要请求冷恢复
        restore_id = new_id("op_context_restore")
        self._pending[restore_id] = request
        flow.emit(
            "context.restore.requested",
            ContextRestoreRequestData(restore_id, session_id),
        )

    async def handle_restore(self, flow: EventFlow) -> None:
        """处理 Data 返回的 Work Session 冷恢复结果，并继续此前暂停 request 的 AgentRun"""

        # 解析恢复结果并检查是否与原始请求匹配
        result: ContextRestoreResultEventData = flow.payload
        request = self._pending.pop(result.operation_id, None)
        if request is None:
            return
        expected_id = work_session_id(request.purpose, request.work_id)
        if result.session_id != expected_id:
            self._fail(
                flow,
                request,
                "work_restore_invalid",
                "Work restore returned a mismatched session identity.",
            )
            return
        # 处理恢复结果: 失败则返回错误, 已加载则直接返回, 完成则安装快照并返回
        if result.status == ContextRestoreStatus.FAILED:
            error = cast(ContextErrorInfo, result.error)
            self._fail(flow, request, error.code, error.message)
            return
        if self._store.is_loaded(result.session_id):
            self._ready(flow, request)
            return
        if result.status == ContextRestoreStatus.COMPLETED:
            installed = self._store.install_work_snapshot(
                snapshot=cast(ContextSnapshot, result.snapshot),
                purpose=request.purpose,
                work_id=request.work_id,
                parent_session_id=request.parent_session_id,
            )
            if not installed:
                self._fail(
                    flow,
                    request,
                    "work_restore_invalid",
                    "Stored work context does not match the requested work identity.",
                )
                return
        self._ready(flow, request)

    def _ready(self, flow: EventFlow, request: ContextWorkRequestData) -> None:
        """解析最终 Work 状态并恢复等待中的 AgentRun。"""

        try:
            # 处理 Work Session 的解析与创建, 并返回最终快照
            snapshot, created = self._store.resolve_work(
                request.purpose,
                request.work_id,
                request.parent_session_id,
            )
        except (LookupError, ValueError) as exc:
            self._fail(flow, request, "work_session_unavailable", str(exc))
            return
        if created:
            # 如果首次创建，则发布 context.state.changed 事件 (Data消费)
            flow.emit(
                "context.state.changed",
                ContextStateChangedEventData.from_snapshot(snapshot),
            )
        # 返回最终 Work Session 快照给等待中的 AgentRun
        flow.emit(
            "context.work.ready",
            ContextWorkReadyEventData(
                request.operation_id,
                request.work_id,
                snapshot.session.session_id,
            ),
        )

    @staticmethod
    def _fail(
        flow: EventFlow,
        request: ContextWorkRequestData,
        code: str,
        message: str,
    ) -> None:
        """将 Work 解析失败作为结构化事件返回给等待中的 AgentRun。"""

        flow.emit(
            "context.work.failed",
            ContextWorkFailedEventData(
                request.operation_id,
                request.work_id,
                ContextErrorInfo(code, message),
            ),
        )
