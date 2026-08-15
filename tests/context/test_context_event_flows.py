"""Context 通过 EventBus 完成会话恢复与上下文准备的链路测试。"""

from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from core.context.body import BodyRouteInfo, InteractionSignals
from core.context.common import Content, SceneInfo, SourceInfo
from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextEntryRecord,
    ContextEntryType,
    ContextErrorInfo,
    ContextInputFailedEventData,
    ContextPreparedEventData,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextSnapshot,
    ContextStateChangedEventData,
    ContextWorkReadyEventData,
    ContextWorkRequestData,
    SessionRecord,
)
from core.context.events import ContextModule
from core.context.identity import conversation_session_id
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.event import EventBus, EventClient, EventEnvelope, EventFlow, ModuleEventAPI


class CompatibleSceneType(StrEnum):
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class CompatibleConversationScope:
    """临时表达 Context 当前需要的稳定会话边界。"""

    platform: str = "discord"
    scene_type: CompatibleSceneType = CompatibleSceneType.GROUP
    scene_id: str = "group_1"
    account_namespace: str = "bot_1"

    @property
    def scene(self) -> SceneInfo:
        return SceneInfo(self.scene_type, self.scene_id, "测试群")


@dataclass(frozen=True, slots=True)
class CompatibleBodyInput:
    """隔离尚未对齐的 Body 公共契约，只保留 Context 实际消费的字段。"""

    conversation_scope: CompatibleConversationScope
    source: SourceInfo
    content: Content
    output_route: BodyRouteInfo
    interaction: InteractionSignals = InteractionSignals()
    reply_target_id: str | None = None


class ContextConversationChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_input_restores_once_then_following_input_reuses_session(self) -> None:
        bus = EventBus()
        ModuleEventAPI(bus, "body").register(
            "body.input.received",
            payload_type=CompatibleBodyInput,
        )
        context = ContextModule(ContextStateStore(), ContextWindowPolicy())
        context.register(ModuleEventAPI(bus, "context"))

        test_api = ModuleEventAPI(bus, "test")
        restore_requests: list[ContextRestoreRequestData] = []
        prepared: list[tuple[EventEnvelope, ContextPreparedEventData]] = []
        state_changes: list[ContextStateChangedEventData] = []
        prepared_changed = asyncio.Event()

        async def restore_not_found(flow: EventFlow) -> None:
            request: ContextRestoreRequestData = flow.payload
            restore_requests.append(request)
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    operation_id=request.operation_id,
                    session_id=request.session_id,
                    status="not_found",
                ),
            )

        async def observe_prepared(flow: EventFlow) -> None:
            prepared.append((flow.envelope, flow.payload))
            prepared_changed.set()

        async def observe_state(flow: EventFlow) -> None:
            state_changes.append(flow.payload)

        test_api.subscribe(
            "context.restore.requested",
            restore_not_found,
            handler_id="test.restore_conversation",
        )
        test_api.subscribe(
            "context.prepared",
            observe_prepared,
            handler_id="test.observe_prepared",
        )
        test_api.subscribe(
            "context.state.changed",
            observe_state,
            handler_id="test.observe_conversation_state",
        )

        source = SourceInfo("platform_user_1", "Alice", False, "user_1")
        route = BodyRouteInfo("discord", "discord", "body_1")
        scope = CompatibleConversationScope()
        client = EventClient(bus, "body")

        await bus.start()
        try:
            await client.publish(
                "body.input.received",
                CompatibleBodyInput(scope, source, Content.from_text("第一条"), route),
            )
            await asyncio.wait_for(prepared_changed.wait(), timeout=1)

            prepared_changed.clear()
            await client.publish(
                "body.input.received",
                CompatibleBodyInput(scope, source, Content.from_text("第二条"), route),
            )
            await asyncio.wait_for(prepared_changed.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(restore_requests), 1)
        self.assertEqual(len(prepared), 2)
        self.assertEqual(prepared[0][1].session_id, prepared[1][1].session_id)
        self.assertEqual(
            [entry.sequence for entry in prepared[1][1].entries],
            [1, 2],
        )
        self.assertEqual(
            [entry.text() for entry in prepared[1][1].entries],
            ["第一条", "第二条"],
        )
        self.assertEqual(
            [change.latest_sequence for change in state_changes],
            [1, 2],
        )
        for envelope, payload in prepared:
            self.assertEqual(envelope.trace.parent_event_id, payload.trigger_event_id)

    async def test_restored_entries_are_kept_before_the_new_input(self) -> None:
        bus = EventBus()
        ModuleEventAPI(bus, "body").register(
            "body.input.received",
            payload_type=CompatibleBodyInput,
        )
        ContextModule(ContextStateStore(), ContextWindowPolicy()).register(
            ModuleEventAPI(bus, "context")
        )

        test_api = ModuleEventAPI(bus, "test")
        prepared_payloads: list[ContextPreparedEventData] = []
        prepared_event = asyncio.Event()
        scope = CompatibleConversationScope()
        session_id = conversation_session_id(scope)
        now = datetime.now(UTC)
        restored_entry = ContextEntryRecord(
            entry_id="entry_restored",
            session_id=session_id,
            sequence=1,
            entry_type=ContextEntryType.SENA_MESSAGE,
            actor=ContextActorRef(ContextActorType.SENA, "sena"),
            content=Content.from_text("之前的回复"),
            source_event_id="event_old",
            created_at=now,
        )
        snapshot = ContextSnapshot(
            session=SessionRecord(
                session_id=session_id,
                created_at=now,
                updated_at=now,
                purpose="conversation",
                conversation_scope=scope,
            ),
            latest_sequence=1,
            entries=(restored_entry,),
        )

        async def restore_snapshot(flow: EventFlow) -> None:
            request: ContextRestoreRequestData = flow.payload
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    operation_id=request.operation_id,
                    session_id=request.session_id,
                    status="completed",
                    snapshot=snapshot,
                ),
            )

        async def observe_prepared(flow: EventFlow) -> None:
            prepared_payloads.append(flow.payload)
            prepared_event.set()

        test_api.subscribe(
            "context.restore.requested",
            restore_snapshot,
            handler_id="test.restore_snapshot",
        )
        test_api.subscribe(
            "context.prepared",
            observe_prepared,
            handler_id="test.observe_restored_context",
        )

        await bus.start()
        try:
            await EventClient(bus, "body").publish(
                "body.input.received",
                CompatibleBodyInput(
                    scope,
                    SourceInfo("platform_user_1", "Alice", False, "user_1"),
                    Content.from_text("新的输入"),
                    BodyRouteInfo("discord", "discord", "body_1"),
                ),
            )
            await asyncio.wait_for(prepared_event.wait(), timeout=1)
        finally:
            await bus.stop()

        prepared = prepared_payloads[0]
        self.assertEqual(prepared.session_id, session_id)
        self.assertEqual([entry.sequence for entry in prepared.entries], [1, 2])
        self.assertEqual(
            [entry.text() for entry in prepared.entries],
            ["之前的回复", "新的输入"],
        )
        self.assertEqual(prepared.trigger_entry_id, prepared.entries[-1].entry_id)

    async def test_restore_failure_emits_failure_without_preparing_context(self) -> None:
        bus = EventBus()
        ModuleEventAPI(bus, "body").register(
            "body.input.received",
            payload_type=CompatibleBodyInput,
        )
        ContextModule(ContextStateStore(), ContextWindowPolicy()).register(
            ModuleEventAPI(bus, "context")
        )

        test_api = ModuleEventAPI(bus, "test")
        failures: list[ContextInputFailedEventData] = []
        prepared: list[ContextPreparedEventData] = []
        failed_event = asyncio.Event()

        async def fail_restore(flow: EventFlow) -> None:
            request: ContextRestoreRequestData = flow.payload
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    operation_id=request.operation_id,
                    session_id=request.session_id,
                    status="failed",
                    error=ContextErrorInfo("storage_unavailable", "暂时无法读取"),
                ),
            )

        async def observe_failure(flow: EventFlow) -> None:
            failures.append(flow.payload)
            failed_event.set()

        async def observe_prepared(flow: EventFlow) -> None:
            prepared.append(flow.payload)

        test_api.subscribe(
            "context.restore.requested",
            fail_restore,
            handler_id="test.fail_restore",
        )
        test_api.subscribe(
            "context.input.failed",
            observe_failure,
            handler_id="test.observe_input_failure",
        )
        test_api.subscribe(
            "context.prepared",
            observe_prepared,
            handler_id="test.reject_prepared_after_failure",
        )

        scope = CompatibleConversationScope()
        await bus.start()
        try:
            await EventClient(bus, "body").publish(
                "body.input.received",
                CompatibleBodyInput(
                    scope,
                    SourceInfo("platform_user_1", "Alice", False, "user_1"),
                    Content.from_text("无法恢复的输入"),
                    BodyRouteInfo("discord", "discord", "body_1"),
                ),
            )
            await asyncio.wait_for(failed_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].error.code, "storage_unavailable")
        self.assertEqual(prepared, [])


class ContextWorkSessionChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_same_work_identity_restores_once_and_reuses_session(self) -> None:
        bus = EventBus()
        ContextModule(ContextStateStore(), ContextWindowPolicy()).register(
            ModuleEventAPI(bus, "context")
        )
        test_api = ModuleEventAPI(bus, "test")
        restore_requests: list[ContextRestoreRequestData] = []
        ready_payloads: list[ContextWorkReadyEventData] = []
        ready_event = asyncio.Event()

        async def restore_not_found(flow: EventFlow) -> None:
            request: ContextRestoreRequestData = flow.payload
            restore_requests.append(request)
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    operation_id=request.operation_id,
                    session_id=request.session_id,
                    status="not_found",
                ),
            )

        async def observe_ready(flow: EventFlow) -> None:
            ready_payloads.append(flow.payload)
            ready_event.set()

        test_api.subscribe(
            "context.restore.requested",
            restore_not_found,
            handler_id="test.restore_work",
        )
        test_api.subscribe(
            "context.work.ready",
            observe_ready,
            handler_id="test.observe_reused_work",
        )

        client = EventClient(bus, "agent")
        await bus.start()
        try:
            await client.publish(
                "context.work.requested",
                ContextWorkRequestData("operation_1", "task_1", "task"),
            )
            await asyncio.wait_for(ready_event.wait(), timeout=1)
            ready_event.clear()
            await client.publish(
                "context.work.requested",
                ContextWorkRequestData("operation_2", "task_1", "task"),
            )
            await asyncio.wait_for(ready_event.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(restore_requests), 1)
        self.assertEqual(
            [payload.operation_id for payload in ready_payloads],
            ["operation_1", "operation_2"],
        )
        self.assertEqual(ready_payloads[0].session_id, ready_payloads[1].session_id)


if __name__ == "__main__":
    unittest.main()
