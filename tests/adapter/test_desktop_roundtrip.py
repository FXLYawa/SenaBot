"""Desktop Adapter 与真实 Body、EventBus 边界的端到端验证。"""

from __future__ import annotations

import asyncio
import functools
import json
import unittest
from collections.abc import Awaitable, Callable

from core.body import (
    AdapterInboundMessage,
    AdapterRegistry,
    BodyInputEventData,
    BodyOutputRequestData,
    BodyOutputResultEventData,
    BodyRuntime,
    Content,
    OperationStatus,
    SceneType,
    UserRole,
    publish_body_input,
    register_body_events,
    subscribe_body_events,
)
from core.event import EventBus, EventClient, EventFlow, ModuleEventAPI

from adapter.desktop import DesktopAdapter, DesktopCodec


class FakeConnector:
    """在不启动真实 WebSocket 的情况下记录 Adapter 原始出站字符串。"""

    def __init__(self) -> None:
        self.on_message: Callable[[str], Awaitable[None]] | None = None
        self.sent: list[str] = []
        self.sent_event = asyncio.Event()

    async def run(self) -> None:
        await asyncio.Event().wait()

    async def send(self, raw: str) -> None:
        self.sent.append(raw)
        self.sent_event.set()

    async def close(self) -> None:
        pass


class DesktopRoundtripTests(unittest.IsolatedAsyncioTestCase):
    """验证 Desktop raw input 经 Body 入站，并由 Body 路由出站。"""

    async def test_desktop_input_and_body_routed_output(self) -> None:
        bus = EventBus()
        registry = AdapterRegistry()
        runtime = BodyRuntime(owner_user_id="local-owner", adapters=registry)

        body_events = ModuleEventAPI(bus, "body")
        register_body_events(body_events)
        subscribe_body_events(body_events, runtime)

        connector = FakeConnector()
        adapter_events = EventClient(bus, "adapter.desktop")
        adapter = DesktopAdapter(
            connector=connector,
            codec=DesktopCodec(),
            publish_input=functools.partial(
                publish_body_input,
                adapter_events,
                runtime,
            ),
            owner_user_id="local-owner",
            owner_display_name="Owner",
        )
        registry.register(adapter)

        observed_inputs: list[BodyInputEventData] = []
        observed_outputs: list[BodyOutputResultEventData] = []
        input_received = asyncio.Event()
        output_completed = asyncio.Event()
        observer_events = ModuleEventAPI(bus, "test.adapter.boundary")

        async def observe_input(flow: EventFlow) -> None:
            self.assertIsInstance(flow.payload, BodyInputEventData)
            observed_inputs.append(flow.payload)
            input_received.set()

        async def observe_output(flow: EventFlow) -> None:
            self.assertIsInstance(flow.payload, BodyOutputResultEventData)
            observed_outputs.append(flow.payload)
            output_completed.set()

        observer_events.subscribe(
            "body.input.received",
            observe_input,
            handler_id="test.adapter.input",
        )
        observer_events.subscribe(
            "body.output.completed",
            observe_output,
            handler_id="test.adapter.output",
        )

        await bus.start()
        try:
            self.assertIs(registry.get("desktop", "desktop"), adapter)
            self.assertIsNotNone(connector.on_message)
            await connector.on_message(
                '{"type":"message","message_id":"m1","text":"hello",'
                '"user_id":"forged","display_name":"Forged"}'
            )
            await asyncio.wait_for(input_received.wait(), 2)

            self.assertEqual(len(observed_inputs), 1)
            inbound = observed_inputs[0]
            # EventBus 收到的是 Body 标准输入，而不是 Adapter 的中间态消息。
            self.assertNotIsInstance(inbound, AdapterInboundMessage)
            self.assertEqual(inbound.content.text_value(), "hello")
            self.assertEqual(inbound.scene.scene_type, SceneType.DESKTOP)
            self.assertEqual(inbound.scene.scene_id, "desktop")
            self.assertEqual(inbound.source.user_id, "local-owner")
            self.assertEqual(inbound.source.display_name, "Owner")
            self.assertEqual(inbound.source.role, UserRole.OWNER)

            await observer_events.publish(
                "body.output.requested",
                BodyOutputRequestData(
                    output_id="o1",
                    session_id=inbound.session_id,
                    content=Content.from_text("pong"),
                    metadata={"internal": "must-not-leak"},
                ),
            )
            await asyncio.wait_for(connector.sent_event.wait(), 2)
            await asyncio.wait_for(output_completed.wait(), 2)

            self.assertEqual(len(connector.sent), 1)
            self.assertEqual(
                json.loads(connector.sent[0]),
                {"type": "message", "text": "pong", "reply_to": "m1"},
            )
            self.assertEqual(len(observed_outputs), 1)
            outbound = observed_outputs[0]
            self.assertEqual(outbound.output_id, "o1")
            self.assertEqual(outbound.outcome, OperationStatus.COMPLETED)
            self.assertIsNone(outbound.error)
            self.assertEqual(len(outbound.items), 1)
            self.assertEqual(outbound.items[0].index, 0)
            self.assertEqual(outbound.items[0].status, OperationStatus.COMPLETED)
            self.assertIsNotNone(outbound.items[0].sent_at)
        finally:
            await bus.stop()


if __name__ == "__main__":
    unittest.main()
