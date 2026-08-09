"""Body 模块的事件定义和 EventBus 接入。"""

from __future__ import annotations

from core.body.contracts import (
    AdapterInboundMessage,
    BodyInputEventData,
    BodyOutputRequestData,
    BodyOutputResultEventData,
)
from core.body.runtime import BodyRuntime
from core.event import EventClient, EventFlow, ModuleEventAPI


async def publish_body_input(
    events: EventClient,
    runtime: BodyRuntime,
    message: AdapterInboundMessage,
) -> BodyInputEventData | None:
    """Body 模块的入站入口：接收平台消息并发布标准输入事件。

    过滤/去重/归一化由 BodyRuntime 完成，随后以 Body 身份发布
    body.input.received；消息被过滤时返回 None。
    """

    payload = await runtime.handle_adapter_input(message)
    if payload is None:
        return None
    await events.publish("body.input.received", payload)
    return payload


def register_body_events(events: ModuleEventAPI) -> None:
    """声明 Body 拥有的事件定义（公共契约，不依赖 runtime）。"""

    # 输入事件：Context 是 consumer，插件可以作为 observer 旁路观察。
    events.register("body.input.received", payload_type=BodyInputEventData)
    events.register("body.output.requested", payload_type=BodyOutputRequestData)
    for event_type in (
        "body.output.completed",
        "body.output.partially_completed",
        "body.output.failed",
    ):
        events.register(event_type, payload_type=BodyOutputResultEventData)


def subscribe_body_events(events: ModuleEventAPI, runtime: BodyRuntime) -> None:
    """Body 的 Handler 接线（内部实现，依赖 runtime）。"""

    async def handle_output(flow: EventFlow) -> None:
        """执行输出请求，并按结果 outcome 分发对应的完成/失败事件。"""
        # 会话路由由 Body 内部解析，Event 核心不解释业务 Payload。
        result = await runtime.handle_output_request(flow.payload)
        flow.emit(f"body.output.{result.outcome}", result)

    events.subscribe(
        "body.output.requested",
        handle_output,
        handler_id="body.output.dispatch",
    )
