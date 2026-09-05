# Data 核心开发指南

本文面向维护 `core.data` 的开发者。Memory 已使用 SQLite 与 sqlite-vec；Context 暂时保留进程内实现。

## 1. 当前职责

Data 负责给其他模块提供持久化边界的 MVP 实现：

```text
Context
  -> context.state.changed
  -> DataModule
  -> InMemoryDataStore

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

Memory 支持事务、跨进程恢复和余弦相似度检索；Context 仍只保存在进程内。

## 2. 文件职责

| 文件 | 职责 |
|---|---|
| `database.py` | 管理 SQLite 连接、迁移、事务与 sqlite-vec 初始化 |
| `store.py` | 暂存 Context 快照的进程内 Store |
| `events.py` | 订阅 Context restore/state changed 事件 |
| `memory.py` | 实现 MemoryRepositoryProtocol 和 MemorySpaceRouterProtocol |
| `__init__.py` | Data 层公开导出 |

## 3. Context 链路

`DataModule` 订阅：

```text
context.restore.requested
context.state.changed
```

收到 `context.restore.requested` 时，Data 按 `session_id` 查找本地 Store：

- 找到快照：发布 `context.restore.resolved(completed, snapshot)`；
- 没找到：发布 `context.restore.resolved(not_found)`；
- 读取异常：发布 `context.restore.resolved(failed, error)`。

收到 `context.state.changed` 时，Data 根据增量事件维护一份可恢复的 `ContextSnapshot`。MVP 实现会保存新增 Entry 和新增 Summary，并按 sequence 排序。

## 4. Memory 链路

`SQLiteMemoryRepository` 实现 Memory 写入端口：

- `add()`：保存新增 MemoryItem、Scope、Provenance 和检索向量；
- `end_fact_validity()`：更新 Fact 的 `valid_to`；
- `supersede()`：原子保存替代版本和新旧版本关系。

`SQLiteMemorySpaceRouter` 实现 Memory 查询端口：

```text
memory_space_id
  -> SQLiteMemoryRetriever
  -> Memory Space / Scope / 当前有效版本过滤
  -> sqlite-vec 余弦相似度排序
```

## 5. 当前限制

- Context 数据只存在进程内，程序重启后丢失；
- Context compaction 的增量事件只保存新 Summary，不删除被覆盖的旧 Entry；
- `operation_id` 不提供幂等或重试 ledger；
- Retriever 当前对关系过滤后的候选计算精确距离，数据量增大后需要增加可预过滤的向量索引方案；
- Context 的 SQLite Repository 和恢复链路尚未实现。
