# Module 接入 Event 指南

本指南展示一个 Module 接入 Event 所需的最小完整流程。

## 1. 组织业务代码

```text
src/core/example/
├── contracts.py     # Payload 契约
├── runtime.py       # 本 Module 的业务实现
└── events.py        # Event 与本地 Runtime 的适配
```

Payload 属于业务 Module，不应定义在 `core.event` 中。

## 2. 定义 Payload

```python
# core/example/contracts.py
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExampleRequest:
    value: str


@dataclass(frozen=True, slots=True)
class ExampleCompleted:
    output: str
```

## 3. 注册事件和 Handler

```python
# core/example/events.py
from core.event import EventHandlerResult, EventMode, ModuleEventAPI

from .contracts import ExampleCompleted, ExampleRequest


def register_example_events(events: ModuleEventAPI, runtime) -> None:
    events.register(
        "example.operation.requested",
        payload_type=ExampleRequest,
        mode=EventMode.UNICAST,
    )
    events.register(
        "example.operation.completed",
        payload_type=ExampleCompleted,
    )

    async def handle_request(envelope):
        request = envelope.payload
        assert isinstance(request, ExampleRequest)

        # Handler 只调用本 Module 的 Runtime。
        output = await runtime.execute(request.value)

        return EventHandlerResult(
            derived_events=[
                # 发布派生事件
                events.derived(
                    "example.operation.completed",
                    ExampleCompleted(output),
                    target_owner_id=envelope.source_owner_id,
                )
            ]
        )

    events.subscribe(
        "example.operation.requested",
        handle_request,
        handler_id="example.execute",
        timeout=10.0,
    )
```

`events.py` 是 Event 到本地 Runtime 的 Adapter。它可以依赖本 Module 的契约和 Runtime，但不得导入其他 Module 的 Runtime。

## 4. 在组合根安装

组合根是应用启动时创建对象和连接依赖的位置：

```python
from core.event import EventBus, EventClient, ModuleEventAPI


bus = EventBus()

example_events = ModuleEventAPI.create(bus, "example")
register_example_events(example_events, example_runtime)

web_client = EventClient(
    bus,
    owner_id="adapter.web",
    publish_patterns=("example.operation.requested",),
)
```

EventBus 不应随着 Module 数量增加而修改。组合根可以认识各 Module 以完成装配，但不处理业务，也不把整个依赖容器交给业务代码。

## 5. 从入口发布

```python
result = await web_client.publish(
    "example.operation.requested",
    ExampleRequest("hello"),
    target_owner_id="example",
)

if result.errors:
    for error in result.errors:
        logger.warning("event failed: %s", error.code)
```

入口使用宿主注入的 `EventClient`，不要手工填写 `source_owner_id`。

## 6. 跨 Module 通信

不要直接调用其他 Module：

```python
# 错误
result = await memory_runtime.query(request)
```

改为声明派生事件：

```python
return EventHandlerResult(
    derived_events=[
        events.derived(
            "memory.query.requested",
            request,
            target_owner_id="memory",
        )
    ]
)
```

Memory Module 注册自己的 Handler、调用自己的 Runtime，并按需要发布结果事件。EventBus 不需要增加路由分支。

## 7. 命名和 Handler 选择

事件名推荐使用 `<domain>.<object>.<state-or-action>`：

```text
body.input.received
memory.query.requested
memory.query.completed
```

- 业务处理使用 Consumer；
- 日志、指标和审计使用 Observer；
- 同一事件进入主处理前确实需要规范化 Payload 时才使用 Transformer；
- 事件类型发生变化时使用派生事件，不使用 Transformer 充当路由器。

owner 使用稳定的 Module 或 Adapter 名称，不要包含用户、Session 或实例 ID。

## 8. 生命周期

需要逐项卸载时保存注册 Token：

```python
token = events.subscribe(...)
await token.unregister()
```

通常由组合根按 owner 清理：

```python
await bus.unregister_owner("example")
```

停止顺序应是：停止新输入、处理必要的在途调用、注销 owner、释放 Runtime 资源。

## 9. 接入检查

- [ ] Payload 定义在所属业务 Module；
- [ ] 事件和 Handler 通过 `ModuleEventAPI` 动态注册；
- [ ] Handler 只调用本 Module Runtime；
- [ ] 跨 Module 操作使用派生事件；
- [ ] 发布入口使用绑定 owner 的 `EventClient`；
- [ ] 调用方检查 `EventDispatchResult.errors`；
- [ ] owner 停止时完成注销；
- [ ] 新增事件不需要修改 `core.event`。

字段、分发模式和错误码见[公开 API](public-api.md)。
