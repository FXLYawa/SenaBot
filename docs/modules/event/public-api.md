# Event 公开 API

本文说明外部 Module 可以依赖的 Event 契约。业务代码应从 `core.event` 导入公开对象，不访问 EventBus 或 EventRegistry 的私有成员。

## 1. 应该使用哪个接口

| 接口 | 使用场景 |
|---|---|
| `ModuleEventAPI` | Module 注册事件、订阅 Handler，同时发布事件 |
| `EventClient` | Adapter 或其他入口只需要发布事件 |
| `EventFlow` | Handler 读取当前事件并描述后续动作 |
| `EventBus` | 组合根管理启动、等待和关闭 |
| `EventRegistry` | 使用新的注册表替换默认注册表；普通 Module 不直接使用 |

`ModuleEventAPI` 继承 `EventClient`：它拥有 `publish()`、`emit()`，并额外提供 `register()`、`subscribe()`。

## 2. 基本概念

### owner

owner 表示一项 Event 能力属于哪个 Module、Adapter 或扩展，例如 `memory`、`body`、`adapter.web`。它不是用户 ID 或 Session ID。

Client 发布的根事件以 Client 绑定的 owner 作为来源；Handler 产生的派生事件以 Handler 所属 owner 作为来源。组合根也可以按 owner 批量注销注册。

### event_type

事件类型是开放字符串，推荐使用 `<domain>.<object>.<state-or-action>`，例如：

```text
body.input.received
memory.query.requested
memory.query.completed
```

名称至少包含两个片段，每个片段只能包含字母、数字和下划线。

### 根事件、派生事件和 Handler

Client 直接发布的是根事件，没有父事件。Handler 通过 `flow.emit()` 产生的是派生事件。它们拥有不同的 event ID，但共享 trace ID，并通过 parent event ID 记录直接父子关系。

Handler 的签名固定为：

```python
async def handle(flow: EventFlow) -> None:
    ...
```

Handler 不返回分发结果。它读取事件、调用自己 Module 的业务实现，并通过 Flow 描述后续动作。

## 3. 公开结构

### `TraceInfo`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `trace_id` | `str` | 必填 | 整条事件链共享的追踪 ID |
| `parent_event_id` | `str \| None` | `None` | 直接父事件 ID；根事件为 `None` |

### `EventEnvelope`

EventEnvelope 是 Handler 收到的完整事件信封：

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_id` | `str` | 当前事件的唯一 ID |
| `event_type` | `str` | 事件类型 |
| `occurred_at` | `datetime` | 事件发生时间 |
| `emitted_at` | `datetime` | 信封发出时间 |
| `source_owner_id` | `str` | 产生该事件的 owner |
| `trace` | `TraceInfo` | 事件链追踪关系 |
| `payload` | `object` | Event 不解释的业务数据 |
| `metadata` | `Mapping[str, object]` | 通用附加信息 |

这些字段是稳定公开契约。信封不可重新赋值；metadata 会被浅复制为只读 Mapping，但 Payload 和 metadata 内部的对象不会被深度冻结。

`with_payload(new_payload)` 返回仅替换 Payload 的新信封。业务 Handler 通常应使用 `flow.replace_payload()`，而不是直接调用它。

### `EventSpec`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `event_type` | `str` | 必填 | 事件类型 |
| `owner_id` | `str` | 必填 | 维护该事件契约的 owner |
| `payload_type` | `type \| None` | `None` | 可选的运行期 `isinstance` 校验类型 |

同一事件类型只能注册一次。`payload_type=None` 表示 Event 不检查 Payload 类型。

### `HandlerSpec`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `handler_id` | `str` | 必填 | owner 内唯一的 Handler ID |
| `owner_id` | `str` | 必填 | Handler 所属 owner |
| `event_pattern` | `str` | 必填 | 精确类型、尾部 `.*` 或全局 `*` |
| `priority` | `int` | `100` | 越小越早进入分发流程 |
| `timeout` | `float \| None` | `None` | 调用超时秒数；`None` 使用 Bus 默认值 |
| `controls_flow` | `bool` | `False` | 是否可以修改 Payload 或停止后续传播 |
| `max_attempts` | `int` | `1` | 普通异常下的总执行次数；`1` 表示不重试 |

同一 owner 内的 `handler_id` 不能重复。

### `EventFlow`

EventFlow 是 Handler 在本次调用中的操作入口，由 Bus 创建，外部代码不应自行构造。

| 成员 | 含义 |
|---|---|
| `envelope` | 当前 Handler 看到的完整信封 |
| `payload` | `envelope.payload` 的便捷访问 |
| `emit(event_type, payload, *, metadata=None)` | 产生一条派生事件 |
| `discard_emitted()` | 清除当前 Handler 尚未提交的派生事件，Flow 仍可继续使用 |
| `replace_payload(new_payload)` | 替换后续 Handler 看到的 Payload |
| `stop_propagation()` | 阻止尚未启动的后续 Handler |

所有 Handler 都可以调用 `emit()`。后两个方法只有注册了 `controls_flow=True` 的 Handler 才能使用。

Flow 中的动作先暂存：Handler 正常返回时一起提交，超时、异常或取消时全部丢弃。Handler 返回后 Flow 失效；后台任务应保存父信封并使用 `EventClient.emit()`。

### `EventError`

`EventError` 继承 `ValueError`，公开字段为：

| 字段 | 类型 | 含义 |
|---|---|---|
| `code` | `str` | 稳定、供程序判断的错误码 |
| `message` | `str` | 面向开发者的说明 |
| `details` | `dict[str, object]` | 诊断信息 |

程序应判断 `code`，不要解析异常字符串。

### `RegistrationToken`

| 成员 | 含义 |
|---|---|
| `registration_id` | 当前注册的唯一 ID |
| `owner_id` | 注册所属 owner |
| `await unregister()` | 注销对应的事件定义或 Handler |

重复注销不会报错。Token 内部的注销回调不是公开接口。

## 4. 注册与发布

### Module 注册

```python
events = ModuleEventAPI(bus, "example")

