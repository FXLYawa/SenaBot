"""SenaBot MVP 组合根与进程入口。"""

from __future__ import annotations

import asyncio
import functools

from adapter.desktop import DesktopAdapter, DesktopCodec, WebSocketConnector
from core.body import (
    AdapterRegistry,
    BodyRuntime,
    publish_body_input,
    register_body_events,
    subscribe_body_events,
)
from core.event import EventBus, EventClient, ModuleEventAPI

_DESKTOP_HOST = "127.0.0.1"
_DESKTOP_PORT = 8765
_OWNER_USER_ID = "local-owner"
_OWNER_DISPLAY_NAME = "Owner"


async def run() -> None:
    """装配并运行 SenaBot Desktop MVP，直到进程收到取消。"""
    bus = EventBus()
    registry = AdapterRegistry()
    runtime = BodyRuntime(owner_user_id=_OWNER_USER_ID, adapters=registry)

    body_events = ModuleEventAPI(bus, "body")
    register_body_events(body_events)
    subscribe_body_events(body_events, runtime)

    adapter_events = EventClient(bus, "adapter.desktop")
    connector = WebSocketConnector(host=_DESKTOP_HOST, port=_DESKTOP_PORT)
    adapter = DesktopAdapter(
        connector=connector,
        codec=DesktopCodec(),
        publish_input=functools.partial(
            publish_body_input,
            adapter_events,
            runtime,
        ),
        owner_user_id=_OWNER_USER_ID,
        owner_display_name=_OWNER_DISPLAY_NAME,
    )
    registry.register(adapter)

    await bus.start()
    try:
        await adapter.start()
        await asyncio.Event().wait()
    finally:
        try:
            await adapter.stop()
        finally:
            await bus.stop()


def main() -> None:
    """运行异步组合根，并把终端中断视为正常关闭。"""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
