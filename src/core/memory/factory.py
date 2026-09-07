"""Memory 模块的创建接口。"""

from __future__ import annotations

from core.embedding import EmbeddingProvider
from core.memory.embedding import ProviderMemoryEmbedder
from core.memory.events import MemoryModule
from core.memory.executor import MemoryChangeExecutor
from core.memory.extractor import LLMMemoryExtractor
from core.memory.materialization import LLMMemoryMaterializer
from core.memory.protocols import (
    MemoryLLMProtocol,
    MemoryRerankerProtocol,
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)
from core.memory.reviewer import LLMMemoryReviewer
from core.memory.service import MemoryRecallPolicy, MemoryService


def create_memory_module(
    memory_llm: MemoryLLMProtocol,
    embedding_provider: EmbeddingProvider,
    repository: MemoryRepositoryProtocol,
    memory_spaces: MemorySpaceRouterProtocol,
    recall_policy: MemoryRecallPolicy | None = None,
    *,
    reranker: MemoryRerankerProtocol | None = None,
) -> MemoryModule:
    """使用外部 LLM、数据端口和 MVP 检索组件创建 Memory 模块。"""

    embedder = ProviderMemoryEmbedder(embedding_provider)
    service = MemoryService(
        extractor=LLMMemoryExtractor(memory_llm),
        embedder=embedder,
        memory_spaces=memory_spaces,
        reranker=reranker,
        materializer=LLMMemoryMaterializer(memory_llm),
        reviewer=LLMMemoryReviewer(memory_llm),
        executor=MemoryChangeExecutor(repository, indexer=embedder),
        recall_policy=recall_policy,
    )
    return MemoryModule(service)
