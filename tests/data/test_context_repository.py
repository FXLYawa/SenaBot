"""SQLite Context Repository 的持久化与活动窗口恢复测试。"""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from core.context.common import (
    Content,
    ContentSegment,
    ContentType,
    ConversationScope,
    SceneType,
)
from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextEntryRecord,
    ContextSnapshot,
    ContextStateChangedEventData,
    ContextSummary,
    SessionRecord,
)
from core.data import SQLiteContextRepository, SQLiteDatabase


class SQLiteContextRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self._path = Path(self._temporary_directory.name) / "context.db"
        self._database = SQLiteDatabase(self._path)
        self._repository = SQLiteContextRepository(self._database)
        self._now = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)
        self._session = SessionRecord(
            session_id="session_conversation",
            created_at=self._now,
            updated_at=self._now,
            conversation_scope=ConversationScope(
                platform="desktop",
                scene_type=SceneType.PRIVATE,
                scene_id="owner",
                account_namespace="primary",
            ),
        )

    def tearDown(self) -> None:
        self._database.close()
        self._temporary_directory.cleanup()

    def test_context_survives_reopening_database(self) -> None:
        entries = tuple(self._entry(index) for index in range(1, 4))
        snapshot = ContextSnapshot(self._session, 3, entries)
        self._repository.save_context_change(
            ContextStateChangedEventData.from_snapshot(snapshot, entries)
        )

        self._database.close()
        self._database = SQLiteDatabase(self._path)
        self._repository = SQLiteContextRepository(self._database)

        self.assertEqual(self._repository.load_context(self._session.session_id), snapshot)

    def test_restore_returns_only_active_entries_and_summaries(self) -> None:
        entries = tuple(self._entry(index) for index in range(1, 6))
        self._save(entries=entries, latest_sequence=5)

        first = self._summary("summary_1", 1, 1, 2)
        second = self._summary("summary_2", 1, 3, 3)
        self._save(summary=first, latest_sequence=5)
        self._save(summary=second, latest_sequence=5)
        promoted = self._summary(
            "summary_3",
            2,
            1,
            3,
            source_summary_ids=(first.summary_id, second.summary_id),
        )
        self._save(summary=promoted, latest_sequence=5)

        restored = self._repository.load_context(self._session.session_id)

        self.assertIsNotNone(restored)
        assert restored is not None
        self.assertEqual([entry.sequence for entry in restored.entries], [4, 5])
        self.assertEqual(restored.summaries, (promoted,))

    def test_replaying_the_same_change_is_idempotent(self) -> None:
        entry = self._entry(1)
        summary = self._summary("summary_1", 1, 1, 1)
        self._save(entries=(entry,), latest_sequence=1)
        change = ContextStateChangedEventData(
            replace(self._session, updated_at=self._now + timedelta(seconds=1)),
            1,
            (),
            summary,
        )

        first = self._repository.save_context_change(change)
        second = self._repository.save_context_change(change)

        self.assertEqual(second, first)
        self.assertEqual(
            self._database.connection.execute(
                "SELECT count(*) FROM context_summaries"
            ).fetchone()[0],
            1,
        )

    def test_work_session_round_trips_without_conversation_scope(self) -> None:
        session = SessionRecord(
            session_id="session_work",
            created_at=self._now,
            updated_at=self._now,
            purpose="agent_run",
            work_id="work_1",
        )
        change = ContextStateChangedEventData(session, 0, ())

        restored = self._repository.save_context_change(change)

        self.assertEqual(restored, ContextSnapshot(session, 0, ()))

    def _save(
        self,
        *,
        entries: tuple[ContextEntryRecord, ...] = (),
        summary: ContextSummary | None = None,
        latest_sequence: int,
    ) -> None:
        session = replace(
            self._session,
            updated_at=self._now + timedelta(seconds=latest_sequence),
        )
        self._repository.save_context_change(
            ContextStateChangedEventData(
                session,
                latest_sequence,
                entries,
                summary,
            )
        )

    def _entry(self, sequence: int) -> ContextEntryRecord:
        content = Content(
            segments=(
                ContentSegment(ContentType.TEXT, {"text": f"消息 {sequence}"}),
                ContentSegment(ContentType.LINK, {"url": "https://example.com"}),
            )
        )
        return ContextEntryRecord(
            entry_id=f"entry_{sequence}",
            session_id=self._session.session_id,
            sequence=sequence,
            entry_type="user_message",
            actor=ContextActorRef(ContextActorType.USER, "user_1", "User"),
            content=content,
            source_event_id=f"event_{sequence}",
            created_at=self._now + timedelta(seconds=sequence),
        )

    def _summary(
        self,
        summary_id: str,
        level: int,
        first_sequence: int,
        last_sequence: int,
        *,
        source_summary_ids: tuple[str, ...] = (),
    ) -> ContextSummary:
        return ContextSummary(
            summary_id=summary_id,
            session_id=self._session.session_id,
            level=level,
            first_sequence=first_sequence,
            last_sequence=last_sequence,
            text=f"摘要 {summary_id}",
            created_at=self._now + timedelta(minutes=level),
            source_summary_ids=source_summary_ids,
        )


if __name__ == "__main__":
    unittest.main()
