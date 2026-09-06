"""身份、场景与交互路由的公共值对象。"""

from __future__ import annotations

from dataclasses import dataclass
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
    """平台内的场景定位；展示名称不参与身份或权限判断。"""

    scene_type: SceneType
    scene_id: str
    scene_name: str = ""

    @property
    def display_name(self) -> str:
        return self.scene_name


@dataclass(frozen=True, slots=True)
class ConversationScope:
    """稳定对话流的外部身份，供 Context 解析 Session。"""

    platform: str
    scene_type: SceneType
    scene_id: str
    account_namespace: str = "default"

    def __post_init__(self) -> None:
        platform = self.platform.strip().casefold()
        scene_id = self.scene_id.strip()
        account_namespace = self.account_namespace.strip().casefold()
        if not platform or not scene_id or not account_namespace:
            raise ValueError("conversation scope fields must not be empty")
        object.__setattr__(self, "platform", platform)
        object.__setattr__(self, "scene_id", scene_id)
        object.__setattr__(self, "account_namespace", account_namespace)

    @property
    def scene(self) -> SceneInfo:
        return SceneInfo(self.scene_type, self.scene_id)


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
