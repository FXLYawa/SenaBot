"""Context 的 SQLite 持久化实现。"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Protocol

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
from core.data.database import SQLiteDatabase
from core.data.serialization import format_datetime, parse_datetime


class ContextRepositoryProtocol(Protocol):
    """DataModule 使用的 Context 持久化端口。"""

    def load_context(self, session_id: str) -> ContextSnapshot | None: ...

    def save_context_change(
        self,
        change: ContextStateChangedEventData,
    ) -> ContextSnapshot: ...


class SQLiteContextRepository:
    """保存完整 Context 历史，并恢复当前活动窗口。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def load_context(self, session_id: str) -> ContextSnapshot | None:
        """按 Session ID 恢复当前活动条目和摘要。"""

        connection = self._database.connection
        session_row = connection.execute(
            "SELECT * FROM context_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            return None

        entry_rows = connection.execute(
            "SELECT entry.* FROM context_entries AS entry "
            "WHERE entry.session_id = ? AND NOT EXISTS ("
            "SELECT 1 FROM context_summaries AS summary "
            "WHERE summary.session_id = entry.session_id AND summary.level = 1 "
            "AND entry.sequence BETWEEN summary.first_sequence AND summary.last_sequence"
            ") ORDER BY entry.sequence",
            (session_id,),
        ).fetchall()
        summary_rows = connection.execute(
            "SELECT summary.* FROM context_summaries AS summary "
            "WHERE summary.session_id = ? AND NOT EXISTS ("
            "SELECT 1 FROM context_summary_sources AS source "
            "WHERE source.child_summary_id = summary.summary_id"
            ") ORDER BY summary.first_sequence, summary.level, summary.last_sequence",
            (session_id,),
        ).fetchall()

        source_ids = self._summary_sources(connection, summary_rows)
        return ContextSnapshot(
            session=_session_from_row(session_row),
            latest_sequence=session_row["latest_sequence"],
            entries=tuple(_entry_from_row(row) for row in entry_rows),
            summaries=tuple(
                _summary_from_row(row, source_ids.get(row["summary_id"], ()))
                for row in summary_rows
            ),
        )

    def save_context_change(
        self,
        change: ContextStateChangedEventData,
    ) -> ContextSnapshot:
        """原子保存一次 Context 增量变化。"""

        _validate_change(change)
        with self._database.transaction() as connection:
            self._save_session(connection, change)
            for entry in change.appended_entries:
                self._insert_entry(connection, entry)
            if change.created_summary is not None:
                self._insert_summary(connection, change.created_summary)

        snapshot = self.load_context(change.session.session_id)
        if snapshot is None:
            raise RuntimeError("saved context session could not be restored")
        return snapshot

    @staticmethod
    def _save_session(
        connection: sqlite3.Connection,
        change: ContextStateChangedEventData,
    ) -> None:
        session = change.session
        scope = session.conversation_scope
        identity = (
            session.purpose,
            None if scope is None else scope.platform,
            None if scope is None else scope.account_namespace,
            None if scope is None else scope.scene_type.value,
            None if scope is None else scope.scene_id,
            session.work_id,
            format_datetime(session.created_at),
        )
        existing = connection.execute(
            "SELECT purpose, platform, account_namespace, scene_type, scene_id, "
            "work_id, created_at FROM context_sessions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
        if existing is not None and tuple(existing) != identity:
            raise ValueError("context session identity cannot change")

        connection.execute(
            "INSERT INTO context_sessions ("
            "session_id, purpose, platform, account_namespace, scene_type, scene_id, "
            "work_id, created_at, updated_at, closed_at, latest_sequence"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "updated_at = max(context_sessions.updated_at, excluded.updated_at), "
            "closed_at = COALESCE(context_sessions.closed_at, excluded.closed_at), "
            "latest_sequence = max(context_sessions.latest_sequence, excluded.latest_sequence)",
            (
                session.session_id,
                *identity,
                format_datetime(session.updated_at),
                format_datetime(session.closed_at),
                change.latest_sequence,
            ),
        )

    @staticmethod
    def _insert_entry(
        connection: sqlite3.Connection,
        entry: ContextEntryRecord,
    ) -> None:
        values = (
            entry.entry_id,
            entry.session_id,
            entry.sequence,
            entry.entry_type,
            entry.actor.actor_type.value,
            entry.actor.actor_id,
            entry.actor.display_name,
            _content_json(entry.content),
            entry.source_event_id,
            format_datetime(entry.created_at),
        )
        existing = connection.execute(
            "SELECT entry_id, session_id, sequence, entry_type, actor_type, actor_id, "
            "actor_display_name, content_json, source_event_id, created_at "
            "FROM context_entries WHERE entry_id = ?",
            (entry.entry_id,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != values:
                raise ValueError("context entry identity cannot change")
            return
        connection.execute(
            "INSERT INTO context_entries ("
            "entry_id, session_id, sequence, entry_type, actor_type, actor_id, "
            "actor_display_name, content_json, source_event_id, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values,
        )

    @staticmethod
    def _insert_summary(
        connection: sqlite3.Connection,
        summary: ContextSummary,
    ) -> None:
        values = (
            summary.summary_id,
            summary.session_id,
            summary.level,
            summary.first_sequence,
            summary.last_sequence,
            summary.text,
            format_datetime(summary.created_at),
        )
        existing = connection.execute(
            "SELECT summary_id, session_id, level, first_sequence, last_sequence, "
            "text, created_at FROM context_summaries WHERE summary_id = ?",
            (summary.summary_id,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != values:
                raise ValueError("context summary identity cannot change")
        else:
            connection.execute(
                "INSERT INTO context_summaries ("
                "summary_id, session_id, level, first_sequence, last_sequence, text, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                values,
            )

        for position, child_id in enumerate(summary.source_summary_ids):
            source = connection.execute(
                "SELECT parent_summary_id, child_summary_id, position "
                "FROM context_summary_sources "
                "WHERE parent_summary_id = ? AND child_summary_id = ?",
                (summary.summary_id, child_id),
            ).fetchone()
            source_values = (summary.summary_id, child_id, position)
            if source is not None:
                if tuple(source) != source_values:
                    raise ValueError("context summary source order cannot change")
                continue
            connection.execute(
                "INSERT INTO context_summary_sources "
                "(parent_summary_id, child_summary_id, position) VALUES (?, ?, ?)",
                source_values,
            )

    @staticmethod
    def _summary_sources(
        connection: sqlite3.Connection,
        summary_rows: list[sqlite3.Row],
    ) -> dict[str, tuple[str, ...]]:
        summary_ids = [row["summary_id"] for row in summary_rows]
        if not summary_ids:
            return {}
        placeholders = ",".join("?" for _ in summary_ids)
        rows = connection.execute(
            "SELECT parent_summary_id, child_summary_id FROM context_summary_sources "
            f"WHERE parent_summary_id IN ({placeholders}) "
            "ORDER BY parent_summary_id, position",
            summary_ids,
        ).fetchall()
        grouped: dict[str, list[str]] = {}
        for row in rows:
            grouped.setdefault(row["parent_summary_id"], []).append(
                row["child_summary_id"]
            )
        return {key: tuple(value) for key, value in grouped.items()}


def _validate_change(change: ContextStateChangedEventData) -> None:
    session_id = change.session.session_id
    if change.latest_sequence < 0:
        raise ValueError("latest_sequence must not be negative")
    for entry in change.appended_entries:
        if entry.session_id != session_id:
            raise ValueError("context entry belongs to another session")
        if entry.sequence > change.latest_sequence:
            raise ValueError("context entry exceeds latest_sequence")
    summary = change.created_summary
    if summary is not None and summary.session_id != session_id:
        raise ValueError("context summary belongs to another session")


def _content_json(content: Content) -> str:
    return json.dumps(
        {
            "content_type": content.content_type.value,
            "text": content.text,
            "segments": [
                {"type": segment.type.value, "data": segment.data}
                for segment in content.segments
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _content_from_json(value: str) -> Content:
    data = json.loads(value)
    return Content(
        content_type=ContentType(data["content_type"]),
        text=data["text"],
        segments=tuple(
            ContentSegment(ContentType(segment["type"]), segment["data"])
            for segment in data["segments"]
        ),
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    scope = None
    if row["purpose"] == "conversation":
        scope = ConversationScope(
            platform=row["platform"],
            account_namespace=row["account_namespace"],
            scene_type=SceneType(row["scene_type"]),
            scene_id=row["scene_id"],
        )
    return SessionRecord(
        session_id=row["session_id"],
        created_at=_required_datetime(row["created_at"]),
        updated_at=_required_datetime(row["updated_at"]),
        closed_at=parse_datetime(row["closed_at"]),
        purpose=row["purpose"],
        conversation_scope=scope,
        work_id=row["work_id"],
    )


def _entry_from_row(row: sqlite3.Row) -> ContextEntryRecord:
    return ContextEntryRecord(
        entry_id=row["entry_id"],
        session_id=row["session_id"],
        sequence=row["sequence"],
        entry_type=row["entry_type"],
        actor=ContextActorRef(
            ContextActorType(row["actor_type"]),
            row["actor_id"],
            row["actor_display_name"],
        ),
        content=_content_from_json(row["content_json"]),
        source_event_id=row["source_event_id"],
        created_at=_required_datetime(row["created_at"]),
    )


def _summary_from_row(
    row: sqlite3.Row,
    source_summary_ids: tuple[str, ...],
) -> ContextSummary:
    return ContextSummary(
        summary_id=row["summary_id"],
        session_id=row["session_id"],
        level=row["level"],
        first_sequence=row["first_sequence"],
        last_sequence=row["last_sequence"],
        text=row["text"],
        created_at=_required_datetime(row["created_at"]),
        source_summary_ids=source_summary_ids,
    )


def _required_datetime(value: str) -> datetime:
    parsed = parse_datetime(value)
    if parsed is None:
        raise ValueError("required datetime must not be null")
    return parsed
