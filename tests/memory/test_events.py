"""Memory 通过 EventBus 接入查询链路的测试。"""

from __future__ import annotations

import asyncio
import unittest

from core.event import EventBus, EventClient, EventFlow, ModuleEventAPI
from core.memory.contracts import (
    MemoryQueryFailedEventData,
    MemoryQueryRequest,
    MemoryQueryResult,
    MemoryWriteFailedEventData,
    MemoryWriteMessage,
    MemoryWriteRequest,
    MemoryWriteResult,
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


class WriteService:
    def __init__(self, result: MemoryWriteResult | None = None) -> None:
        self.result = result
        self.requests: list[MemoryWriteRequest] = []

    async def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        self.requests.append(request)
        if self.result is None:
            return MemoryWriteResult(
                operation_id=request.operation_id,
                memory_space_id=request.memory_space_id,
            )
        return self.result


class FailingWriteService:
    async def write(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        raise RuntimeError("memory write unavailable")


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


class MemoryModuleWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_requested_emits_completed_result(self) -> None:
        bus = EventBus()
        service = WriteService()
        MemoryModule(service).register(ModuleEventAPI(bus, "memory"))

        completed: list[MemoryWriteResult] = []
        completed_event = asyncio.Event()

        async def observe_completed(flow: EventFlow) -> None:
            completed.append(flow.payload)
            completed_event.set()

        ModuleEventAPI(bus, "test").subscribe(
            "memory.write.completed",
            observe_completed,
            handler_id="test.memory_write_completed",
        )

        request = MemoryWriteRequest(
            operation_id="write_1",
            memory_space_id="sena",
            user_id="user_1",
            session_id="session_1",
            group_id="group_1",
            messages=(
                MemoryWriteMessage(
                    message_id="message_1",
                    role="user",
                    content="用户喜欢咖啡",
                ),
            ),
            source_event_id="event_1",
        )

        await bus.start()
        try:
            await EventClient(bus, "agent").publish(
                "memory.write.requested",
                request,
            )
            await asyncio.wait_for(completed_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(service.requests, [request])
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0].operation_id, "write_1")
        self.assertEqual(completed[0].memory_space_id, "sena")

    async def test_write_failure_emits_failed_result(self) -> None:
        bus = EventBus()
        MemoryModule(FailingWriteService()).register(ModuleEventAPI(bus, "memory"))

        failures: list[MemoryWriteFailedEventData] = []
        failed_event = asyncio.Event()

        async def observe_failed(flow: EventFlow) -> None:
            failures.append(flow.payload)
            failed_event.set()

        ModuleEventAPI(bus, "test").subscribe(
            "memory.write.failed",
            observe_failed,
            handler_id="test.memory_write_failed",
        )

        await bus.start()
        try:
            await EventClient(bus, "agent").publish(
                "memory.write.requested",
                MemoryWriteRequest(
                    operation_id="write_1",
                    memory_space_id="sena",
                    user_id="user_1",
                    session_id="session_1",
                    group_id="group_1",
                    messages=(
                        MemoryWriteMessage(
                            message_id="message_1",
                            role="user",
                            content="用户喜欢咖啡",
                        ),
                    ),
                    source_event_id="event_1",
                ),
            )
            await asyncio.wait_for(failed_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].operation_id, "write_1")
        self.assertEqual(failures[0].memory_space_id, "sena")
        self.assertEqual(failures[0].error.code, "RuntimeError")


if __name__ == "__main__":
    unittest.main()
