"""WebSocketConnector 的本地单连接传输集成测试。"""

from __future__ import annotations

import asyncio
import socket
import unittest

import websockets
from websockets.exceptions import ConnectionClosed

from adapter.desktop.connector import WebSocketConnector


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class WebSocketConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.connector = WebSocketConnector("127.0.0.1", free_port())
        self.received: list[str] = []
        self.received_event = asyncio.Event()

        async def record(raw: str) -> None:
            self.received.append(raw)
            self.received_event.set()

        self.connector.on_message = record
        self.run_task = asyncio.create_task(self.connector.run())
        await self._wait_until_ready()

    async def asyncTearDown(self) -> None:
        await self.connector.close()
        await asyncio.wait_for(self.run_task, 2)

    async def test_one_connection_sends_and_receives_text(self) -> None:
        async with self._connect() as client:
            await client.send("hello")
            await asyncio.wait_for(self.received_event.wait(), 1)
            self.assertEqual(self.received, ["hello"])

            await self.connector.send("reply")
            self.assertEqual(await asyncio.wait_for(client.recv(), 1), "reply")

    async def test_binary_frame_is_ignored(self) -> None:
        async with self._connect() as client:
            await client.send(b"binary")
            await asyncio.sleep(0.05)

            self.assertEqual(self.received, [])
            await self.connector.send("still-open")
            self.assertEqual(await asyncio.wait_for(client.recv(), 1), "still-open")

    async def test_server_accepts_new_connection_after_disconnect(self) -> None:
        async with self._connect() as first:
            await first.send("first")
            await asyncio.wait_for(self.received_event.wait(), 1)

        await self._wait_until_no_active_connection()
        self.received_event.clear()
        async with self._connect() as second:
            await second.send("second")
            await asyncio.wait_for(self.received_event.wait(), 1)

        self.assertEqual(self.received, ["first", "second"])
        self.assertFalse(self.run_task.done())

    async def test_second_connection_is_rejected_and_receives_no_messages(self) -> None:
        async with self._connect() as first:
            second = await self._connect()
            try:
                with self.assertRaises(ConnectionClosed):
                    await asyncio.wait_for(second.recv(), 1)
                self.assertEqual(second.close_code, 1013)
                self.assertEqual(second.close_reason, "Desktop connection already active")

                await self.connector.send("first-only")
                self.assertEqual(await asyncio.wait_for(first.recv(), 1), "first-only")
                with self.assertRaises(ConnectionClosed):
                    await second.recv()
            finally:
                await second.close()

    async def test_send_without_active_connection_fails(self) -> None:
        with self.assertRaises(ConnectionError):
            await self.connector.send("message")

    async def test_close_is_idempotent_and_ends_run(self) -> None:
        client = await self._connect()

        await self.connector.close()
        await self.connector.close()
        await asyncio.wait_for(self.run_task, 2)

        self.assertTrue(self.run_task.done())
        self.assertIsNone(self.connector._active_connection)
        with self.assertRaises(ConnectionError):
            await self.connector.send("message")
        await client.close()

    async def test_connector_can_restart_after_close(self) -> None:
        await self.connector.close()
        await asyncio.wait_for(self.run_task, 2)

        self.run_task = asyncio.create_task(self.connector.run())
        await self._wait_until_ready()
        async with self._connect() as client:
            await client.send("after-restart")
            await asyncio.wait_for(self.received_event.wait(), 1)

        self.assertEqual(self.received, ["after-restart"])
        self.assertFalse(self.run_task.done())

    async def test_close_before_run_starts_is_not_lost(self) -> None:
        await self.connector.close()
        await asyncio.wait_for(self.run_task, 2)

        await self.connector.close()
        self.run_task = asyncio.create_task(self.connector.run())

        await asyncio.wait_for(self.run_task, 2)
        self.assertTrue(self.run_task.done())

    def _connect(self):
        return websockets.connect(
            f"ws://{self.connector.host}:{self.connector.port}",
            open_timeout=1,
            close_timeout=1,
        )

    async def _wait_until_ready(self) -> None:
        for _ in range(100):
            if self.connector._server is not None:
                return
            await asyncio.sleep(0.01)
        self.fail("WebSocket server did not start")

    async def _wait_until_no_active_connection(self) -> None:
        for _ in range(100):
            if self.connector._active_connection is None:
                return
            await asyncio.sleep(0.01)
        self.fail("Active WebSocket connection was not released")


if __name__ == "__main__":
    unittest.main()
