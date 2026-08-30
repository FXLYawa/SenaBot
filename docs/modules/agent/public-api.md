# Agent 公开 API

本文说明外部 Module 可以依赖的 Agent 契约。跨模块协作通过事件完成，业务代码不直接操作 `AgentRuntime`，也不修改正在执行的 `AgentRun`。

## 1. 应该使用哪个事件

| 目标 | 事件 |
|---|---|
| 向 Agent 提供一轮对话上下文 | `context.prepared`，通常由 Context 自动发布 |
| 观察一次 Run 正常结束 | `agent.run.completed` |
| 观察 Agent 内部执行失败 | `agent.run.failed` |
| 观察 Sena 没有参与某次输入 | `agent.interaction.ignored` |
| 为 Agent 返回记忆结果 | 发布对应 Memory 完成事件 |

`agent.run.requested` 用于连接 Agent 内部流程，不是普通 Module 的调用入口。新功能如果需要触发一种行为，应先定义能表达实际业务含义的入口事件，再由 Agent 把它转换为 Run。这样不会绕过交互判断，也不会让调用方依赖 Agent 的内部状态。

## 2. 基本概念

### AgentRun

`AgentRun` 表示 Agent 正在处理的一项任务。`run_id` 标识这次执行，`session_id` 记录它关联的 Context，`behavior_type` 决定由哪个 Behavior 处理。

Run 不等于 Session。Session 可以持续很久，同一个 Session 会产生多次 Run；Run 结束后，Context 仍然存在。

### Behavior、Observation 和 Effect

Behavior 是具体的行为逻辑。每次执行 `step()` 时，它会拿到上一步留下的状态和一条 Observation，然后给出新的状态以及接下来要执行的 Effect。

Observation 告诉 Behavior 这次执行是刚刚开始，还是之前请求的外部操作已经有了结果。Effect 则用来表达下一步动作，例如查询记忆、回复用户、结束任务或报告失败。真正的跨模块调用不写在 Behavior 里。

### 等待与恢复

当外部结果会影响下一步决策时，Effect 会携带一个关联 ID。Dispatcher 在发布请求前把这个 ID 记到 Run 上；结果事件回来时，RunFlow 再用同一个 ID 恢复对应的任务。

当前一个 Run 同时只能等待一个结果。Memory 查询和写入属于等待型 Effect，它们返回后会再次调用 Behavior。Reply Effect 在发布 Context 和 Body 请求的同一步配合 Finish Effect，完成本次 Run。

## 3. 对外事件

### `agent.run.completed`

Payload 为 `AgentRunCompletedEventData`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `agent_run_id` | `str` | 必填 | 已结束的 Run ID |
| `session_id` | `str \| None` | 必填 | 关联 Session |
| `behavior_type` | `str` | 必填 | 执行的 Behavior 类型 |
| `outcome` | `str` | `completed` | 终止结果 |

这里的“完成”是指 Agent 已经完成本次行为决策和事件发布。Body 随后独立处理输出请求，并通过自己的完成、部分完成或失败事件报告交付状态。

### `agent.run.failed`

Payload 为 `AgentRunFailedEventData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `agent_run_id` | `str` | 失败的 Run ID |
| `session_id` | `str \| None` | 关联 Session |
| `behavior_type` | `str` | Behavior 类型 |
| `code` | `str` | 稳定错误码 |
| `message` | `str` | 面向开发者的诊断信息 |

需要在程序中区分错误时应使用 `code`；`message` 只用于日志和排查。现有错误码如下：

| code | 含义 |
|---|---|
| `run_conflict` | 同一 Runtime 中已经存在相同 Run ID |
| `behavior_not_found` | 没有安装对应 Behavior |
| `behavior_failed` | Behavior 抛出异常或返回了不合法状态 |
| `step_limit_exceeded` | Run 超过最大 step 数 |
| `effect_not_supported` | 没有安装处理该 Effect 的 Delivery |
| `step_invalid` | step 包含多个 Finish、多个等待操作，或同时等待并结束 |
| `step_stalled` | step 既不等待外部结果，也没有结束 Run |
| `empty_step` | Runtime 迁移缺少 step 数据 |
| `observation_unsupported` | Conversation Behavior 收到了无法处理的观察结果 |

### `agent.interaction.ignored`

Payload 为 `AgentInteractionIgnoredEventData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `session_id` | `str` | 本次输入所属 Session |
| `reason` | `str` | 未参与原因 |

