# Module 接入 Agent 指南

本指南说明 Context、Memory、Body 和观察模块如何通过事件与 Agent 协作。完整事件和字段见[公开 API](public-api.md)。

## 1. 从 Context 进入 Agent

普通对话不需要由调用方创建 `AgentRun`。Context 收到输入、准备好 Session 并写入本轮 Entry 后，会发布 `context.prepared`；Agent 从这个事件开始判断是否参与当前交互。

```text
body.input.received
→ Context 写入用户 Entry
→ context.prepared
→ Agent 判断是否参与
→ agent.run.requested 或 agent.interaction.ignored
```

`ContextPreparedEventData.trigger_entry_id` 必须能在 `entries` 中找到。Agent 会把这条 Entry 的文本作为本轮输入；如果找不到，说明 Context 快照不完整，Handler 会直接报错，而不会把它当成空消息继续处理。

如果新功能不是普通对话，就不要为了复用流程而伪造 `context.prepared`。更合适的做法是定义一个能说明用途的业务事件，再在 Agent 内部为它选择 Behavior。

## 2. 为 Agent 完成外部操作

当 Behavior 产生 Memory 或 Reply Effect 时，Delivery 会把它转换成目标模块的请求事件。目标模块完成工作后，再发布对应的结果事件。Handler 的返回值不会用来恢复 Agent。

以 Memory 查询为例：

```python
async def handle_query(flow: EventFlow) -> None:
    request = flow.payload
    result = await memory_service.query(request)
    flow.emit("memory.query.completed", result)
```

查询结果要原样带回请求中的关联 ID。Agent 靠它找到正在等待的 Run；如果 ID 不属于当前 Runtime，或者已经使用过，结果会被忽略。

Body 输出也是同样的做法：请求中的输出 ID 要原样出现在完成、部分完成或失败事件里。Reply Effect 会同时请求 Context 记录回复、Body 发送回复，但这两个模块彼此不需要直接调用。

## 3. 观察 Agent 终态

日志、指标和上层协调模块可以订阅 Agent 的终态事件：

```python
from core.agent import AgentRunCompletedEventData
from core.event import EventFlow


async def observe_completed(flow: EventFlow) -> None:
    completed = flow.payload
    assert isinstance(completed, AgentRunCompletedEventData)
    record_agent_outcome(
        completed.agent_run_id,
        completed.outcome,
    )


events.subscribe(
    "agent.run.completed",
    observe_completed,
    handler_id="metrics.agent_completed",
)
```

观察者只记录结果，不修改 Run。需要区分正常结束和内部错误时，分别订阅 `agent.run.completed` 与 `agent.run.failed`；处理失败类型时读取 `code`，不要解析 `message`。

`agent.run.completed` 的 `outcome` 可能是 `completed`、部分完成或失败。这个事件说明 Agent 已经按流程收尾；只有 `agent.run.failed` 才说明 Behavior、Effect 或 Runtime 本身无法继续。

## 4. 处理未参与的交互

Agent 会忽略机器人发来的输入，也不会参与群组中的普通聊天。如果需要记录这些判断，可以订阅 `agent.interaction.ignored`：

```python
async def observe_ignored(flow: EventFlow) -> None:
    ignored = flow.payload
    logger.debug(
        "Agent ignored session=%s reason=%s",
        ignored.session_id,
        ignored.reason,
    )
```

“忽略”是一次正常的参与判断，不需要重试，也不应重新发布同一输入。如果产品需要调整参与规则，应修改 `InteractionPolicy`，而不是让调用方反复触发 Agent。

## 5. 在组合根安装 Agent

应用启动时，由组合根创建 Behavior、Runtime、Delivery 和 AgentModule，并把它们连接起来：

```python
from core.agent.behaviors import ConversationBehavior
from core.agent.contracts import (
    CONVERSATION_BEHAVIOR,
    MemoryQueryEffect,
    MemoryWriteEffect,
    ReplyEffect,
)
from core.agent.deliveries import MemoryDelivery, ReplyDelivery
from core.agent.dispatcher import AgentDispatcher
from core.agent.events import AgentModule
from core.agent.interaction import InteractionPolicy
from core.agent.runtime import AgentRuntime
from core.event import ModuleEventAPI


conversation = ConversationBehavior(persona_responder)
runtime = AgentRuntime(
    {CONVERSATION_BEHAVIOR: conversation},
)
memory_delivery = MemoryDelivery()
dispatcher = AgentDispatcher(
    runtime,
    {
        MemoryQueryEffect: memory_delivery,
        MemoryWriteEffect: memory_delivery,
        ReplyEffect: ReplyDelivery("sena", "Sena"),
    },
)

agent = AgentModule(runtime, dispatcher, InteractionPolicy())
agent.register(ModuleEventAPI(bus, "agent"))
```

这里的代码只选择实现并建立依赖。以后增加 Behavior 或 Delivery，只需要扩展组合根中的映射，不要在 Runtime 里增加对应的业务分支。

## 6. 接入检查

- [ ] 普通对话通过 `context.prepared` 进入 Agent；
- [ ] 不从其他 Module 直接调用 AgentRuntime；
- [ ] 外部请求和结果使用同一个关联 ID；
- [ ] Handler 通过事件发布结果，不返回业务对象；
- [ ] 未知或重复结果不会重新执行 Run；
- [ ] 正常终态和内部失败分别观察；
- [ ] 新 Behavior 通过映射安装，不修改 Runtime；
- [ ] 新 Effect 同时提供对应 Delivery；
- [ ] 组合根只负责创建和连接对象。
