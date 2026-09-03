# Memory 公开 API

本文说明其他 Module 或组合根当前可以依赖的 Memory 契约。当前示例按对象所在子模块导入；外部调用方不应访问以下划线开头的方法、Converter 私有函数或 LLM 解析细节。

## 1. 入口与依赖

业务入口为 `MemoryService`：

```python
from core.memory.service import MemoryService
```

构造函数需要完整注入七项能力：

```python
MemoryService(
    extractor=extractor,
    embedder=embedder,
    memory_spaces=memory_spaces,
    reranker=reranker,
    materializer=materializer,
    reviewer=reviewer,
    executor=executor,
)
```

| 依赖 | 协议 | 职责 |
|---|---|---|
| `extractor` | `MemoryExtractorProtocol` | 从新消息提取候选 |
| `embedder` | `MemoryEmbeddingProtocol` | 把查询或 Candidate 文本转为向量 |
| `memory_spaces` | `MemorySpaceRouterProtocol` | 根据 `memory_space_id` 路由到对应 Retriever |
| `reranker` | `MemoryRerankerProtocol` | 对查询候选重新排序 |
| `materializer` | `MemoryMaterializerProtocol` | 把 Candidate 转为 typed Payload |
| `reviewer` | `MemoryReviewerProtocol` | 比较 Payload 与旧记忆并生成 ChangePlan |
| `executor` | `MemoryChangeExecutorProtocol` | 校验并执行 ChangePlan |

Query 和 Formation 复用 Embedder/Memory Space Router/Retriever。Reranker 目前只用于 Query；Formation 直接消费 Retriever 返回的相关记忆快照。

## 2. `MemoryService.extract()`

```python
async def extract(
    input_data: MemoryExtractionInput,
    *,
    summary: str | None,
    recent_messages: list[MemoryExtractionMessage],
) -> list[MemoryCandidate]:
    ...
```

### 输入结构

`MemoryExtractionMessage`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `message_id` | `str` | 消息唯一标识，用于候选引用来源 |
| `role` | `str` | 消息角色，例如 `user`、`assistant` |
| `content` | `str` | 消息正文 |

`MemoryExtractionInput`：

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `messages` | `list[MemoryExtractionMessage]` | 必填 | 本轮允许提取的新消息 |
| `provenance` | `tuple[Provenance, ...]` | 必填 | 可信的输入来源，不能为空 |

`summary` 和 `recent_messages` 由 Context 层提供。Memory 不负责生成或持久化它们。

### 返回值

返回零个或多个 `MemoryCandidate`：

```python
@dataclass
class MemoryCandidate:
    candidate_id: str
    content: str
    provenance: tuple[Provenance, ...]
    source_message_ids: tuple[str, ...]
```

`candidate_id` 只标识本次候选，不是正式记忆的 `item_id`。Candidate 没有 Scope 或领域类型，不能直接交给 Repository。

### 行为

`MemoryService` 把输入组装为 `MemoryExtractionContext` 后调用 Extractor。当前 `LLMMemoryExtractor` 要求 LLM 返回顶层 JSON object，其 `memories` 必须是 array。每个合法候选必须同时包含非空 `content` 和 `source_message_ids`；来源 ID 只能引用本轮 `new_messages`，不能引用 summary 或 recent messages。合法 content 会执行 `strip()`。

非法 JSON 的 `JSONDecodeError` 和结构错误的 `ValueError` 会向调用方传播。

## 3. `MemoryService.form()`

```python
async def form(
    input_data: MemoryFormationInput,
) -> MemoryChangeExecutionResult:
    ...
```

### `MemoryFormationInput`

| 字段 | 类型 | 含义 |
|---|---|---|
| `candidate` | `MemoryCandidate` | 待形成的候选记忆 |
| `recorded_at` | `datetime` | Memory 记录该信息的时间 |
| `recall_context` | `MemoryRecallContext` | 检索相关旧记忆时的长期主体集合 |
| `memory_space_id` | `str` | 新记忆的来源 Memory Space，不能为空 |
| `scopes` | `frozenset[MemoryScopeRef]` | 新记忆的长期主体归属，不能为空 |
| `operation_id` | `str` | 本次操作来源标识，不能为空 |

