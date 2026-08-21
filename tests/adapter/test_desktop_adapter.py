"""DesktopAdapter 固定归属与 owner identity 补齐测试。"""

from __future__ import annotations

import unittest
from collections.abc import Awaitable, Callable

from core.body import AdapterInboundMessage, BodyInputEventData

from adapter.desktop.adapter import DesktopAdapter
from adapter.desktop.codec import DesktopCodec


class FakeConnector:
    def __init__(self) -> None:
        self.on_message: Callable[[str], Awaitable[None]] | None = None

    async def run(self) -> None:
        pass

    async def send(self, raw: str) -> None:
        pass

    async def close(self) -> None:
        pass


class DesktopAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_receives_adapter_identity_and_fixed_owner(self) -> None:
        connector = FakeConnector()
        published: list[AdapterInboundMessage] = []

        async def publish(
            message: AdapterInboundMessage,
        ) -> BodyInputEventData | None:
            published.append(message)
            return None

        DesktopAdapter(
            connector=connector,
            codec=DesktopCodec(),
            publish_input=publish,
            owner_user_id="local-owner",
            owner_display_name="Owner",
        )

        self.assertIsNotNone(connector.on_message)
        await connector.on_message(
            '{"type":"message","message_id":"m1","text":"hello",'
            '"user_id":"forged","display_name":"Forged"}'
        )

        self.assertEqual(len(published), 1)
        message = published[0]
        self.assertEqual(message.adapter_type, "desktop")
        self.assertEqual(message.platform, "desktop")
        self.assertEqual(message.user_id, "local-owner")
        self.assertEqual(message.display_name, "Owner")
        self.assertEqual(message.content.text_value(), "hello")


if __name__ == "__main__":
    unittest.main()
