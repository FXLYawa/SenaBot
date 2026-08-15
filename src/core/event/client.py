from __future__ import annotations

from collections.abc import Mapping

from core.event.common import new_id, utc_now
from core.event.bus import EventBus
from core.event.contracts import EventSpec, HandlerSpec
from core.event.envelope import EventEnvelope, TraceInfo
from core.event.protocols import EventHandler
from core.event.registry import RegistrationToken


class EventClient:
    """创建来源可信的根事件或独立派生事件"""
    
    def __init__(self, bus: EventBus, owner_id: str) -> None:
        self._bus = bus
        self._owner_id = owner_id
        
    
    async def publish(
        self,
        event_type: str,
        payload: object,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """发布事件"""
        
        await self._bus.publish(
            self._build(event_type, payload, metadata or {}, trace=None)
        )
        
        
    async def emit(
        self,
        parent: EventEnvelope,
        event_type: str,
        payload: object,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        
        inherited = dict(parent.metadata)
        if metadata is not None:
            inherited.update(metadata)
        await self._bus.publish(
            self._build(
                event_type,
                payload,
                metadata=inherited,
                trace=TraceInfo(trace_id=parent.trace.trace_id, parent_event_id=parent.event_id),
            )
        )
        
        
    
    def _build(
        self,
        event_type: str,
        payload: object,
        metadata: Mapping[str, object],
        *,
        trace: TraceInfo | None,
    ) -> EventEnvelope:
        """构建事件信封"""
        
        return EventEnvelope(
            event_id=new_id("event"),
            event_type=event_type,
            occurred_at=utc_now(),
            emitted_at=utc_now(),
            source_owner_id=self._owner_id,
            trace=trace or TraceInfo(trace_id=new_id("trace")),
            payload=payload,
            metadata=metadata,
        )

    

class ModuleEventAPI(EventClient):
    
        
    def register(
        self,
        event_type: str,
        *,
        payload_type: type | None = None,
    ) -> RegistrationToken:
        """注册事件类型"""
        
        return self._bus.register(
            EventSpec(
                event_type=event_type,
                owner_id=self._owner_id,
                payload_type=payload_type,
            )
        )
        
        
    def subscribe(
        self,
        event_pattern: str,
        handler: EventHandler,
        *,
        handler_id: str,
        priority: int = 100,
        timeout: float | None = None,
        controls_flow: bool = False,
        max_attempts: int = 1,
    ) -> RegistrationToken:
        """注册事件处理器"""
        
        return self._bus.subscribe(
            HandlerSpec(
                handler_id=handler_id,
                owner_id=self._owner_id,
                event_pattern=event_pattern,
                priority=priority,
                timeout=timeout,
                controls_flow=controls_flow,
                 max_attempts=max_attempts,
            ),
            handler,
        )
