"""BodyRuntime 会话绑定、输出路由、错误映射与 EventBus 接入的单元测试。"""

from __future__ import annotations

import unittest

from core.body import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
    AdapterRegistry,
    BodyInputEventData,
    BodyModule,
    BodyOutputItemResult,
    BodyOutputRequestData,
    BodyOutputResultEventData,
    BodyRuntime,
    Content,
    OperationStatus,
    SceneInfo,
    SceneType,
    UserRole,
    create_body_module,
)
from core.event import EventBus, EventClient, EventFlow, ModuleEventAPI


class FakeAdapter:
    """记录收到的出站消息并返回固定成功结果的测试适配器。"""

    adapter_type = "discord"
    platform = "discord"

    def __init__(self) -> None:
        self.sent: list[AdapterOutboundMessage] = []

    async def send(self, outbound: AdapterOutboundMessage) -> list[BodyOutputItemResult]:
        self.sent.append(outbound)
        return [BodyOutputItemResult(index=0, status=OperationStatus.COMPLETED)]


class FailingAdapter(FakeAdapter):
    """始终抛出异常的测试适配器。"""

    async def send(self, outbound: AdapterOutboundMessage) -> list[BodyOutputItemResult]:
        raise RuntimeError("boom")


def make_message(
    *,
    message_id: str = "msg-1",
    user_id: str = "u1",
    scene_type: SceneType = SceneType.GROUP,
    scene_id: str = "g1",
    content: Content | None = None,
) -> AdapterInboundMessage:
    """构造一条默认指向 discord 群 g1 的入站消息。"""
    return AdapterInboundMessage(
        adapter_type="discord",
        platform="discord",
        message_id=message_id,
        user_id=user_id,
        display_name="display",
        scene_type=scene_type,
        scene_id=scene_id,
        content=content or Content.from_text("hello"),
    )


def make_runtime(
    *, owner_user_id: str = "owner"
) -> tuple[BodyRuntime, FakeAdapter, AdapterRegistry]:
    """构造绑定单适配器的 BodyRuntime，返回 (runtime, adapter, registry)。"""
    registry = AdapterRegistry()
    adapter = FakeAdapter()
    registry.register(adapter)
    return BodyRuntime(owner_user_id=owner_user_id, adapters=registry), adapter, registry


