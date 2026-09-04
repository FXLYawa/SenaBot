"""Memory 模块的创建接口。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from core.memory.protocols import (
    MemoryLLMProtocol,
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)

if TYPE_CHECKING:
    from core.memory.events import MemoryModule


def create_memory_module(
    memory_llm: MemoryLLMProtocol,
    repository: MemoryRepositoryProtocol,
    memory_spaces: MemorySpaceRouterProtocol,
) -> MemoryModule:
    """使用公开依赖创建完整的 Memory 模块。"""

    pass
