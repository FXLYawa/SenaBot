from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class TraceInfo:
    """事件追踪信息: 派生事件保持并记录父事件"""
    trace_id: str
    parent_event_id: str | None = None
    

@dataclass(frozen=True, slots=True)
class EventEnvelope:
    """事件信封: 包含事件的元信息"""
    
    event_id: str # 事件唯一标识
    event_type: str # 事件类型
    occurred_at: datetime # 事件发生时间
    emitted_at: datetime # 事件发出时间
    source_owner_id: str # 事件源
    trace: TraceInfo # 事件追踪信息
    payload: object # 事件业务数据
    # 非业务主契约的通用附加信息
    metadata: Mapping[str, object] = field(default_factory=dict)
    
    def __post_init__(self) -> None:

        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.event_type:
            raise ValueError("event_type is required")
        if not self.source_owner_id:
            raise ValueError("source_owner_id is required")
        if not self.trace.trace_id:
            raise ValueError("trace_id is required")
        
        # 将 metadata 转换为不可变的 MappingProxyType，以确保事件信封的不可变性
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        
    def with_payload(self, new_payload: object) -> EventEnvelope:
        """创建一个新的 EventEnvelope 实例，替换 payload"""
        return replace(self, payload=new_payload)