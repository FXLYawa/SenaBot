"""身份、场景与交互路由的公共值对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class UserRole(StrEnum):
    """来源主体在系统中的权限角色。"""

    OWNER = "owner"
    OPERATOR = "operator"
    PRIVATE_USER = "private_user"
    GROUP_MEMBER = "group_member"
    SYSTEM = "system"


class SceneType(StrEnum):
    """输入或输出发生的交互场景。"""

    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    DESKTOP = "desktop"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """来源主体；平台标识与系统映射身份分别保留。"""

    platform_user_id: str
    display_name: str
    is_bot: bool = False
    principal_id: str | None = None
    role: UserRole = UserRole.PRIVATE_USER

    @property
    def user_id(self) -> str:
        """优先返回系统主体 ID，未映射时退回平台内 ID。"""

        return self.principal_id or self.platform_user_id


@dataclass(frozen=True, slots=True)
class SceneInfo:
    """交互场景的完整身份与展示信息，供 Context 解析 Session。"""

    platform: str
    scene_type: SceneType
    scene_id: str
    account_namespace: str = "default"
    scene_name: str = field(default="", compare=False)  # 名称变化不改变身份或哈希。

    def __post_init__(self) -> None:
        platform = self.platform.strip().casefold()
        scene_id = self.scene_id.strip()
        account_namespace = self.account_namespace.strip().casefold()
        if not platform or not scene_id or not account_namespace:
            raise ValueError("scene identity fields must not be empty")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "account_namespace", account_namespace)

    @property
    def display_name(self) -> str:
        return self.scene_name


@dataclass(frozen=True, slots=True)
class InteractionSignals:
    """由输入边界归一化的显式交互信号。"""

    mentioned_agent: bool = False
    reply_to_agent: bool = False

    @property
    def directed_to_agent(self) -> bool:
        return self.mentioned_agent or self.reply_to_agent


@dataclass(frozen=True, slots=True)
class OutputRoute:
    """输出 Adapter 的显式定位，不参与 Session 划分。"""

    adapter_type: str
    platform: str
    body_id: str
