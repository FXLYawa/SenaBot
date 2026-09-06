"""DataModule 对 Context restore/state changed 事件的 MVP 支撑测试。"""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from core.common import Content
from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextEntryRecord,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextRestoreStatus,
    ContextSnapshot,
    ContextStateChangedEventData,
    SessionRecord,
)
from core.common import Summary
from core.data import DataModule, InMemoryDataStore
from core.event import EventBus, EventClient, EventFlow, ModuleEventAPI


def _snapshot() -> ContextSnapshot:
    now = datetime.now(UTC)
    session = SessionRecord(
        session_id="session_1",
        created_at=now,
        updated_at=now,
    )
    entry = ContextEntryRecord(
        entry_id="entry_1",
        session_id="session_1",
        sequence=1,
        entry_type="user_message",
        actor=ContextActorRef(ContextActorType.USER, "user_1"),
        content=Content.from_text("你好"),
        source_event_id="event_1",
        created_at=now,
    )
    return ContextSnapshot(
        session=session,
        latest_sequence=1,
        entries=(entry,),
    )


def _register_context_events(events: ModuleEventAPI) -> None:
    events.register(
        "context.restore.requested",
        payload_type=ContextRestoreRequestData,
    )
    events.register(
        "context.restore.resolved",
        payload_type=ContextRestoreResultEventData,
    )
    events.register(
        "context.state.changed",
        payload_type=ContextStateChangedEventData,
    )


class DataModuleContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_restore_returns_not_found_when_session_is_absent(self) -> None:
        bus = EventBus(dispatch_concurrency=1)
        _register_context_events(ModuleEventAPI(bus, "context"))
        DataModule(InMemoryDataStore()).register(ModuleEventAPI(bus, "data"))

        resolved: list[ContextRestoreResultEventData] = []
        resolved_event = asyncio.Event()

        async def observe_resolved(flow: EventFlow) -> None:
            resolved.append(flow.payload)
            resolved_event.set()

        ModuleEventAPI(bus, "test").subscribe(
            "context.restore.resolved",
            observe_resolved,
            handler_id="test.context_restore_resolved",
        )

        await bus.start()
        try:
            await EventClient(bus, "context").publish(
                "context.restore.requested",
                ContextRestoreRequestData("session_1"),
            )
            await asyncio.wait_for(resolved_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].session_id, "session_1")
        self.assertEqual(resolved[0].status, ContextRestoreStatus.NOT_FOUND)

    async def test_state_changed_can_be_restored_as_snapshot(self) -> None:
        bus = EventBus(dispatch_concurrency=1)
        _register_context_events(ModuleEventAPI(bus, "context"))
        DataModule(InMemoryDataStore()).register(ModuleEventAPI(bus, "data"))

        resolved: list[ContextRestoreResultEventData] = []
        resolved_event = asyncio.Event()

        async def observe_resolved(flow: EventFlow) -> None:
            resolved.append(flow.payload)
            resolved_event.set()

        ModuleEventAPI(bus, "test").subscribe(
            "context.restore.resolved",
            observe_resolved,
            handler_id="test.context_restore_resolved",
        )

        snapshot = _snapshot()

        await bus.start()
        try:
            await EventClient(bus, "context").publish(
                "context.state.changed",
                ContextStateChangedEventData.from_snapshot(
                    snapshot,
                    appended_entries=snapshot.entries,
                ),
            )
            await EventClient(bus, "context").publish(
                "context.restore.requested",
                ContextRestoreRequestData("session_1"),
            )
            await asyncio.wait_for(resolved_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].status, ContextRestoreStatus.COMPLETED)
        self.assertEqual(resolved[0].snapshot, snapshot)


if __name__ == "__main__":
    unittest.main()