`recall_context.scopes` 与新记忆的 `scopes` 是两个概念：前者描述本轮允许检索哪些长期主体，后者描述新记忆自身属于哪些主体。调用方不应假设二者永远相等。

### 执行顺序

1. `embed(candidate.content)`；
2. `retrieve(embedding, context=recall_context)`；
3. 固定本轮 `related_items` 快照；
4. `materialize(candidate + related_items)`；
5. `review(payload + same related_items)`；
6. `execute(plan + same related_items + write context)`。

Materialization 从 `candidate.provenance` 构造正式 Payload 的来源字段，`MemoryFormationInput` 和 `MemoryMaterializationInput` 不再重复传递另一份 provenance。

### `MemoryChangeExecutionResult`

| 字段 | 类型 | 含义 |
|---|---|---|
| `added_items` | `tuple[MemoryItem, ...]` | 本轮新增或作为替代版本新增的正式记忆 |
| `updated_items` | `tuple[MemoryItem, ...]` | 本轮结束有效期或被替代后返回的旧版本 |

`NoMemoryChange` 返回两个空 tuple。Formation 的 Repository 调用是否原子、能否重试和如何恢复失败，当前没有统一保证。

## 4. `MemoryService.write()`

```python
async def write(
    request: MemoryWriteRequest,
) -> MemoryWriteResult:
    ...
```

`write()` 是公开写入入口，内部串联 Extraction 和 Formation。调用方提供消息、来源、时间和归属信息，Memory 自行判断是否形成长期记忆以及如何变更旧记忆。

### `MemoryWriteMessage`

| 字段 | 类型 | 含义 |
|---|---|---|
| `message_id` | `str` | 消息唯一标识 |
| `role` | `str` | 消息角色，例如 `user`、`assistant` |
| `content` | `str` | 消息正文 |

### `MemoryWriteRequest`

| 字段 | 类型 | 默认值 | 含义 |
|---|---|---|---|
| `operation_id` | `str` | 必填 | 本次写入操作标识 |
| `memory_space_id` | `str` | 必填 | 目标长期 Memory Space |
| `user_id` | `str` | 必填 | 当前相关用户 |
| `session_id` | `str` | 必填 | 当前会话 |
| `group_id` | `str` | 必填 | 当前群聊；私聊可传空字符串 |
| `messages` | `tuple[MemoryWriteMessage, ...]` | 必填 | 本轮允许作为新记忆来源的消息 |
| `recent_messages` | `tuple[MemoryWriteMessage, ...]` | `()` | 只供 Extraction 辅助理解的近期消息 |
| `summary` | `str | None` | `None` | 只供 Extraction 辅助理解的摘要 |
| `source_event_id` | `str` | `""` | 上游事件或 Context Entry 来源 |
| `recorded_at` | `datetime | None` | `None` | 记录时间；为空时由 Service 使用当前 UTC 时间 |

`messages` 不能为空。`summary` 和 `recent_messages` 不会被当作本轮新记忆来源。

### 执行顺序

1. `MemoryWriteRequest` 通过 `converters.py` 转为 `MemoryExtractionInput`；
2. `extract()` 产出零个或多个 `MemoryCandidate`；
3. Service 构造 Recall Context 和新记忆 Scopes；
4. 每个 Candidate 单独进入 `form()`；
5. 多个 `MemoryChangeExecutionResult` 聚合成 `MemoryWriteResult`。

### `MemoryWriteResult`

| 字段 | 类型 | 含义 |
|---|---|---|
| `operation_id` | `str` | 原写入操作标识 |
| `memory_space_id` | `str` | 原 Memory Space |
| `added_item_ids` | `tuple[str, ...]` | 本轮新增的正式 MemoryItem ID |
| `updated_item_ids` | `tuple[str, ...]` | 本轮更新的正式 MemoryItem ID |

返回空 ID tuple 是正常结果，表示没有新增或更新正式记忆。

## 5. `MemoryService.query()`

```python
async def query(
    request: MemoryQueryRequest,
) -> MemoryQueryResult:
    ...
```

### `MemoryQueryRequest`

| 字段 | 类型 | 含义 |
|---|---|---|
| `query_id` | `str` | 本次查询标识 |
| `memory_space_id` | `str` | 要查询的长期 Memory Space，不能为空 |
| `user_id` | `str` | 当前相关用户 |
| `session_id` | `str` | 当前会话 |
| `group_id` | `str` | 当前群聊 |
| `query_text` | `str` | 用于 embedding 和 rerank 的查询文本 |

