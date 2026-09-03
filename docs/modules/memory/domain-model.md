# Memory 领域模型

本文说明 Memory 的核心术语、数据结构和生命周期约束。字段定义以 `core.memory.models`、`change_plan` 和 `executor` 为准。

## 1. 模型层次

```text
MemoryCandidate        尚未形成的自然语言候选
        ↓ Materialization
MemoryPayload          受领域约束的内容,即Memory的类型
        ↓ Execution
MemoryItem             具有 ID、来源空间和主体归属的正式记忆
        ↓ Write Boundary
MemoryWriteEnvelope    正式记忆 + 本次 operation_id
```

这四层不能互换：Candidate 不能直接入库，Payload 不具有正式实体身份，MemoryItem 不携带一次操作的全部上下文，Envelope 也不是长期领域内容。

公开写入入口位于另一条边界：

```text
MemoryWriteRequest     跨模块写入请求
        ↓ MemoryService.write()
MemoryExtractionInput
        ↓ Extraction
MemoryCandidate
        ↓ Formation
MemoryChangeExecutionResult
        ↓ converters.to_write_result()
MemoryWriteResult      跨模块写入结果
```

`MemoryWriteRequest` 不是 Candidate，也不是 Formation Input。它只描述上游能确定的消息、来源、Memory Space 和当前交互身份。

## 2. `MemoryCandidate`

```python
@dataclass
class MemoryCandidate:
    candidate_id: str
    content: str
    provenance: tuple[Provenance, ...]
    source_message_ids: tuple[str, ...]
```

Candidate 表示“可能值得形成长期记忆”的文本。它尚未完成：

- 领域分类；
- 记录时间补齐；
- Scope 归属；
- 相关旧记忆比较；
- 冲突、重复和生命周期判断；
- 正式 `item_id` 分配。

`candidate_id` 是候选阶段标识，`source_message_ids` 列出直接支持该候选的本轮新消息。`MemoryCandidate` 自身会校验 candidate ID、content、provenance 和来源消息 ID 非空，并拒绝重复的来源消息 ID。Extractor 还会进一步校验这些 ID 只引用 `new_messages`。

## 3. `MemoryItem`

```python
@dataclass
class MemoryItem:
    item_id: str
    memory_space_id: str
    scopes: frozenset[MemoryScopeRef]
    payload: MemoryPayload
```

`MemoryItem` 是正式记忆实体，也是 Recall 和 Repository 边界使用的统一结构。

| 字段 | 含义 |
|---|---|
| `item_id` | 正式记忆唯一标识 |
| `memory_space_id` | 这条记忆所属的长期 Memory Space |
| `scopes` | 记忆关于哪些长期主体 |
| `payload` | 具体领域内容 |

`domain` 属性由 `payload.DOMAIN` 推导，调用方不需要额外保存一份可能不一致的 domain 字段。

当前约束：

- scopes 不能为空；
- GLOBAL 不能与其他 Scope 同时存在；
- `item_id` 和 `memory_space_id` 当前没有在 `MemoryItem.__post_init__` 中执行非空校验，调用边界仍应提供有效值。

## 4. Scope

```python
class MemoryScopeKind(str, Enum):
    GLOBAL = "global"
    USER = "user"
    GROUP = "group"
    SESSION = "session"
```

Scope 表达长期主体归属：

| Scope | 含义 | 示例 |
|---|---|---|
| `USER(A)` | 关于用户 A 或 Sena 与 A 的长期认知 | “A 最近开始玩 FF14” |
| `GROUP(G)` | 群 G 的共同长期语境 | “这个群约定周五固定开黑” |
| `SESSION(S)` | 极少数只归属于某段交互的长期内容 | 特定会话约定 |
| `GLOBAL` | 整个 Memory Space 可考虑的长期信息 | Sena 的通用知识 |

Scope 不表达：

- 只能在哪个聊天窗口使用；
- 是否允许向当前参与者披露；
- Agent 是否应该发言；
- 信息是否敏感。

`MemoryScopeRef` 约束：GLOBAL 的 `scope_id` 必须为 `None`；其他类型的 `scope_id` 必须是非空字符串。

粗粒度 Recall 规则为：GLOBAL Item 始终可进入候选；其他 Item 至少有一个 Scope 与 `MemoryRecallContext.scopes` 相交。语义相关性、敏感度和表达适宜性应在后续阶段处理。

Memory Space 与 Scope 不同。`memory_space_id` 先把查询或写入路由到一片长期记忆空间；Scope 再描述该空间内 MemoryItem 关于哪些长期主体。

## 5. Provenance 与时间

```python
@dataclass(frozen=True)
class Provenance:
    source_type: str
    source_id: str
```

Provenance 描述信息来源，例如 Event、消息或导入数据。`source_type` 和 `source_id` 都不能为空。Extraction Input 接收可信 provenance，Extractor 将它贯穿到 Candidate，Materializer 再从 Candidate 贯穿到正式 Payload；这三层都要求至少一个 Provenance。

