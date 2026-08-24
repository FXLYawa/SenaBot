from typing import Protocol

from .models import (
    Memory,
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryQueryCriteria,
    MemoryRetrievalCandidate,
    MemoryUpdateDecision,
)


class MemoryRepositoryProtocol(Protocol):
    """规定 Memory 层访问底层数据时必须具备的能力。"""

    async def query(self, criteria: MemoryQueryCriteria) -> list[Memory]:
        ...

    async def save(self, memory: Memory) -> Memory:
        ...

    async def find_by_source_event_id(self, source_event_id: str) -> Memory | None:
        ...

    async def find_by_operation_id(self, operation_id: str) -> Memory | None:
        ...

    async def update(
        self,
        memory: Memory,
    ) -> Memory:
        ...

    async def delete(
        self,
        memory_id: str,
    ) -> None:
        ...


class MemoryExtractorProtocol(Protocol):
    """
    定义长期记忆候选提取能力。

    """

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        ...


class MemoryEmbeddingProtocol(Protocol):
    """将预处理后的查询文本转换为检索向量。"""

    async def embed(
        self,
        query: str,
    ) -> list[float]:
        ...


class MemoryRetrieverProtocol(Protocol):
    """根据查询向量和作用域召回候选记忆。"""

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        user_id: str,
        session_id: str,
        group_id: str,
    ) -> list[MemoryRetrievalCandidate]:
        ...


class MemoryRerankerProtocol(Protocol):
    """根据查询文本对候选记忆重新排序。"""

    async def rerank(
        self,
        query: str,
        candidates: list[MemoryRetrievalCandidate],
    ) -> list[MemoryRetrievalCandidate]:
        ...


class MemoryLLMProtocol(Protocol):
    """
       Memory提取器所需的最小LLM调用能力

    """

    async def generate(
        self,
        prompt: str,
    ) -> str:
        ...


class MemoryUpdaterProtocol(Protocol):
    """
    负责比较新记忆和检索记忆,并给出最终进行的操作
    """

    async def decide(
        self,
        candidate: MemoryCandidate,
        existing_memories: list[Memory],
    ) -> MemoryUpdateDecision:
        ...
