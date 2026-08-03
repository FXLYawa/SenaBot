from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field, replace

from core.common.types import new_id, utc_now
from core.event.contracts import (
    EventDispatchResult,
    EventEnvelope,
    EventHandlerResult,
    EventMode,
    EventPublishRequest,
    EventSpec,
    EventTransform,
    HandlerExecutionResult,
    HandlerKind,
    HandlerSpec,
    TraceInfo,
)
from core.event.errors import EventError
from core.event.patterns import event_pattern_matches
from core.event.protocols import EventHandler, Logger
from core.event.registry import EventRegistry, HandlerRegistration, RegistrationToken


@dataclass(slots=True)
class _DispatchAccumulator:
    """一次信封分发期间共用的结果与派生请求累加器"""
    
    results: EventDispatchResult
    derived: list[tuple[EventPublishRequest, HandlerRegistration]] = field(default_factory=list)
    
    def record(
        self,
        registration: HandlerRegistration,
        handler_result: EventHandlerResult,
        error: EventError | None
    ) -> None:
        """记录一次 Handler 执行结果"""
        self.results.handlers.append(
            HandlerExecutionResult(
                registration.spec.handler_id,
                registration.spec.owner_id,
                handler_result.handled,
                dict(handler_result.metadata),
                error,
            )
        )
        if error is not None:
            self.results.errors.append(error)
        self.derived.extend(
            (request, registration) for request in handler_result.derived_events
            )


