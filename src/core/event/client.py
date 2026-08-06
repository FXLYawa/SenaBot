from __future__ import annotations

from dataclasses import dataclass

from core.common.types import new_id, utc_now
from core.event.bus import EventBus
from core.event.contracts import (
    EventDispatchResult,
    EventEnvelope,
    EventMode,
    EventPublishRequest,
    EventSpec,
    HandlerKind,
    HandlerSpec,
    TraceInfo,
)
from core.event.errors import EventError, EventPermissionError
from core.event.patterns import event_pattern_matches
from core.event.protocols import EventHandler
from core.event.registry import RegistrationToken


class EventClient:
    
    def __init__(
        self,
        bus: EventBus,
        owner_id: str,
        publish_patterns: tuple[str, ...] = (),
    ) -> None:
        self.bus = bus
        self.owner_id = owner_id
        self.publish_patterns = publish_patterns
        
    
    async def publish(
        self,
        event_type: str,
        payload: object,
        target_owner_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> EventDispatchResult:
        """发布事件"""
        
        spec = self._authorize(event_type)
        return await self.bus.publish(
            self._build(
                event_type=event_type,
                payload=payload,
                target_owner_id=target_owner_id,
                metadata=metadata or {},
                spec=spec,
                trace=None
            )
        )
        
        
    
    def _build(
        self,
        event_type: str,
        payload: object,
        target_owner_id: str | None,
        metadata: dict[str, object],
        spec: EventSpec | None,
        trace: TraceInfo | None = None,
    ) -> EventEnvelope:
        """构建事件信封"""

        return EventEnvelope(
            event_id=new_id("event"),
            event_type=event_type,
            occurred_at=utc_now(),
            emitted_at=utc_now(),
            source_owner_id=self.owner_id,
            target_owner_id=target_owner_id,
            trace=trace or TraceInfo(trace_id=new_id("trace")),
            payload=payload,
            metadata=metadata,
        )
    
    def derived(
        self,
        event_type: str,
        payload: object,
        target_owner_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> EventPublishRequest:
        """构建派生事件请求"""

        self._authorize(event_type)
        return EventPublishRequest(
            event_type=event_type,
            payload=payload,
            target_owner_id=target_owner_id,
            metadata=metadata or {},
        )    
    
    def _authorize(self, event_type: str) -> EventSpec | None:
        """检查是否有权限发布事件"""
        
        spec = self.bus.registry.event_spec(event_type)
        owns_event = bool(spec and spec.owner_id == self.owner_id)
        explicitly_allowed = any(
            event_pattern_matches(pattern, event_type)
            for pattern in self.publish_patterns
        )
        allowed = owns_event or explicitly_allowed
        if not allowed:
            raise EventPermissionError(
                EventError(
                    code="permission_denied",
                    message=f"Owner {self.owner_id} cannot publish {event_type}.",
                    details={
                        "owner_id": self.owner_id,
                        "event_type": event_type,
                    },
                )
            )
        return spec
    

@dataclass(slots=True)
class ModuleEventAPI:
    
    bus: EventBus
    owner_id: str
    client: EventClient
    
    @classmethod
    def create(cls, bus: EventBus, owner_id: str) -> ModuleEventAPI:
        """创建模块事件 API 实例"""
        
        return cls(
            bus=bus,
            owner_id=owner_id,
            client=EventClient(bus, owner_id, publish_patterns=("*",)) # 核心模块默认拥有全部事件的发布权限
        )
        
        
    def register(
        self,
        event_type: str,
        payload_type: type | None = None,
        mode: EventMode = EventMode.BROADCAST,
    ) -> RegistrationToken:
        """注册事件类型"""
        
        return self.bus.register_event(
            EventSpec(
                event_type=event_type,
                owner_id=self.owner_id,
                payload_type=payload_type,
                mode=mode,
            )
        )
        
        
    def subscribe(
        self,
        event_pattern: str,
        handler: EventHandler,
        handler_id: str,
        priority: int = 100,
        kind: HandlerKind = HandlerKind.CONSUMER,
        timeout: float | None = None,
        publish_patterns: tuple[str, ...] = (),
    ) -> RegistrationToken:
        """注册事件处理器"""
        
        return self.bus.subscribe(
            HandlerSpec(
                handler_id=handler_id,
                owner_id=self.owner_id,
                event_pattern=event_pattern,
                priority=priority,
                kind=kind,
                timeout=timeout,
                publish_patterns=("*",),
            ),
            handler,
        )
        
    def derived(
        self,
        event_type: str,
        payload: object,
        target_owner_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> EventPublishRequest:
        """构建派生事件请求"""
        
        return self.client.derived(
            event_type=event_type,
            payload=payload,
            target_owner_id=target_owner_id,
            metadata=metadata or {},
        )
