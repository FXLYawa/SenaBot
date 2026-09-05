"""Body 输入、内容、场景、输出和 Adapter 交互的公开业务契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from core.body.common import ErrorInfo, OperationStatus, UserRole


class SceneType(StrEnum):
    """Body 输入可出现的会话场景类型，例如私有、群聊、桌面、系统。"""

    PRIVATE = "private"
    GROUP = "group"
    CHANNEL = "channel"
    DESKTOP = "desktop"
    SYSTEM = "system"


class ContentType(StrEnum):
    """消息内容片段的类型枚举，例如文本、图片、音频、视频、文件、互动、混合类型。"""

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

    platform_user_id: str  # 平台作用域用户 ID；上层身份判定请用 user_id 属性
    display_name: str
    principal_id: str | None = None  # 规范化主体 ID；引入身份映射后与 platform_user_id 分叉
    role: UserRole = UserRole.PRIVATE_USER

    @property
    def user_id(self) -> str:
        """返回用于身份判定的规范化用户 ID（优先 principal_id）。"""
        return self.principal_id or self.platform_user_id


@dataclass(frozen=True, slots=True)
class SceneInfo:
    """消息所属的会话场景（类型与场景 ID）。"""

    scene_type: SceneType
    scene_id: str  # 平台作用域场景 ID；与 adapter_type/platform 组合才全局唯一


@dataclass(frozen=True, slots=True)
class ConversationScope:
    """供 Context 解析 Session 的稳定对话范围；本身不是 Session。"""

    platform: str
    scene_type: SceneType
    scene_id: str
    account_namespace: str = "default"

    @property
    def scene(self) -> SceneInfo:
        return SceneInfo(self.scene_type, self.scene_id)


@dataclass(frozen=True, slots=True)
class BodyRouteInfo:
    """Body 输出所需的显式 Adapter 路由，不承载 Session 状态。"""

    adapter_type: str
    platform: str
    body_id: str


@dataclass(frozen=True, slots=True)
class ContentSegment:
    """消息内容片段：类型与其对应的结构化数据。"""

    type: ContentType
    data: dict[str, Any]  # 片段结构化数据，键依 type 而定（如文本片段为 {"text": ...}）


@dataclass(frozen=True, slots=True)
class Content:
    """统一的消息内容模型，支持纯文本与多类型片段。"""

    content_type: ContentType = ContentType.TEXT
    text: str | None = None  # 纯文本摘要；未显式传入时由 segments 补全
    segments: tuple[ContentSegment, ...] = ()  # 结构化片段；非空时优先于 text

    def __post_init__(self) -> None:
        """补全纯文本摘要；片段含多种类型时把 content_type 修正为 MIXED。"""
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
        """用纯文本快速构造 Content，并同步生成文本摘要片段。"""
        return cls(
            ContentType.TEXT,
            value,
            (ContentSegment(ContentType.TEXT, {"text": value}),),
        )

    def text_value(self) -> str:
        """返回去除首尾空白的纯文本内容。"""
        return (self.text or "").strip()


@dataclass(slots=True)
class AdapterInboundMessage:
    """Adapter 私有的归一化消息；原始 SDK 对象不得越过此边界。

    user_id 必须是 Adapter 已经解析完成的规范身份，不得传平台原始 ID；
    Body 的角色判定（owner/群成员/私聊用户）直接信任该字段。
    """

    adapter_type: str  # Adapter 实现标识，与 platform 共同构成 AdapterRegistry 注册键
    platform: str  # 平台名称，与 adapter_type 共同构成注册键
    message_id: str  # 平台消息 ID，用于输入去重
    user_id: str  # Adapter 已解析完成的规范用户 ID，Body 直接信任
    display_name: str
    scene_type: SceneType
    scene_id: str  # 平台作用域场景 ID，Body 据此绑定会话
    content: Content
    reply_to_message_id: str | None = None  # 本条入站消息回复的平台消息 ID，MVP 暂不参与路由


@dataclass(slots=True)
class BodyInputEventData:
    """发布给 Context/Agent 的标准输入契约；时间与事件元数据由 Envelope 承载。

    Session 身份由 Context 根据 conversation_scope 解析。
    """

    conversation_scope: ConversationScope
    source: SourceInfo  # 归一化发言者；身份判定请用 source.user_id
    scene: SceneInfo  # 会话场景，仅供语义判断（私聊/群聊/哪个群），不用于寻址
    content: Content
    output_route: BodyRouteInfo
    reply_target_id: str | None = None
    payload_type: str = "body"
    body_data_type: str = "input"


@dataclass(slots=True)
class BodyOutputRequestData:
    """Body 输出请求；使用显式路由，不通过 Session 寻址。"""

    output_id: str  # 输出幂等键：同一 output_id 重复请求直接返回缓存结果
    route: BodyRouteInfo
    scene: SceneInfo
    content: Content
    reply_to_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)  # 展示/附加元数据，如 presentation.emotion/state
    payload_type: str = "body"
    body_data_type: str = "output_request"

    @property
    def emotion(self) -> str:
        """读取展示元数据中的情绪，缺省为 neutral。"""
        return str(self.metadata.get("presentation", {}).get("emotion", "neutral"))

    @property
    def state(self) -> str:
        """读取展示元数据中的状态，缺省为 idle。"""
        return str(self.metadata.get("presentation", {}).get("state", "idle"))


@dataclass(slots=True)
class AdapterOutboundMessage:
    """Body 私有的出站消息；由 BodyRuntime 解析会话路由后填充，平台具体。"""

    adapter_type: str  # Adapter 实现标识，与 platform 共同构成注册键
    platform: str  # 平台名称
    scene: SceneInfo  # 从会话路由解析出的平台作用域场景
    content: Content
    reply_to_message_id: str | None = None  # 默认回复该会话最近一条入站消息；None 表示普通发送
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BodyOutputItemResult:
    """单个发送项的发送结果（索引、状态、平台事件 ID 与时间）。"""

    index: int  # 发送项序号（内容拆分后的第几项）
    status: OperationStatus
    platform_event_id: str | None = None  # 平台消息 ID，用于发送结果追溯
    sent_at: datetime | None = None


@dataclass(slots=True)
class BodyOutputResultEventData:
    """一次输出请求的整体结果事件，可携带汇总错误。"""

    output_id: str
    items: list[BodyOutputItemResult]  # 逐项发送结果
    error: ErrorInfo | None = None  # 汇总错误；None 表示至少有一项发送成功
    payload_type: str = "body"
    body_data_type: str = "output_result"

    @property
    def outcome(self) -> OperationStatus:
        """按逐项发送结果汇总整体状态：全部成功/部分成功/失败。"""
        completed = sum(item.status == OperationStatus.COMPLETED for item in self.items)
        if completed == len(self.items) and self.items:
            return OperationStatus.COMPLETED
        if completed:
            return OperationStatus.PARTIALLY_COMPLETED
        return OperationStatus.FAILED