event_token = events.register(
    "example.operation.requested",
    payload_type=ExampleRequest,
)

handler_token = events.subscribe(
    "example.operation.requested",
    handle_request,
    handler_id="example.execute",
    priority=100,
    timeout=10.0,
    controls_flow=False,
    max_attempts=1,
)
```

ModuleEventAPI 自动把绑定 owner 写入 EventSpec 和 HandlerSpec。

### 发布根事件

```python
client = EventClient(bus, "adapter.web")

await client.publish(
    "example.operation.requested",
    ExampleRequest("hello"),
    metadata={"channel": "web"},
)
```

Client 自动生成 ID、UTC 时间、trace 和 source。`metadata` 是仅限关键字参数。

`publish()` 在校验并入队后返回 `None`，不等待 Handler，也不返回业务结果。


### 在后台延续事件链

```python
await client.emit(
    parent_envelope,
    "example.operation.completed",
    completed,
    metadata={"worker": "background"},
)
```

`emit()` 继承父事件的 trace 和 metadata，并记录父 event ID。它是独立发布，不属于原 Handler 的提交过程。

### Bus 管理

| 方法 | 用途 |
|---|---|
| `await start()` | 启动事件 worker |
| `await stop()` | 拒绝新事件，排空队列并停止 worker |
| `await unregister_owner(owner_id)` | 注销一个 owner 的全部事件定义和 Handler |
| `register(spec)`、`subscribe(spec, handler)` | ModuleEventAPI 使用的低层注册入口 |
| `await publish(envelope)` | EventClient 使用的低层信封入口 |

EventBus 默认创建 EventRegistry；如果需要替换注册表时可通过构造函数注入。普通 Module 使用 ModuleEventAPI 和 EventClient 即可。EventBus 只在组合根中直接创建和管理。

## 5. 匹配与分发

事件必须先注册才能发布。订阅 pattern 支持：

```text
body.input.received   # 精确匹配
body.*                # 命名空间匹配
*                     # 全部事件
```

匹配结果按 priority 和注册顺序排列。普通 Handler 可以并发，因此 priority 只保证发布顺序，不保证完成顺序。

| Handler | 执行方式 | 能力 |
|---|---|---|
| `controls_flow=False` | 创建独立任务，可与其他普通 Handler 并发 | 读取事件、产生派生事件 |
| `controls_flow=True` | Bus 等待其完成后继续 | 还可以替换 Payload、停止后续传播 |

流控制 Handler 的修改只影响尚未启动的后续 Handler；已经启动的普通 Handler 不会被取消，并继续使用启动时的信封。流控制 Handler 失败时，其修改被丢弃，Bus 使用原信封继续分发。

派生事件使用 Handler owner 作为 source，继承父 trace 和 metadata，并以自身 metadata 覆盖同名键。没有匹配 Handler 时，事件直接完成。

## 6. 错误与生命周期

| code | 场景 |
|---|---|
| `registration_conflict` | 重复注册，或事件名/pattern 非法 |
| `event_bus_unavailable` | Bus 未运行或正在关闭 |
| `event_not_registered` | 发布未注册事件 |
| `payload_invalid` | Payload 不符合 `payload_type` |

注册和发布边界错误直接抛出。Handler 超时或异常由 Bus 记录并隔离，不返回给发布者，也不会自动重试。

Bus 的基本生命周期：

```text
创建并注册 -> start -> 发布事件 -> stop
```

`stop()` 先拒绝新事件，再等待已有事件处理；超过 `shutdown_timeout` 后取消 worker 并丢弃剩余队列。注册不会随 Bus 停止自动清空，可通过 Token 或 `unregister_owner(owner_id)` 注销。

组合根需要直接创建 Bus 时，可配置 `dispatch_concurrency`、普通/流控制 Handler 默认超时、关闭超时、Registry 和 Logger。普通 Module 不应直接构造信封调用 `bus.publish()`。

## 7. 当前限制

当前没有 target、广播/单播、请求结果汇总、自动重试、持久化、跨进程 Transport 或插件权限沙箱。

完整接入示例见 [Module 接入指南](integration-guide.md)。
