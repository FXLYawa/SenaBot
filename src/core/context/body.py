from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from core.common import (
    Content,
    InteractionSignals,
    SceneInfo,
    SourceInfo,
)


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
