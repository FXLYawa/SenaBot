"""按原始条目边界读取并组装独立于活动窗口的上下文视图。"""

from core.common import Summary
from core.context.contracts import (
    ContextEntryRecord,
    ContextErrorInfo,
    ContextReadRequestData,
    ContextReadResultEventData,
    ContextReadView,
)
from core.context.ports import ContextArchiveProtocol
from core.context.store import ContextStateStore
from core.event import EventFlow


class ContextReader:
    """结合活动窗口与归档，组装指定范围的原文及其前置上下文。"""

    def __init__(
        self, store: ContextStateStore, archive: ContextArchiveProtocol | None,
    ) -> None:
        self._store = store
        self._archive = archive

    async def handle_request(self, flow: EventFlow) -> None:
        """处理 context.read 请求，返回 context.read.resolved 结果。"""
        
        request: ContextReadRequestData = flow.payload
        try:
            view = self.read(request)
        except Exception as error:
            result = ContextReadResultEventData(
                request.operation_id,
                request.session_id,
                error=ContextErrorInfo(type(error).__name__, "Requested context range is unavailable."),
            )
        else:
            result = ContextReadResultEventData(
                request.operation_id, request.session_id, view=view,
            )
        # 成功和失败都携带原 operation_id，调用方据此接续自己等待的读取批次。
        flow.emit("context.read.resolved", result)

    def read(self, request: ContextReadRequestData) -> ContextReadView:
        """优先使用活动窗口，只从归档补足本次视图缺少的内容。"""
        
        # 获取会话及活动快照；会话信息缺失时从归档加载。
        snapshot = self._store.snapshot(request.session_id)
        session = None if snapshot is None else snapshot.session
        if session is None and self._archive is not None:
            session = self._archive.load_session(request.session_id)
        if session is None:
            raise LookupError("session_not_found")
        active_entries = () if snapshot is None else snapshot.entries
        active_summaries = () if snapshot is None else snapshot.summaries
        # 选取目标范围之前的摘要，确定前置历史中已由摘要覆盖的部分。
        summaries = self._read_preceding_summaries(
            request, active_summaries, active_entries,
        )

        # 从摘要覆盖终点读到目标起点，补齐前置上下文的剩余原文。
        covered = summaries[-1].last_sequence if summaries else 0
        preceding = self._entries(
            request.session_id, covered, request.after_sequence, active_entries,
        )
        # 读取本批目标原文 (after_sequence, through_sequence]，与前置历史一起返回。
        entries = self._entries(
            request.session_id, request.after_sequence, request.through_sequence, active_entries,
        )
        return ContextReadView(
            session=session,
            after_sequence=request.after_sequence,
            through_sequence=request.through_sequence,
            entries=entries,
            preceding_entries=preceding,
            summaries=summaries,
        )

    def _read_preceding_summaries(
        self,
        request: ContextReadRequestData,
        active_summaries: tuple[Summary, ...],
        active_entries: tuple[ContextEntryRecord, ...],
    ) -> tuple[Summary, ...]:
        """先选活动摘要，前置历史覆盖不足时再合并归档摘要重新选择。"""

        summaries = self._select_preceding_summaries(active_summaries, request.after_sequence)
        covered = summaries[-1].last_sequence if summaries else 0
        # 统计摘要之后的活动原文，判断前置历史是否已完整覆盖。
        remaining = {
            entry.sequence for entry in active_entries
            if covered < entry.sequence <= request.after_sequence
        }
        if len(remaining) == request.after_sequence - covered or self._archive is None:
            return summaries
        # 合并归档中的摘要节点，以完整位于目标之前的节点补足摘要前缀。
        archived = self._archive.load_summaries(request.session_id, request.after_sequence)
        return self._select_preceding_summaries(
            (*archived, *active_summaries), request.after_sequence,
        )

    def _entries(
        self,
        session_id: str,
        after_sequence: int,
        through_sequence: int,
        active: tuple[ContextEntryRecord, ...],
    ) -> tuple[ContextEntryRecord, ...]:
        """保留活动原文，仅按连续缺口查询归档，最后检查范围完整性。"""

        if through_sequence <= after_sequence:
            return ()
        # 按原始序号收集活动窗口中落在请求范围内的条目。
        by_sequence = {
            entry.sequence: entry
            for entry in active if after_sequence < entry.sequence <= through_sequence
        }
        if self._archive is not None:
            covered = after_sequence
            # 遍历相邻序号，从归档补齐中间缺口；末尾哨兵同时覆盖尾部缺口。
            for sequence in (*sorted(by_sequence), through_sequence + 1):
                if sequence > covered + 1:
                    archived = self._archive.load_entries(session_id, covered, sequence - 1)
                    by_sequence.update((entry.sequence, entry) for entry in archived)
                covered = sequence
        # 校验合并后的序号完整覆盖请求范围，再按顺序返回原文。
        if sorted(by_sequence) != list(range(after_sequence + 1, through_sequence + 1)):
            raise LookupError("context_range_unavailable")
        return tuple(by_sequence[sequence] for sequence in sorted(by_sequence))

    @staticmethod
    def _select_preceding_summaries(
        candidates: tuple[Summary, ...], through_sequence: int,
    ) -> tuple[Summary, ...]:
        # 按 ID 合并有正文且完整位于目标之前的摘要节点。
        eligible = {
            summary.summary_id: summary for summary in candidates
            if summary.last_sequence <= through_sequence and summary.text.strip()
        }
        # 按起点排序，同一起点优先选择覆盖范围更长、层级更高的节点。
        ordered = sorted(
            eligible.values(),
            key=lambda summary: (summary.first_sequence, -summary.last_sequence, -summary.level),
        )
        selected: list[Summary] = []
        covered = 0
        for summary in ordered:
            # 摘要组成连续前缀；遇到缺口后统一读原文，保证摘要早于前置原始条目。
            if summary.first_sequence > covered + 1:
                break
            if summary.first_sequence == covered + 1:
                selected.append(summary)
                covered = summary.last_sequence
        return tuple(selected)
