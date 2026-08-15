"""Context 工作窗口与滚动压缩规则"""

from __future__ import annotations

from core.context.compression import (
    CompactionInput,
    CompactionRequestData,
    CompressionItem,
)
from core.context.contracts import ContextEntryRecord, ContextSnapshot, ContextSummary


class ContextWindowPolicy:
    """规则控制的上下文压缩策略，避免过度压缩导致上下文丢失
    主要包括两部分, 原始条目条目压缩成一级摘要和同层摘要晋升成更高层摘要, 以保证上下文的完整性和可理解性
    """
    
    def __init__(
        self,
        *,
        recent_entries: int = 24,
        compression_trigger_entries: int = 40,
        summary_fanout: int = 8,
        compaction_lookahead_entries: int = 8,
    ) -> None:
        # 至少保留两条最近条目，避免压缩掉所有内容
        if recent_entries < 2:
            raise ValueError("recent_entries must be at least 2")
        if compression_trigger_entries <= recent_entries:
            raise ValueError("compression_trigger_entries must exceed recent_entries")
        if summary_fanout < 2:
            raise ValueError("summary_fanout must be at least two")
        if compaction_lookahead_entries < 0:
            raise ValueError("compaction_lookahead_entries must not be negative")
        self._recent_entries = recent_entries  # 每次压缩后保护的最近原文数量。
        self._trigger_entries = (
            compression_trigger_entries  # 未摘要条目超过该值才触发压缩。
        )
        self._summary_fanout = summary_fanout # 每个摘要最多包含的子摘要数量，超过该值会触发更高层级的压缩。
        self._lookahead = compaction_lookahead_entries # 压缩时额外保留的条目数量，避免丢失上下文连续性。
        
    def plan_compaction(self, snapshot: ContextSnapshot) -> CompactionRequestData | None:
        """优先规划原始条目压缩，否则检查同层摘要晋升"""

        entry_plan = self._plan_entries(snapshot)
        if entry_plan is not None:
            return entry_plan
        return self._plan_summary_promotion(snapshot)
    
    def _plan_entries(self, snapshot: ContextSnapshot) -> CompactionRequestData | None:
        """把达到阈值的最早一组原始条目规划为一级摘要"""
        
        pending = snapshot.entries  # 提取可能需要压缩的条目
        # 等于阈值时仍保留全部原文，只有真正超出才创建后台任务。
        if len(pending) <= self._trigger_entries:
            return None

        # 只压缩较早的条目，并提供最近若干条消息供参考，避免丢失上下文连续性
        candidates = pending[: -self._recent_entries]
        following = pending[len(candidates) : len(candidates) + self._lookahead]
        
        return CompactionRequestData(
            snapshot.session.session_id,
            CompactionInput(
                target_level=1,
                items=tuple(_entry_item(entry) for entry in candidates),
                context_before=_preceding_summary(
                    snapshot.summaries,
                    candidates[0].sequence,
                ),
                context_after=tuple(_entry_item(entry) for entry in following),
            ),
        )
        
    def _plan_summary_promotion(self, snapshot: ContextSnapshot) -> CompactionRequestData | None:
        """把达到 fanout 的最早一组同层摘要压缩为更高层摘要"""
        # 获取同层摘要的分组，按 level 升序处理，优先压缩较低层级的摘要
        summaries_by_level: dict[int, list[ContextSummary]] = {}
        for summary in snapshot.summaries:
            summaries_by_level.setdefault(summary.level, []).append(summary)
        
        # 遍历每个层级的摘要，找到达到 fanout 的最早一组进行压缩
        for level in sorted(summaries_by_level):
            candidates = summaries_by_level[level][: self._summary_fanout]
            if len(candidates) < self._summary_fanout:
                continue
            first_sequence = candidates[0].first_sequence
            last_sequence = candidates[-1].last_sequence
            # 提取目标区间后面的若干条目，有摘要则用摘要，没有摘要则用原始条目
            following = _following_summary(snapshot.summaries, last_sequence)
            if not following:
                following = tuple(
                    _entry_item(entry)
                    for entry in snapshot.entries
                    if entry.sequence > last_sequence
                )[: self._lookahead]
            return CompactionRequestData(
                snapshot.session.session_id,
                CompactionInput(
                    target_level=level + 1,
                    items=tuple(_summary_item(summary) for summary in candidates),
                    context_before=_preceding_summary(
                        snapshot.summaries,
                        first_sequence,
                    ),
                    context_after=following,
                ),
                tuple(summary.summary_id for summary in candidates),
            )
        return None


def _entry_item(entry: ContextEntryRecord) -> CompressionItem:
    """把原始条目转换为 Compressor 使用的统一文本块"""

    actor = entry.actor.display_name or entry.actor.actor_id
    return CompressionItem(
        entry.sequence,
        entry.sequence,
        f"{entry.entry_type} | {actor}",
        entry.text(),
    )


def _summary_item(summary: ContextSummary) -> CompressionItem:
    """把摘要节点转换为 Compressor 使用的统一文本块"""

    return CompressionItem(
        summary.first_sequence,
        summary.last_sequence,
        f"Level {summary.level} 摘要",
        summary.text,
    )


def _preceding_summary(
    summaries: tuple[ContextSummary, ...],
    first_sequence: int,
) -> tuple[CompressionItem, ...]:
    """选择目标区间前最近的一个有语义摘要, 只作为理解参考"""

    for summary in reversed(summaries):
        if summary.last_sequence < first_sequence and summary.text.strip():
            return (_summary_item(summary),)
    return ()


def _following_summary(
    summaries: tuple[ContextSummary, ...],
    last_sequence: int,
) -> tuple[CompressionItem, ...]:
    """选择目标区间后最近的一个有语义摘要, 只作为理解参考"""

    for summary in summaries:
        if summary.first_sequence > last_sequence and summary.text.strip():
            return (_summary_item(summary),)
    return ()
