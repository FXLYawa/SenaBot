"""Body 输入、内容、场景、输出和 Adapter 交互的公开业务契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from core.body.common import ErrorInfo, OperationStatus
from core.common import (
    Content,
    ConversationScope,
    OutputRoute,
    SceneInfo,
    SceneType,
    SourceInfo,
)


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
    output_route: OutputRoute
    reply_target_id: str | None = None
    payload_type: str = "body"
    body_data_type: str = "input"


@dataclass(slots=True)
class BodyOutputRequestData:
    """Body 输出请求；使用显式路由，不通过 Session 寻址。"""

    output_id: str  # 输出幂等键：同一 output_id 重复请求直接返回缓存结果
    route: OutputRoute
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