`recorded_at` 表示 Memory 记录信息的时间，不必等于事实开始时间或经历发生时间：

- Fact 使用 `valid_from` / `valid_to` 表达有效期；
- Experience 使用 `occurred_from` / `occurred_to` 表达发生区间；
- Understanding 和 Knowledge 保留形成时的 `recorded_at`。

## 6. 四类 Payload

### `Fact`

客观、可判断真假的长期事实，不包含专业知识或 Sena 的主观推断。

```python
Fact(
    content="用户居住在上海",
    provenance=(...),
    recorded_at=...,
    valid_from=...,
    valid_to=None,
)
```

`valid_from` 和 `valid_to` 都可为空；二者同时存在时，结束时间不能早于开始时间。

### `Experience`

Sena、用户或其他参与者共同经历过的事件。

```python
Experience(
    summary="用户参加了第一次马拉松",
    provenance=(...),
    participants=(Entity("user", "user-001"),),
    occurred_from=...,
    occurred_to=...,
    recorded_at=...,
)
```

经历一旦发生，不会因为后续信息而失效或被改写为另一个版本；可以新增独立 Experience，或者判断本次无需变更。

### `Understanding`

Sena 根据证据逐步形成的长期理解，不应伪装成用户明确确认的客观 Fact。

```python
Understanding(
    content="用户在深度工作时偏好独处",
    provenance=(...),
    evidence_item_ids=("item-001",),
    recorded_at=...,
)
```

`evidence_item_ids` 不能为空。LLM Materializer 只能引用本轮 `related_items` 中存在的 Item ID，不能生成未知证据 ID。

### `Knowledge`

Sena 可以跨场景复用的专业或通用知识。

```python
Knowledge(
    content="规律运动有助于改善心肺能力",
    provenance=(...),
    recorded_at=...,
)
```

Knowledge 可以被更准确的新版本替代，但不使用 Fact 的有效期语义。

## 7. 生命周期与变更操作

| Payload | Add | EndFactValidity | Supersede | NoChange |
|---|---:|---:|---:|---:|
| Fact | ✓ | ✓ | ✗ | ✓ |
| Experience | ✓ | ✗ | ✗ | ✓ |
| Understanding | ✓ | ✗ | ✓ | ✓ |
| Knowledge | ✓ | ✗ | ✓ | ✓ |

### `AddMemoryItem`

候选包含一条需要独立保存的新记忆。Executor 为 Payload 生成 `item_id`，补齐 `memory_space_id` 和 scopes，再包装成 `MemoryWriteEnvelope` 调用 Repository。

### `EndFactValidity`

旧 Fact 过去成立，但从 `valid_to` 开始不再成立。它不删除历史记录，通常与一个新 Fact 的 Add 同时出现：

```text
旧：用户居住在北京，valid_to = 搬家时间
新：用户居住在上海，valid_from = 搬家时间
```

目标必须是本轮 related items 中的 Fact，`valid_to` 不能早于旧 Fact 的 `valid_from`。

### `SupersedeMemoryItem`

新的 Understanding 或 Knowledge 替代旧版本，同时保留旧版本痕迹。Replacement 必须与目标具有完全相同的 Payload 类型。

Repository 返回：

```python
MemorySupersedeResult(
    previous_item=old_item,
    replacement_item=new_item,
)
```

旧版本和新版本如何建立持久化关系，由未来 Data 层模型定义。

### `NoMemoryChange`

候选已被现有记忆覆盖，或者不值得形成正式记忆。NoChange 必须是计划中的唯一操作，不得与其他操作组合。

## 8. ChangePlan 不变量

`MemoryChangePlan` 至少包含一个操作。Plan 创建时会先校验只依赖自身的结构不变量：

- 同一个 Plan 不能 Add 两次；
- 同一个 Plan 不能 Supersede 两次；
- Add 和 Supersede 不能同时出现；
- NoChange 不能和其他操作共存；
- 同一个 target 不能被操作两次。

执行前还会通过 `MemoryChangePlan.validate_against(related_items)` 校验引用的旧记忆：

- End/Supersede 的 target 必须来自同一份 `related_items`；
- End 只能指向 Fact；
- Supersede 只能指向 Understanding 或 Knowledge；
- Supersede replacement 与 target 必须属于同一领域类型；

Reviewer 另外负责依赖当前 Payload 的约束：Fact 只能 Add、EndFactValidity 或 NoChange；Experience 只能 Add 或 NoChange；Understanding 和 Knowledge 才允许 Supersede。

## 9. Write Envelope 与 operation ID

```python
MemoryWriteEnvelope(
    operation_id="operation-001",
    item=MemoryItem(...),
)
```

Envelope 表达“一次操作准备写入哪条正式记忆”。`operation_id` 不放进 Payload，也不改变 MemoryItem 的领域内容。

当前 `operation_id` 只是操作来源标识。没有 operation ledger、事务和失败恢复时，不能宣称 Add、End 或 Supersede 具备完整重试幂等性。
