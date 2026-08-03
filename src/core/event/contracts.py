from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, is_dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from core.event.errors import EventError


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
    target_owner_id: str | None # 事件目标
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


class EventMode(StrEnum):
    """事件分发模式: 由事件 owner 注册时决定"""
    
    BROADCAST = "broadcast"  # 广播模式: 所有订阅者都能收到事件
    UNICAST = "unicast"      # 单播模式: 只有一个订阅者能收到事件


class HandlerKind(StrEnum):
    """事件处理器类型: 由事件订阅者注册时决定"""
    
    CONSUMER = "consumer"  # 消费者: 消费事件
    OBSERVER = "observer"  # 观察者: 观察事件
    TRANSFORMER = "transformer"  # 转换器: 转换事件, 保留其原链路


@dataclass(frozen=True, slots=True)
class EventSpec:
    """事件定义
    ``owner_id`` 表示事件定义的拥有者
    """
    
    event_type: str
    owner_id: str
    # payload 运行时类型, 由eventbus在运行时检查与注册内容是否一致, None表示不检查
    payload_type: type | None = None 
    mode: EventMode = EventMode.BROADCAST


@dataclass(frozen=True, slots=True)
class HandlerSpec:
    """事件处理器定义
    
    ``owner_id`` 表示事件处理器的拥有者
    ``priority`` 表示事件处理器的优先级，数值越小优先级越高
    """
    
    handler_id: str
    owner_id: str
    event_pattern: str
    priority: int = 100
    kind: HandlerKind = HandlerKind.CONSUMER
    timeout: float | None = None  # 处理器超时时间，单位为秒
    publish_patterns: tuple[str, ...] = ()  # 处理器可能发布的事件类型


@dataclass(frozen=True, slots=True)
class EventPublishRequest:
    """Handler 请求 EventBus 发布派生事件请求"""
    
    event_type: str
    # 派生事件的业务数据
    payload: object
    # 派生事件的目标 owner_id, None 则由目标事件的 owner 契约定义
    target_owner_id: str | None = None
    # 仅属于派生事件的非业务主契约的附加信息
    metadata: dict[str, object] = field(default_factory=dict)
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventTransform:
    """Transformer 对下一处理阶段提出的 Payload 替换结果
    这里只允许提供新 payloa
    """
    
    payload: object

    @classmethod
    def with_changes(cls, payload: object, /, **changes: object) -> EventTransform:
        """创建一个新的 EventTransform 实例, 并应用指定的更改"""
        
        if is_dataclass(payload) and not isinstance(payload, type):
            # 如果 payload 是 dataclass 实例，则使用 replace 创建一个新的实例并应用更改
            return cls(replace(payload, **changes))
        if isinstance(payload, Mapping):
            # 如果 payload 是 Mapping 类型，则创建一个新的字典并应用更改
            new_payload = dict(payload)
            new_payload.update(changes)
            return cls(new_payload)
        raise TypeError("Payload must be a dataclass instance or a Mapping type to apply changes.")


@dataclass(slots=True)
class EventHandlerResult:
    """事件处理器执行结果"""
    
    # Handler 是否接受事件; unicast 在首个 无错误的 True 处停止 后续 Consumer
    handled: bool = True
    # Transformer 对下一处理阶段提出的 Payload 替换结果
    transform: EventTransform | None = None  
    # 请求 EventBus 发布的派生事件
    derived_events: list[EventPublishRequest] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    error: EventError | None = None


@dataclass(slots=True)
class HandlerExecutionResult:
    """事件处理器执行结果"""
    
    handler_id: str
    owner_id: str
    handled: bool
    metadata: dict[str, object] = field(default_factory=dict)
    error: EventError | None = None    


@dataclass(slots=True)
class EventDispatchResult:
    """一次 publish 产生的完整事件、Handler 结果和隔离错误"""
    
    envelopes: list[EventEnvelope] = field(default_factory=list)
    handlers: list[HandlerExecutionResult] = field(default_factory=list)
    errors: list[EventError] = field(default_factory=list)

