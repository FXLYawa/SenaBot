# Memory 公开 API

本文说明其他 Module 或组合根当前可以依赖的 Memory 契约。当前 `core.memory.__init__` 尚未提供统一导出，因此示例按对象所在子模块导入；外部调用方不应访问以下划线开头的方法或 LLM 解析细节。

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
    retriever=retriever,
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
| `retriever` | `MemoryRetrieverProtocol` | 根据向量和 Recall Context 返回候选 |
| `reranker` | `MemoryRerankerProtocol` | 对查询候选重新排序 |
| `materializer` | `MemoryMaterializerProtocol` | 把 Candidate 转为 typed Payload |
| `reviewer` | `MemoryReviewerProtocol` | 比较 Payload 与旧记忆并生成 ChangePlan |
| `executor` | `MemoryChangeExecutorProtocol` | 校验并执行 ChangePlan |

Query 和 Formation 复用 Embedder/Retriever。Reranker 目前只用于 Query；Formation 直接消费 Retriever 返回的相关记忆快照。

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

## 4. `MemoryService.query()`

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
| `user_id` | `str` | 当前相关用户 |
| `session_id` | `str` | 当前会话 |
| `group_id` | `str` | 当前群聊 |
| `query_text` | `str` | 用于 embedding 和 rerank 的查询文本 |

Service 会根据 user/session/group 构造三个 `MemoryScopeRef`，形成 `MemoryRecallContext`。Scope 是粗粒度长期主体边界，不表示当前信息适合公开披露。

### `MemoryQueryResult`

| 字段 | 类型 | 含义 |
|---|---|---|
| `query_id` | `str` | 原查询标识 |
| `user_id` | `str` | 原用户 ID |
| `session_id` | `str` | 原会话 ID |
| `group_id` | `str` | 原群聊 ID |
| `memories` | `list[MemoryItem]` | rerank 后的正式记忆 |

Service 不向调用方暴露 `MemoryRetrievalCandidate` 或 score。

## 5. 依赖协议

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

## 6. 失败行为与当前保证

- 模型和 ChangePlan 边界错误抛出 `ValueError`；
- LLM 非法 JSON 可抛出 `json.JSONDecodeError`；
- LLM、Retriever、Repository 的异常不在 Service 内吞掉；
- 当前没有稳定错误码体系；
- `operation_id` 当前是操作来源标识，不代表完整幂等；
- 多操作 ChangePlan 的事务边界由未来 Data 层定义；
- 当前没有具体 Repository 实现、自动重试或失败补偿。

领域约束详见[领域模型](domain-model.md)，完整装配示例见[接入指南](integration-guide.md)。
