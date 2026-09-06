# Data 核心开发指南

本文面向维护 `core.data` 的开发者。Memory 与 Context 均使用 SQLite，Memory 向量由 sqlite-vec 保存和检索。

## 1. 当前职责

Data 负责给其他模块提供持久化边界的 MVP 实现：

```text
Context
  -> context.state.changed
  -> DataModule
  -> SQLiteContextRepository
  -> SQLite

Context
  -> context.restore.requested
  -> DataModule
  -> context.restore.resolved

Memory
  -> MemoryRepositoryProtocol
  -> SQLiteMemoryRepository
  -> SQLite + sqlite-vec

Memory
  -> MemorySpaceRouterProtocol
  -> SQLiteMemorySpaceRouter
  -> SQLiteMemoryRetriever
```

Memory 支持事务、跨进程恢复和余弦相似度检索；Context 保存完整历史，并在恢复时重建当前活动窗口。

## 2. 文件职责

| 文件 | 职责 |
|---|---|
| `database.py` | 管理 SQLite 连接、迁移、事务与 sqlite-vec 初始化 |
| `context.py` | 实现 Context Repository、结构化正文序列化和活动窗口恢复 |
| `store.py` | Context Repository 的进程内测试实现 |
| `events.py` | 订阅 Context restore/state changed 事件 |
| `memory.py` | 实现 MemoryRepositoryProtocol 和 MemorySpaceRouterProtocol |
| `serialization.py` | 统一各 Repository 的 UTC 时间序列化规则 |
| `__init__.py` | Data 层公开导出 |

## 3. Context 链路

`DataModule` 订阅：

```text
context.restore.requested
context.state.changed
```

收到 `context.restore.requested` 时，Data 按 `session_id` 查询 SQLite：

- 找到快照：发布 `context.restore.resolved(completed, snapshot)`；
- 没找到：发布 `context.restore.resolved(not_found)`；
- 读取异常：发布 `context.restore.resolved(failed, error)`。

收到 `context.state.changed` 时，Data 在一个事务中保存 Session、新增 Entry、新增 Summary 及其有序来源关系。数据库保留完整历史；恢复活动快照时，会排除已经被一级摘要覆盖的 Entry，以及已经被高层摘要覆盖的子 Summary。

## 4. Memory 链路

`SQLiteMemoryRepository` 实现 Memory 写入端口：

- `add()`：保存新增 MemoryItem、Scope、Provenance 和检索向量；
- `end_fact_validity()`：更新 Fact 的 `valid_to`；
- `supersede()`：原子保存替代版本和新旧版本关系。

Memory 负责选择索引文本并生成向量，Repository 接收包含 Item 与向量的 `MemoryWriteEnvelope`，只处理持久化。

`SQLiteMemorySpaceRouter` 实现 Memory 查询端口：

```text
memory_space_id
  -> SQLiteMemoryRetriever
  -> Memory Space / Scope / 当前有效版本过滤
  -> sqlite-vec 余弦相似度排序
```

## 5. 当前限制

- Context 压缩保留被覆盖的 Entry 和 Summary，历史逐层读取接口仍待接入这些完整记录；
- `operation_id` 不提供幂等或重试 ledger；
- Retriever 当前对关系过滤后的候选计算精确距离，数据量增大后需要增加可预过滤的向量索引方案；
