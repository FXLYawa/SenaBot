"""Data 模块的装配入口。"""

from __future__ import annotations

from dataclasses import dataclass

from core.data.context import ContextRepositoryProtocol, SQLiteContextRepository
from core.data.events import DataModule
from core.data.database import SQLiteDatabase
from core.data.memory import SQLiteMemoryRepository, SQLiteMemorySpaceRouter
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
    database: SQLiteDatabase,
    context_repository: ContextRepositoryProtocol | None = None,
) -> DataComponents:
    """创建 SQLite Data 端口，允许测试替换 Context Repository。"""

    resolved_context = context_repository or SQLiteContextRepository(database)
    return DataComponents(
        module=DataModule(resolved_context),
        memory_repository=SQLiteMemoryRepository(database),
        memory_spaces=SQLiteMemorySpaceRouter(database),
    )
