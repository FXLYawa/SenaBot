from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Protocol

from .change_plan import MemoryChangePlan
from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryMaterializationInput,
    MemoryPayload,
    MemoryRecallContext,
    MemoryReviewInput,
    MemoryRetrievalCandidate,
    MemorySupersedeResult,
    MemoryItem,
    MemoryWriteEnvelope,
)

if TYPE_CHECKING:
    from .executor import (
        MemoryChangeExecutionInput,
        MemoryChangeExecutionResult,
    )


class MemoryExtractorProtocol(Protocol):
    """
    定义长期记忆候选提取能力。

    """

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        ...


class MemoryMaterializerProtocol(Protocol):
    """将原始候选转换为具体领域 Payload。"""

    async def materialize(
        self,
        input_data: MemoryMaterializationInput,
    ) -> MemoryPayload:
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
        context: MemoryRecallContext,
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


class MemoryRepositoryProtocol(Protocol):
    """新 MemoryItem 变更链路所依赖的持久化端口。"""

    async def add(
        self,
        envelope: MemoryWriteEnvelope,
    ) -> MemoryItem:
        ...

    async def end_fact_validity(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        valid_to: datetime,
    ) -> MemoryItem:
        ...

    async def supersede(
        self,
        *,
        operation_id: str,
        target_item_id: str,
        replacement: MemoryWriteEnvelope,
    ) -> MemorySupersedeResult:
        ...


class MemoryReviewerProtocol(Protocol):
    """根据payload和related_item生成具体执行计划"""

    async def review(
        self,
        input_data: MemoryReviewInput,
    ) -> MemoryChangePlan:
        ...


class MemoryChangeExecutorProtocol(Protocol):
    """执行经过校验的 Memory 变更计划。"""

    async def execute(
        self,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryChangeExecutionResult:
        ...
