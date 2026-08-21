"""Context 接入 EventBus 的声明与装配入口。"""

from __future__ import annotations

from core.context.compaction import CompactionFlow
from core.context.compression import CompactionRequestData, ContextCompressor
from core.context.contracts import (
    ContextAppendRequestData,
    ContextHistoryRequestData,
    ContextHistoryResultEventData,
    ContextInputFailedEventData,
    ContextPreparedEventData,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextStateChangedEventData,
    ContextWorkFailedEventData,
    ContextWorkReadyEventData,
    ContextWorkRequestData,
)
from core.context.conversation import ConversationFlow
from core.context.entry_appender import EntryAppender
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.context.work_session import WorkSessionFlow
from core.event import EventFlow, ModuleEventAPI


class ContextModule:
    """组装 Context 内部流程，并提供唯一的事件注册 Interface。"""

    def __init__(
        self,
        store: ContextStateStore,
        window: ContextWindowPolicy,
        compressor: ContextCompressor | None = None,
    ) -> None:
        compaction = CompactionFlow(store, window, compressor)
        appender = EntryAppender(store, compaction)
        self._store = store # 
        self._work = WorkSessionFlow(store)
        self._compaction = compaction
        self._appender = appender

    def register(self, events: ModuleEventAPI) -> None:
        """声明 Context 拥有的事件，并订阅输入、恢复和内部工作事件。"""

        conversation = ConversationFlow(self._store, self._appender, events)
        # event 注册
        event_definitions = (
            ("context.prepared", ContextPreparedEventData),
            ("context.input.failed", ContextInputFailedEventData),
            ("context.append.requested", ContextAppendRequestData),
            ("context.history.requested", ContextHistoryRequestData),
            ("context.history.resolved", ContextHistoryResultEventData),
            ("context.work.requested", ContextWorkRequestData),
            ("context.work.ready", ContextWorkReadyEventData),
            ("context.work.failed", ContextWorkFailedEventData),
            ("context.state.changed", ContextStateChangedEventData),
            ("context.restore.requested", ContextRestoreRequestData),
            ("context.restore.resolved", ContextRestoreResultEventData),
            ("context.compaction.requested", CompactionRequestData),
        )
        # handler 订阅
        subscriptions = (
            (
                "body.input.received",
                conversation.handle_input,
                "context.body_input",
            ),
            ("context.append.requested", self._handle_append, "context.append"),
            ("context.work.requested", self._work.handle_request, "context.work"),
            (
                "context.restore.resolved",
                conversation.handle_restore,
                "context.restore_conversation",
            ),
            (
                "context.restore.resolved",
                self._work.handle_restore,
                "context.restore_work",
            ),
            (
                "context.compaction.requested",
                self._compaction.handle_request,
                "context.compaction",
            ),
        )
        for event_type, payload_type in event_definitions:
            events.register(event_type, payload_type=payload_type)
        for event_pattern, handler, handler_id in subscriptions:
            events.subscribe(event_pattern, handler, handler_id=handler_id)

    async def _handle_append(self, flow: EventFlow) -> None:
        """追加来自 Agent 等模块的条目，并发布完整状态变化事实。"""

        request: ContextAppendRequestData = flow.payload
        result = self._appender.append(
            request.session_id,
            request.entries,
            close_after=request.close_after,
        )
        self._appender.publish(flow, result)
