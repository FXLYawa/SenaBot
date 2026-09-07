"""厂商无关的生成、向量化契约及模型调用异常。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class ModelError(Exception):
    """模型调用的统一基础异常。"""


class ModelRequestError(ModelError):
    """厂商无关的模型请求不符合公共协议。"""


class ModelResponseError(ModelError):
    """模型响应不符合所需的结构、结束状态或文本格式。"""


class ModelAuthError(ModelError):
    """模型服务拒绝了调用凭证。"""


class ModelRateLimitError(ModelError):
    """模型服务对调用进行了限流。"""


class ModelTimeoutError(ModelError):
    """模型调用超时。"""


class ModelUnavailableError(ModelError):
    """模型服务当前不可连接或不可用。"""


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """厂商无关的有序模型消息。"""

    role: str  # system、user、assistant 或具体 Provider 支持的其他角色。
    content: str  # 已由调用模块组装好的文本内容。

    def __post_init__(self) -> None:
        if not isinstance(self.role, str) or not self.role.strip():
            raise ModelRequestError("model message role must not be empty")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ModelRequestError("model message content must not be empty")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """不包含 Agent、Context 或 Persona 语义的文本生成请求。"""

    messages: tuple[ModelMessage, ...]

    # 采样温度，控制输出的随机性。
    temperature: float | None = None

    # 输出 Token 数量上限。
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.messages, tuple) or not self.messages:
            raise ModelRequestError("model request messages must not be empty")
        if not all(isinstance(message, ModelMessage) for message in self.messages):
            raise ModelRequestError(
                "model request messages must contain only ModelMessage values"
            )
        if self.temperature is not None and (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or self.temperature < 0
        ):
            raise ModelRequestError("model request temperature must be >= 0")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens <= 0
        ):
            raise ModelRequestError(
                "model request max_output_tokens must be greater than 0"
            )


@dataclass(frozen=True, slots=True)
class ModelUsage:

    """统一记录一次模型调用消耗了多少Token"""
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:

    """模型的返回结果,可供SenaBot内部消费"""

    text: str
    # 实际响应对应的模型名
    model: str
    # Provider 将正常完成归一化为 stop，其他结束原因保留以供调用方判断。
    finish_reason: str = "stop"
    # token使用统计,可选
    usage: ModelUsage | None = None


class ModelProvider(Protocol):
    """文本生成能力；客户端由创建方管理，借用方不负责关闭。"""

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    async def close(self) -> None: ...


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
    """向量化能力；客户端由创建方管理，借用方不负责关闭。"""

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse: ...

    async def close(self) -> None: ...
