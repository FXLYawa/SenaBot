"""Desktop 本地单连接 WebSocket 传输。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from websockets.asyncio.server import Server, ServerConnection, serve

_CONNECTION_IN_USE_CODE = 1013
_CONNECTION_IN_USE_REASON = "Desktop connection already active"


class WebSocketConnector:
    """运行只允许一个 active browser connection 的本地 WebSocket 服务。"""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.on_message: Callable[[str], Awaitable[None]] | None = None
        self._server: Server | None = None
        self._active_connection: ServerConnection | None = None
        self._close_requested = asyncio.Event()

    async def run(self) -> None:
        """运行本地 WebSocket server，直到 close() 请求关闭。"""
        close_requested = self._close_requested
        server = await serve(self._handle_connection, self.host, self.port)
        self._server = server
        try:
            await close_requested.wait()
        finally:
            try:
                server.close()
                await server.wait_closed()
            finally:
                self._active_connection = None
                self._server = None
                if self._close_requested is close_requested:
                    self._close_requested = asyncio.Event()

    async def send(self, raw: str) -> None:
        """只向当前 active connection 发送原始字符串。"""
        active = self._active_connection
        if active is None:
            raise ConnectionError("Desktop browser is not connected.")
        await active.send(raw)

    async def close(self) -> None:
        """发起服务关闭；完整资源释放由当前 run() 负责。"""
        self._close_requested.set()
        server = self._server
        if server is not None:
            server.close()

    async def _handle_connection(self, connection: ServerConnection) -> None:
        """拒绝第二连接，并把 active connection 的文本帧交给上层。"""
        if self._active_connection is not None:
            await connection.close(
                code=_CONNECTION_IN_USE_CODE,
                reason=_CONNECTION_IN_USE_REASON,
            )
            return

        self._active_connection = connection
        try:
            async for raw in connection:
                if not isinstance(raw, str):
                    continue
                on_message = self.on_message
                if on_message is not None:
                    await on_message(raw)
        finally:
            if self._active_connection is connection:
                self._active_connection = None
