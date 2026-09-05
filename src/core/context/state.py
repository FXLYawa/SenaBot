"""单个 Session 及其 Context 的进程内状态。"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.common import Summary, new_id, utc_now
from core.context.compression import CompactionRequestData
from core.context.contracts import (
    ContextEntryDraft,
    ContextEntryRecord,
    ContextSnapshot,
    SessionRecord,
)


@dataclass(frozen=True, slots=True)
class AppendResult:
    """一次原子追加的结果"""

    snapshot: ContextSnapshot  # 追加完成后的只读快照
    entries: tuple[ContextEntryRecord, ...]  # 本次新增的有序条目
    

@dataclass(frozen=True, slots=True)
class CompactionResult:
    """一次成功完成的摘要压缩的状态与新节点"""

    snapshot: ContextSnapshot # 提交压缩后的完整 Context 快照
    summary: Summary # 本次新增的摘要节点
    
    
@dataclass(slots=True)
class SessionState:
    """集中维护一个 Session 的追加、关闭和摘要不变量"""

    session: SessionRecord
    latest_sequence: int
    entries: list[ContextEntryRecord]
    summaries: list[Summary]

    @classmethod
    def from_snapshot(cls, snapshot: ContextSnapshot) -> SessionState:
        """从已校验的持久化快照恢复独立的可变运行时状态"""

        return cls(
            snapshot.session,
            snapshot.latest_sequence,
            list(snapshot.entries),
            list(snapshot.summaries),
        )

    def append(
        self,
        drafts: tuple[ContextEntryDraft, ...],
        *,
        close_after: bool = False,
    ) -> AppendResult:
        """追加一批有序条目，并可在同一次状态变化中关闭 Session"""

        if not drafts:
            raise ValueError("entries_required")
        if self.session.is_closed:
            raise LookupError("session_closed")

        appended = tuple(self._append_one(draft) for draft in drafts)
        updated_at = appended[-1].created_at
        self.session = replace(
            self.session,
            updated_at=updated_at,
            closed_at=updated_at if close_after else self.session.closed_at,
        )
        return AppendResult(self.snapshot(), appended)

    def compact(
        self,
        request: CompactionRequestData,
        text: str,
    ) -> CompactionResult | None:
        """提交一个不可变摘要节点；输入已过期时不修改状态"""

        if self.session.is_closed or not request.input.items:
            return None
        target_level = request.input.target_level
        covered_range = (
            self._consume_entries(request)
            if target_level == 1
            else self._consume_summaries(request)
        )
        if covered_range is None:
            return None
        first_sequence, last_sequence = covered_range

        now = utc_now()
        summary = Summary(
            summary_id=new_id("summary"),
            session_id=self.session.session_id,
            level=target_level,
            first_sequence=first_sequence,
            last_sequence=last_sequence,
            text=text.strip(),
            created_at=now,
            source_summary_ids=request.source_summary_ids,
        )
        self.summaries.append(summary)
        self.summaries.sort(key=lambda item: item.first_sequence)
        self.session = replace(self.session, updated_at=now)
        return CompactionResult(self.snapshot(), summary)

    def _consume_entries(
        self,
        request: CompactionRequestData,
    ) -> tuple[int, int] | None:
        """校验并移除 Level 1 摘要覆盖的原始条目前缀"""

        if request.source_summary_ids:
            return None
        items = request.input.items
        last_sequence = items[-1].last_sequence
        # 确保原始条目和压缩请求的范围完全匹配，避免出现跳跃或遗漏
        entries = tuple(
            entry for entry in self.entries if entry.sequence <= last_sequence
        )
        expected_ranges = tuple((entry.sequence, entry.sequence) for entry in entries)
        item_ranges = tuple(
            (item.first_sequence, item.last_sequence) for item in items
        )
        if expected_ranges != item_ranges:
            return None
        # 移除已被摘要覆盖的原始条目，保留后续条目
        self.entries = [
            entry for entry in self.entries if entry.sequence > last_sequence
        ]
        return entries[0].sequence, entries[-1].sequence

    def _consume_summaries(
        self,
        request: CompactionRequestData,
    ) -> tuple[int, int] | None:
        """校验并移除高层摘要直接覆盖的活动子摘要"""

        # 确保所有参与的子摘要都存在于当前活动摘要中，并且它们的层级和覆盖范围符合要求
        items = request.input.items
        target_level = request.input.target_level
        source_ids = request.source_summary_ids
        by_id = {summary.summary_id: summary for summary in self.summaries}
        if any(summary_id not in by_id for summary_id in source_ids):
            return None
        summaries = tuple(by_id[summary_id] for summary_id in source_ids)
        # 确保子摘要的层级是目标层级的前一层，并且它们的覆盖范围与请求的 items 完全匹配
        source_ranges = tuple(
            (summary.first_sequence, summary.last_sequence) for summary in summaries
        )
        item_ranges = tuple(
            (item.first_sequence, item.last_sequence) for item in items
        )
        if (
            any(summary.level != target_level - 1 for summary in summaries)
            or source_ranges != item_ranges
            or any(
                left.last_sequence + 1 != right.first_sequence
                for left, right in zip(summaries, summaries[1:], strict=False)
            )
        ):
            return None
        consumed = set(request.source_summary_ids)
        # 移除已被更高层摘要覆盖的子摘要，保留其他活动摘要
        self.summaries = [
            summary
            for summary in self.summaries
            if summary.summary_id not in consumed
        ]
        return summaries[0].first_sequence, summaries[-1].last_sequence

    def snapshot(self) -> ContextSnapshot:
        """冻结可变容器，返回只读快照"""

        return ContextSnapshot(
            self.session,
            self.latest_sequence,
            tuple(self.entries),
            tuple(self.summaries),
        )

    def _append_one(self, draft: ContextEntryDraft) -> ContextEntryRecord:
        """为一个新条目分配严格递增的 Session 内序号。"""

        now = utc_now()
        self.latest_sequence += 1
        entry = ContextEntryRecord(
            entry_id=new_id("entry"),
            session_id=self.session.session_id,
            sequence=self.latest_sequence,
            entry_type=draft.entry_type,
            actor=draft.actor,
            content=draft.content,
            source_event_id=draft.source_event_id,
            created_at=now,
        )
        
        self.entries.append(entry)
        return entry
