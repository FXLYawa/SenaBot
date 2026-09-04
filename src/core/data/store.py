"""MVP Data 层的进程内存储。"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from core.context.contracts import (
    ContextSnapshot,
    ContextStateChangedEventData,
)
from core.memory.models import Fact, MemoryItem


class InMemoryDataStore:
    """用于首次运行的进程内 Data Store。

    该实现只支撑 MVP 链路验证。它不提供跨进程持久化、事务、
    operation ledger 或向量索引。
    """

    def __init__(self) -> None:
        self._context_snapshots: dict[str, ContextSnapshot] = {}
        self._memory_items_by_space: dict[str, dict[str, MemoryItem]] = {}

    def load_context(
        self,
        session_id: str,
    ) -> ContextSnapshot | None:
        """按 session_id 读取 Context 快照。"""

        return self._context_snapshots.get(session_id)

    def save_context_change(
        self,
        change: ContextStateChangedEventData,
    ) -> ContextSnapshot:
        """根据 Context 增量变化维护可恢复快照。"""

        current = self._context_snapshots.get(change.session.session_id)
        entries = () if current is None else current.entries
        summaries = () if current is None else current.summaries

        entries_by_id = {entry.entry_id: entry for entry in entries}
        for entry in change.appended_entries:
            entries_by_id[entry.entry_id] = entry

        summaries_by_id = {summary.summary_id: summary for summary in summaries}
        if change.created_summary is not None:
            summaries_by_id[change.created_summary.summary_id] = change.created_summary

        snapshot = ContextSnapshot(
            session=change.session,
            latest_sequence=change.latest_sequence,
            entries=tuple(
                sorted(
                    entries_by_id.values(),
                    key=lambda entry: entry.sequence,
                )
            ),
            summaries=tuple(
                sorted(
                    summaries_by_id.values(),
                    key=lambda summary: (
                        summary.first_sequence,
                        summary.level,
                        summary.last_sequence,
                    ),
                )
            ),
        )
        self._context_snapshots[change.session.session_id] = snapshot
        return snapshot

    def add_memory(
        self,
        item: MemoryItem,
    ) -> MemoryItem:
        """把正式 MemoryItem 放入对应 Memory Space。"""

        self._space(item.memory_space_id)[item.item_id] = item
        return item

    def memory_items(
        self,
        memory_space_id: str,
    ) -> tuple[MemoryItem, ...]:
        """读取单个 Memory Space 中的当前 MemoryItem 快照。"""

        return tuple(self._space(memory_space_id).values())

    def end_fact_validity(
        self,
        target_item_id: str,
        valid_to: datetime,
    ) -> MemoryItem:
        """结束一个 Fact 的有效期并返回更新后的 MemoryItem。"""

        space_id, item = self._find_memory_item(target_item_id)
        if not isinstance(item.payload, Fact):
            raise ValueError("target memory item must be a Fact")

        updated = MemoryItem(
            item_id=item.item_id,
            memory_space_id=item.memory_space_id,
            scopes=item.scopes,
            payload=replace(item.payload, valid_to=valid_to),
        )
        self._memory_items_by_space[space_id][target_item_id] = updated
        return updated

    def get_memory_item(
        self,
        item_id: str,
    ) -> MemoryItem:
        """按 item_id 查找 MemoryItem。"""

        return self._find_memory_item(item_id)[1]

    def _space(
        self,
        memory_space_id: str,
    ) -> dict[str, MemoryItem]:
        if not memory_space_id.strip():
            raise ValueError("memory_space_id must not be blank")
        return self._memory_items_by_space.setdefault(memory_space_id, {})

    def _find_memory_item(
        self,
        item_id: str,
    ) -> tuple[str, MemoryItem]:
        for space_id, items in self._memory_items_by_space.items():
            item = items.get(item_id)
            if item is not None:
                return space_id, item
        raise ValueError(f"memory item not found: {item_id}")
