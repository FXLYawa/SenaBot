# Memory 模块

Memory 模块负责提取、形成和召回长期记忆。领域数据统一使用
`MemoryItem`，具体内容由 `Fact`、`Experience`、`Understanding`
和 `Knowledge` 四类 Payload 表达。

## 主要链路

### 候选提取

```text
new messages + summary + recent messages
        ↓
MemoryService.extract()
        ↓
MemoryCandidate[]
```

Extraction 只从新消息提取候选；摘要和最近消息仅用于辅助理解。

### 记忆形成

```text
MemoryCandidate
        ↓
embedding → retrieve related MemoryItem
        ↓
materialize MemoryPayload
        ↓
review MemoryChangePlan
        ↓
execute ADD / END_VALIDITY / SUPERSEDE / NONE
        ↓
MemoryRepositoryProtocol
```

同一批 `related_items` 会贯穿 Materialization、Review 和 Execution，
避免一次 Formation 内使用不一致的旧记忆快照。

### 记忆召回

```text
MemoryQueryRequest
        ↓
embedding
        ↓
retrieval with MemoryRecallContext
        ↓
rerank
        ↓
MemoryQueryResult[list[MemoryItem]]
```

`MemoryScopeRef` 表示长期主体归属，不是未来使用场景的发布白名单。
GLOBAL 记忆始终进入粗候选；其他记忆通过 Scope 交集进入候选。

## 持久化边界

当前只定义 `MemoryRepositoryProtocol`，不提供具体 Data 层实现。
接口包括：

- `add()`：新增正式 `MemoryItem`
- `end_fact_validity()`：结束旧 Fact 的有效期
- `supersede()`：用新 Understanding 或 Knowledge 替代旧版本

数据库结构、事务、失败恢复和完整幂等语义由后续 Data 层 Issue 处理。
当前 `operation_id` 仅作为操作来源标识，不代表完整幂等保证。

## 占位实现

`SimpleMemoryEmbedder`、`SimpleMemoryRetriever` 和
`SimpleMemoryReranker` 只用于 MVP 编排及本地测试：

- Simple Embedder 生成占位向量；
- Simple Retriever 在内存快照上执行 Scope 过滤，不计算语义相关性；
- Simple Reranker 按已有 score 排序。

这些实现不代表正式 Data 层或模型能力。

## 测试

```bash
pytest tests/memory -q
```

当前测试覆盖领域模型、Extraction、Recall、Materialization、Review、
ChangePlan、Executor 和完整 Formation 编排。
