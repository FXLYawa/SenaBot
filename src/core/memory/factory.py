"""Memory 模块的创建接口。"""

from __future__ import annotations

from core.model import EmbeddingProvider, ModelProvider
from core.memory.extraction_flow import MemoryExtractionConfig, MemoryExtractionFlow
from core.memory.embedding import ProviderMemoryEmbedder
from core.memory.events import MemoryModule
from core.memory.executor import MemoryChangeExecutor
from core.memory.extractor import LLMMemoryExtractor
from core.memory.materialization import LLMMemoryMaterializer
from core.memory.protocols import (
    MemoryExtractionProgressProtocol,
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)
from core.memory.reranker import SimpleMemoryReranker
from core.memory.reviewer import LLMMemoryReviewer
from core.memory.service import MemoryRecallPolicy, MemoryService


def create_memory_module(
    model_provider: ModelProvider,
    embedding_provider: EmbeddingProvider,
    repository: MemoryRepositoryProtocol,
    memory_spaces: MemorySpaceRouterProtocol,
    recall_policy: MemoryRecallPolicy | None = None,
    *,
    extraction: MemoryExtractionConfig | None = None,
    extraction_progress: MemoryExtractionProgressProtocol | None = None,
) -> MemoryModule:
    """使用外部 LLM、数据端口和 MVP 检索组件创建 Memory 模块。"""

    embedder = ProviderMemoryEmbedder(embedding_provider)
    service = MemoryService(
        extractor=LLMMemoryExtractor(model_provider),
        embedder=embedder,
        memory_spaces=memory_spaces,
        reranker=SimpleMemoryReranker(),
        materializer=LLMMemoryMaterializer(model_provider),
        reviewer=LLMMemoryReviewer(model_provider),
        executor=MemoryChangeExecutor(repository, indexer=embedder),
        recall_policy=recall_policy,
    )
    extraction_flow = None
    extraction_handler_timeout = None
    if extraction is not None and extraction.policy.enabled:
        if extraction_progress is None:
            raise ValueError("automatic extraction requires a progress repository")
        extraction_flow = MemoryExtractionFlow(service, extraction_progress, extraction)
        # 事件处理器比内部提取时限多留 5 秒，供流程发布失败结果并释放批次状态。
        extraction_handler_timeout = extraction.policy.processing_timeout_seconds + 5
    return MemoryModule(
        service, extraction_flow,
        extraction_handler_timeout=extraction_handler_timeout,
    )
