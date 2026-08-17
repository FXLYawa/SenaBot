from typing import Protocol

from .models import Memory, MemoryQueryCriteria, MemoryRetrievalCandidate


class MemoryRepositoryProtocol(Protocol):
    """规定 Memory 层访问底层数据时必须具备的能力。"""

    async def query(
        self,
        criteria: MemoryQueryCriteria,
    ) -> list[Memory]:
        ...

    async def save(self, memory: Memory) -> Memory:
        ...

    async def find_by_source_event_id(
        self,
        source_event_id: str,
    ) -> Memory | None:
        ...

    async def find_by_operation_id(
        self,
        operation_id: str,
    ) -> Memory | None:
        ...


class MemoryRetrieverProtocol(Protocol):
    """检索主链路"""

    async def retrieve(
        self,
        query_embedding: list[float],
        *,
        user_id: str,
        session_id: str,
        group_id: str,
    ) -> list[MemoryRetrievalCandidate]:
        ...


class MemoryEmbeddingProtocol(Protocol):
    """向量化"""

    async def embed(
        self,
        query: str,
    ) -> list[float]:
        ...


class MemoryRerankerProtocol(Protocol):
    """重排"""

    async def rerank(
        self,
        query: str,
        candidates: list[MemoryRetrievalCandidate],
    ) -> list[MemoryRetrievalCandidate]:
        ...
