from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.agent.common import SceneInfo, Content

    
    
@dataclass(frozen=True, slots=True)
class BodyRouteInfo:
    """可持久化的输出 Adapter 定位，不包含平台凭证或 SDK 对象。"""

    adapter_type: str  # Adapter 实现类型，如 desktop、qq 或 telegram。
    platform: str  # AdapterRegistry 使用的平台命名空间。
    body_id: str  # 可跨重启解析的逻辑收发端点 ID，不参与 Session 划分。
    

# AI的，单纯占位
@dataclass(slots=True)
class PersonaConfig:
    persona_id: str = "sena"  # Persona 稳定 ID，用于 Context/Memory 隔离。
    name: str = "Sena"  # 面向用户展示的名称。
    identity: str = "长期陪伴型数字角色与个人助手"  # 系统提示词中的身份摘要。
    # 稳定人格特征。
    traits: list[str] = field(
        default_factory=lambda: ["真诚", "有分寸", "好奇", "可靠"]
    )
    speaking_style: str = "自然、简洁、温和；处理任务时清楚直接"  # 回复风格约束。
    values: list[str] = field(  # 行为和安全价值约束。
        default_factory=lambda: ["尊重隐私", "不伪造事实", "高风险操作先确认"]
    )
    relationship_mode: str = "companion"  # Persona 与用户的关系模式。
    
    
@dataclass(frozen=True, slots=True)
class BodyOutputOptions:
    allow_split: bool = True  # 是否允许 Adapter 按平台限制拆分长消息。
    silent: bool = False  # 是否请求平台采用静默通知方式发送。
    ephemeral: bool = False  # 是否请求平台发送仅当前用户可见的临时消息。
    
    
@dataclass(slots=True)
class BodyOutputRequestData:
    output_id: str  # 一次逻辑输出的唯一 ID，用于关联分片结果。
    route: BodyRouteInfo  # 选择输出 Adapter 的显式路由。
    scene: SceneInfo  # 输出目标场景。
    content: Content  # 待发送的归一化内容。
    reply_to: OutputReplyInfo | None = None  # 可选回复/引用目标。
    options: BodyOutputOptions = field(default_factory=BodyOutputOptions)  # 平台无关发送选项。
    metadata: dict[str, Any] = field(default_factory=dict)  # 展示层所需的非敏感附加数据。

    @property
    def state(self) -> str:
        return str(self.metadata.get("presentation", {}).get("state", "idle"))
    
    
@dataclass(frozen=True, slots=True)
class OutputReplyInfo:
    platform_event_id: str  # 要回复/引用的平台事件 ID。
    quote_text: str | None = None  # Adapter 不支持原生引用时可用的显示文本。
