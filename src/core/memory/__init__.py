"""Memory 模块的公开接口。"""

from core.memory.factory import create_memory_module
from core.memory.service import MemoryRecallPolicy
from core.memory.protocols import (
    MemoryLLMProtocol,
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)

__all__ = [
    "MemoryLLMProtocol",
    "MemoryRecallPolicy",
    "MemoryRepositoryProtocol",
    "MemorySpaceRouterProtocol",
    "create_memory_module",
]
