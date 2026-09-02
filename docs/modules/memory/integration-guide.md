# Module 接入 Memory 指南

本指南说明如何在组合根中装配 Memory，并分别调用 Extraction、Formation 和 Recall。字段和方法行为见[公开 API](public-api.md)，领域语义见[领域模型](domain-model.md)。

## 1. 依赖准备

MemoryService 只负责编排，不自行创建 LLM、Retriever 或 Repository。组合根需要提供：

```text
Extractor
Embedder
Retriever
Reranker
Materializer
Reviewer
Executor
    └── Repository Protocol implementation
```

当前代码提供：

- `LLMMemoryExtractor`
- `LLMMemoryMaterializer`
- `LLMMemoryReviewer`
- `MemoryChangeExecutor`
- `SimpleMemoryEmbedder`
- `SimpleMemoryRetriever`
- `SimpleMemoryReranker`

其中三个 Simple 实现只适用于测试或 MVP 验证；项目当前没有正式 Repository Adapter。

## 2. 实现持久化端口

Data 层 Adapter 需要实现 `MemoryRepositoryProtocol`：

```python
from datetime import datetime

from core.memory.models import (
    MemoryItem,
    MemorySupersedeResult,
    MemoryWriteEnvelope,
)


class DataMemoryRepository:
    async def add(
        self,
        envelope: MemoryWriteEnvelope,
    ) -> MemoryItem:
        ...

    async def end_fact_validity(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        valid_to: datetime,
    ) -> MemoryItem:
        ...

    async def supersede(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        replacement: MemoryWriteEnvelope,
    ) -> MemorySupersedeResult:
        ...
```

Adapter 应返回持久化后的领域对象。不要在 Memory Service 中加入数据库字段、ORM Model 或文件格式转换。

多操作 Plan 的事务、operation ledger、失败恢复和幂等语义尚未规定；实现正式 Adapter 前需要单独确定这些边界。

## 3. 组合根装配

```python
from core.memory.embedding import SimpleMemoryEmbedder
from core.memory.executor import MemoryChangeExecutor
from core.memory.extractor import LLMMemoryExtractor
from core.memory.materialization import LLMMemoryMaterializer
from core.memory.reranker import SimpleMemoryReranker
from core.memory.retriever import SimpleMemoryRetriever
from core.memory.reviewer import LLMMemoryReviewer
from core.memory.service import MemoryService


extractor = LLMMemoryExtractor(llm)
materializer = LLMMemoryMaterializer(llm)
reviewer = LLMMemoryReviewer(llm)

embedder = SimpleMemoryEmbedder()
retriever = SimpleMemoryRetriever(initial_items)
reranker = SimpleMemoryReranker()

executor = MemoryChangeExecutor(repository)

memory = MemoryService(
    extractor=extractor,
    embedder=embedder,
    retriever=retriever,
    reranker=reranker,
    materializer=materializer,
    reviewer=reviewer,
    executor=executor,
)
```

`SimpleMemoryRetriever` 在构造时复制一份 `initial_items` 快照，Repository 后续新增数据不会自动进入它。正式运行需要注入连接真实 Data/Vector 层的 Retriever。

## 4. 调用 Extraction

Context 层负责提供 summary 和 recent messages：

```python
from core.memory.models import (
    MemoryExtractionInput,
    MemoryExtractionMessage,
    Provenance,
)


candidates = await memory.extract(
    MemoryExtractionInput(
        messages=[
            MemoryExtractionMessage(
                message_id="message-001",
                role="user",
                content="我最近搬到上海了",
            ),
            MemoryExtractionMessage(
                message_id="message-002",
                role="assistant",
                content="以后可以探索上海周边。",
            ),
        ],
        provenance=(Provenance("event", "event-001"),),
    ),
    summary=context_summary,
    recent_messages=recent_messages,
)
```

注意：

