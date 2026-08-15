from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any
from uuid import uuid4





def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"

class SceneType(StrEnum):
    """输入或输出发生的标准交互场景。"""

    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    DESKTOP = "desktop"
    SYSTEM = "system"



class UserRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    PRIVATE_USER = "private_user"
    GROUP_MEMBER = "group_member"
    SYSTEM = "system"
    
    
class ContentType(StrEnum):
    """内容类型"""
    
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    LINK = "link"
    COMMAND = "command"
    INTERACTION = "interaction"
    MIXED = "mixed"
    SYSTEM_MESSAGE = "system_message"

    
@dataclass(frozen=True, slots=True)
class SourceInfo:
    """归一化系统内主体信息"""
    
    platform_user_id: str  # 平台用户唯一标识
    display_name: str  # 平台用户显示名称
    is_bot: bool  # 是否为机器人
    principal_id: str | None = None  # 平台用户在本系统中的唯一标识
    role: UserRole = UserRole.PRIVATE_USER  # 平台用户在本系统中的角色
    
    @property
    def user_id(self) -> str:
        """返回平台用户在本系统中的唯一标识，如果没有则返回平台自身的标识"""
        return self.principal_id or self.platform_user_id


@dataclass(frozen=True, slots=True)
class SceneInfo:
    """平台无关的场景信息"""
    
    scene_type: str  # 场景类型
    scene_id: str  # 场景唯一标识
    scene_name: str  # 场景名称
    
    @property
    def display_name(self) -> str:
        return f"{self.scene_type}:{self.scene_name}"


@dataclass(frozen=True, slots=True)
class ContentSegment:
    """上下文片段"""
    
    type: ContentType # 当前片段的内容类型
    data: dict[str, Any] # 类型对应的数据
    

@dataclass(frozen=True, slots=True)
class Content:
    """供核心模块使用的标准上下文信息"""
    
    content_type: ContentType = ContentType.TEXT # 用于快速判断内容的类型
    text: str | None = None # 用于检索和模型处理的归一化文本
    segments: tuple[ContentSegment, ...] = () # 顺序的内容片段
    
    def __post_init__(self) -> None:
        
        # 通过 segment 的种类快速判断类型
        segment_types = {segment.type for segment in self.segments}
        if len(segment_types) == 1:
            object.__setattr__(self, "content_type", next(iter(segment_types)))
        elif len(segment_types) > 1:
            object.__setattr__(self, "content_type", ContentType.MIXED)
            
        # 没有文本直接拼接一个文本出来
        if self.text is None:
            value = "\n".join(
                str(segment.data.get("text", ""))
                for segment in self.segments
                if segment.type == ContentType.TEXT
            ).strip()
            object.__setattr__(self, "text", value or None)
            
    @classmethod
    def from_text(cls, value: str) -> Content:
        return cls(
            ContentType.TEXT,
            value,
            (ContentSegment(ContentType.TEXT, {"text": value}),),
        )
        
    def text_value(self) -> str:
        return (self.text or "").strip()
    
    
@lru_cache(maxsize=None)
def load_prompt(package: str, name: str) -> str:
    """读取固定提示词文本；缺失资源属于发布错误，应直接抛出异常。"""

    return files(package).joinpath(name).read_text(encoding="utf-8").strip()


def render_prompt(package: str, name: str, **values: object) -> str:
    """使用命名变量渲染提示词，模板字段缺失时立即失败。"""

    return load_prompt(package, name).format_map(values)



@dataclass(frozen=True, slots=True)
class ConversationScope:
    """稳定对话流的外部身份，不包含消息发送者或进程内 Body 身份。"""

    platform: str  # 平台命名空间，例如 desktop、qq 或 telegram。
    scene_type: SceneType  # 私聊、群聊、频道或桌面场景。
    scene_id: str  # 平台内稳定的私聊、群或频道 ID。
    account_namespace: str = "default"  # 同平台多 Bot 账号的稳定命名空间。

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
        """返回 Body 输出和 Agent 交互策略使用的场景值对象。"""

        return SceneInfo(self.scene_type, self.scene_id)
