"""DesktopCodec 的入站校验与出站 JSON 单元测试。"""

from __future__ import annotations

import json
import unittest

from core.body import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
    Content,
    ContentSegment,
    ContentType,
    SceneInfo,
    SceneType,
)

from adapter.codec import CodecError
from adapter.desktop.codec import SCENE_ID, SCENE_TYPE, DesktopCodec


def make_outbound(
    *,
    content: Content | None = None,
    reply_to: str | None = "m1",
    metadata: dict | None = None,
) -> AdapterOutboundMessage:
    return AdapterOutboundMessage(
        adapter_type="desktop",
        platform="desktop",
        scene=SceneInfo(SceneType.DESKTOP, SCENE_ID),
        content=content or Content.from_text("hi"),
        reply_to_message_id=reply_to,
        metadata=metadata or {},
    )


class DesktopCodecDecodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = DesktopCodec()

    def test_decode_valid_message(self) -> None:
        message = self.codec.decode(
            '{"type":"message","message_id":"m1","text":"你好"}'
        )

        self.assertIsInstance(message, AdapterInboundMessage)
        self.assertEqual(message.adapter_type, "")
        self.assertEqual(message.platform, "")
        self.assertEqual(message.user_id, "")
        self.assertEqual(message.display_name, "")
        self.assertEqual(message.message_id, "m1")
        self.assertEqual(message.content.text_value(), "你好")
        self.assertEqual(message.scene_type, SCENE_TYPE)
        self.assertEqual(message.scene_id, SCENE_ID)

    def test_decode_ignores_untrusted_browser_identity(self) -> None:
        message = self.codec.decode(
            '{"type":"message","message_id":"m1","text":"hi",'
            '"user_id":"attacker","display_name":"Forged"}'
        )

        self.assertEqual(message.user_id, "")
        self.assertEqual(message.display_name, "")

    def test_decode_rejects_bad_json(self) -> None:
        with self.assertRaises(CodecError):
            self.codec.decode("{not json")

    def test_decode_rejects_non_object(self) -> None:
        with self.assertRaises(CodecError):
            self.codec.decode('["message", "m1"]')

    def test_decode_rejects_wrong_type(self) -> None:
        with self.assertRaises(CodecError):
            self.codec.decode('{"type":"other","message_id":"m1","text":"hi"}')

    def test_decode_rejects_missing_or_invalid_message_id(self) -> None:
        frames = (
            '{"type":"message","text":"hi"}',
            '{"type":"message","message_id":1,"text":"hi"}',
            '{"type":"message","message_id":"  ","text":"hi"}',
        )
        for frame in frames:
            with self.subTest(frame=frame), self.assertRaises(CodecError):
                self.codec.decode(frame)

    def test_decode_rejects_missing_or_invalid_text(self) -> None:
        frames = (
            '{"type":"message","message_id":"m1"}',
            '{"type":"message","message_id":"m1","text":1}',
            '{"type":"message","message_id":"m1","text":null}',
        )
        for frame in frames:
            with self.subTest(frame=frame), self.assertRaises(CodecError):
                self.codec.decode(frame)


class DesktopCodecEncodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codec = DesktopCodec()

    def test_encode_returns_complete_json_string(self) -> None:
        encoded = self.codec.encode(make_outbound())

        self.assertEqual(len(encoded), 1)
        self.assertIsInstance(encoded[0], str)
        self.assertEqual(
            json.loads(encoded[0]),
            {"type": "message", "text": "hi", "reply_to": "m1"},
        )

    def test_encode_reply_to_none(self) -> None:
        payload = json.loads(self.codec.encode(make_outbound(reply_to=None))[0])

        self.assertIsNone(payload["reply_to"])

    def test_encode_does_not_leak_metadata(self) -> None:
        payload = json.loads(
            self.codec.encode(
                make_outbound(metadata={"secret": "internal", "presentation": {}})
            )[0]
        )

        self.assertNotIn("metadata", payload)
        self.assertNotIn("secret", payload)

    def test_encode_ignores_non_text_segments(self) -> None:
        content = Content(
            content_type=ContentType.IMAGE,
            segments=(ContentSegment(ContentType.IMAGE, {"url": "internal"}),),
        )
        payload = json.loads(self.codec.encode(make_outbound(content=content))[0])

        self.assertEqual(payload["text"], "")
        self.assertNotIn("url", payload)


if __name__ == "__main__":
    unittest.main()
