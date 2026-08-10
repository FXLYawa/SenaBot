from typing import Protocol

from .models import Memory,MemoryQueryCriteria

class MemoryRepositoryProtocol(Protocol):
    """规定 Memory 层访问底层数据时必须具备的能力。"""

    async def query(self,criteria:MemoryQueryCriteria) -> list[Memory]:
        ...

    async def save(self, memory: Memory) -> Memory:
        ...

    async def find_by_source_event_id(self,source_event_id: str) -> Memory | None:
        ...

    async def find_by_operation_id(self,operation_id: str) -> Memory | None:
        ...