"""业务模块共享的单文本向量化契约。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from core.model import ModelRequestError, ModelResponseError, ModelUsage


@dataclass(frozen=True, slots=True)
class EmbeddingRequest:
    """保留调用方原文的一次向量化请求。"""

    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.text, str) or not self.text.strip():
            raise ModelRequestError("embedding text must not be empty")


@dataclass(frozen=True, slots=True)
class EmbeddingResponse:
    """向量化结果，包含服务实际返回的模型标识。"""

    vector: tuple[float, ...]

    # 具体模型标识
    model: str
    # 使用的Token用量结构
    usage: ModelUsage | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ModelResponseError("embedding model must not be empty")
        if not isinstance(self.vector, tuple) or not self.vector:
            raise ModelResponseError("embedding vector must not be empty")
        for value in self.vector:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ModelResponseError("embedding vector must contain numbers")
            try:
                # 检查数值是否有限
                finite = math.isfinite(value)
            except OverflowError as exc:
                raise ModelResponseError("embedding value is out of range") from exc
            if not finite:
                raise ModelResponseError("embedding vector must contain finite numbers")
        object.__setattr__(self, "vector", tuple(float(v) for v in self.vector))

    @property
    def dimensions(self) -> int:
        """模型实际输出维度。"""
        return len(self.vector)


class EmbeddingProvider(Protocol):
    """可替换的 Embedding 模型能力。"""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    async def close(self) -> None: ...
