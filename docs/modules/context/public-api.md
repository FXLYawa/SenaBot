# Context 公开 API

本文说明外部 Module 可以依赖的 Context 契约。业务代码从 `core.context` 导入公开对象，不访问 Store、Flow 或状态容器。

## 1. 应该使用哪个事件

| 目标 | 事件 |
|---|---|
| 获取一轮对话的工作上下文 | 订阅 `context.prepared` |
| 追加 Agent、Tool 或系统记录 | 发布 `context.append.requested` |
| 获取独立 Work Session | 发布 `context.work.requested`，订阅 ready/failed |
| 持久化 Context | 使用 restore 和 state changed 事件 |
| 展开历史摘要 | 当前暂不可用 |

发布接口不返回业务结果。需要结果的请求使用 `operation_id` 关联后续成功或失败事件。

## 2. 基本概念

每个 Session 对应一份相互隔离的 Context：Conversation Session 表示一段持续交互，Work Session 表示一个独立任务。`session_id` 由 Context 根据稳定业务身份生成，调用方只保存和传递，不解析其格式。

写入 Context 的原始记录称为 Entry，使用 Session 内严格递增的 `sequence` 表示顺序。Context 保留近期 Entry，并用 Summary 表示更早的内容；两者共同组成 Agent 当前使用的工作窗口。

程序启动后首次访问某个 Session 时，Context 通过 restore 事件读取此前保存的 `ContextSnapshot`。`completed` 表示恢复成功，`not_found` 表示需要新建 Session，`failed` 表示读取出错。

## 3. 业务公开结构

除特别说明外，本节对象都由 `core.context` 导出。

### Entry 类型与来源

`ContextEntryType` 提供三个核心值：

| 值 | 含义 |
|---|---|
| `USER_MESSAGE` / `user_message` | 用户输入 |
| `SENA_MESSAGE` / `sena_message` | Sena 消息 |
| `SYSTEM_NOTE` / `system_note` | 系统说明 |

`entry_type` 实际接受开放字符串，扩展可以使用自己的命名空间。

`ContextActorType` 表示条目来源，可取 `USER`、`SENA`、`SYSTEM`、`TOOL` 或 `EXTENSION`。它只描述来源，不承担权限判断。

`ContextActorRef`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `actor_type` | `ContextActorType` | 必填 | 来源类别 |
| `actor_id` | `str` | 必填 | 稳定主体 ID |
| `display_name` | `str` | `""` | 展示名称 |

### `ContextEntryDraft`

请求写入但尚未分配记录字段的 Entry：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `entry_type` | `str` | 必填 | 开放条目类型 |
| `actor` | `ContextActorRef` | 必填 | 条目来源 |
| `content` | `Content` | 必填 | 结构化正文 |
| `source_event_id` | `str \| None` | `None` | 产生该条目的事件 ID |

### `ContextEntryRecord`

Context 写入后生成的不可变记录：

| 字段 | 类型 | 含义 |
|---|---|---|
| `entry_id` | `str` | 条目唯一 ID |
| `session_id` | `str` | 所属 Session |
| `sequence` | `int` | Session 内顺序号 |
| `entry_type` | `str` | 条目类型 |
| `actor` | `ContextActorRef` | 条目来源 |
| `content` | `Content` | 结构化正文 |
| `source_event_id` | `str \| None` | 来源事件 ID |
| `created_at` | `datetime` | 写入时间 |

`text()` 返回正文的纯文本表示。`entry_id`、`session_id`、`sequence` 和时间均由 Context 分配。

### `ContextSummary`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `summary_id` | `str` | 必填 | 摘要唯一 ID |
| `session_id` | `str` | 必填 | 所属 Session |
| `level` | `int` | 必填 | 摘要层级，最小为 1 |
| `first_sequence` | `int` | 必填 | 覆盖范围起点，包含 |
| `last_sequence` | `int` | 必填 | 覆盖范围终点，包含 |
| `text` | `str` | 必填 | 摘要正文，可能为空 |
| `created_at` | `datetime` | 必填 | 创建时间 |
| `source_summary_ids` | `tuple[str, ...]` | `()` | 高层摘要直接覆盖的下级摘要 ID |

