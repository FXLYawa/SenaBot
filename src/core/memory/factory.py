"""Memory 模块的创建接口。"""

from __future__ import annotations

from core.memory.embedding import SimpleMemoryEmbedder
from core.memory.events import MemoryModule
from core.memory.executor import MemoryChangeExecutor
from core.memory.extractor import LLMMemoryExtractor
from core.memory.materialization import LLMMemoryMaterializer
from core.memory.protocols import (
    MemoryLLMProtocol,
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)
from core.memory.reranker import SimpleMemoryReranker
from core.memory.reviewer import LLMMemoryReviewer
from core.memory.service import MemoryService


def create_memory_module(
    memory_llm: MemoryLLMProtocol,
    repository: MemoryRepositoryProtocol,
    memory_spaces: MemorySpaceRouterProtocol,
) -> MemoryModule:
    """使用外部 LLM、数据端口和 MVP 检索组件创建 Memory 模块。"""

    service = MemoryService(
        extractor=LLMMemoryExtractor(memory_llm),
        embedder=SimpleMemoryEmbedder(),
        memory_spaces=memory_spaces,
        reranker=SimpleMemoryReranker(),
        materializer=LLMMemoryMaterializer(memory_llm),
        reviewer=LLMMemoryReviewer(memory_llm),
        executor=MemoryChangeExecutor(repository),
    )
    return MemoryModule(service)