class SessionBindingTests(unittest.IsolatedAsyncioTestCase):
    """入站消息归一化、会话绑定与去重。"""

    async def test_inbound_event_is_platform_agnostic(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        event = await runtime.handle_adapter_input(make_message(user_id="owner"))
        self.assertIsInstance(event, BodyInputEventData)
        self.assertTrue(event.session_id)
        self.assertEqual(event.source.user_id, "owner")
        self.assertEqual(event.source.role, UserRole.OWNER)
        self.assertEqual(event.scene.scene_type, SceneType.GROUP)
        # 公共契约不得暴露平台标识或路由字段。
        for field_name in ("adapter_type", "platform", "body_id", "platform_message_id"):
            self.assertNotIn(field_name, BodyInputEventData.__dataclass_fields__)
        for field_name in ("adapter_type", "platform", "scene", "reply_to"):
            self.assertNotIn(field_name, BodyOutputRequestData.__dataclass_fields__)

    async def test_same_conversation_reuses_session(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        first = await runtime.handle_adapter_input(make_message(message_id="msg-1"))
        second = await runtime.handle_adapter_input(
            make_message(message_id="msg-2", user_id="u2")
        )
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(second.session_id, first.session_id)

    async def test_different_scene_gets_different_session(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        group = await runtime.handle_adapter_input(make_message(scene_id="g1"))
        other = await runtime.handle_adapter_input(
            make_message(message_id="msg-2", scene_id="g2")
        )
        self.assertNotEqual(group.session_id, other.session_id)

    async def test_duplicate_message_is_filtered(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        message = make_message(message_id="msg-dup")
        self.assertIsNotNone(await runtime.handle_adapter_input(message))
        self.assertIsNone(await runtime.handle_adapter_input(message))

    async def test_empty_content_is_filtered(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        message = make_message(content=Content(""))
        self.assertIsNone(await runtime.handle_adapter_input(message))

    async def test_role_resolution(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        owner = await runtime.handle_adapter_input(
            make_message(user_id="owner", scene_type=SceneType.GROUP)
        )
        member = await runtime.handle_adapter_input(
            make_message(message_id="m2", user_id="u2", scene_type=SceneType.GROUP)
        )
        private = await runtime.handle_adapter_input(
            make_message(message_id="m3", user_id="u2", scene_type=SceneType.PRIVATE)
        )
        self.assertEqual(owner.source.role, UserRole.OWNER)
        self.assertEqual(member.source.role, UserRole.GROUP_MEMBER)
        self.assertEqual(private.source.role, UserRole.PRIVATE_USER)


class OutputRoutingTests(unittest.IsolatedAsyncioTestCase):
    """输出路由、幂等与错误映射。"""

    async def test_output_routes_to_adapter_with_reply_target(self) -> None:
        runtime, adapter, _registry = make_runtime()
        first = await runtime.handle_adapter_input(make_message(message_id="msg-1"))
        await runtime.handle_adapter_input(make_message(message_id="msg-2", user_id="u2"))
        request = BodyOutputRequestData(
            output_id="o1",
            session_id=first.session_id,
            content=Content.from_text("hi"),
            metadata={"presentation": {"emotion": "happy"}},
        )
        result = await runtime.handle_output_request(request)
        self.assertEqual(result.outcome, OperationStatus.COMPLETED)
        self.assertEqual(len(adapter.sent), 1)
        outbound = adapter.sent[0]
        self.assertEqual(outbound.adapter_type, "discord")
        self.assertEqual(outbound.platform, "discord")
        self.assertEqual(outbound.scene.scene_id, "g1")
        self.assertEqual(outbound.content.text_value(), "hi")
        self.assertEqual(outbound.reply_to_message_id, "msg-2")
        self.assertEqual(outbound.metadata["presentation"]["emotion"], "happy")

    async def test_output_is_idempotent(self) -> None:
        runtime, adapter, _registry = make_runtime()
        event = await runtime.handle_adapter_input(make_message())
        request = BodyOutputRequestData(
            output_id="o1", session_id=event.session_id, content=Content.from_text("hi")
        )
        first = await runtime.handle_output_request(request)
        second = await runtime.handle_output_request(request)
        self.assertIs(second, first)
        self.assertEqual(len(adapter.sent), 1)

    async def test_unknown_session_reports_session_not_found(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        request = BodyOutputRequestData(
            output_id="o1",
            session_id="not-a-session",
            content=Content.from_text("hi"),
        )
        result = await runtime.handle_output_request(request)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, "session_not_found")

    async def test_unregistered_adapter_reports_adapter_not_found(self) -> None:
        runtime, _adapter, registry = make_runtime()
        event = await runtime.handle_adapter_input(make_message())
        registry._adapter_map.clear()  # 模拟运行期适配器被移除
        request = BodyOutputRequestData(
            output_id="o1", session_id=event.session_id, content=Content.from_text("hi")
        )
        result = await runtime.handle_output_request(request)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, "adapter_not_found")

    async def test_adapter_exception_maps_to_send_failed(self) -> None:
        registry = AdapterRegistry()
        registry.register(FailingAdapter())
        runtime = BodyRuntime(owner_user_id="owner", adapters=registry)
        event = await runtime.handle_adapter_input(make_message())
        request = BodyOutputRequestData(
            output_id="o1", session_id=event.session_id, content=Content.from_text("hi")
        )
        result = await runtime.handle_output_request(request)
        self.assertIsNotNone(result.error)
        self.assertEqual(result.error.code, "adapter_send_failed")

    async def test_outbound_metadata_is_copied(self) -> None:
        runtime, adapter, _registry = make_runtime()
        event = await runtime.handle_adapter_input(make_message())
        metadata = {"presentation": {"emotion": "happy"}}
        request = BodyOutputRequestData(
            output_id="o1",
            session_id=event.session_id,
            content=Content.from_text("hi"),
            metadata=metadata,
        )
        await runtime.handle_output_request(request)
        adapter.sent[0].metadata["injected"] = True
        self.assertNotIn("injected", metadata)

    async def test_open_session_enables_proactive_send(self) -> None:
        runtime, adapter, _registry = make_runtime()
        session_id = await runtime.open_session(
            "discord", "discord", SceneInfo(SceneType.PRIVATE, "p1")
        )
        request = BodyOutputRequestData(
            output_id="o1", session_id=session_id, content=Content.from_text("notice")
        )
        result = await runtime.handle_output_request(request)
        self.assertEqual(result.outcome, OperationStatus.COMPLETED)
        self.assertIsNone(adapter.sent[0].reply_to_message_id)
        # 同一路由的入站消息应复用主动创建的会话。
        event = await runtime.handle_adapter_input(
            make_message(message_id="m1", scene_type=SceneType.PRIVATE, scene_id="p1")
        )
        self.assertEqual(event.session_id, session_id)

    async def test_open_session_rejects_unregistered_adapter(self) -> None:
        runtime, _adapter, _registry = make_runtime()
        with self.assertRaises(LookupError):
            await runtime.open_session(
                "telegram", "telegram", SceneInfo(SceneType.PRIVATE, "p1")
            )


class OutcomeAggregationTests(unittest.TestCase):
    """BodyOutputResultEventData.outcome 汇总逻辑。"""

    def test_outcome_aggregation(self) -> None:
        completed = [BodyOutputItemResult(index=0, status=OperationStatus.COMPLETED)]
        mixed = [
            BodyOutputItemResult(index=0, status=OperationStatus.COMPLETED),
            BodyOutputItemResult(index=1, status=OperationStatus.FAILED),
        ]
        failed = [BodyOutputItemResult(index=0, status=OperationStatus.FAILED)]
        self.assertEqual(
            BodyOutputResultEventData("o1", completed).outcome,
            OperationStatus.COMPLETED,
        )
        self.assertEqual(
            BodyOutputResultEventData("o1", mixed).outcome,
            OperationStatus.PARTIALLY_COMPLETED,
        )
        self.assertEqual(
            BodyOutputResultEventData("o1", failed).outcome,
            OperationStatus.FAILED,
        )
        self.assertEqual(
            BodyOutputResultEventData("o1", []).outcome,
            OperationStatus.FAILED,
        )


class BodyEventIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """Body events 与重构后 EventBus 的接入往返。"""

    async def test_input_publish_round_trip(self) -> None:
        bus = EventBus()
        await bus.start()
        try:
            runtime, _adapter, _registry = make_runtime()
            events = ModuleEventAPI(bus, "body")
            module = BodyModule(runtime)
            module.register(events)
            observed: list[BodyInputEventData] = []

            async def observer(flow: EventFlow) -> None:
                observed.append(flow.payload)

            events.subscribe(
                "body.input.received", observer, handler_id="test.input.observer"
            )
            client = EventClient(bus, "adapter.discord")
            event = await module.publish_input(client, make_message())
            await bus.stop()
            self.assertIsNotNone(event)
            self.assertEqual(observed, [event])
        finally:
            await bus.stop()

    async def test_output_request_round_trip(self) -> None:
        bus = EventBus()
        await bus.start()
        try:
            runtime, adapter, _registry = make_runtime()
            events = ModuleEventAPI(bus, "body")
            module = BodyModule(runtime)
            module.register(events)
            observed: list[BodyOutputResultEventData] = []

            async def observer(flow: EventFlow) -> None:
                if isinstance(flow.payload, BodyOutputResultEventData):
                    observed.append(flow.payload)

            events.subscribe(
                "body.output.*", observer, handler_id="test.output.observer"
            )
            client = EventClient(bus, "adapter.discord")
            event = await module.publish_input(client, make_message())
            await events.publish(
                "body.output.requested",
                BodyOutputRequestData(
                    output_id="o1",
                    session_id="not-a-session",
                    content=Content.from_text("hi"),
                ),
            )
            await events.publish(
                "body.output.requested",
                BodyOutputRequestData(
                    output_id="o2",
                    session_id=event.session_id,
                    content=Content.from_text("hi"),
                ),
            )
            await bus.stop()
            self.assertEqual(len(adapter.sent), 1)
            kinds = sorted(
                item.error.code if item.error is not None else item.outcome.value
                for item in observed
            )
            self.assertEqual(kinds, ["completed", "session_not_found"])
        finally:
            await bus.stop()


class BodyFactoryTests(unittest.IsolatedAsyncioTestCase):
    """Body 组合入口应装配 Registry、Runtime 和事件边界。"""

    async def test_factory_wires_adapter_input_and_output(self) -> None:
        bus = EventBus()
        module = create_body_module("owner")
        self.assertIsInstance(module, BodyModule)
        adapter = FakeAdapter()
        module.register_adapter(adapter)
        module.register(ModuleEventAPI(bus, "body"))

        observed: list[BodyInputEventData] = []

        async def observe_input(flow: EventFlow) -> None:
            observed.append(flow.payload)

        ModuleEventAPI(bus, "test").subscribe(
            "body.input.received",
            observe_input,
            handler_id="test.factory_input",
        )
        await bus.start()
        try:
            event = await module.publish_input(
                EventClient(bus, "adapter.discord"),
                make_message(user_id="owner"),
            )
            self.assertIsNotNone(event)
            await EventClient(bus, "agent").publish(
                "body.output.requested",
                BodyOutputRequestData(
                    output_id="factory-output",
                    session_id=event.session_id,
                    content=Content.from_text("hello from factory"),
                ),
            )
            await bus.stop()
        finally:
            await bus.stop()

        self.assertEqual(observed, [event])
        self.assertEqual(len(adapter.sent), 1)
        self.assertEqual(adapter.sent[0].content.text_value(), "hello from factory")

    async def test_factory_accepts_replacement_registry(self) -> None:
        registry = AdapterRegistry()
        adapter = FakeAdapter()
        registry.register(adapter)
        module = create_body_module("owner", adapters=registry)

        bus = EventBus()
        module.register(ModuleEventAPI(bus, "body"))
        await bus.start()
        try:
            event = await module.publish_input(
                EventClient(bus, "adapter.discord"),
                make_message(),
            )
            self.assertIsNotNone(event)
        finally:
            await bus.stop()

if __name__ == "__main__":
    unittest.main()
