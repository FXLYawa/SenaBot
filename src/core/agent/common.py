from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from typing import Any
from uuid import uuid4
from datetime import datetime, UTC


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class UserRole(StrEnum):
    OWNER = "owner"
    OPERATOR = "operator"
    PRIVATE_USER = "private_user"
    GROUP_MEMBER = "group_member"
    SYSTEM = "system"
    
    
class SceneType(StrEnum):
    """输入或输出发生的标准交互场景。"""

    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    DESKTOP = "desktop"
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
    """归一化主体信息；平台用户 ID 不直接作为稳定系统身份。"""

    platform_user_id: str  # 平台内原始用户 ID，只用于适配和映射。
    display_name: str  # 当前平台展示名，不作为稳定身份依据。
    is_bot: bool = False  # 消息来源是否为机器人账号。
    principal_id: str | None = None  # 系统统一主体 ID；未映射时为空。
    role: UserRole = UserRole.PRIVATE_USER  # 系统内归一化用户角色。

    @property
    def user_id(self) -> str:
        """返回核心业务使用的主体 ID，未映射时退回平台 ID。"""

        return self.principal_id or self.platform_user_id


@dataclass(frozen=True, slots=True)
class SceneInfo:
    """平台无关的交互场景定位。"""

    scene_type: SceneType  # 私聊、群聊、频道、桌面或系统场景。
    scene_id: str  # 可定位交互目标的稳定 ID。
    scene_name: str = ""  # 可选展示名称，不参与权限判断。

    @property
    def display_name(self) -> str:
        return self.scene_name


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