Service 会先用 `memory_space_id` 路由到对应 Retriever，再根据 user/session/group 构造 `MemoryRecallContext`。Scope 是粗粒度长期主体边界，不表示当前信息适合公开披露。

### `MemoryQueryResult`

| 字段 | 类型 | 含义 |
|---|---|---|
| `query_id` | `str` | 原查询标识 |
| `memory_space_id` | `str` | 原 Memory Space |
| `user_id` | `str` | 原用户 ID |
| `session_id` | `str` | 原会话 ID |
| `group_id` | `str` | 原群聊 ID |
| `memories` | `list[MemoryItem]` | rerank 后的正式记忆 |

Service 不向调用方暴露 `MemoryRetrievalCandidate` 或 score。

## 6. Event Payload

组合根安装 `MemoryModule` 后，可以通过 EventBus 使用 Memory：

| 事件 | Payload | 含义 |
|---|---|---|
| `memory.query.requested` | `MemoryQueryRequest` | 请求召回相关长期记忆 |
| `memory.query.completed` | `MemoryQueryResult` | 查询完成 |
| `memory.query.failed` | `MemoryQueryFailedEventData` | 查询失败 |
| `memory.write.requested` | `MemoryWriteRequest` | 请求执行一次完整写入流程 |
| `memory.write.completed` | `MemoryWriteResult` | 写入流程完成 |
| `memory.write.failed` | `MemoryWriteFailedEventData` | 写入失败 |

失败事件携带：

```python
@dataclass(frozen=True)
class MemoryErrorInfo:
    code: str
    message: str
```

当前 `code` 使用异常类型名，`message` 用于诊断。稳定业务错误码体系尚未定义。

## 7. 依赖协议

### 检索协议

```python
class MemoryEmbeddingProtocol(Protocol):
    async def embed(self, query: str) -> list[float]: ...

class MemoryRetrieverProtocol(Protocol):
    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]: ...

class MemoryRerankerProtocol(Protocol):
    async def rerank(
        self,
        query: str,
        candidates: list[MemoryRetrievalCandidate],
    ) -> list[MemoryRetrievalCandidate]: ...
```

```python
class MemorySpaceRouterProtocol(Protocol):
    def for_space(
        self,
        memory_space_id: str,
    ) -> MemoryRetrieverProtocol: ...
```

### Formation 协议

```python
class MemoryMaterializerProtocol(Protocol):
    async def materialize(
        self,
        input_data: MemoryMaterializationInput,
    ) -> MemoryPayload: ...

class MemoryReviewerProtocol(Protocol):
    async def review(
        self,
        input_data: MemoryReviewInput,
    ) -> MemoryChangePlan: ...

class MemoryChangeExecutorProtocol(Protocol):
    async def execute(
        self,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryChangeExecutionResult: ...
```

### 持久化协议

```python
class MemoryRepositoryProtocol(Protocol):
    async def add(self, envelope: MemoryWriteEnvelope) -> MemoryItem: ...

    async def end_fact_validity(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        valid_to: datetime,
    ) -> MemoryItem: ...

    async def supersede(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        replacement: MemoryWriteEnvelope,
    ) -> MemorySupersedeResult: ...
```

Repository 只负责变更持久化。Recall 由 Retriever 完成，不应重新向 Repository 添加旧式 `query_text/user_id/session_id/group_id` 查询接口。

## 8. 失败行为与当前保证

- 模型和 ChangePlan 边界错误抛出 `ValueError`；
- LLM 非法 JSON 可抛出 `json.JSONDecodeError`；
- LLM、Retriever、Repository 的异常不在 Service 内吞掉；
- Event Handler 会把 Service 异常转换为 `memory.*.failed`；
- 当前没有稳定业务错误码体系；
- `operation_id` 当前是操作来源标识，不代表完整幂等；
- 多操作 ChangePlan 的事务边界由未来 Data 层定义；
- 当前没有具体 Repository 实现、自动重试或失败补偿。

领域约束详见[领域模型](domain-model.md)，完整装配示例见[接入指南](integration-guide.md)。
