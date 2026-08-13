from typing import Protocol

from .models import Memory, MemoryCandidate, MemoryExtractionContext, MemoryQueryCriteria


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


class MemoryExtractorProtocol(Protocol):
    """
    定义长期记忆候选提取能力。

    """

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
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
