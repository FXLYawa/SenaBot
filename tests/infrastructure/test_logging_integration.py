"""使用真实 EventBus 和应用装配验证日志，不调用远程模型。"""

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from core.event import EventBus, EventClient, EventSpec, HandlerSpec
from infrastructure.logging import LoggingConfig, configure_logging, get_logger, log_context, shutdown_logging
from infrastructure.logging.context import current_context


@dataclass
class Payload:
    session_id: str


class EventLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_queue_and_derived_events_preserve_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            configure_logging(LoggingConfig(directory=directory, console=False, trace=True, trace_level="DEBUG"))
            bus = EventBus(dispatch_concurrency=2)
            for name in ("test.input", "test.child"):
                bus.register(EventSpec(name, "test", Payload))
            observed = []
            ready = asyncio.Event()
            arrived = 0

            async def parent(flow):
                nonlocal arrived
                arrived += 1
                if arrived == 2:
                    ready.set()
                await ready.wait()
                observed.append((flow.envelope, current_context()))
                flow.emit("test.child", flow.payload)

            async def child(flow):
                observed.append((flow.envelope, current_context()))
                get_logger("test").info("observed", extra={"log_kind": "trace"})

            bus.subscribe(HandlerSpec("parent", "test", "test.input"), parent)
            bus.subscribe(HandlerSpec("child", "test", "test.child"), child)
            try:
                with log_context(trace_id="stale-worker", session_id="stale-session", event_id="stale-event"):
                    await bus.start()
                for identity in ("one", "two"):
                    with log_context(trace_id="wrong-producer"):
                        await EventClient(bus, "test").publish("test.input", Payload(identity))
                await asyncio.wait_for(bus._queue.join(), 3)
                await bus.stop()
            finally:
                await bus.stop()
                shutdown_logging()
            self.assertEqual(len(observed), 4)
            for envelope, context in observed:
                self.assertEqual(context["trace_id"], envelope.trace.trace_id)
                self.assertEqual(context["event_id"], envelope.event_id)
                self.assertEqual(context["session_id"], envelope.payload.session_id)
            for identity in ("one", "two"):
                pair = [e for e, _ in observed if e.payload.session_id == identity]
                self.assertEqual(pair[0].trace.trace_id, pair[1].trace.trace_id)
                self.assertNotEqual(pair[0].event_id, pair[1].event_id)
            text = (Path(directory) / "senabot.trace.log").read_text(encoding="utf-8")
            self.assertNotIn("stale", text)
            self.assertNotIn("wrong-producer", text)
            self.assertEqual(current_context(), {})

    async def test_background_metadata_has_separate_log_trace(self):
        from core.memory.extraction_flow import MemoryExtractionConfig, MemoryExtractionFlow, _ExtractionState
        from core.context import ContextReadRequestData
        bus = EventBus()
        bus.register(EventSpec("test.trigger", "test", Payload))
        bus.register(EventSpec("context.read.requested", "test", ContextReadRequestData))
        batches = []
        extraction = MemoryExtractionFlow(AsyncMock(), AsyncMock(), MemoryExtractionConfig("space", "user"))

        async def trigger(flow):
            extraction._schedule_batch(flow, flow.payload.session_id, _ExtractionState(40, 0))

        async def read(flow):
            batches.append((flow.envelope, current_context()))

        bus.subscribe(HandlerSpec("trigger", "test", "test.trigger"), trigger)
        bus.subscribe(HandlerSpec("read", "test", "context.read.requested"), read)
        configure_logging(LoggingConfig(file=False, console=False))
        try:
            await bus.start()
            await EventClient(bus, "test").publish("test.trigger", Payload("session"))
            await asyncio.wait_for(bus._queue.join(), 3)
        finally:
            await bus.stop()
            shutdown_logging()
        envelope, context = batches[0]
        self.assertNotEqual(context["trace_id"], envelope.trace.trace_id)
        self.assertEqual(context["parent_trace_id"], envelope.trace.trace_id)
        self.assertEqual(context["operation_id"], envelope.payload.operation_id)
        self.assertEqual(context["event_id"], envelope.event_id)

    async def test_entry_shutdown_on_completion_failure_and_cancel(self):
        import main
        for failure in (None, RuntimeError("failure"), asyncio.CancelledError()):
            with patch.object(main, "load_logging_config", return_value=LoggingConfig(file=False, console=False)), patch.object(
                main, "_run_from_config", new=AsyncMock(side_effect=failure)
            ), patch.object(main, "shutdown_logging", wraps=shutdown_logging) as shutdown:
                if failure is None:
                    await main.run_from_config()
                else:
                    with self.assertRaises(type(failure)):
                        await main.run_from_config()
                shutdown.assert_called_once()


class ConversationLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_conversation_has_correlated_logs_without_private_text(self):
        from application import SenaBotConfig, SenaBotDependencies, create_senabot_app
        from core.body import AdapterInboundMessage, BodyOutputItemResult, OperationStatus
        from core.common import Content, SceneType
        from core.data import SQLiteDatabase
        from core.model import EmbeddingResponse, ModelResponse

        class Model:
            async def generate(self, request):
                return ModelResponse(text="PRIVATE REPLY", model="stub")

        class Embedding:
            async def embed(self, request):
                return EmbeddingResponse((1.0, 0.0), "stub")

        class Adapter:
            adapter_type = platform = "test"

            def __init__(self, publish):
                self.publish = publish
                self.outputs = asyncio.Queue()

            async def start(self):
                pass

            async def stop(self):
                pass

            async def send(self, message):
                self.outputs.put_nowait(message)
                return [BodyOutputItemResult(0, OperationStatus.COMPLETED)]

        with tempfile.TemporaryDirectory() as directory:
            configure_logging(LoggingConfig(directory=directory, console=False, trace=True, trace_level="DEBUG"))
            adapters = []

            def factory(publish):
                adapter = Adapter(publish)
                adapters.append(adapter)
                return adapter

            try:
                with SQLiteDatabase(":memory:") as database:
                    app = create_senabot_app(SenaBotDependencies(
                        model_provider=Model(), memory_model_provider=Model(), embedding_provider=Embedding(),
                        database=database, adapter_factories=(factory,),
                    ), SenaBotConfig(desktop=None, enable_context_compression=False))
                    async with app:
                        await adapters[0].publish(AdapterInboundMessage(
                            adapter_type="test", platform="test", message_id="message-id",
                            user_id="local-owner", display_name="Owner", scene_type=SceneType.PRIVATE,
                            scene_id="owner", content=Content.from_text("PRIVATE CHAT"),
                        ))
                        reply = await asyncio.wait_for(adapters[0].outputs.get(), 3)
                        self.assertEqual(reply.content.text_value(), "PRIVATE REPLY")
            finally:
                shutdown_logging()
            text = "\n".join(p.read_text(encoding="utf-8") for p in Path(directory).glob("*.log"))
            self.assertNotIn("PRIVATE", text)
            rows = [json.loads(line) for line in text.splitlines() if line]
            actions = {row.get("action") for row in rows}
            self.assertTrue({"body.input_received", "context.prepared", "agent.run_started",
                             "memory.query_completed", "body.output_completed"} <= actions)
            steps = [row for row in rows if row.get("action") in {
                "body.input_received", "context.prepared", "agent.run_started", "body.output_completed"}]
            self.assertEqual(len({row["trace_id"] for row in steps}), 1)
