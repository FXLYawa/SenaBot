"""Data 模块的装配入口。"""

from __future__ import annotations

from dataclasses import dataclass

from core.data.events import DataModule
from core.data.database import SQLiteDatabase
from core.data.memory import SQLiteMemoryRepository, SQLiteMemorySpaceRouter
from core.data.store import InMemoryDataStore
from core.embedding import EmbeddingProvider
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
    embedding_provider: EmbeddingProvider,
    context_store: InMemoryDataStore | None = None,
) -> DataComponents:
    """创建 SQLite Memory 端口；Context 暂时继续使用进程内 Store。"""

    resolved_store = context_store or InMemoryDataStore()
    return DataComponents(
        module=DataModule(resolved_store),
        memory_repository=SQLiteMemoryRepository(database, embedding_provider),
        memory_spaces=SQLiteMemorySpaceRouter(database),
    )
