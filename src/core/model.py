"""业务模块共享的最小语言模型调用契约，不构成独立业务层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ModelError(Exception):
    """语言模型调用的统一基础异常。"""


class ModelRequestError(ModelError):
    """厂商无关的模型请求不符合公共协议。"""


class ModelResponseError(ModelError):
    """模型响应无法转换为公共响应协议。"""


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
    temperature: float | None = None
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
            or not self.temperature >= 0
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
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str
    model: str
    finish_reason: str = "stop"
    usage: ModelUsage | None = None


class ModelProvider(Protocol):
    """具体模型 Adapter 实现的共享技术 Interface。"""

    async def generate(self, request: ModelRequest) -> ModelResponse: ...

    async def close(self) -> None: ...
