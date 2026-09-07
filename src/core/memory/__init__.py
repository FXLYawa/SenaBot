"""Memory 模块的公开接口。"""

from core.memory.factory import create_memory_module
from core.memory.extraction_flow import MemoryExtractionConfig, MemoryExtractionPolicy
from core.memory.contracts import (
    MemoryExtractionFailedEventData,
    MemoryExtractionResult,
    MemoryQueryFailedEventData,
    MemoryQueryRequest,
    MemoryQueryResult,
)
from core.memory.service import MemoryRecallPolicy
from core.memory.protocols import (
    MemoryExtractionProgressProtocol,
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)

__all__ = [
    "MemoryExtractionConfig",
    "MemoryExtractionFailedEventData",
    "MemoryExtractionPolicy",
    "MemoryExtractionProgressProtocol",
    "MemoryExtractionResult",
    "MemoryQueryFailedEventData",
    "MemoryQueryRequest",
    "MemoryQueryResult",
    "MemoryRecallPolicy",
    "MemoryRepositoryProtocol",
    "MemorySpaceRouterProtocol",
    "create_memory_module",
]
