"""Context 条目追加及其后续事件交互"""

from __future__ import annotations

from core.context.compaction import CompactionFlow
from core.context.contracts import ContextEntryDraft, ContextStateChangedEventData
from core.context.state import AppendResult
from core.context.store import ContextStateStore
from core.event import EventClient, EventEnvelope, EventFlow


class EntryAppender:
    """统一 Context 条目追加完成后的公共流程"""

    def __init__(
        self,
        store: ContextStateStore,
        compaction: CompactionFlow,
    ) -> None:
        self._store = store
        self._compaction = compaction

    def append(
        self,
        session_id: str,
        entries: tuple[ContextEntryDraft, ...],
        *,
        close_after: bool = False,
    ) -> AppendResult:
        """只完成原子状态追加；事件发布由调用方选择当前或原始事件链。"""

        return self._store.append_entries(
            session_id=session_id,
            drafts=entries,
            close_after=close_after,
        )

    def publish(self, flow: EventFlow, result: AppendResult) -> None:
        """在当前 Handler 的事件链上发布追加事实和压缩请求。"""

        flow.emit(
            "context.state.changed",
            ContextStateChangedEventData.from_snapshot(
                snapshot=result.snapshot,
                appended_entries=result.entries,
            ),
        )
        self._compaction.request(flow, result.snapshot)

    async def publish_from(
        self,
        events: EventClient,
        parent: EventEnvelope,
        result: AppendResult,
    ) -> None:
        """在原始输入 trace 上恢复后续事件
        
        在Session恢复的过程中存在追加输入时
        因为原EventFlow已经关闭, 无法发布派生事件, 因此通过这部分的缓存来完成
        """

        # 在原始事件链上发布追加事实和压缩请求
        await events.emit(
            parent,
            "context.state.changed",
            ContextStateChangedEventData.from_snapshot(
                result.snapshot,
                result.entries,
            ),
        )
        compaction = self._compaction.schedule(result.snapshot)
        if compaction is not None:
            await events.emit(parent, "context.compaction.requested", compaction)
