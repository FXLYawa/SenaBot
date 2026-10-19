"""Memory 通过 EventBus 接入查询链路的测试。"""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from core.common import Content, SceneInfo, SceneType
from core.context import (
    ContextActorRef, ContextActorType, ContextEntryRecord, ContextReadView,
    ContextReadRequestData, ContextReadResultEventData, ContextStateChangedEventData,
    SessionRecord,
)
from core.memory.extraction_flow import MemoryExtractionFlow, MemoryExtractionConfig, MemoryExtractionPolicy

from core.event import EventBus, EventClient, EventFlow, ModuleEventAPI
from core.memory.contracts import (
    MemoryQueryFailedEventData,
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryExtractionFailedEventData,
    MemoryExtractionResult,
)
from core.memory.events import MemoryModule


class QueryService:
    def __init__(self, result: MemoryQueryResult | None = None) -> None:
        self.result = result
        self.requests: list[MemoryQueryRequest] = []

    async def query(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        self.requests.append(request)
        if self.result is None:
            return MemoryQueryResult(
                query_id=request.query_id,
                memory_space_id=request.memory_space_id,
                user_id=request.user_id,
                session_id=request.session_id,
                group_id=request.group_id,
                memories=[],
            )
        return self.result


class FailingQueryService:
    async def query(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        raise RuntimeError("memory store unavailable")


class ExtractionService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, str, str, ContextReadView]] = []

    async def extract_and_store(
        self, *, operation_id: str, memory_space_id: str, user_id: str, context: ContextReadView,
    ) -> MemoryExtractionResult:
        self.calls.append((operation_id, memory_space_id, user_id, context))
        if self.fail:
            raise RuntimeError("store unavailable")
        return MemoryExtractionResult(
            operation_id, memory_space_id, context.session.session_id,
            context.through_sequence, added_item_ids=("memory-001",),
        )


class RecordingProgress:
    def __init__(self) -> None:
        self.saved: list[tuple[str, str, int]] = []

    def load_processed_sequence(self, memory_space_id: str, session_id: str) -> int:
        return 0

    def save_processed_sequence(self, memory_space_id: str, session_id: str, through_sequence: int) -> None:
        self.saved.append((memory_space_id, session_id, through_sequence))


class MemoryModuleQueryTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_requested_emits_completed_result(self) -> None:
        bus = EventBus()
        service = QueryService()
        MemoryModule(service).register(ModuleEventAPI(bus, "memory"))

        completed: list[MemoryQueryResult] = []
        completed_event = asyncio.Event()

        async def observe_completed(flow: EventFlow) -> None:
            completed.append(flow.payload)
            completed_event.set()

        ModuleEventAPI(bus, "test").subscribe(
            "memory.query.completed",
            observe_completed,
            handler_id="test.memory_query_completed",
        )

        request = MemoryQueryRequest(
            query_id="query_1",
            memory_space_id="sena",
            group_id="group_1",
            session_id="session_1",
            user_id="user_1",
            query_text="用户喜欢什么？",
        )

        await bus.start()
        try:
            await EventClient(bus, "agent").publish(
                "memory.query.requested",
                request,
            )
            await asyncio.wait_for(completed_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(service.requests, [request])
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].query_id, "query_1")
        self.assertEqual(completed[0].memory_space_id, "sena")
        self.assertEqual(completed[0].memories, [])

    async def test_query_failure_emits_failed_result(self) -> None:
        bus = EventBus()
        MemoryModule(FailingQueryService()).register(ModuleEventAPI(bus, "memory"))

        failures: list[MemoryQueryFailedEventData] = []
        failed_event = asyncio.Event()

        async def observe_failed(flow: EventFlow) -> None:
            failures.append(flow.payload)
            failed_event.set()

        ModuleEventAPI(bus, "test").subscribe(
            "memory.query.failed",
            observe_failed,
            handler_id="test.memory_query_failed",
        )

        await bus.start()
        try:
            await EventClient(bus, "agent").publish(
                "memory.query.requested",
                MemoryQueryRequest(
                    query_id="query_1",
                    memory_space_id="sena",
                    group_id="group_1",
                    session_id="session_1",
                    user_id="user_1",
                    query_text="用户喜欢什么？",
                ),
            )
            await asyncio.wait_for(failed_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].query_id, "query_1")
        self.assertEqual(failures[0].memory_space_id, "sena")
        self.assertEqual(failures[0].error.code, "RuntimeError")


class MemoryModuleExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_change_reads_batch_and_emits_extraction_outcome(self) -> None:
        for fail in (False, True):
            with self.subTest(fail=fail):
                bus = EventBus()
                service = ExtractionService(fail=fail)
                progress = RecordingProgress()
                scene = SceneInfo(platform="desktop", scene_type=SceneType.DESKTOP, scene_id="desktop")
                config = MemoryExtractionConfig(
                    memory_space_id="sena", user_id="user-001", scene=scene,
                    policy=MemoryExtractionPolicy(entry_threshold=1, batch_size=1),
                )
                MemoryModule(service, MemoryExtractionFlow(service, progress, config)).register(
                    ModuleEventAPI(bus, "memory"),
                )
                context_api = ModuleEventAPI(bus, "context")
                context_api.register("context.state.changed", payload_type=ContextStateChangedEventData)
                context_api.register("context.read.requested", payload_type=ContextReadRequestData)
                context_api.register("context.read.resolved", payload_type=ContextReadResultEventData)
                now = datetime(2026, 9, 11, tzinfo=UTC)
                session = SessionRecord("session-desktop", now, now, scene=scene)
                entry = ContextEntryRecord(
                    "entry-001", session.session_id, 1, "user_message",
                    ContextActorRef(ContextActorType.USER, "user-001", "Alice"),
                    Content.from_text("我喜欢咖啡"), "event-001", now,
                )
                view = ContextReadView(session, 0, 1, (entry,))
                reads: list[ContextReadRequestData] = []
                outcomes: list[tuple[str, object]] = []
                done = asyncio.Event()

                async def read_context(flow: EventFlow) -> None:
                    request = flow.payload
                    reads.append(request)
                    flow.emit("context.read.resolved", ContextReadResultEventData(
                        request.operation_id, request.session_id, view=view,
                    ))

                async def observe(flow: EventFlow) -> None:
                    outcomes.append((flow.envelope.event_type, flow.payload))
                    done.set()

                context_api.subscribe("context.read.requested", read_context, handler_id="test.read")
                ModuleEventAPI(bus, "test").subscribe("memory.extraction.*", observe, handler_id="test.outcome")
                await bus.start()
                try:
                    await context_api.publish("context.state.changed", ContextStateChangedEventData(
                        session, 1, (entry,),
                    ))
                    await asyncio.wait_for(done.wait(), timeout=1)
                finally:
                    await bus.stop()

                self.assertEqual(len(reads), 1)
                request = reads[0]
                self.assertEqual((request.session_id, request.after_sequence, request.through_sequence),
                                 (session.session_id, 0, 1))
                self.assertEqual(service.calls, [(request.operation_id, "sena", "user-001", view)])
                self.assertEqual(len(outcomes), 1)
                event_type, result = outcomes[0]
                self.assertEqual(result.operation_id, request.operation_id)
                self.assertEqual(result.memory_space_id, "sena")
                self.assertEqual(result.session_id, session.session_id)
                if fail:
                    self.assertEqual(event_type, "memory.extraction.failed")
                    self.assertIsInstance(result, MemoryExtractionFailedEventData)
                    self.assertEqual(result.error.code, "RuntimeError")
                    self.assertEqual(result.error.message, "Automatic memory extraction failed.")
                    self.assertEqual(progress.saved, [])
                else:
                    self.assertEqual(event_type, "memory.extraction.completed")
                    self.assertIsInstance(result, MemoryExtractionResult)
                    self.assertEqual(result.processed_through_sequence, 1)
                    self.assertEqual(result.added_item_ids, ("memory-001",))
                    self.assertEqual(result.updated_item_ids, ())
                    self.assertEqual(progress.saved, [("sena", session.session_id, 1)])


if __name__ == "__main__":
    unittest.main()
