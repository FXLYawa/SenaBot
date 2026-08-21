"""BaseAdapter 的入站、出站与生命周期单元测试。"""

from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable, Callable

from core.body import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
    BodyInputEventData,
    Content,
    OperationStatus,
    SceneInfo,
    SceneType,
)

from adapter.base import BaseAdapter
from adapter.codec import CodecError


def make_inbound(*, message_id: str = "m1") -> AdapterInboundMessage:
    return AdapterInboundMessage(
        adapter_type="wire-adapter",
        platform="wire-platform",
        message_id=message_id,
        user_id="u1",
        display_name="Alice",
        scene_type=SceneType.DESKTOP,
        scene_id="desktop",
        content=Content.from_text("hello"),
    )


def make_outbound() -> AdapterOutboundMessage:
    return AdapterOutboundMessage(
        adapter_type="test",
        platform="test",
        scene=SceneInfo(SceneType.DESKTOP, "desktop"),
        content=Content.from_text("hi"),
    )


class FakeConnector:
    def __init__(self) -> None:
        self.on_message: Callable[[str], Awaitable[None]] | None = None
        self.sent: list[str] = []
        self.send_attempts = 0
        self.fail_send: set[int] = set()
        self.runs = 0
        self.closed = 0
        self.run_started = asyncio.Event()
        self.close_requested = asyncio.Event()
        self.run_error: Exception | None = None

    async def run(self) -> None:
        self.runs += 1
        self.run_started.set()
        if self.run_error is not None:
            raise self.run_error
        await self.close_requested.wait()

    async def send(self, raw: str) -> None:
        index = self.send_attempts
        self.send_attempts += 1
        if index in self.fail_send:
            raise RuntimeError("send boom")
        self.sent.append(raw)

    async def close(self) -> None:
        self.closed += 1
        self.close_requested.set()


class FakeCodec:
    def __init__(self, payloads: list[str] | None = None) -> None:
        self.payloads = payloads if payloads is not None else ["item-0", "item-1"]
        self.decode_error: CodecError | None = None
        self.encode_error: Exception | None = None
        self.encoded: list[AdapterOutboundMessage] = []

    def decode(self, raw: str) -> AdapterInboundMessage:
        if self.decode_error is not None:
            raise self.decode_error
        return make_inbound(message_id=raw)

    def encode(self, outbound: AdapterOutboundMessage) -> list[str]:
        self.encoded.append(outbound)
        if self.encode_error is not None:
            raise self.encode_error
        return self.payloads


class RecordingPublisher:
    def __init__(self) -> None:
        self.published: list[AdapterInboundMessage] = []
        self.raise_on_publish = False

    async def __call__(
        self, message: AdapterInboundMessage
    ) -> BodyInputEventData | None:
        if self.raise_on_publish:
            raise RuntimeError("publish boom")
        self.published.append(message)
        return None


class FakeAdapter(BaseAdapter):
    adapter_type = "test"
    platform = "test"


class CompletingAdapter(FakeAdapter):
    def _complete_inbound_message(self, message: AdapterInboundMessage) -> None:
        message.user_id = "trusted-user"
        message.display_name = "Trusted User"


class InboundTests(unittest.IsolatedAsyncioTestCase):
    async def test_valid_message_is_completed_and_published(self) -> None:
        connector = FakeConnector()
        publisher = RecordingPublisher()
        FakeAdapter(connector, FakeCodec(), publisher)

        self.assertIsNotNone(connector.on_message)
        await connector.on_message("message-1")

        self.assertEqual(len(publisher.published), 1)
        message = publisher.published[0]
        self.assertEqual(message.message_id, "message-1")
        self.assertEqual(message.adapter_type, "test")
        self.assertEqual(message.platform, "test")

    async def test_platform_hook_completes_message_before_publish(self) -> None:
        connector = FakeConnector()
        publisher = RecordingPublisher()
        CompletingAdapter(connector, FakeCodec(), publisher)

        await connector.on_message("message-1")

        message = publisher.published[0]
        self.assertEqual(message.adapter_type, "test")
        self.assertEqual(message.platform, "test")
        self.assertEqual(message.user_id, "trusted-user")
        self.assertEqual(message.display_name, "Trusted User")

    async def test_codec_error_skips_publish(self) -> None:
        connector = FakeConnector()
        codec = FakeCodec()
        codec.decode_error = CodecError("bad frame")
        publisher = RecordingPublisher()
        FakeAdapter(connector, codec, publisher)

        await connector.on_message("bad")

        self.assertEqual(publisher.published, [])

    async def test_publish_error_is_swallowed(self) -> None:
        connector = FakeConnector()
        publisher = RecordingPublisher()
        publisher.raise_on_publish = True
        FakeAdapter(connector, FakeCodec(), publisher)

        await connector.on_message("message-1")


class SendTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_items_succeed(self) -> None:
        connector = FakeConnector()
        codec = FakeCodec(["first", "second"])
        outbound = make_outbound()
        adapter = FakeAdapter(connector, codec, RecordingPublisher())

        results = await adapter.send(outbound)

        self.assertEqual(connector.sent, ["first", "second"])
        self.assertEqual(codec.encoded, [outbound])
        self.assertEqual([item.index for item in results], [0, 1])
        self.assertTrue(
            all(item.status == OperationStatus.COMPLETED for item in results)
        )
        self.assertTrue(all(item.sent_at is not None for item in results))

    async def test_item_failure_continues_with_later_items(self) -> None:
        connector = FakeConnector()
        connector.fail_send = {0}
        adapter = FakeAdapter(connector, FakeCodec(), RecordingPublisher())

        results = await adapter.send(make_outbound())

        self.assertEqual(
            [item.status for item in results],
            [OperationStatus.FAILED, OperationStatus.COMPLETED],
        )
        self.assertEqual(connector.sent, ["item-1"])
        self.assertIsNone(results[0].sent_at)

    async def test_encode_failure_returns_synthetic_failed_item(self) -> None:
        connector = FakeConnector()
        codec = FakeCodec()
        codec.encode_error = RuntimeError("encode boom")
        adapter = FakeAdapter(connector, codec, RecordingPublisher())

        results = await adapter.send(make_outbound())

        self.assertEqual(connector.send_attempts, 0)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].index, 0)
        self.assertEqual(results[0].status, OperationStatus.FAILED)
        self.assertIsNone(results[0].sent_at)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    def make_adapter(self) -> tuple[FakeConnector, FakeAdapter]:
        connector = FakeConnector()
        return connector, FakeAdapter(connector, FakeCodec(), RecordingPublisher())

    async def test_start_is_idempotent(self) -> None:
        connector, adapter = self.make_adapter()
        await adapter.start()
        await asyncio.wait_for(connector.run_started.wait(), 1)

        await adapter.start()
        await asyncio.sleep(0)

        self.assertEqual(connector.runs, 1)
        await adapter.stop()

    async def test_stop_is_idempotent(self) -> None:
        connector, adapter = self.make_adapter()
        await adapter.start()
        await asyncio.wait_for(connector.run_started.wait(), 1)

        await adapter.stop()
        await adapter.stop()

        self.assertEqual(connector.closed, 1)
        self.assertIsNone(adapter._run_task)
        self.assertIsNone(adapter._stop_task)

    async def test_stop_before_start_is_idempotent(self) -> None:
        connector, adapter = self.make_adapter()

        await adapter.stop()
        await adapter.stop()

        self.assertEqual(connector.closed, 1)
        self.assertTrue(adapter._stopped)
        self.assertIsNone(adapter._stop_task)

    async def test_run_failure_is_logged_and_can_be_restarted(self) -> None:
        connector, adapter = self.make_adapter()
        connector.run_error = RuntimeError("run boom")

        with self.assertLogs("senabot.adapter", level="ERROR") as captured:
            await adapter.start()
            await asyncio.wait_for(connector.run_started.wait(), 1)
            await asyncio.sleep(0)

        self.assertTrue(adapter._run_task.done())
        self.assertIn("Adapter connector service failed", captured.output[0])

        connector.run_started.clear()
        connector.run_error = None
        await adapter.start()
        await asyncio.wait_for(connector.run_started.wait(), 1)
        self.assertEqual(connector.runs, 2)
        await adapter.stop()

if __name__ == "__main__":
    unittest.main()