Level 1 直接覆盖 Entry，不能包含 `source_summary_ids`；更高层必须记录直接下级摘要 ID。

### `ContextPreparedEventData`

一次对话输入写入后，Context 向下游提供的工作上下文：

| 字段 | 类型 | 含义 |
|---|---|---|
| `session_id` | `str` | 本轮所属 Session |
| `trigger_event_id` | `str` | 原始输入事件 ID |
| `trigger_entry_id` | `str` | 本轮新增的用户 Entry ID |
| `entries` | `tuple[ContextEntryRecord, ...]` | 近期原文 |
| `summaries` | `tuple[ContextSummary, ...]` | 当前有效摘要 |
| `output_route` | `BodyRouteInfo` | Body 输出需要的稳定路由 |
| `source` | `SourceInfo` | 原始主体 |
| `scene` | `SceneInfo` | 交互场景 |
| `interaction` | `InteractionSignals` | 交互信号 |
| `reply_to_message_id` | `str \| None` | 可选回复目标 |

这些值只描述本轮工作上下文，不能跨 Session 复用。

### `ContextAppendRequestData`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `session_id` | `str` | 必填 | 目标 Session |
| `entries` | `tuple[ContextEntryDraft, ...]` | 必填 | 按顺序追加的草稿，不能为空 |
| `close_after` | `bool` | `False` | 是否在追加后关闭 Session |

关闭后的 Session 不再接受追加。

### Work Session 契约

`ContextWorkRequestData`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `operation_id` | `str` | 必填 | 请求方生成的关联 ID |
| `work_id` | `str` | 必填 | 稳定业务 ID |
| `purpose` | `str` | 必填 | 开放用途，例如 `task`、`diary` |
| `parent_session_id` | `str \| None` | `None` | 可选来源 Conversation Session |

`purpose` 会去除空白并转为小写，不能为空或 `conversation`。同一 `(purpose, work_id)` 始终对应同一 Session。

`ContextWorkReadyEventData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `operation_id` | `str` | 对应请求 ID |
| `work_id` | `str` | 稳定 Work ID |
| `session_id` | `str` | 已恢复或创建的 Session |

`ContextWorkFailedEventData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `operation_id` | `str` | 对应请求 ID |
| `work_id` | `str` | 稳定 Work ID |
| `error` | `ContextErrorInfo` | 失败信息 |

### 错误结构

`ContextErrorInfo` 包含稳定错误码 `code` 和诊断文本 `message`。它目前定义在 `core.context.contracts`，通常由失败事件间接携带。程序判断 `code`，不解析 `message`。

`ContextInputFailedEventData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `session_id` | `str` | 输入原本所属 Session |
| `trigger_event_id` | `str` | 未被接纳的输入事件 ID |
| `error` | `ContextErrorInfo` | 失败原因 |

收到该事件后，对应输入不会再产生 `context.prepared`。

### 历史读取契约

`ContextHistoryRequestData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `operation_id` | `str` | 请求关联 ID |
| `session_id` | `str` | 当前 Session |
| `summary_id` | `str` | 要展开的摘要 ID |

`ContextHistoryLevel`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `summary` | `ContextSummary` | 被展开的摘要 |
| `summaries` | `tuple[ContextSummary, ...]` | 高层摘要的直接子摘要 |
| `entries` | `tuple[ContextEntryRecord, ...]` | Level 1 覆盖的原始 Entry |

Level 1 只返回 `entries`，更高层只返回 `summaries`。

