# Module 接入 Event 指南

本指南给出一个 Module 接入 Event 的最小完整流程。完整字段和分发规则见[公开 API](public-api.md)。

## 1. 组织代码

```text
src/core/example/
├── contracts.py     # 本 Module 公开的 Payload
├── runtime.py       # 本 Module 的业务实现
└── events.py        # Event 与 Runtime 的连接代码
```

Payload 属于业务 Module，不定义在 `core.event`。`events.py` 可以调用本 Module 的 Runtime，但不能导入其他 Module 的 Runtime。

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

Event 只检查可选的 Payload 类型。字段有效性、权限和业务约束仍由 example Module 负责。

## 3. 注册事件和 Handler

```python
# core/example/events.py
from core.event import EventFlow, ModuleEventAPI, RegistrationToken

from .contracts import ExampleCompleted, ExampleRequest


def register_example_events(
    events: ModuleEventAPI,
    runtime,
) -> list[RegistrationToken]:
    tokens = [
        events.register(
            "example.operation.requested",
            payload_type=ExampleRequest,
        ),
        events.register(
            "example.operation.completed",
            payload_type=ExampleCompleted,
        ),
    ]

    async def handle_request(flow: EventFlow) -> None:
        request = flow.payload
        assert isinstance(request, ExampleRequest)

        output = await runtime.execute(request.value)
        flow.emit(
            "example.operation.completed",
            ExampleCompleted(output=output),
        )

    tokens.append(
        events.subscribe(
            "example.operation.requested",
            handle_request,
            handler_id="example.execute",
            timeout=10.0,
        )
    )
    return tokens
```

这段代码声明了两种事件，并把 `handle_request` 注册为请求事件的处理者。Handler 只调用 example 自己的 Runtime；成功后通过 `flow.emit()` 产生完成事件，不返回结果对象。

如果下一步需要其他 Module 完成，也应发布对方公开的事件：

```python
flow.emit("memory.query.requested", memory_request)
```

当前 Module 只依赖事件契约，不直接调用 `memory_runtime`。

## 4. 在组合根安装

组合根通常是应用启动函数或 bootstrap 模块。它集中创建 Bus、Runtime 和 Module API，再把它们连接起来；它只负责装配，不处理业务。

```python
from core.event import EventBus, EventClient, ModuleEventAPI

from core.example.events import register_example_events


bus = EventBus()

example_events = ModuleEventAPI(bus, "example")
example_tokens = register_example_events(example_events, example_runtime)

web_events = EventClient(bus, "adapter.web")

await bus.start()
```

新增 Module 时只增加它的注册函数和装配代码，不修改 EventBus。

## 5. 发布事件

```python
await web_events.publish(
    "example.operation.requested",
    ExampleRequest(value="hello"),
    metadata={"channel": "web"},
)
```

Client 会填写 source、ID、时间和 trace。不要手工构造这些可信字段。

`publish()` 表示“事件已经校验并进入队列”，不表示业务处理已经完成，也不返回 Handler 结果。测试或批处理需要等待整个队列时：

```python
await bus.wait_idle()
```

不要把 `wait_idle()` 当作单个线上请求的响应接口；同步响应应由业务协议单独设计。

## 6. 只在必要时控制事件流

普通 Handler 可以并发执行，适合互不依赖的业务处理。如果某个 Handler 必须先规范化 Payload 或决定是否继续传播，再使用 `controls_flow=True`：

```python
async def normalize(flow: EventFlow) -> None:
    request = flow.payload
    assert isinstance(request, ExampleRequest)

    value = request.value.strip()
    if not value:
        flow.stop_propagation()
        return

    flow.replace_payload(ExampleRequest(value=value))


events.subscribe(
    "example.operation.requested",
    normalize,
    handler_id="example.normalize",
    priority=10,
    controls_flow=True,
)
```

Bus 会等待这个 Handler，再启动排在它后面的处理器。它的修改只影响尚未启动的 Handler；超时或异常时，修改和派生事件都会被丢弃。

## 7. 后台任务和卸载

EventFlow 只在当前 Handler 执行期间有效。后台任务需要延续事件链时，保存父信封并使用注入的 Client：

```python
parent = flow.envelope

async def background_work() -> None:
    completed = await runtime.execute_later()
    await example_events.emit(
        parent,
        "example.operation.completed",
        completed,
    )
```

Module 卸载时可以逐项注销 Token，也可以按 owner 清理：

```python
for token in example_tokens:
    await token.unregister()

# 或者
await bus.unregister_owner("example")
```

应用关闭顺序是：停止外部输入，排空并停止 Bus，注销 owner，最后释放 Runtime。不要先关闭 Runtime，否则在途 Handler 可能访问已经释放的资源。

## 8. 接入检查

- [ ] Payload 定义在所属 Module；
- [ ] 事件与 Handler 通过 ModuleEventAPI 注册；
- [ ] Handler 签名为 `async (EventFlow) -> None`；
- [ ] Handler 只调用本 Module 函数和类；
- [ ] 跨 Module 派生操作使用 `flow.emit()`；
- [ ] 发布入口使用绑定 owner 的 Client；
- [ ] 不把 `publish()` 当作业务结果接口；
- [ ] 只有必要的 Handler 使用流控制；
- [ ] 关闭时先排空事件，再释放 Runtime。
