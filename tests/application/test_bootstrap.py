"""SenaBot 组合根的 Body 装配链路测试。"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable
from unittest.mock import patch

from core.application.bootstrap import (
    SenaBotConfig,
    SenaBotDependencies,
    create_senabot_app,
)
from core.body import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
    BodyInputEventData,
    BodyOutputItemResult,
    BodyOutputRequestData,
    Content,
    OperationStatus,
    SceneType,
)
from core.event import EventBus, EventClient
from core.data import SQLiteDatabase
from core.embedding import EmbeddingRequest, EmbeddingResponse
from core.model import ModelRequest, ModelResponse


class StubModelProvider:
    async def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(text="unused", model="stub")


class StubMemoryLLM:
    async def generate(self, prompt: str) -> str:
        return "{}"


class StubEmbeddingProvider:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        return EmbeddingResponse((1.0,), "stub")

    async def close(self) -> None:
        pass


class StubModule:
    def register(self, events: object) -> None:
        pass


class RecordingAdapter:
    adapter_type = "test"
    platform = "test"

    def __init__(
        self,
        publish_input: Callable[
            [AdapterInboundMessage], Awaitable[BodyInputEventData | None]
        ],
    ) -> None:
        self.publish_input = publish_input
        self.sent: list[AdapterOutboundMessage] = []
        self.sent_event = asyncio.Event()
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def send(
        self,
        outbound: AdapterOutboundMessage,
    ) -> list[BodyOutputItemResult]:
        self.sent.append(outbound)
        self.sent_event.set()
        return [BodyOutputItemResult(0, OperationStatus.COMPLETED)]


class BodyBootstrapTests(unittest.IsolatedAsyncioTestCase):
    async def test_app_wires_body_publisher_registry_and_lifecycle(self) -> None:
        bus = EventBus()
        created_adapters: list[RecordingAdapter] = []

        def create_adapter(
            publish_input: Callable[
                [AdapterInboundMessage], Awaitable[BodyInputEventData | None]
            ],
        ) -> RecordingAdapter:
            adapter = RecordingAdapter(publish_input)
            created_adapters.append(adapter)
            return adapter

        dependencies = SenaBotDependencies(
            model_provider=StubModelProvider(),
            memory_llm=StubMemoryLLM(),
            embedding_provider=StubEmbeddingProvider(),
            database=SQLiteDatabase(":memory:"),
            event_bus=bus,
            adapter_factories=(create_adapter,),
        )
        config = SenaBotConfig(
            owner_user_id="owner",
            desktop=None,
            enable_context_compression=False,
        )

        with patch(
            "core.application.bootstrap.create_memory_module",
            return_value=StubModule(),
        ), patch(
            "core.application.bootstrap.create_context_module",
            return_value=StubModule(),
        ), patch(
            "core.application.bootstrap.create_agent_module",
            return_value=StubModule(),
        ):
            app = create_senabot_app(dependencies, config)

        self.assertEqual(len(created_adapters), 1)
        adapter = created_adapters[0]

        await app.start()
        try:
            self.assertTrue(adapter.started)
            inbound = await adapter.publish_input(
                AdapterInboundMessage(
                    adapter_type="test",
                    platform="test",
                    message_id="message-1",
                    user_id="owner",
                    display_name="Owner",
                    scene_type=SceneType.GROUP,
                    scene_id="group-1",
                    content=Content.from_text("hello"),
                )
            )
            self.assertIsNotNone(inbound)

            await EventClient(bus, "test").publish(
                "body.output.requested",
                BodyOutputRequestData(
                    output_id="output-1",
                    route=inbound.output_route,
                    scene=inbound.scene,
                    content=Content.from_text("world"),
                    reply_to_message_id=inbound.reply_target_id,
                ),
            )
            await asyncio.wait_for(adapter.sent_event.wait(), timeout=2)

            self.assertEqual(len(adapter.sent), 1)
            self.assertEqual(adapter.sent[0].content.text_value(), "world")
            self.assertEqual(adapter.sent[0].reply_to_message_id, "message-1")
        finally:
            await app.stop()

        self.assertTrue(adapter.stopped)
        self.assertFalse(app.is_running)
        dependencies.database.close()


if __name__ == "__main__":
    unittest.main()
