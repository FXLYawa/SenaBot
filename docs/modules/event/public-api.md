# Event 公开 API

本文记录外部 Module 可以依赖的契约和行为。业务代码应从 `core.event` 导入公开对象，不访问 Registry 状态或 EventBus 私有方法。

## 1. 调用入口

| 接口 | 使用者 | 用途 |
|---|---|---|
| `ModuleEventAPI` | 受信核心 Module | 注册事件、订阅 Handler、构造派生事件 |
| `EventClient` | 输入 Adapter、业务入口 | 以绑定 owner 发布根事件 |
| `EventBus` | 组合根 | 创建通信核心、执行 owner 清理 |

普通 Module 不应直接使用 `EventRegistry` 或手工构造带有可信 source 的 `EventEnvelope`。

## 2. 核心概念

### owner

owner 是稳定的 Module、Adapter 或扩展身份，例如 `memory`、`body`、`adapter.web`。它不是用户 ID、Session ID 或进程实例 ID。

- 事件 owner 维护事件契约；
- Handler owner 表示处理能力属于谁；
- 根事件 source 由 `EventClient` 的 owner 决定；
- 派生事件 source 由产生它的 Handler owner 决定；
- `target_owner_id` 只筛选目标 Handler owner。

### event_type

事件名是开放字符串，推荐格式为：

```text
<domain>.<object>.<state-or-action>
```

例如 `body.input.received`、`memory.query.requested`。名称至少包含两个片段，每个片段只能使用字母、数字和下划线。

### Handler

Handler 是异步 callable，接收 `EventEnvelope`，必须返回 `EventHandlerResult`。

| 类型 | 用途 |
|---|---|
| `CONSUMER` | 承担业务处理责任 |
| `OBSERVER` | 日志、指标、审计等旁路处理 |
| `TRANSFORMER` | 在主处理前替换同一事件的 Payload |

## 3. 公开契约

### `EventEnvelope`

Handler 接收到的事件信封：

| 字段 | 类型 | 含义 |
|---|---|---|
| `event_id` | `str` | 当前事件唯一 ID |
| `event_type` | `str` | 开放字符串事件名 |
| `occurred_at` | `datetime` | 业务事实发生时间 |
| `emitted_at` | `datetime` | 信封发出时间 |
| `source_owner_id` | `str` | 可信发布身份 |
| `target_owner_id` | `str \| None` | 可选目标 Handler owner |
| `trace` | `TraceInfo` | 当前事件的追踪关系 |
| `payload` | `object` | Event 不解释的业务数据 |
| `metadata` | `Mapping[str, object]` | 通用诊断或附加信息 |

信封不可重新赋值，metadata 会被复制为只读 Mapping；Payload 本身不会被深拷贝或递归冻结。

### `EventHandlerResult`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `handled` | `bool` | `True` | unicast Consumer 是否接受事件 |
| `transform` | `EventTransform \| None` | `None` | 仅 Transformer 可以提供的 Payload 替换 |
| `derived_events` | `list[EventPublishRequest]` | 空列表 | 请求 EventBus 后续发布的事件 |
| `metadata` | `dict[str, object]` | 空字典 | 本次 Handler 的少量诊断信息 |
| `error` | `EventError \| None` | `None` | Handler 主动返回的结构化错误 |

### `EventDispatchResult`

`publish()` 返回：

| 字段 | 类型 | 含义 |
|---|---|---|
| `envelopes` | `list[EventEnvelope]` | 根事件和本次同步处理的派生事件 |
| `handlers` | `list[HandlerExecutionResult]` | 每次 Handler 的执行记录 |
| `errors` | `list[EventError]` | 校验、选择、执行和派生阶段的错误 |

调用方必须检查 `errors`，并根据稳定的 `error.code` 处理，不要解析 `message`。

### `HandlerExecutionResult`

它是 `EventDispatchResult.handlers` 中的元素：

| 字段 | 类型 | 含义 |
|---|---|---|
| `handler_id` | `str` | Handler 在 owner 内的稳定 ID |
| `owner_id` | `str` | Handler 所属 owner |
| `handled` | `bool` | Handler 返回的接受状态 |
| `metadata` | `dict[str, object]` | Handler 返回的诊断信息 |
| `error` | `EventError \| None` | 本次 Handler 的错误 |

该类型已从 `core.event` 导出，字段属于稳定公开契约。外部代码可以导入它进行类型标注，并读取字段用于日志、测试和观测；通常不应主动构造或修改它，也不应根据具体 `handler_id` 编写业务流程。

### `TraceInfo`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `trace_id` | `str` | 必填 | 一条根事件及其派生链共享的追踪 ID |
| `parent_event_id` | `str \| None` | `None` | 直接父事件 ID；根事件为 `None` |

### `EventSpec`

EventBus 的底层事件注册声明；Module 通常通过 `ModuleEventAPI.register()` 创建。

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `event_type` | `str` | 必填 | 事件名称 |
| `owner_id` | `str` | 必填 | 维护该事件契约的 owner |
| `payload_type` | `type \| None` | `None` | 可选运行期 `isinstance` 校验类型 |
| `mode` | `EventMode` | `BROADCAST` | broadcast 或 unicast |

### `HandlerSpec`

EventBus 的底层 Handler 声明；Module 通常通过 `ModuleEventAPI.subscribe()` 创建。

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `handler_id` | `str` | 必填 | owner 内唯一的 Handler ID |
| `owner_id` | `str` | 必填 | Handler 所属 owner |
| `event_pattern` | `str` | 必填 | exact、尾部 `.*` 或全局 `*` |
| `priority` | `int` | `100` | 越小越先执行 |
| `kind` | `HandlerKind` | `CONSUMER` | Handler 类型 |
| `timeout` | `float \| None` | `None` | 单次调用超时秒数 |
| `publish_patterns` | `tuple[str, ...]` | `()` | 允许产生的跨 owner 派生事件 pattern |

