"""SenaBot MVP 组合根与进程入口。"""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path

from adapter.desktop import DesktopAdapter, DesktopCodec, WebSocketConnector
from adapter.model import OpenAICompatibleProvider
from config import load_model_config
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
_MODEL_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "model.toml"


async def run() -> None:
    """装配并运行 SenaBot Desktop MVP，直到进程收到取消。"""
    model_config = load_model_config(_MODEL_CONFIG_PATH)
    if model_config.provider == "openai_compatible":
        model_provider = OpenAICompatibleProvider(
            api_key=model_config.api_key,
            base_url=model_config.base_url,
            model=model_config.model,
            timeout_seconds=model_config.timeout_seconds,
        )
    else:  # load_model_config 已拒绝不支持的 Provider，此分支防止未来静默遗漏。
        raise RuntimeError(f"unsupported model provider: {model_config.provider}")

    try:
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
    finally:
        await model_provider.close()


def main() -> None:
    """运行异步组合根，并把终端中断视为正常关闭。"""
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
