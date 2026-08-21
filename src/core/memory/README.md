# Memory 模块

Memory 模块负责记忆的写入、查询与持久化管理，为其他模块提供统一的记忆访问能力。

## 当前功能

- 支持基础记忆写入
- 支持按用户、会话、群组和文本查询记忆
- 支持 User、Session、Group 维度的数据隔离
- 支持 `source_event_id` 去重
- 支持 `operation_id` 写入幂等
- 支持持久化失败的统一异常处理

## 目录结构

```text
memory/
├── __init__.py
├── contracts.py
├── errors.py
├── models.py
├── protocols.py
├── repository.py
├── service.py
└── README.md
```

各文件职责：

- `contracts.py`：定义其他模块与 Memory 模块之间的输入、输出契约
- `models.py`：定义 Memory 模块内部使用的数据结构
- `protocols.py`：声明 Repository 必须提供的能力
- `repository.py`：实现记忆查询与持久化
- `service.py`：实现记忆查询、写入和幂等处理流程
- `errors.py`：定义 Memory 模块异常

## 查询流程

```text
MemoryQueryRequest
        ↓
MemoryService.query()
        ↓
MemoryQueryCriteria
        ↓
MemoryRepositoryProtocol.query()
        ↓
MemoryQueryResult
```

查询条件包括：

- `user_id`
- `session_id`
- `group_id`
- `query_text`

不同用户、会话和群组之间的记忆互相隔离。

## 写入流程

```text
MemoryWriteRequest
        ↓
检查 operation_id
        ↓
检查 source_event_id
        ↓
创建 Memory
        ↓
MemoryRepositoryProtocol.save()
        ↓
MemoryWriteResult
```

### operation_id

`operation_id` 是一次 Memory 写入操作的唯一标识。

普通 `write()` 流程中，相同 `operation_id` 被重复提交时，不会重复写入，
而是返回第一次创建的 `memory_id`。

候选审查与更新流程 `review_and_update()` 在当前 MVP 中不提供重试幂等保证。
该流程中的 `operation_id` 仅作为操作来源标识。ADD、UPDATE、DELETE 的完整幂等语义，
需要后续通过独立操作记录及正式 Data 层事务边界实现。

### source_event_id

`source_event_id` 表示触发记忆写入的来源事件。

相同来源事件被重复处理时，不会创建重复记忆。

### memory_id

`memory_id` 是最终生成的记忆自身的唯一标识，由 Memory 模块生成。

## 持久化

当前版本使用 JSON 文件作为临时持久化方式。

Memory 层内部的时间字段使用 `datetime`。写入 JSON 时转换为 ISO 格式字符串，读取时再转换回 `datetime`。

后续接入 Data 层时，可以替换 `FileMemoryRepository`，而不需要修改 `MemoryService`。

## 异常处理

文件读取失败、JSON 数据损坏或文件写入失败时，Repository 会抛出：

```python
MemoryPersistenceError
```

Memory 模块不会直接向上暴露 `OSError` 或 `JSONDecodeError` 等底层异常。

## 测试

运行测试：

```bash
pytest tests/memory/test_service.py -v
```

当前测试覆盖：

- 基础记忆写入和查询
- User、Session、Group 隔离
- `source_event_id` 去重
- `operation_id` 幂等
- 持久化失败处理

## 当前限制

- 暂未实现记忆遗忘
- 暂未接入正式 Data 层
- 当前文本查询仅使用字符串包含匹配
- 暂未完成 Event 接入
