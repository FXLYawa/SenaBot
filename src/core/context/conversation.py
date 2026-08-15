"""普通 Conversation Session 的输入与冷恢复流程"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import cast

from core.context.body import BodyInputEventData
from core.context.common import new_id, ConversationScope
from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextEntryDraft,
    ContextEntryType,
    ContextErrorInfo,
    ContextInputFailedEventData,
    ContextPreparedEventData,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextSnapshot,
)
from core.context.entry_appender import EntryAppender
from core.context.identity import conversation_session_id
from core.context.state import AppendResult
from core.context.store import ContextStateStore
from core.event import EventClient, EventEnvelope, EventFlow


@dataclass(frozen=True, slots=True)
class _PendingInput:
    """恢复期间暂存的输入及其原始事件链。"""

    parent: EventEnvelope
    payload: BodyInputEventData


@dataclass(slots=True)
class _PendingRestore:
    """同一 Conversation Session 共享的一次恢复及有序输入批次。"""

    operation_id: str
    scope: ConversationScope
    inputs: list[_PendingInput]


class ConversationFlow:
    """解析 Conversation Session、冷恢复并准备 Agent 上下文窗口。"""

    def __init__(
        self,
        store: ContextStateStore,
        appender: EntryAppender,
        events: EventClient,
    ) -> None:
        self._store = store # ContextStateStore 管理已加载的 Session 集合
        self._appender = appender # 用于追加条目并发布状态变更事件
        self._events = events # 用于在当前事件链上发布追加和准备事件
        # Session 是恢复槽位；同一 Session 只发起一个 I/O，请求期间的输入按到达顺序排队。
        self._restoring: dict[str, _PendingRestore] = {} # session_id -> _PendingRestore
        self._logger = logging.getLogger("senabot.context")

    async def handle_input(self, flow: EventFlow) -> None:
        """解析输入所属 Session; 未加载时先请求 Data 冷恢复"""

        # 解析输入所属的 Conversation Session
        payload: BodyInputEventData = flow.payload
        session_id = conversation_session_id(payload.conversation_scope)
        if self._store.is_loaded(session_id):
            # Session 已加载，直接追加输入并发布 Agent 工作窗口
            self._accept(flow, payload, session_id)
            return
        # Session 尚未加载，先暂存输入并请求 Data 冷恢复
        pending_input = _PendingInput(flow.envelope, payload)
        pending = self._restoring.get(session_id)
        if pending is not None:
            pending.inputs.append(pending_input)
            return
        # 首次请求恢复时，生成唯一 operation_id 以便 Data 返回结果时匹配原始请求
        operation_id = new_id("op_context_restore")
        self._restoring[session_id] = _PendingRestore(
            operation_id,
            payload.conversation_scope,
            [pending_input],
        )
        flow.emit(
            "context.restore.requested",
            ContextRestoreRequestData(operation_id, session_id),
        )

    async def handle_restore(self, flow: EventFlow) -> None:
        """恢复或初始化 Conversation Session，然后继续原输入流程。"""

        result: ContextRestoreResultEventData = flow.payload
        matched = next(
            (
                (session_id, pending)
                for session_id, pending in self._restoring.items()
                if pending.operation_id == result.operation_id
            ),
            None,
        )
        if matched is None:
            return
        session_id, pending = matched
        self._restoring.pop(session_id)

        error = self._apply_restore_result(result, session_id, pending.scope)
        if error is not None:
            await self._fail_pending(pending, session_id, error)
            return
        await self._resume_pending_inputs(pending, session_id)

    def _apply_restore_result(
        self,
        result: ContextRestoreResultEventData,
        session_id: str,
        scope: ConversationScope,
    ) -> ContextErrorInfo | None:
        """校验并应用 Data 恢复结果，不发布后续事件。"""

        if result.session_id != session_id:
            return ContextErrorInfo(
                "context_restore_invalid",
                "Context restore returned a mismatched session identity.",
            )
        if result.status == "failed":
            return cast(ContextErrorInfo, result.error)

        if not self._store.is_loaded(session_id):
            if result.status == "completed":
                installed = self._store.install_conversation_snapshot(
                    cast(ContextSnapshot, result.snapshot),
                    scope,
                )
                if not installed:
                    return ContextErrorInfo(
                        "context_restore_invalid",
                        "Stored context does not match the requested conversation scope.",
                    )
            else:
                self._store.initialize_conversation(scope)
        return None

    async def _resume_pending_inputs(
        self,
        pending: _PendingRestore,
        session_id: str,
    ) -> None:
        """先固定恢复批次的写入顺序，再恢复每条输入的独立事件链。"""

        # 先完成整个批次的同步追加，避免发布事件的 await 点让新输入插入批次中间。
        accepted: list[
            tuple[_PendingInput, AppendResult, ContextPreparedEventData]
        ] = []
        rejected: list[tuple[_PendingInput, ContextErrorInfo]] = []
        for item in pending.inputs:
            try:
                appended, prepared = self._append_input(
                    item.payload,
                    item.parent.event_id,
                    session_id,
                )
            except LookupError as exc:
                rejected.append(
                    (
                        item,
                        ContextErrorInfo("context_append_failed", str(exc)),
                    )
                )
            else:
                accepted.append((item, appended, prepared))

        # 状态顺序确定后，每条输入再沿自己的 parent envelope 发布，保留独立
        # trace/request_id；后续 Agent 协调仍可依据 trigger sequence 判断新旧。
        for item, appended, prepared in accepted:
            await self._appender.publish_from(self._events, item.parent, appended)
            await self._events.emit(item.parent, "context.prepared", prepared)
        for item, error in rejected:
            await self._fail_from(
                item.parent,
                session_id,
                error,
            )

    def _accept(
        self,
        flow: EventFlow,
        payload: BodyInputEventData,
        session_id: str,
    ) -> None:
        """追加已加载 Session 的实时输入，并发布 Agent 工作窗口。"""

        source_event_id = flow.envelope.event_id
        try:
            result, prepared = self._append_input(
                payload,
                source_event_id,
                session_id,
            )
        except LookupError as exc:
            self._fail(
                flow,
                session_id,
                ContextErrorInfo("context_append_failed", str(exc)),
            )
            return
        self._appender.publish(flow, result)
        flow.emit("context.prepared", prepared)

    def _append_input(
        self,
        payload: BodyInputEventData,
        source_event_id: str,
        session_id: str,
    ) -> tuple[AppendResult, ContextPreparedEventData]:
        """完成单条输入的状态追加，并构造与该 sequence 对应的只读快照。"""

        result = self._appender.append(
            session_id,
            (
                ContextEntryDraft(
                    entry_type=ContextEntryType.USER_MESSAGE,
                    actor=ContextActorRef(
                        actor_type=ContextActorType.USER,
                        actor_id=payload.source.user_id,
                        display_name=payload.source.display_name,
                    ),
                    content=payload.content,
                    source_event_id=source_event_id,
                ),
            ),
        )
        trigger = result.entries[0]
        return result, ContextPreparedEventData(
            session_id=session_id,
            trigger_event_id=source_event_id,
            trigger_entry_id=trigger.entry_id,
            entries=result.snapshot.entries,
            summaries=result.snapshot.summaries,
            output_route=payload.output_route,
            source=payload.source,
            scene=payload.conversation_scope.scene,
            interaction=payload.interaction,
            reply_to_message_id=payload.reply_target_id,
        )

    async def _fail_pending(
        self,
        pending: _PendingRestore,
        session_id: str,
        error: ContextErrorInfo,
    ) -> None:
        """让恢复批次中的每个调用方都收到属于自己 trace 的失败事实。"""
        # 等Event添加错误逻辑后应该交给event去记录和重新发送，而不是调用方自行判断

        self._log_failure(session_id, error)
        for item in pending.inputs:
            await self._events.emit(
                item.parent,
                "context.input.failed",
                ContextInputFailedEventData(session_id, item.parent.event_id, error),
            )

    async def _fail_from(
        self,
        parent: EventEnvelope,
        session_id: str,
        error: ContextErrorInfo,
    ) -> None:
        self._log_failure(session_id, error)
        await self._events.emit(
            parent,
            "context.input.failed",
            ContextInputFailedEventData(session_id, parent.event_id, error),
        )

    def _fail(
        self,
        flow: EventFlow,
        session_id: str,
        error: ContextErrorInfo,
    ) -> None:
        """保留可观察失败事实，不继续产生 ``context.prepared``。"""

        self._log_failure(session_id, error)
        flow.emit(
            "context.input.failed",
            ContextInputFailedEventData(session_id, flow.envelope.event_id, error),
        )

    def _log_failure(self, session_id: str, error: ContextErrorInfo) -> None:
        # 记录失败事实，便于追踪和排查问题, 后续应该要换成依赖EventBus的日志系统
        self._logger.error(
            "Context input rejected: session=%s code=%s",
            session_id,
            error.code,
        )
