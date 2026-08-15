# Module 接入 Context 指南

本指南给出业务 Module 接入 Context 的最小流程。完整字段和事件目录见[公开 API](public-api.md)。

## 1. 消费对话上下文

Body 输入写入 Context 后，会产生 `context.prepared`。Agent 从该事件取得本轮所属 Session、近期 Entry 和较早内容的 Summary：

```python
from core.context import ContextPreparedEventData
from core.event import EventFlow


async def handle_context_prepared(flow: EventFlow) -> None:
    prepared = flow.payload
    assert isinstance(prepared, ContextPreparedEventData)

    await agent_runtime.start(
        session_id=prepared.session_id,
        entries=prepared.entries,
        summaries=prepared.summaries,
    )


events.subscribe(
    "context.prepared",
    handle_context_prepared,
    handler_id="agent.context_prepared",
)
```

Handler 可以调用本 Module 的 Runtime。跨 Module 的下一步仍通过事件完成。

`trigger_entry_id` 指向本轮输入对应的 Entry。并发处理同一 Session 时，以 Entry 的 `sequence` 判断先后，不依赖 Handler 完成顺序。

## 2. 追加记录

Agent 输出、Tool 结果或系统说明需要进入 Context 时，发布 `context.append.requested`：

```python
from core.context import (
    ContextActorRef,
    ContextActorType,
    ContextAppendRequestData,
    ContextEntryDraft,
    ContextEntryType,
)


flow.emit(
    "context.append.requested",
    ContextAppendRequestData(
        session_id=session_id,
        entries=(
            ContextEntryDraft(
                entry_type=ContextEntryType.SENA_MESSAGE,
                actor=ContextActorRef(ContextActorType.SENA, "sena", "Sena"),
                content=content,
                source_event_id=flow.envelope.event_id,
            ),
        ),
    ),
)
```

Context 按传入顺序写入整批 Draft，并分配 ID、sequence 和时间。`close_after=True` 用于写入 Work Session 的最后一批内容；普通 Conversation Session 通常不关闭。

追加目前没有结果事件，也不返回处理结果。需要确认写入时，应先补充明确的结果事件，不能读取内部 Store。

## 3. 使用 Work Session

需要独立长期上下文的任务使用 Work Session。`purpose` 表示用途，`work_id` 使用稳定业务 ID；两者共同确定 Session。

```python
from core.context import ContextWorkRequestData


flow.emit(
    "context.work.requested",
    ContextWorkRequestData(
        operation_id=operation_id,
        purpose="task",
        work_id=task_id,
        parent_session_id=conversation_session_id,
    ),
)
```

请求方保存 `operation_id`，并订阅两种终态：

```python
from core.context import ContextWorkFailedEventData, ContextWorkReadyEventData


async def handle_work_ready(flow: EventFlow) -> None:
    result = flow.payload
    assert isinstance(result, ContextWorkReadyEventData)
    pending = pending_operations.pop(result.operation_id, None)
    if pending is not None:
        await pending.continue_with(result.session_id)


async def handle_work_failed(flow: EventFlow) -> None:
    result = flow.payload
    assert isinstance(result, ContextWorkFailedEventData)
    pending = pending_operations.pop(result.operation_id, None)
    if pending is not None:
        await pending.fail(result.error.code)


events.subscribe(
    "context.work.ready",
    handle_work_ready,
    handler_id="agent.work_ready",
)
events.subscribe(
    "context.work.failed",
    handle_work_failed,
    handler_id="agent.work_failed",
)
```

同一 `(purpose, work_id)` 会复用同一 Session。`parent_session_id` 在创建后不能改绑。

## 4. 接入持久化

Context 只保存进程内状态。持久化 Module 订阅恢复请求和状态变化，不直接操作 Context Store。本节契约目前从 `core.context.contracts` 导入。

### 恢复 Session

收到 `context.restore.requested` 后，按 `session_id` 查询并返回一个终态：

```python
from core.context.contracts import ContextRestoreResultEventData


async def handle_restore(flow: EventFlow) -> None:
    request = flow.payload
    snapshot = await repository.load_context(request.session_id)

    result = ContextRestoreResultEventData(
        operation_id=request.operation_id,
        session_id=request.session_id,
        status="not_found" if snapshot is None else "completed",
        snapshot=snapshot,
    )
    flow.emit("context.restore.resolved", result)
```

没有记录时使用 `not_found`；数据库或网络错误使用 `failed + ContextErrorInfo`。Context 会重新校验快照中的 Session 身份。

### 保存变化

```python
async def handle_state_changed(flow: EventFlow) -> None:
    change = flow.payload
    await repository.upsert_session(change.session)
    await repository.append_entries(change.appended_entries)
    if change.created_summary is not None:
        await repository.apply_summary(change.created_summary)
```

`context.state.changed` 是增量事件。持久化实现根据稳定 Entry 和 Summary ID 做幂等写入，并保留原始历史以支持以后展开。

## 5. 在组合根安装

组合根创建 Context 内部组件，再使用 owner 为 `context` 的 `ModuleEventAPI` 注册：

```python
from core.context.compression import LLMCompressor
from core.context.events import ContextModule
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.event import ModuleEventAPI


context_module = ContextModule(
    store=ContextStateStore(),
    window=ContextWindowPolicy(),
    compressor=LLMCompressor(model_provider),
)
context_module.register(ModuleEventAPI(bus, "context"))
```

在 `bus.start()` 前完成注册。没有摘要模型时可以传入 `compressor=None`，此时窗口仍会滚动，但 Summary 文本为空。

## 6. 失败事件

| 事件 | 常见 code | 含义 |
|---|---|---|
| `context.input.failed` | `context_restore_invalid` | 恢复结果与请求不匹配 |
| `context.input.failed` | `context_append_failed` | Session 不可写 |
| `context.work.failed` | `work_identity_invalid` | Work 身份非法 |
| `context.work.failed` | `work_restore_invalid` | Work 恢复结果不匹配 |
| `context.work.failed` | `work_session_unavailable` | Session 关闭或父关系冲突 |

Data 返回的错误码也可能被原样传播。调用方判断 `code`，不解析 `message`。

## 7. 接入检查

- [ ] 只依赖公开 Context 契约；
- [ ] Entry 使用 Draft 提交，Session ID 使用 Context 返回值；
- [ ] Work 同时处理 ready 和 failed，并用 `operation_id` 关联；
- [ ] 不把 `publish()` 当作业务结果接口；
- [ ] Data 区分 completed、not_found 和 failed，并幂等保存状态变化；
- [ ] 不直接使用 Context Store 或内部压缩事件。
