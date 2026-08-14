"""Adapter 传输接缝。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol


class Connector(Protocol):
    """运行传输服务并收发原始字符串。"""

    on_message: Callable[[str], Awaitable[None]] | None

    async def run(self) -> None:
        """运行传输服务并持续接收输入，直到服务被关闭。"""
        ...

    async def send(self, raw: str) -> None:
        """发送一项已经编码完成的原始字符串。"""
        ...

    async def close(self) -> None:
        """停止接受新输入并关闭传输服务。"""
        ...
