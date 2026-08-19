"""Context 滚动压缩的事件流程"""

from __future__ import annotations

from core.context.compression import CompactionRequestData, ContextCompressor
from core.context.contracts import (
    ContextSnapshot,
    ContextStateChangedEventData,
)
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.event import EventFlow


class CompactionFlow:
    """Context 后台压缩流程的协调器
    
    串联三个模块:
    - ContextWindowPolicy: 决定是否需要压缩、压缩哪些内容
    - ContextCompressor: 调用 LLM 生成摘要文本
    - ContextStateStore: 校验并提交压缩结果
    """

    def __init__(
        self,
        store: ContextStateStore,
        window: ContextWindowPolicy,
        compressor: ContextCompressor | None,
    ) -> None:
        self._store = store
        self._window = window
        self._compressor = compressor
        # 每个 Session同时最多保留一个任务
        self._scheduled: set[str] = set()

    def request(self, flow: EventFlow, snapshot: ContextSnapshot) -> None:
        """窗口超限时发布后台压缩事件；当前对话流程不等待模型调用"""

        request = self.schedule(snapshot)
        if request is not None:
            flow.emit("context.compaction.requested", request)

    def schedule(self, snapshot: ContextSnapshot) -> CompactionRequestData | None:
        """生成至多一个压缩请求，并在发布前占用对应 Session槽位"""

        session_id = snapshot.session.session_id
        if snapshot.session.is_closed or session_id in self._scheduled:
            return None
        # 规划压缩请求，若不需要压缩则返回 None
        request = self._window.plan_compaction(snapshot)
        if request is None:
            return None
        self._scheduled.add(session_id)
        return request

    async def handle_request(self, flow: EventFlow) -> None:
        """执行一次压缩，并仅在摘要检查点仍然有效时提交。"""

        request: CompactionRequestData = flow.payload
        result = None
        try:
            summary_text = ""
            if self._compressor is not None:
                # 执行压缩，若无法生成完整摘要则返回 None
                generated = await self._compressor.compress(request.input)
                if generated is None:
                    return
                summary_text = generated
            result = self._store.apply_compaction(request, summary_text)
        finally:
            self._scheduled.discard(request.session_id)
        if result is None:
            return
        flow.emit(
            "context.state.changed",
            ContextStateChangedEventData.from_snapshot(
                result.snapshot,
                created_summary=result.summary,
            ),
        )
        self.request(flow, result.snapshot)
