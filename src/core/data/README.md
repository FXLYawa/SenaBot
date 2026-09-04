# Data 核心开发指南

本文面向维护 `core.data` 的开发者。当前 Data 层只为 SenaBot MVP 首次运行提供最小基础设施，后续正式 Data 层可以在保持协议的前提下替换实现。

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
  -> InMemoryMemoryRepository
  -> InMemoryDataStore

Memory
  -> MemorySpaceRouterProtocol
  -> InMemoryMemorySpaceRouter
  -> InMemoryMemoryRetriever
```

当前实现全部在进程内存中，不写磁盘，不提供事务，不提供跨进程恢复，也不提供真正的向量索引。

## 2. 文件职责

| 文件 | 职责 |
|---|---|
| `store.py` | 保存 Context 快照和 MemoryItem 的进程内 Store |
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

`InMemoryMemoryRepository` 实现 Memory 写入端口：

- `add()`：保存新增 MemoryItem；
- `end_fact_validity()`：更新 Fact 的 `valid_to`；
- `supersede()`：保存替代版本，并返回旧版本和新版本。

`InMemoryMemorySpaceRouter` 实现 Memory 查询端口：

```text
memory_space_id
  -> InMemoryMemoryRetriever
  -> Store 中同一 Memory Space 的 MemoryItem
  -> MemoryRecallContext.matches(item)
```

当前 Retriever 忽略 query embedding，只做 Memory Space 和 Scope 粗筛，适合 MVP 链路验证，不代表正式语义检索。

## 5. 当前限制

- 数据只存在进程内，程序重启后丢失；
- Context compaction 的增量事件只保存新 Summary，不删除被覆盖的旧 Entry；
- Memory supersede 只保存替代版本，不记录新旧版本关系；
- `operation_id` 不提供幂等或重试 ledger；
- 没有事务、锁、磁盘文件、数据库或向量库；
- 后续正式 Data 层应优先替换 `store.py` 和 `memory.py` 的实现，而不是修改 Context/Memory 领域逻辑。
