from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.context.common import SourceInfo, SceneInfo, Content



@dataclass(frozen=True, slots=True)
class InteractionSignals:
    """Body 归一化的交互信号，不携带平台 SDK 对象。"""

    mentioned_agent: bool = False  # 消息是否显式 @ 当前角色。
    reply_to_agent: bool = False  # 消息是否回复当前角色的消息。

    @property
    def directed_to_agent(self) -> bool:
        """当前输入是否明确朝向角色。"""

        return self.mentioned_agent or self.reply_to_agent
    
    
@dataclass(frozen=True, slots=True)
class BodyInputEventData:
    """Body 完成身份、Session、场景和内容归一化后发布的标准输入。"""

    session_id: str  # Body 解析出的逻辑对话边界。
    session_is_new: bool  # 本次输入是否创建了新的 Session。
    occurred_at: datetime  # 原始输入实际发生时间。
    source: SourceInfo  # 已映射为系统主体的来源。
    scene: SceneInfo  # 已归一化的交互场景。
    interaction: InteractionSignals  # @、回复角色等显式交互信号。
    content: Content  # 已归一化的内容。
    replaced_session_id: str | None = None  # 创建新 Session 时被关闭的旧 Session。
    reply_target_id: str | None = None  # 默认回复的平台事件 ID。
    
    
@dataclass(frozen=True, slots=True)
class BodyRouteInfo:
    """可持久化的输出 Adapter 定位，不包含平台凭证或 SDK 对象。"""

    adapter_type: str  # Adapter 实现类型，如 desktop、qq 或 telegram。
    platform: str  # AdapterRegistry 使用的平台命名空间。
    body_id: str  # 可跨重启解析的逻辑收发端点 ID，不参与 Session 划分。