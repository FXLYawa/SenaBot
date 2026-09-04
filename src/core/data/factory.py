"""Data 模块的装配入口。"""

from __future__ import annotations

from dataclasses import dataclass

from core.data.events import DataModule
from core.data.memory import (
    InMemoryMemoryRepository,
    InMemoryMemorySpaceRouter,
)
from core.data.store import InMemoryDataStore
from core.memory import (
    MemoryRepositoryProtocol,
    MemorySpaceRouterProtocol,
)


@dataclass(frozen=True, slots=True)
class DataComponents:
    """Data 模块及其向其他模块提供的公开端口。"""

    module: DataModule
    memory_repository: MemoryRepositoryProtocol
    memory_spaces: MemorySpaceRouterProtocol


def create_data_components(
    store: InMemoryDataStore | None = None,
) -> DataComponents:
    """创建共享同一存储实例的 Data 模块与 Memory 数据端口。"""

    resolved_store = store or InMemoryDataStore()
    return DataComponents(
        module=DataModule(resolved_store),
        memory_repository=InMemoryMemoryRepository(resolved_store),
        memory_spaces=InMemoryMemorySpaceRouter(resolved_store),
    )
