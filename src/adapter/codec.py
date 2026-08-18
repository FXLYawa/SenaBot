"""Adapter 编解码接缝与最小异常。"""

from __future__ import annotations

from typing import Protocol

from core.body import AdapterInboundMessage, AdapterOutboundMessage


class CodecError(Exception):
    """Wire format 与 Body 契约转换失败。"""


class Codec(Protocol):
    """在 wire format 与 Body 契约之间转换，不执行传输。"""

    def decode(self, raw: str) -> AdapterInboundMessage:
        """把原始字符串解码为 Adapter 入站消息。"""
        ...

    def encode(self, outbound: AdapterOutboundMessage) -> list[str]:
        """把 Body 出站消息编码为可发送的原始字符串列表。"""
        ...