`ContextHistoryResultEventData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `operation_id` | `str` | 对应请求 ID |
| `history` | `ContextHistoryLevel \| None` | 成功结果 |
| `error` | `ContextErrorInfo \| None` | 失败结果 |

`history` 和 `error` 必须且只能存在一个。

当前只注册了这些契约，尚未安装读取 Handler，业务流程暂时不能依赖它们。

### 摘要器

`ContextCompressor` 定义 `async compress(input) -> str | None`，用于生成摘要文本。`LLMCompressor(provider, entry_char_limit=8000)` 是当前模型实现。它们由组合根配置，不在普通业务 Handler 中使用。

## 4. 持久化协作结构

本节对象目前从 `core.context.contracts` 导入，只供 Context 与持久化 Module 协作。

### `SessionRecord`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `session_id` | `str` | 必填 | Session ID |
| `created_at` | `datetime` | 必填 | 创建时间 |
| `updated_at` | `datetime` | 必填 | 最近更新时间 |
| `closed_at` | `datetime \| None` | `None` | 关闭时间 |
| `purpose` | `str` | `conversation` | Session 用途 |
| `conversation_scope` | `ConversationScope \| None` | `None` | Conversation 身份来源 |
| `work_id` | `str \| None` | `None` | Work 身份来源 |
| `parent_session_id` | `str \| None` | `None` | 可选父 Session |

`is_closed` 由 `closed_at` 判断。

### `ContextSnapshot`

| 字段 | 类型 | 含义 |
|---|---|---|
| `session` | `SessionRecord` | Session 状态 |
| `latest_sequence` | `int` | 已分配的最大 Entry sequence |
| `entries` | `tuple[ContextEntryRecord, ...]` | 当前原始 Entry |
| `summaries` | `tuple[ContextSummary, ...]` | 当前有效 Summary |

### 恢复契约

`ContextRestoreRequestData`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `operation_id` | `str` | 本次恢复操作 ID |
| `session_id` | `str` | 要恢复的 Session |

`ContextRestoreResultEventData`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `operation_id` | `str` | 必填 | 对应恢复请求 |
| `session_id` | `str` | 必填 | 对应 Session |
| `status` | `str` | 必填 | `completed`、`not_found` 或 `failed` |
| `snapshot` | `ContextSnapshot \| None` | `None` | `completed` 时必填 |
| `error` | `ContextErrorInfo \| None` | `None` | `failed` 时必填 |

三种 status 的数据形状互斥，`not_found` 不携带 snapshot 或 error。

### `ContextStateChangedEventData`

| 字段 | 类型 | 含义 |
|---|---|---|
| `session` | `SessionRecord` | 变化后的 Session 状态 |
| `latest_sequence` | `int` | 变化后的最大 sequence |
| `appended_entries` | `tuple[ContextEntryRecord, ...]` | 本次新增 Entry |
| `created_summary` | `ContextSummary \| None` | 本次新增 Summary |

这是增量状态事件：新建 Session 时没有新增内容，追加时携带本批 Entry，压缩时携带新 Summary。它不是完整 `ContextSnapshot`。

## 5. 事件目录

| 事件 | Payload | 方向 | 说明 |
|---|---|---|---|
| `body.input.received` | Body 输入契约 | Body → Context | Context 消费普通输入 |
| `context.prepared` | `ContextPreparedEventData` | Context → Agent 等 | 工作上下文已经准备好 |
| `context.input.failed` | `ContextInputFailedEventData` | Context → 订阅方 | 输入未进入 Context |
| `context.append.requested` | `ContextAppendRequestData` | Module → Context | 追加 Entry |
| `context.work.requested` | `ContextWorkRequestData` | Module → Context | 请求 Work Session |
| `context.work.ready` | `ContextWorkReadyEventData` | Context → 请求方 | Work Session 可用 |
| `context.work.failed` | `ContextWorkFailedEventData` | Context → 请求方 | Work Session 不可用 |
| `context.state.changed` | `ContextStateChangedEventData` | Context → Data 等 | 持久化增量变化 |
| `context.restore.requested` | `ContextRestoreRequestData` | Context → Data 等 | 请求恢复 Session |
| `context.restore.resolved` | `ContextRestoreResultEventData` | Data 等 → Context | 返回恢复终态 |
| `context.history.requested` | `ContextHistoryRequestData` | Module → Context | 预留历史请求 |
| `context.history.resolved` | `ContextHistoryResultEventData` | Context → 请求方 | 预留历史结果 |
| `context.compaction.requested` | `CompactionRequestData` | Context 内部 | 内部压缩任务 |

## 6. 当前限制

`context.append.requested` 没有独立完成或失败事件，历史读取 Handler 尚未实现。`context.compaction.requested` 和 Context Store 都是内部接口，普通 Module 不应直接使用。

接入示例见 [Module 接入指南](integration-guide.md)。
