# Data MVP 接入说明

Data 当前是 SenaBot MVP 的临时基础设施层，用于支撑首次运行的 Context 恢复/保存和 Memory 查询/写入。实现位于 `src/core/data`。

## 当前提供的能力

```text
DataModule
  订阅 context.restore.requested
  订阅 context.state.changed
  发布 context.restore.resolved

InMemoryDataStore
  保存 ContextSnapshot
  保存 MemoryItem

InMemoryMemoryRepository
  实现 MemoryRepositoryProtocol

InMemoryMemorySpaceRouter
  实现 MemorySpaceRouterProtocol
```

## 组合方式

```python
from core.data import (
    DataModule,
    InMemoryDataStore,
    InMemoryMemoryRepository,
    InMemoryMemorySpaceRouter,
)
from core.event import ModuleEventAPI


data_store = InMemoryDataStore()
DataModule(data_store).register(ModuleEventAPI(bus, "data"))

memory_repository = InMemoryMemoryRepository(data_store)
memory_spaces = InMemoryMemorySpaceRouter(data_store)
```

`memory_repository` 注入 `MemoryChangeExecutor`，`memory_spaces` 注入 `MemoryService`。

## 当前限制

- 数据只存在进程内，重启后丢失；
- 不写磁盘，不连接数据库或向量库；
- Memory Retriever 忽略 embedding，只做 Memory Space 和 Scope 粗筛；
- Context Summary 只增量保存，不删除被覆盖的旧 Entry；
- Memory supersede 只保存替代版本，不记录正式版本链；
- `operation_id` 不提供完整幂等。

这个模块的目标是让 MVP 链路先能跑起来。正式 Data 层重构时，应优先替换这些 in-memory Adapter，而不是让 Context 或 Memory 直接依赖数据库实现。
