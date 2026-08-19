"""ContextStateStore 的 Session 状态链路测试。"""

from __future__ import annotations

import unittest

from core.context.common import Content
from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextEntryDraft,
    ContextEntryType,
)
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy


def make_draft(text: str, entry_type: str = ContextEntryType.USER_MESSAGE) -> ContextEntryDraft:
    return ContextEntryDraft(
        entry_type=entry_type,
        actor=ContextActorRef(ContextActorType.USER, "user_1"),
        content=Content.from_text(text),
    )


class ContextStoreLifecycleTests(unittest.TestCase):
    def test_append_orders_entries_and_close_prevents_later_writes(self) -> None:
        store = ContextStateStore()
        snapshot, created = store.resolve_work("task", "task_1")

        first = store.append_entries(
            snapshot.session.session_id,
            (make_draft("第一条"), make_draft("第二条")),
        )
        closed = store.append_entries(
            snapshot.session.session_id,
            (make_draft("完成", ContextEntryType.SENA_MESSAGE),),
            close_after=True,
        )

        self.assertTrue(created)
        self.assertEqual([entry.sequence for entry in first.entries], [1, 2])
        self.assertEqual([entry.sequence for entry in closed.snapshot.entries], [1, 2, 3])
        self.assertTrue(closed.snapshot.session.is_closed)
        with self.assertRaisesRegex(LookupError, "session_closed"):
            store.append_entries(snapshot.session.session_id, (make_draft("迟到的写入"),))

    def test_repeated_compaction_request_does_not_create_a_second_summary(self) -> None:
        store = ContextStateStore()
        snapshot, _created = store.resolve_work("task", "task_1")
        appended = store.append_entries(
            snapshot.session.session_id,
            tuple(make_draft(f"消息 {index}") for index in range(1, 5)),
        )
        request = ContextWindowPolicy(
            recent_entries=2,
            compression_trigger_entries=3,
        ).plan_compaction(appended.snapshot)
        self.assertIsNotNone(request)

        first = store.apply_compaction(request, "摘要")
        repeated = store.apply_compaction(request, "重复摘要")

        self.assertIsNotNone(first)
        self.assertEqual(len(first.snapshot.summaries), 1)
        self.assertEqual(first.summary.text, "摘要")
        self.assertIsNone(repeated)

    def test_level_one_summaries_promote_to_one_higher_level_summary(self) -> None:
        store = ContextStateStore()
        snapshot, _created = store.resolve_work("task", "task_1")
        policy = ContextWindowPolicy(
            recent_entries=2,
            compression_trigger_entries=3,
            summary_fanout=2,
        )

        snapshot = store.append_entries(
            snapshot.session.session_id,
            tuple(make_draft(f"消息 {index}") for index in range(1, 7)),
        ).snapshot
        first_request = policy.plan_compaction(snapshot)
        self.assertIsNotNone(first_request)
        snapshot = store.apply_compaction(first_request, "一级摘要 A").snapshot

        snapshot = store.append_entries(
            snapshot.session.session_id,
            tuple(make_draft(f"消息 {index}") for index in range(7, 11)),
        ).snapshot
        second_request = policy.plan_compaction(snapshot)
        self.assertIsNotNone(second_request)
        second_result = store.apply_compaction(second_request, "一级摘要 B")
        self.assertIsNotNone(second_result)

        promotion = policy.plan_compaction(second_result.snapshot)
        self.assertIsNotNone(promotion)
        promoted = store.apply_compaction(promotion, "二级摘要")

        self.assertIsNotNone(promoted)
        self.assertEqual(promoted.summary.level, 2)
        self.assertEqual(
            (promoted.summary.first_sequence, promoted.summary.last_sequence),
            (1, 8),
        )
        self.assertEqual(len(promoted.summary.source_summary_ids), 2)
        self.assertEqual(
            [entry.sequence for entry in promoted.snapshot.entries],
            [9, 10],
        )
        self.assertEqual(promoted.snapshot.summaries, (promoted.summary,))


if __name__ == "__main__":
    unittest.main()
