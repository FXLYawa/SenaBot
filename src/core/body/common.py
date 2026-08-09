"""Body 内部复用的最小状态与错误契约；待 core/common 落地后可整体迁移。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OperationStatus(StrEnum):
    """通用操作状态枚举，用于表达一次发送/查询的整体或逐项结果。"""

    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    VERSION_CONFLICT = "version_conflict"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """结构化的错误信息，供事件结果携带而不依赖异常对象。"""

    code: str
    message: str
    retryable: bool = False  # 是否允许调用方重试
    details: dict[str, Any] = field(default_factory=dict)  # 额外诊断细节


class UserRole(StrEnum):
    """归一化用户角色枚举，Body 根据属主身份与场景类型解析。"""

    OWNER = "owner"
    OPERATOR = "operator"
    PRIVATE_USER = "private_user"
    GROUP_MEMBER = "group_member"
    SYSTEM = "system"