class EventBus:
    """统一完成注册、匹配、分发、派生事件和 request/reply
    
    EventBus 只依据 EventSpec、HandlerSpec 和 Envelope 工作，不导入任何业务 Runtime
    """
    
    def __init__(
        self,
        registry: EventRegistry | None = None,
        max_dispatch_depth: int = 100,
        logger: Logger | None = None
    ) -> None:
        self.registry = registry or EventRegistry()
        self.max_dispatch_depth = max_dispatch_depth
        self.logger = logger or logging.getLogger("senabot.event")
        
        
    def register_event(self, spec: EventSpec) -> RegistrationToken:
        """注册事件类型"""
        return self.registry.register(spec)
    
    
    def subscribe(self, spec: HandlerSpec, handler: EventHandler) -> RegistrationToken:
        """注册事件处理器"""    
        return self.registry.subscribe(spec, handler)
    
    
    async def publish(self, envelope: EventEnvelope) -> EventDispatchResult:
        """在 BUS 上发布事件"""
        
        result = EventDispatchResult()
        queue: deque[EventEnvelope] = deque([envelope])
        processed = 0
        while queue:
            current = queue.popleft()
            if processed >= self.max_dispatch_depth:
                result.errors.append(
                    EventError(
                        code="handler_failed",
                        message="Maximum derived event count exceeded.",
                        details={"limit": self.max_dispatch_depth},
                        retryable=False
                    )
                )
                break
            processed += 1
            derived, effective, dispatch_error = await self._dispatch_one(current, result)
            
            result.envelopes.append(effective)
            if dispatch_error is not None:
                result.errors.append(dispatch_error)
            for request, registration in derived:
                child, error = self._derive(effective, request, registration)
                if error is not None:
                    result.errors.append(error)
                elif child is not None:
                    queue.append(child)
        return result
            
    
    async def unregister_owner(self, owner_id: str) -> None:
        await self.registry.unregister_owner(owner_id)
        
        
    async def _dispatch_one(
        self,
        envelope: EventEnvelope,
        result: EventDispatchResult,
    ) -> tuple[
        list[tuple[EventPublishRequest, HandlerRegistration]], 
        EventEnvelope, 
        EventError | None
    ]:
        """分发单个事件信封, 运行所有匹配的 Handler"""
        
        spec, error = self._validate_envelope(envelope)
        if error is not None:
            return [], envelope, error
        assert spec is not None
        # 创建一个累加器来记录 Handler 执行结果和派生事件请求
        accumulator = _DispatchAccumulator(result)
        # 运行所有匹配的 Handler, 包括 Transformer、Consumer 和 Observer
        registrations = self.registry.matching_handlers(envelope.event_type)
        # 先运行 Transformer, 允许每个 Transformer 替换 Payload
        transformers = [reg for reg in registrations if reg.spec.kind == HandlerKind.TRANSFORMER]
        # 运行 Transformer 并获取最终的有效事件信封
        effective = await self._run_transformers(spec, envelope, transformers, accumulator)
        # 运行 Consumer 和 Observer, 直到 unicast 的首个 Consumer 接受事件
        destinations = [
            reg for reg in registrations 
            if reg.spec.kind != HandlerKind.TRANSFORMER
            and self._target_matches(effective, reg)
        ]
        dispatch_error = await self._run_handlers(spec, effective, destinations, accumulator)
        return accumulator.derived, effective, dispatch_error
        

    async def  _run_transformers(
        self,
        evnet_spec: EventSpec,
        envelope: EventEnvelope,
        registrations: list[HandlerRegistration],
        accumulator: _DispatchAccumulator,
    ) -> EventEnvelope:
        """依次运行 Transformer, 允许每个 Transformer 替换 Payload"""
        
        current = envelope
        for reg in registrations:
            handler_result = await self._invoke(current, reg)
            transform_error = handler_result.error
            if handler_result.transform is not None and transform_error is None:
                transformed, transform_error = self._transform(
                    evnet_spec, 
                    current, 
                    handler_result.transform, 
                    reg,
                )
                if transformed is not None:
                    current = transformed
            accumulator.record(reg, handler_result, transform_error)
        return current
        
        
    async def _run_handlers(
        self,
        event_spec: EventSpec,
        envelope: EventEnvelope,
        registrations: list[HandlerRegistration],
        accumulator: _DispatchAccumulator,
    ) -> EventError | None:
        """依次运行 Consumer 和 Observer, 直到 unicast 的首个 Consumer 接受事件"""
        
        consumers, observers = self._group_handlers(registrations)
        if not consumers and not observers:
            return EventError(
                code="handler_not_found",
                message=f"No handler matched: {envelope.event_type}",
                details={"target_owner_id": envelope.target_owner_id},
                retryable=False
            )
            
        accepted = (event_spec.mode == EventMode.BROADCAST)
        for reg in consumers:
            handler_result, error = await self._invoke_handler(envelope, reg, accumulator)
            if (
                event_spec.mode == EventMode.UNICAST 
                and handler_result.handled
                and error is None
            ):
                accepted = True
                break
            
        for reg in observers:
            await self._invoke_handler(envelope, reg, accumulator)
        if not accepted:
            return EventError(
                code="handler_not_found",
                message=f"No consumer accepted: {envelope.event_type}",
                details={"target_owner_id": envelope.target_owner_id},
                retryable=False
            )
        return None        
    
    
    async def _invoke_handler(
        self,
        envelope: EventEnvelope,
        registration: HandlerRegistration,
        accumulator: _DispatchAccumulator,
    ) -> tuple[EventHandlerResult, EventError | None]:
        """调用指定的 Handler 并记录结果到累加器"""

        handler_result = await self._invoke(envelope, registration)
        result_error = handler_result.error
        if handler_result.transform is not None:
            result_error = result_error or EventError(
                code="permission_denied",
                message="Only a transformer Handler may return EventTransform.",
                details={"handler_id": registration.spec.handler_id},
                retryable=False
            )
        accumulator.record(registration, handler_result, result_error)
        return handler_result, result_error
    
    
    @staticmethod
    def _transform(
        event_spec: EventSpec,
        envelope: EventEnvelope,
        transformer: EventTransform,
        registration: HandlerRegistration,
    ) -> tuple[EventEnvelope | None, EventError | None]:
        """根据 Transformer 的结果生成新的事件信封"""

        if event_spec.payload_type is not None and not isinstance(transformer.payload, event_spec.payload_type):
            return None, EventError(
                code="payload_invalid",
                message=f"Transformer payload does not match {event_spec.event_type}.",
                details={
                    "handler_id": registration.spec.handler_id,
                    "expected": event_spec.payload_type.__name__,
                    "actual": type(transformer.payload).__name__,
                },
                retryable=False
            )
        return replace(envelope, payload=transformer.payload), None


    async def _invoke(
        self,
        envelope: EventEnvelope,
        registration: HandlerRegistration,
    ) -> EventHandlerResult:
        """隔离单个 Handler 的超时、异常和非法返回值"""

        try:
            call = registration.handler(envelope)
            outcome = (
                await asyncio.wait_for(call, registration.spec.timeout)
                if registration.spec.timeout is not None
                else await call
            )
            if not isinstance(outcome, EventHandlerResult):
                return EventHandlerResult(
                    handled=False,
                    error=EventError(
                        code="handler_failed",
                        message="Handler returned an unsupported result.",
                        details={"handler_id": registration.spec.handler_id},
                        retryable=False
                    )
                )
            return outcome
        except TimeoutError:
            return EventHandlerResult(
                handled=False,
                error=EventError(
                    code="handler_timeout",
                    message=f"Handler timed out: {registration.spec.handler_id}",
                    details={"owner_id": registration.spec.owner_id},
                    retryable=True
                )
            )
        except Exception as exc:
            # 记录异常日志
            self.logger.exception(
                "Event handler failed: %s", registration.spec.handler_id
            )
            return EventHandlerResult(
                handled=False,
                error=EventError(
                    code="handler_failed",
                    message=f"Handler failed: {registration.spec.handler_id}",
                    details={
                        "owner_id": registration.spec.owner_id,
                        "exception_type": type(exc).__name__,
                    },
                ),
            )


    def _validate_envelope(
        self, envelope: EventEnvelope
    ) -> tuple[EventSpec | None, EventError | None]:
        """验证事件信封,确认其已注册且 payload 类型正确"""
        
        spec = self.registry.event_spec(envelope.event_type)
        if spec is None:
            return None, EventError(
                code="event_not_registered",
                message=f"Event type {envelope.event_type} is not registered.",
                details={"event_type": envelope.event_type},
                retryable=False
            )
        if spec.payload_type is not None and not isinstance(envelope.payload, spec.payload_type):
            return None, EventError(
                code="payload_invalid",
                message=f"Payload type {type(envelope.payload).__name__} does not match expected type {spec.payload_type.__name__}.",
                details={"event_type": envelope.event_type},
                retryable=False
            )
        return spec, None
    
    
    @staticmethod
    def _group_handlers(
        registrations: list[HandlerRegistration],
    ) -> tuple[list[HandlerRegistration], list[HandlerRegistration]]:
        """根据事件类型和分发模式选择合适的处理器"""
        
        primary: list[HandlerRegistration] = []
        observers: list[HandlerRegistration] = []
        for reg in registrations:
            if reg.spec.kind == HandlerKind.CONSUMER:
                primary.append(reg)
            elif reg.spec.kind == HandlerKind.OBSERVER:
                observers.append(reg)
        
        return primary, observers
        
        
    @staticmethod
    def _target_matches(
        envelope: EventEnvelope, registration: HandlerRegistration
    ) -> bool:
        
        target_owner_id = envelope.target_owner_id
        if target_owner_id is None:
            return True
        return target_owner_id == registration.spec.owner_id
        
        
    def _derive(
        self,
        parent: EventEnvelope,
        request: EventPublishRequest,
        registration: HandlerRegistration,
    ) -> tuple[EventEnvelope | None, EventError | None]:
        """根据 Handler 的派生请求生成新的事件信封"""
        
        event_spec = self.registry.event_spec(request.event_type)
        if event_spec is None:
            return None, EventError(
                code="event_not_registered",
                message=f"Derived event type {request.event_type} is not registered.",
                details={"event_type": request.event_type},
                retryable=False
            )
        if not self._may_publish(registration, request.event_type, event_spec.owner_id):
            return None, EventError(
                code="permission_denied",
                message="Handler attempted to publish outside its allowed namespace.",
                details={"handler_id": registration.spec.handler_id, "event_type": request.event_type},
                retryable=False
            )
        metadata = dict(parent.metadata)
        metadata.update(request.metadata)
        return (
            EventEnvelope(
                event_id=new_id("event"),
                event_type=request.event_type,
                occurred_at=request.occurred_at or utc_now(),
                emitted_at=utc_now(),
                source_owner_id=registration.spec.owner_id,
                target_owner_id=request.target_owner_id,
                trace=TraceInfo(parent.trace.trace_id, parent.event_id),
                payload=request.payload,
                metadata=metadata
            ),
            None
        )
    
    
    @staticmethod
    def _may_publish(
        registration: HandlerRegistration, event_type: str, event_owner: str
    ) -> bool:
        """检查 Handler 是否允许发布指定类型的事件"""
        
        if event_owner == registration.spec.owner_id:
            return True
        return any(
            event_pattern_matches(pattern, event_type)
            for pattern in registration.spec.publish_patterns
        )
