"""独立 Work Session 的解析与冷恢复流程。"""

from __future__ import annotations

from typing import cast

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
        self._store = store
        # Data 恢复按 Session 合并；列表中的 operation_id 仍分别对应各 AgentRun。
        self._restoring: dict[str, list[ContextWorkRequestData]] = {}

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

        # 同一 Work Session 恢复期间只读取一次 Data，其余请求加入等待列表。
        pending = self._restoring.get(session_id)
        if pending is not None:
            pending.append(request)
            return

        self._restoring[session_id] = [request]
        flow.emit(
            "context.restore.requested",
            ContextRestoreRequestData(session_id),
        )

    async def handle_restore(self, flow: EventFlow) -> None:
        """处理 Data 返回的 Work Session 冷恢复结果，并继续此前暂停 request 的 AgentRun"""

        # session_id 同时定位恢复槽位和 Store 中的唯一 Context。
        result: ContextRestoreResultEventData = flow.payload
        pending = self._restoring.pop(result.session_id, None)
        if pending is None:
            return

        requests = tuple(pending)
        anchor = requests[0]

        # Data 失败属于整个 Session 恢复，所有等待请求收到各自的失败结果。
        if result.status == ContextRestoreStatus.FAILED:
            error = cast(ContextErrorInfo, result.error)
            for request in requests:
                self._fail(flow, request, error.code, error.message)
            return

        # 只有第一个恢复结果负责安装快照；NOT_FOUND 由首个 _ready 创建状态。
        if self._store.is_loaded(result.session_id):
            for request in requests:
                self._ready(flow, request)
            return
        if result.status == ContextRestoreStatus.COMPLETED:
            installed = self._store.install_work_snapshot(
                snapshot=cast(ContextSnapshot, result.snapshot),
                purpose=anchor.purpose,
                work_id=anchor.work_id,
            )
            if not installed:
                for request in requests:
                    self._fail(
                        flow,
                        request,
                        "work_restore_invalid",
                        "Stored work context does not match the requested work identity.",
                    )
                return

        # 每个 Agent 请求仍使用自己的 operation_id 接收 ready/failed。
        for request in requests:
            self._ready(flow, request)

    def _ready(self, flow: EventFlow, request: ContextWorkRequestData) -> None:
        """解析最终 Work 状态并恢复等待中的 AgentRun。"""

        try:
            # 处理 Work Session 的解析与创建, 并返回最终快照
            snapshot, created = self._store.resolve_work(
                request.purpose,
                request.work_id,
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
