"""Body 输入、内容、场景、输出和 Adapter 交互的公开业务契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from core.common.contracts import ErrorInfo, OperationStatus
from core.common.types import UserRole


class SceneType(StrEnum):
    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    DESKTOP = "desktop"
    SYSTEM = "system"


class ContentType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"
    INTERACTION = "interaction"
    MIXED = "mixed"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """归一化后的发言者信息。

    当前 MVP 中 principal_id 与 platform_user_id 相同：Adapter 边界已把
    平台标识解析为规范 user_id 后才进入 Body。引入真实身份映射前，
    两者保持一致；映射引入后再由 BodyRuntime 填充不同的 principal_id。
    """

    platform_user_id: str
    display_name: str
    principal_id: str | None = None
    role: UserRole = UserRole.PRIVATE_USER

    @property
    def user_id(self) -> str:
        return self.principal_id or self.platform_user_id


@dataclass(frozen=True, slots=True)
class SceneInfo:
    scene_type: SceneType
    scene_id: str


@dataclass(frozen=True, slots=True)
class ContentSegment:
    type: ContentType
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Content:
    content_type: ContentType = ContentType.TEXT
    text: str | None = None
    segments: tuple[ContentSegment, ...] = ()

    def __post_init__(self) -> None:
        if self.text is None:
            value = "\n".join(
                str(segment.data.get("text", ""))
                for segment in self.segments
                if segment.type == ContentType.TEXT
            ).strip()
            object.__setattr__(self, "text", value or None)
        if len({segment.type for segment in self.segments}) > 1:
            object.__setattr__(self, "content_type", ContentType.MIXED)

    @classmethod
    def from_text(cls, value: str) -> Content:
        return cls(
            ContentType.TEXT,
            value,
            (ContentSegment(ContentType.TEXT, {"text": value}),),
        )

    def text_value(self) -> str:
        return (self.text or "").strip()


@dataclass(slots=True)
class AdapterInboundMessage:
    """Adapter 私有的归一化消息；原始 SDK 对象不得越过此边界。

    user_id 必须是 Adapter 已经解析完成的规范身份，不得传平台原始 ID；
    Body 的角色判定（owner/群成员/私聊用户）直接信任该字段。
    """

    adapter_type: str
    platform: str
    body_id: str
    message_id: str
    user_id: str
    display_name: str
    scene_type: SceneType
    scene_id: str
    content: Content
    reply_to_message_id: str | None = None


@dataclass(slots=True)
class BodyInputEventData:
    """发布给 Context/Agent 的标准输入契约；时间与事件元数据由 Envelope 承载。"""

    body_id: str
    adapter_type: str
    platform: str
    platform_message_id: str | None
    source: SourceInfo
    scene: SceneInfo
    content: Content
    reply_to_message_id: str | None = None
    payload_type: str = "body"
    body_data_type: str = "input"


@dataclass(frozen=True, slots=True)
class OutputReplyInfo:
    platform_event_id: str


@dataclass(slots=True)
class BodyOutputRequestData:
    output_id: str
    scene: SceneInfo
    content: Content
    # 路由信息由 Payload 字段携带；事件层在发布前填充，空值表示未完成路由。
    adapter_type: str = ""
    platform: str = ""
    reply_to: OutputReplyInfo | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    payload_type: str = "body"
    body_data_type: str = "output_request"

    @property
    def emotion(self) -> str:
        return str(self.metadata.get("presentation", {}).get("emotion", "neutral"))

    @property
    def state(self) -> str:
        return str(self.metadata.get("presentation", {}).get("state", "idle"))


@dataclass(slots=True)
class BodyOutputItemResult:
    index: int
    status: OperationStatus
    platform_event_id: str | None = None
    sent_at: datetime | None = None


@dataclass(slots=True)
class BodyOutputResultEventData:
    output_id: str
    items: list[BodyOutputItemResult]
    error: ErrorInfo | None = None
    payload_type: str = "body"
    body_data_type: str = "output_result"

    @property
    def outcome(self) -> OperationStatus:
        completed = sum(item.status == OperationStatus.COMPLETED for item in self.items)
        if completed == len(self.items) and self.items:
            return OperationStatus.COMPLETED
        if completed:
            return OperationStatus.PARTIALLY_COMPLETED
        return OperationStatus.FAILED
