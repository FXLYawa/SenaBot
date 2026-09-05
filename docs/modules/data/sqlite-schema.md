# SQLite + sqlite-vec 第一版存储设计

对应 Issue #63。本轮包含 Context 历史与恢复、Memory 正式记忆及向量存储。
数据库实现基于 develop，不依赖尚未合并的 PR #64 组合根。

## 当前实现进度

已实现 `core.data.database.SQLiteDatabase`、初始 SQL 迁移以及真实数据库测试。
本阶段只交付建表、连接、事务和扩展加载基础。现有 `DataModule`、Memory Repository
仍使用内存实现；数据库序列化、业务读写、冷恢复、范围过滤及检索适配是后续步骤。
因此基础设施测试通过不等于 Context/Memory 已完成持久化。

## 初始化与生命周期

```python
from core.data.database import SQLiteDatabase

with SQLiteDatabase("sena.db") as database:
    with database.transaction() as connection:
        # 在这里执行属于同一次存储操作的 SQL。
        pass

    # 确认实际 Embedding 模型后传入维度；3 仅为测试示例。
    database.initialize_vectors(3)
```

- 每个实例持有一个同线程连接；调用方负责关闭。现阶段按同步调用使用，不能跨线程共享。
- 每个连接启用外键，并加载 sqlite-vec；加载完成后关闭扩展加载入口。
- `transaction()` 使用显式事务；异常回滚，成功提交。不支持嵌套。
- 普通表使用 SQLite `PRAGMA user_version` 管理迁移。它仅表示数据库结构版本，
  不属于此前暂缓的 Memory 内容版本或 Context 状态序号。
- 初次建表在一个事务中完成；重开不会重建表；未知的更高结构版本报错。
- sqlite-vec 固定为已在 Windows / Python 3.12 验证的 0.1.9。
- 未提供维度时只建普通表，不创建 `memory_vectors`。
- `initialize_vectors(dimensions)` 创建固定维度、余弦距离的向量表。
  同维度可重复调用；不匹配时明确报错，不删除或重建旧数据。

## Context

| 表 | 字段 |
| --- | --- |
| `context_sessions` | `session_id`, `purpose`, `platform`, `account_namespace`, `scene_type`, `scene_id`, `work_id`, `created_at`, `updated_at`, `closed_at`, `latest_sequence` |
| `context_entries` | `entry_id`, `session_id`, `sequence`, `entry_type`, `actor_type`, `actor_id`, `actor_display_name`, `content_json`, `source_event_id`, `created_at` |
| `context_summaries` | `summary_id`, `session_id`, `level`, `first_sequence`, `last_sequence`, `text`, `created_at` |
| `context_summary_sources` | `parent_summary_id`, `child_summary_id`, `position` |

### 身份与序号

- Session ID 沿用 Context 的确定性生成规则，不由数据库生成。
- 普通会话：purpose 为 conversation，四个来源字段非空，work_id 为空。
- Work Session：purpose 非 conversation，work_id 非空，四个来源字段为空。
- 普通会话来源组合唯一；Work 的 `(purpose, work_id)` 唯一。
- Entry 的 `(session_id, sequence)` 唯一，sequence 从 1 开始。
- latest_sequence 从 0 开始，只表达消息序号，不用于排序全部状态事件。
- source_event_id 可空且不唯一，一个事件可以产生多条条目。
- `Content` 的类型、文本和 segments 一起保存在 content_json，不能仅保存 text。

### 摘要与历史

- 原始条目和旧摘要不因压缩删除。
- 每层摘要都使用原始消息序号表示覆盖范围，不对范围做唯一约束。
- 一级摘要无子摘要；更高层摘要通过 sources 表保存有序的直接子摘要。
- 活动摘要为未被更高层摘要引用的节点；活动条目不包含这些摘要覆盖的历史。
- 同一父摘要的子节点和 position 分别唯一，parent 不能等于 child。
- 新摘要和其来源关系在同一事务中保存。
- Repository 必须额外校验同 Session、父子层级相差 1、position 连续、子节点范围
  连续且并集等于父范围。这些跨行领域规则未由当前基础 DDL 完整实现。
