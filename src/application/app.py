"""已装配 SenaBot 应用的运行生命周期。"""

from __future__ import annotations

import asyncio

from adapter import BaseAdapter
from core.event import EventBus


__all__ = ["SenaBotApp"]


class SenaBotApp:
    """启动和停止已装配的 SenaBot，不暴露模块内部对象。"""

    def __init__(
        self,
        event_bus: EventBus,
        adapters: tuple[BaseAdapter, ...],
        module_graph: tuple[object, ...],
    ) -> None:
        self._event_bus = event_bus
        self._adapters = adapters
        # 保持完整模块图的生命周期，同时不向应用调用方公开内部对象。
        self._module_graph = module_graph
        self._bus_started = False
        self._started_adapters: list[BaseAdapter] = []

    @property
    def is_running(self) -> bool:
        """应用是否已启动。"""
        return self._bus_started

    async def start(self) -> None:
        """先启动 EventBus, 再开放各 Adapter 的外部输入。"""

        if self._bus_started:
            return

        await self._event_bus.start()
        self._bus_started = True
        try:
            for adapter in self._adapters:
                # 启动前先记录，确保启动中途失败的 Adapter 也会被清理。
                self._started_adapters.append(adapter)
                await adapter.start()
        except BaseException:
            await self._stop_started_components()
            raise

    async def stop(self) -> None:
        """先停止外部输入，再排空并停止 EventBus。"""

        if not self._bus_started:
            return
        await self._stop_started_components()

    async def run_forever(self) -> None:
        """启动应用，并保持运行直到任务被取消。"""

        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()

    async def __aenter__(self) -> SenaBotApp:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    async def _stop_started_components(self) -> None:
        errors: list[BaseException] = []
        # 逆序关闭外部输入后仍需停止 EventBus，因此集中收集关闭异常。
        for adapter in reversed(self._started_adapters):
            try:
                await adapter.stop()
            except BaseException as error:
                errors.append(error)
        self._started_adapters.clear()

        try:
            await self._event_bus.stop()
        except BaseException as error:
            errors.append(error)
        finally:
            self._bus_started = False

        if errors:
            raise RuntimeError("SenaBot App failed to stop cleanly") from errors[0]
