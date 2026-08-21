"""Context 对外数据契约的行为测试。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextEntryRecord,
    ContextHistoryLevel,
    ContextSnapshot,
    ContextStateChangedEventData,
    ContextSummary,
    SessionRecord,
)
from core.context.common import Content


class ContextStateChangedContractTests(unittest.TestCase):
    def test_created_summary_keeps_its_creation_time(self) -> None:
        now = datetime.now(UTC)
        summary = ContextSummary(
            summary_id="summary_1",
            session_id="session_1",
            level=1,
            first_sequence=1,
            last_sequence=2,
            text="摘要",
            created_at=now,
        )
        snapshot = ContextSnapshot(
            session=SessionRecord("session_1", now, now),
            latest_sequence=2,
            entries=(),
            summaries=(summary,),
        )

        event = ContextStateChangedEventData.from_snapshot(
            snapshot,
            created_summary=summary,
        )

        self.assertIs(event.created_summary, summary)
        self.assertEqual(event.created_summary.created_at, now)


class ContextHistoryContractTests(unittest.TestCase):
    def test_history_level_rejects_content_from_the_wrong_layer(self) -> None:
        now = datetime.now(UTC)
        level_one = ContextSummary("summary_1", "session_1", 1, 1, 1, "摘要", now)
        level_two = ContextSummary(
            "summary_2",
            "session_1",
            2,
            1,
            1,
            "高层摘要",
            now,
            (level_one.summary_id,),
        )
        entry = ContextEntryRecord(
            "entry_1",
            "session_1",
            1,
            "user_message",
            ContextActorRef(ContextActorType.USER, "user_1"),
            Content.from_text("你好"),
            "event_1",
            now,
        )

        with self.assertRaises(ValueError):
            ContextHistoryLevel(level_one, summaries=(level_one,))
        with self.assertRaises(ValueError):
            ContextHistoryLevel(level_two, entries=(entry,))


if __name__ == "__main__":
    unittest.main()