- 同 ID 相同内容重放可复用；同 ID 不同内容或同序号不同条目应报冲突，不能 REPLACE。
- 时间由存储适配层规范化为固定精度 UTC 文本，例如 `2026-09-05T00:00:00.000000Z`。

## Memory

| 表 | 字段 |
| --- | --- |
| `memory_items` | `item_id`, `memory_space_id`, `domain`, `payload_json`, `recorded_at`, `valid_from`, `valid_to` |
| `memory_scopes` | `item_id`, `scope_kind`, `scope_id` |
| `memory_provenances` | `item_id`, `position`, `source_type`, `source_id` |
| `memory_replacements` | `previous_item_id`, `replacement_item_id`, `operation_id` |
| `memory_embeddings` | `embedding_id`, `item_id`, `model`, `dimensions`, `created_at` |
| `memory_vectors`（vec0） | `embedding_id`, `embedding` |

### 主体、来源、归属

- 四种 domain 共用主表，差异字段存入 payload_json。
- Provenance **只保存到 memory_provenances**，不在 payload_json 再保存一份。
  读取时按 position 重建 tuple 并组装回 Fact/Experience/Understanding/Knowledge。
- participants、evidence_item_ids 等已有领域字段保留在对应 JSON 内。
- domain、recorded_at、Fact 有效期与 payload 对应值由 Repository 统一序列化并校验。
- 正文替代产生新 item_id，本轮不加入 content_version 或 text_hash。
- 每条记忆至少一个 Scope 和一个 Provenance，由 Repository 在完整写入时校验。
- global 的 scope_id 必须为 NULL；其他 Scope 的 scope_id 必须非空白。
- 分别为 global 和其他 Scope 建部分唯一索引，避免 NULL 导致 global 重复。
- global 不能与其他 Scope 共存，此跨行规则由 Repository 校验。
- Scope 只做同一 Memory Space 内的召回粗筛，不等于当前场景的披露权限。
- 来源类型是开放字符串；source_id 不能统一外键到 Context Entry。
- 删除记忆时，Scope 与 Provenance 级联删除。

### 替代关系

- previous_item_id 唯一，禁止自身替代；operation_id 仅作追溯，不是整次请求去重记录。
- Repository 校验新旧记忆处于同空间、同 domain，且只允许 Understanding/Knowledge。
- 新记忆、Scope、Provenance 和替代关系一起提交，避免半份替代。
- 旧记录保留。默认当前记忆检索排除被替代项，历史查询可显式包含。
- Fact 通过有效期处理变化，不使用此表替代。
- 替代关系外键默认限制删除；需要删除被关联的记忆时，由业务接口明确清理关系，
  不通过级联悄悄截断历史。

### 向量

- 一条记忆一份当前向量，metadata.item_id 唯一。
- metadata.embedding_id 与 vec0 的同名整数主键对应；不假设虚拟表支持普通外键级联。
- Embedding 在数据库事务外生成，成功后 metadata 与 vector 同事务写入。
- 生成失败保留正文，本阶段不实现后台重试编排。
- 删除有向量的记忆时，Repository 先显式删除向量与元数据，再删除正文，整个过程同事务。
- 模型、维度必须匹配配置；相同维度的不同模型也不能混用，Repository 接入时校验。
- 检索前必须确定空间、Scope、替代与有效期条件。不能先全库取 Top-K 再过滤。
  具体 SQL 在检索实现阶段对固定 sqlite-vec 版本验证。
- 模型与真实维度尚待配置确认，不将测试维度当作产品默认值。

## 后续与明确不包含

下一步先实现 Context 的序列化与 Repository，接入 Data 状态保存、冷恢复和摘要展开。
然后实现 Memory Repository 与向量检索，最后对接应用生命周期。

以下可靠性工作已后置，不阻塞本轮正常路径：

- [#69 Memory 写入重试去重与部分失败恢复](https://github.com/FXLYawa/SenaBot/issues/69)
- [#70 Context 状态事件重复与乱序持久化](https://github.com/FXLYawa/SenaBot/issues/70)

不创建操作去重表、状态变更缓冲表，也不增加 state_revision/applied_revision。
常规外键、唯一约束和单次存储操作事务仍属于本轮基础实现。
