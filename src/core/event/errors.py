from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EventError:
    """事件错误信息: 用于描述事件处理过程中发生的错误"""
    code: str # 稳定的可读错误代码
    message: str # 简短错误说明
    details: dict[str, object] = field(default_factory=dict) # 可选的详细信息, 用于调试和日志记录
    retryable: bool = False # 是否允许调用方重试
    
    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class EventRegistrationError(ValueError):
    """事件或 Handler 注册声明无效。"""

    def __init__(self, error: EventError) -> None:
        super().__init__(str(error))
        self.error = error


class EventPermissionError(PermissionError):
    """绑定身份尝试执行未授权的事件操作。"""

    def __init__(self, error: EventError) -> None:
        super().__init__(str(error))
        self.error = error