- 只有 `messages` 是本轮新记忆来源；
- summary/recent 只帮助理解；
- 每条新消息和 recent message 都必须具有非空 `message_id`；
- Extractor 输出的 `source_message_ids` 只能引用本轮新消息；
- `provenance` 会从 Extraction Input 贯穿到 Candidate，再贯穿到 Payload；
- 返回空列表是正常结果；
- Candidate 尚未成为正式 MemoryItem。

## 5. 调用 Formation

调用方需要把记录时间、Recall Context 和新记忆归属显式传入。可信来源已由 Candidate 携带：

```python
from datetime import datetime, timezone

from core.memory.models import (
    MemoryFormationInput,
    MemoryRecallContext,
    MemoryScopeKind,
    MemoryScopeRef,
)


user_scope = MemoryScopeRef(
    MemoryScopeKind.USER,
    "user-001",
)

for index, candidate in enumerate(candidates):
    result = await memory.form(
        MemoryFormationInput(
            candidate=candidate,
            recorded_at=datetime.now(timezone.utc),
            recall_context=MemoryRecallContext(
                scopes=frozenset({user_scope}),
            ),
            memory_space_id="sena-main",
            scopes=frozenset({user_scope}),
            operation_id=f"event-001:candidate:{index}",
        )
    )
```

这里的两个 Scope 字段不能混淆：

```text
recall_context.scopes
= 本轮可以从哪些长期主体中找相关旧记忆

scopes
= 新记忆本身关于哪些长期主体
```

普通个人信息通常写入 `USER(A)`，即使它未来可能在与 A 相关的群聊中被召回。只有群体共同事实才写入 `GROUP(G)`。

`operation_id` 当前不会自动提供重试幂等。调用方可以提供稳定标识用于来源追踪，但不能据此假设重复调用不会产生副作用。

## 6. 调用 Recall

```python
from core.memory.contracts import MemoryQueryRequest


result = await memory.query(
    MemoryQueryRequest(
        query_id="query-001",
        user_id="user-001",
        session_id="session-001",
        group_id="group-001",
        query_text="用户最近在玩什么游戏？",
    )
)

for item in result.memories:
    use_memory(item)
```

Service 会构造 USER、SESSION、GROUP 三个 Recall Scope，并依次执行 embedding、retrieval 和 rerank。

返回 MemoryItem 只表示它可以成为当前 Agent 请求的认知输入，不表示：

- Agent 必须发言；
- 可以直接向群成员复述；
- 已经通过敏感信息披露检查；
- Character 必须采用某种表达方式。

## 7. LLM 输出与异常

Extractor、Materializer 和 Reviewer 当前要求 LLM 返回严格 JSON。接入的 LLM Adapter 应返回原始文本，不要在 Adapter 内静默修正领域结果。

调用方需要准备处理：

- `json.JSONDecodeError`：LLM 返回非法 JSON；
- `ValueError`：模型字段、领域关系或 ChangePlan 不合法；
- Retriever、LLM、Repository Adapter 自身抛出的异常。

MemoryService 当前不提供统一重试、错误码或补偿。重试有持久化副作用的 Formation 前，必须先明确 operation 幂等策略。

## 8. 接入检查

- [ ] Context 层提供 summary/recent，Memory 不负责生成；
- [ ] Extraction 只把 new messages 当作新记忆来源；
- [ ] 每个 Candidate 单独进入 Formation；
- [ ] Extraction provenance 和 Formation recorded_at 来自可信调用方；
- [ ] Candidate 的 source message ID 只引用本轮 new messages；
- [ ] Recall Context 与新记忆 scopes 分开构造；
- [ ] USER/GROUP Scope 表达长期主体，不表达发布白名单；
- [ ] Retriever 返回 `MemoryRetrievalCandidate`，Repository 不承担 Recall；
- [ ] Materializer、Reviewer 和 Executor 使用同一份 related items 快照；
- [ ] Repository Adapter 返回正式 `MemoryItem`；
- [ ] 不宣称当前写入链路具备完整事务或重试幂等；
- [ ] Agent/Character/Safety 负责最终行为和披露。