### `EventPublishRequest`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `event_type` | `str` | 必填 | 要发布的派生事件类型 |
| `payload` | `object` | 必填 | 派生事件 Payload |
| `target_owner_id` | `str \| None` | `None` | 可选目标 Handler owner |
| `metadata` | `dict[str, object]` | 空字典 | 覆盖或补充父事件 metadata |
| `occurred_at` | `datetime \| None` | `None` | 业务发生时间；省略时由 EventBus 生成 |

该请求不允许指定 source、event ID、emitted time 或 trace，这些字段由 EventBus 根据 Handler 身份和父事件补全。

### `EventTransform`

| 字段 | 类型 | 含义 |
|---|---|---|
| `payload` | `object` | 替换当前信封的 Payload |

`EventTransform.with_changes(payload, **changes)` 可以浅复制 dataclass 或 Mapping 并修改指定字段。其他 Payload 类型会抛出 `TypeError`。

### `EventError`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `code` | `str` | 必填 | 稳定、供程序判断的错误码 |
| `message` | `str` | 必填 | 面向开发者的简短说明 |
| `details` | `dict[str, object]` | 空字典 | 不含敏感数据的诊断信息 |
| `retryable` | `bool` | `False` | 是否允许调用方重试 |

### `RegistrationToken`

| 成员 | 类型 | 含义 |
|---|---|---|
| `registration_id` | `str` | 当前事件定义或 Handler 注册的 ID |
| `owner_id` | `str` | 注册所属 owner |
| `active` | `bool` | 注册当前是否有效 |
| `await unregister()` | 方法 | 幂等地注销当前注册 |

`active` 用于观察状态，不应手工修改。Token 内部持有的注销回调不是公开接口，外部代码不应访问或替换。

## 4. 注册和发布

### 创建 Module API

```python
events = ModuleEventAPI.create(bus, "memory")
```

owner 创建后固定用于注册和发布身份。当前 `ModuleEventAPI` 面向受信核心 Module，不能直接暴露给第三方插件。

### 注册事件

```python
token = events.register(
    "memory.query.requested",
    payload_type=MemoryQueryRequest,
    mode=EventMode.UNICAST,
)
```

一个 `event_type` 只能有一个 owner。`payload_type=None` 表示不进行运行期类型检查。

### 注册 Handler

```python
token = events.subscribe(
    "memory.query.requested",
    handle_query,
    handler_id="memory.query",
    priority=100,
    kind=HandlerKind.CONSUMER,
    timeout=10.0,
)
```

pattern 支持精确事件名、尾部通配 `memory.*` 和全局通配 `*`。priority 越小越先执行；同 priority 按注册顺序执行。

当前 `ModuleEventAPI.subscribe()` 的 `publish_patterns` 参数尚未用于权限收缩，核心 Handler 实际使用 `("*",)`。不要依赖该参数实现插件权限隔离。

### 发布根事件

```python
result = await client.publish(
    "body.input.received",
    payload,
    target_owner_id="body",
    metadata={"channel": "web"},
)
```

`EventClient` 自动生成 event ID、trace、时间和 source。Client 可以发布自己拥有的事件，或 `publish_patterns` 明确允许的事件；越权时抛出 `EventPermissionError`。

### 构造派生事件

```python
return EventHandlerResult(
    derived_events=[
        events.derived(
            "memory.query.completed",
            completed,
            target_owner_id=envelope.source_owner_id,
        )
    ]
)
```

Handler 不直接递归调用 `publish()`。EventBus 为派生事件生成新 ID，使用 Handler owner 作为 source，继承 trace，并记录父 event ID。

## 5. 分发规则

一次事件按以下顺序处理：

```text
校验 -> 匹配并排序 -> Transformer -> target 过滤
     -> Consumer -> Observer -> 派生事件
```

- `broadcast`：执行全部 Consumer，再执行全部 Observer；
- `unicast`：首个无错误且 `handled=True` 的 Consumer 接受事件，随后仍执行 Observer；
- 所有 Consumer 都未接受 unicast 时返回 `handler_not_found`；
- 单个 Handler 超时或异常会被隔离，后续 Handler 继续执行；
- 派生事件使用 FIFO 队列，按广度优先顺序处理；
- Transformer 只能精确订阅已注册事件，并且只能替换 Payload。

## 6. 错误

分发期错误写入 `EventDispatchResult.errors`：

| code | 含义 |
|---|---|
| `event_not_registered` | 事件没有注册 |
| `payload_invalid` | Payload 类型不符合 EventSpec |
| `handler_not_found` | 没有匹配或接受事件的 Handler |
| `handler_timeout` | Handler 超时 |
| `handler_failed` | Handler 异常或返回值非法 |
| `permission_denied` | 发布或 transform 操作越权 |

注册冲突抛出 `EventRegistrationError`，其结构化错误码为 `registration_conflict`；Client 发布越权抛出 `EventPermissionError`，非法信封构造抛出 `ValueError`。前两个异常都通过 `.error` 暴露对应的 `EventError`。`retryable=True` 只表示允许调用方重试，EventBus 不会自动重试。

## 7. 注销

事件注册和 Handler 注册都会返回 `RegistrationToken`：

```python
await token.unregister()
```

注销是幂等的。Module 停止时通常由组合根统一清理：

```python
await bus.unregister_owner("memory")
```

owner 清理会移除该 owner 的事件定义、Handler 和相关 callable 引用。
