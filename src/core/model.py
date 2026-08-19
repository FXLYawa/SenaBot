"""业务模块共享的最小语言模型调用契约，不构成独立业务层。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """厂商无关的有序模型消息。"""

    role: str  # system、user、assistant 或具体 Provider 支持的其他角色。
    content: str  # 已由调用模块组装好的文本内容。


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """不包含 Agent、Context 或 Persona 语义的文本生成请求。"""

    messages: tuple[ModelMessage, ...]
    temperature: float | None = None
    max_output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class ModelResponse:
    text: str
    model: str
    finish_reason: str = "stop"


class ModelProvider(Protocol):
    """具体模型 Adapter 实现的共享技术 Interface。"""

    async def generate(self, request: ModelRequest) -> ModelResponse: ...
