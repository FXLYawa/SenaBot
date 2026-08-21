"""Adapter 通用入站、出站与生命周期骨架。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import ClassVar

from core.body import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
    BodyInputEventData,
    BodyOutputItemResult,
    OperationStatus,
)

from adapter.codec import Codec, CodecError
from adapter.connector import Connector

InboundPublisher = Callable[
    [AdapterInboundMessage], Awaitable[BodyInputEventData | None]
]

_CONNECTOR_RUN_EXIT_TIMEOUT = 1.0


class BaseAdapter:
    """复用 Adapter 的编解码、发送、入站分发与传输服务生命周期。"""

    adapter_type: ClassVar[str]
    platform: ClassVar[str]

    def __init__(
        self,
        connector: Connector,
        codec: Codec,
        publish_input: InboundPublisher,
    ) -> None:
        self.connector = connector
        self.codec = codec
        self.publish_input = publish_input
        self.logger = logging.getLogger("senabot.adapter")
        self._run_task: asyncio.Task[None] | None = None
        self._stop_task: asyncio.Task[None] | None = None
        self._stopped = False
        self.connector.on_message = self._on_message

    async def start(self) -> None:
        """启动一次传输服务任务；服务运行期间重复调用不创建新任务。"""
        if self._stop_task is not None:
            await asyncio.shield(self._stop_task)
            self._stop_task = None
        if self._run_task is not None:
            if not self._run_task.done():
                return
            await asyncio.gather(self._run_task, return_exceptions=True)
            self._run_task = None
        self._stopped = False
        self._run_task = asyncio.create_task(
            self._run_connector(),
            name=f"senabot-adapter:{self.adapter_type}:{self.platform}",
        )

    async def stop(self) -> None:
        """先关闭传输入口，再等待运行任务退出，必要时取消任务。"""
        if self._stopped:
            return
        stop_task = self._stop_task
        if stop_task is None:
            stop_task = asyncio.create_task(
                self._stop(),
                name=f"senabot-adapter-stop:{self.adapter_type}:{self.platform}",
            )
            self._stop_task = stop_task
        try:
            await asyncio.shield(stop_task)
        finally:
            if self._stop_task is stop_task and stop_task.done():
                self._stop_task = None

    async def send(
        self, outbound: AdapterOutboundMessage
    ) -> list[BodyOutputItemResult]:
        """编码并逐项发送，将编解码和传输异常收敛为失败结果。"""
        try:
            payloads = self.codec.encode(outbound)
        except Exception as exc:
            self.logger.exception("Adapter failed to encode outbound message: %s", exc)
            # 现有 Body 契约无法表达 adapter-level failure；该项不对应 wire item。
            return [BodyOutputItemResult(index=0, status=OperationStatus.FAILED)]

        results: list[BodyOutputItemResult] = []
        for index, raw in enumerate(payloads):
            try:
                await self.connector.send(raw)
            except Exception as exc:
                self.logger.exception(
                    "Adapter failed to send outbound item %d: %s", index, exc
                )
                results.append(
                    BodyOutputItemResult(index=index, status=OperationStatus.FAILED)
                )
                continue
            results.append(
                BodyOutputItemResult(
                    index=index,
                    status=OperationStatus.COMPLETED,
                    sent_at=datetime.now(UTC),
                )
            )
        return results

    async def _on_message(self, raw: str) -> None:
        """解码并补齐归属字段后，把入站消息交给注入的 Body 入口。"""
        try:
            message = self.codec.decode(raw)
        except CodecError as exc:
            self.logger.warning("Adapter skipped invalid inbound message: %s", exc)
            return

        message.adapter_type = self.adapter_type
        message.platform = self.platform
        try:
            self._complete_inbound_message(message)
        except Exception as exc:
            self.logger.exception("Adapter failed to complete inbound message: %s", exc)
            return
        try:
            await self.publish_input(message)
        except Exception as exc:
            self.logger.exception("Adapter failed to publish inbound message: %s", exc)

    def _complete_inbound_message(self, message: AdapterInboundMessage) -> None:
        """供具体 Adapter 在发布前补齐平台特有的可信字段。"""

    async def _run_connector(self) -> None:
        """运行 Connector 服务并记录其未处理异常。"""
        try:
            await self.connector.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.exception("Adapter connector service failed: %s", exc)

    async def _stop(self) -> None:
        """执行一次关闭流程。"""
        try:
            await self.connector.close()
        except Exception as exc:
            self.logger.exception("Adapter connector close failed: %s", exc)

        run_task = self._run_task
        if run_task is None:
            self._stopped = True
            return
        try:
            await asyncio.wait_for(
                asyncio.shield(run_task), timeout=_CONNECTOR_RUN_EXIT_TIMEOUT
            )
        except TimeoutError:
            run_task.cancel()
            await asyncio.gather(run_task, return_exceptions=True)
        self._run_task = None
        self._stopped = True
