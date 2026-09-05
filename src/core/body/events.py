"""Body 模块的事件定义和 EventBus 接入。"""

from __future__ import annotations

from core.body.contracts import (
    AdapterInboundMessage,
    BodyInputEventData,
    BodyOutputRequestData,
    BodyOutputResultEventData,
)
from core.body.ports import BodyAdapter
from core.body.runtime import BodyRuntime
from core.event import EventClient, EventFlow, ModuleEventAPI


class BodyModule:
    """组装 Body Runtime 与 Adapter，并提供统一的事件注册和输入入口。"""

    def __init__(self, runtime: BodyRuntime) -> None:
        self._runtime = runtime

    def register(self, events: ModuleEventAPI) -> None:
        """声明 Body 事件并订阅输出请求。"""

        event_definitions = (
            ("body.input.received", BodyInputEventData),
            ("body.output.requested", BodyOutputRequestData),
            ("body.output.completed", BodyOutputResultEventData),
            ("body.output.partially_completed", BodyOutputResultEventData),
            ("body.output.failed", BodyOutputResultEventData),
        )
        subscriptions = (
            (
                "body.output.requested",
                self._handle_output,
                "body.output.dispatch",
            ),
        )

        for event_type, payload_type in event_definitions:
            events.register(event_type, payload_type=payload_type)
        for event_pattern, handler, handler_id in subscriptions:
            events.subscribe(event_pattern, handler, handler_id=handler_id)

    def register_adapter(self, adapter: BodyAdapter) -> None:
        """注册组合根创建的平台 Adapter。"""

        self._runtime.adapters.register(adapter)

    async def publish_input(
        self,
        events: EventClient,
        message: AdapterInboundMessage,
    ) -> BodyInputEventData | None:
        """接收 Adapter 输入并发布标准 Body 输入事件。"""

        payload = await self._runtime.handle_adapter_input(message)
        if payload is None:
            return None
        await events.publish("body.input.received", payload)
        return payload

    async def _handle_output(self, flow: EventFlow) -> None:
        """执行输出请求，并按结果发布完成、部分完成或失败事件。"""

        result = await self._runtime.handle_output_request(flow.payload)
        flow.emit(f"body.output.{result.outcome}", result)