当前原因包括：

| reason | 含义 |
|---|---|
| `bot_source` | 输入来自机器人账号 |
| `ambient_group_message` | 群组或频道消息没有明确指向 Sena |
| `unsupported_scene` | 当前场景不在参与规则中 |

私聊和桌面输入会直接进入 Agent。群组与频道中的普通消息不会触发回复，只有明确指向 Sena 的消息才会继续处理。

## 4. `core.agent` 公开对象

当前包根导出以下对象：

| 对象 | 用途 |
|---|---|
| `AgentRuntime` | 组合根创建并注入 Behavior；普通 Module 不直接调用 |
| `AgentRun` | Runtime 中的一次运行状态 |
| `Behavior` | Behavior 最小协议 |
| `AgentStepResult` | 一次 Behavior step 的新状态和 Effect |
| `AgentRunCompletedEventData` | Run 正常结束事件 Payload |

`AgentRun` 和 `AgentRuntime` 虽然可以从包根导入，主要还是供组合根和核心扩展使用。跨模块协作应继续依赖事件。

失败和忽略事件的 Payload 已经定义，但还没有全部加入包根导出。在插件接口稳定前，外置插件不应直接依赖 Agent 内部文件路径。

## 5. Behavior 协议

Behavior 的调用形式为：

```python
class Behavior(Protocol):
    async def step(
        self,
        state: object,
        observation: AgentObservation,
    ) -> AgentStepResult:
        ...
```

`AgentStepResult`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `next_state` | `object` | 下一次 step 使用的纯数据状态 |
| `effects` | `tuple[AgentEffect, ...]` | 本次需要执行的 Effect |

Runtime 不会读取这些状态的业务字段，只检查它们是不是适合保存的数据。基础值、枚举、日期时间、dataclass、Mapping 和 Sequence 都可以使用；函数、协程、文件对象和循环引用会被拒绝。

目前新增 Behavior 仍属于核心开发工作。Effect、Observation 以及运行时约束见[核心开发指南](../../../src/core/agent/README.md)。

## 6. 事件目录

| 事件 | 方向 | 说明 |
|---|---|---|
| `context.prepared` | Context → Agent | 触发交互判断和 Conversation Run |
| `agent.run.requested` | Agent 内部 | 创建并启动 Run |
| `agent.run.completed` | Agent → 观察者 | Run 正常结束 |
| `agent.run.failed` | Agent → 观察者 | Run 因内部错误终止 |
| `agent.interaction.ignored` | Agent → 观察者 | 本次输入未进入 Behavior |
| `memory.query.requested` | Agent → Memory | Behavior 请求相关记忆 |
| `memory.query.completed` | Memory → Agent | 恢复等待查询结果的 Run |
| `memory.write.requested` | Agent → Memory | Behavior 请求写入记忆 |
| `memory.write.completed` | Memory → Agent | 恢复等待写入结果的 Run |
| `context.append.requested` | Agent → Context | 记录 Sena 回复 |
| `body.output.requested` | Agent → Body | 请求交付回复 |
| `body.output.completed` | Body → 观察者 | 输出全部完成 |
| `body.output.partially_completed` | Body → 观察者 | 输出部分完成 |
| `body.output.failed` | Body → 观察者 | 输出失败 |

这些请求事件都没有业务返回值。Memory 的完成事件用于恢复 Run；Body 的结果事件描述回复交付情况，由关心交付状态的模块订阅。

## 7. 当前限制

Run 目前只保存在内存中，进程重启后无法恢复；一个 Run 也只能同时等待一个操作。现在安装的 Behavior 只有 Conversation，Memory 失败事件还没有接入恢复流程。各模块的结果契约稳定后，还需要再统一外部结果接口。

接入示例见 [Module 接入指南](integration-guide.md)。
