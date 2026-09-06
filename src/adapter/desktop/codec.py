"""Desktop 文本消息的 JSON 编解码实现。"""

from __future__ import annotations

import json
from typing import Any

from core.body import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
)
from core.common import Content, SceneType

from adapter.codec import CodecError

SCENE_TYPE = SceneType.DESKTOP
SCENE_ID = "desktop"

_INBOUND_PLACEHOLDER = ""


class DesktopCodec:
    """在 Desktop JSON 字符串与 Body 消息契约之间转换。"""

    def decode(self, raw: str) -> AdapterInboundMessage:
        """解析并校验一条 Desktop 入站文本消息。"""
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise CodecError("Invalid Desktop JSON message.") from exc
        if not isinstance(payload, dict):
            raise CodecError("Desktop message must be a JSON object.")
        # type 字段必须为 "message"
        if payload.get("type") != "message":
            raise CodecError("Desktop message type must be 'message'.")

        message_id = self._required_string(payload, "message_id", allow_empty=False)
        text = self._required_string(payload, "text", allow_empty=True)
        return AdapterInboundMessage(
            adapter_type=_INBOUND_PLACEHOLDER,
            platform=_INBOUND_PLACEHOLDER,
            message_id=message_id,
            user_id=_INBOUND_PLACEHOLDER,
            display_name=_INBOUND_PLACEHOLDER,
            scene_type=SCENE_TYPE,
            scene_id=SCENE_ID,
            content=Content.from_text(text),
        )

    def encode(self, outbound: AdapterOutboundMessage) -> list[str]:
        """把 Desktop 出站文本消息编码为完整 JSON 字符串。"""
        payload = {
            "type": "message",
            "text": outbound.content.text_value(),
            "reply_to": outbound.reply_to_message_id,
        }
        return [json.dumps(payload, ensure_ascii=False, separators=(",", ":"))]

    @staticmethod
    def _required_string(
        payload: dict[str, Any], field: str, *, allow_empty: bool
    ) -> str:
        """读取必需字符串字段，并按协议校验空值。"""
        value = payload.get(field)
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise CodecError(f"Desktop message field '{field}' is invalid.")
        return value
