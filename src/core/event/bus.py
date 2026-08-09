from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from enum import Enum, auto

from core.event.common import new_id, utc_now
from core.event.contracts import EventSpec, HandlerSpec
from core.event.envelope import EventEnvelope, TraceInfo
from core.event.errors import EventError
from core.event.flow import EventFlow
from core.event.protocols import EventHandler, Logger
from core.event.registry import EventRegistry, HandlerRegistration, RegistrationToken

class _BusState(Enum):
    """EventBus 内部生命周期; DRAINING 关闭入口但继续处理现有事件"""

    STOPPED = auto()
    RUNNING = auto()
    DRAINING = auto()


class EventBus:
    """统一完成注册、匹配、分发、派生事件和 request/reply
    
    EventBus 只依据 EventSpec、HandlerSpec 和 Envelope 工作，不导入任何业务 Runtime
    """
    
    def __init__(
        self,
        registry: EventRegistry | None = None,
        *,
        dispatch_concurrency: int = 8,  # 最大并发分发数
        default_handler_timeout: float = 60.0,
        flow_control_timeout: float = 5.0,
        shutdown_timeout: float = 10.0,
        logger: Logger | None = None
    ) -> None:
        self.registry = registry or EventRegistry()
        self.logger = logger or logging.getLogger("senabot.event")
        self.dispatch_concurrency = dispatch_concurrency
        self.default_handler_timeout = default_handler_timeout
        self.flow_control_timeout = flow_control_timeout
        self.shutdown_timeout = shutdown_timeout
        self._queue: asyncio.Queue[EventEnvelope | None] = asyncio.Queue()
        self._workers: tuple[asyncio.Task[None], ...] = ()
        self._shutdown_task: asyncio.Task[None] | None = None
        self._state: _BusState = _BusState.STOPPED
        
        
    def register(self, spec: EventSpec) -> RegistrationToken:
        """注册事件类型"""
        return self.registry.register(spec)
    
    
    def subscribe(self, spec: HandlerSpec, handler: EventHandler) -> RegistrationToken:
        """注册事件处理器"""    
        return self.registry.subscribe(spec, handler)
    
    
    async def start(self) -> None:
        """启动事件 worker"""
        
        if self._state is _BusState.RUNNING:
            return
        if self._state is _BusState.DRAINING:
            raise EventError(
                "event_bus_unavailable",
                "EventBus is not accepting events.",
                {"state": "draining"},
            )
        self._state = _BusState.RUNNING
        self._workers = tuple(
            asyncio.create_task(
                self._run_worker(),
                name=f"senabot-event-worker:{i}",
            )
            for i in range(self.dispatch_concurrency)
        )


    async def stop(self) -> None:
        """拒绝新事件，排空队列并停止 worker"""
        
        if self._state is _BusState.STOPPED:
            return
        shutdown_task = self._shutdown_task
        if shutdown_task is None:
            self._state = _BusState.DRAINING
            shutdown_task = asyncio.create_task(self._drain_and_stop(), name="senabot-event-shutdown")
            self._shutdown_task = shutdown_task
        await asyncio.shield(shutdown_task)
    
    
    async def publish(self, envelope: EventEnvelope) -> None:
        """发布事件"""
        
        if self._state is not _BusState.RUNNING:
            raise EventError(
                "event_bus_unavailable",
                "EventBus is not accepting events.",
                {"state": self._state.name.lower()},
            )
        self._validate_envelope(envelope)
        self._queue.put_nowait(envelope)
    
    
    async def unregister_owner(self, owner_id: str) -> None:
        """注销指定 owner_id 的所有注册"""
        await self.registry.unregister_owner(owner_id)
        
        
    async def _drain_and_stop(self) -> None:
        """关闭入口但继续处理现有事件"""
        try:
            await asyncio.wait_for(self._queue.join(), timeout=self.shutdown_timeout)
        except TimeoutError:
            self.logger.warning(
                "EventBus shutdown timed out after %.1f seconds",
                self.shutdown_timeout,
            )
        finally:
            for task in self._workers:
                task.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._discard_queued_events()
            self._workers = ()
            self._state = _BusState.STOPPED
            self._shutdown_task = None
    
    def _discard_queued_events(self) -> None:
        """丢弃队列中未处理的事件"""
        while True:
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            else:
                self._queue.task_done()
    
    
    async def _run_worker(self) -> None:
        """事件分发 worker"""
        while True:
            envelope = await self._queue.get()
            try:
                await self._dispatch_one(envelope)
            except Exception as e:
                self.logger.exception("Error dispatching event: %s", e)
            finally:
                self._queue.task_done()
    
    
    async def _dispatch_one(self, envelope: EventEnvelope) -> None:
        """分发单个事件"""
        
        event_spec = self._validate_envelope(envelope)
        registrations = self.registry.matching_handlers(envelope.event_type)
        current = envelope
        
        async with asyncio.TaskGroup() as group:
            for reg in registrations:
                if not reg.spec.controls_flow:
                    group.create_task(
                        self._run_handler(reg, current, event_spec),
                        name=(
                            f"event-handler:{reg.spec.owner_id}:"
                            f"{reg.spec.handler_id}"
                        ),
                    )
                    continue
                
                flow = self._new_flow(current, reg, event_spec)
                committed = await self._invoke(reg, flow)
                if committed is None:
                    continue
                current, stopped, derived = committed
                self._enqueue_all(derived)
                if stopped:
                    return
    
    
    async def _run_handler(
        self, 
        registration: HandlerRegistration, 
        envelope: EventEnvelope,
        event_spec: EventSpec,
    ) -> None:
        """运行单个事件处理器"""
        
        flow = self._new_flow(envelope, registration, event_spec)
        committed = await self._invoke(registration, flow)
        if committed is not None:
            self._enqueue_all(committed[2])
    
    
    def _new_flow(
        self,
        envelope: EventEnvelope,
        registration: HandlerRegistration,
        event_spec: EventSpec,
    ) -> EventFlow:
        """创建一个新的事件流"""
        
        return EventFlow(
            envelope,
            lambda payload: self._validate_payload(event_spec, payload),
            lambda parent, event_type, payload, metadata: self._build_derived(
                parent,
                event_type,
                payload,
                metadata,
                source_owner_id=registration.spec.owner_id,
            ),
            controls_flow=registration.spec.controls_flow,
        )
    
    
    def _enqueue_all(self, envelopes: tuple[EventEnvelope, ...]) -> None:
        """将事件列表加入队列"""
        for envelope in envelopes:
            self._queue.put_nowait(envelope)
    
    
    async def _invoke(
        self,
        registration: HandlerRegistration,
        flow: EventFlow,
    ) -> tuple[EventEnvelope, bool, tuple[EventEnvelope, ...]] | None:
        """调用事件处理器并返回结果"""
        
        timeout = registration.spec.timeout
        if timeout is None:
            timeout = (
                self.flow_control_timeout 
                if registration.spec.controls_flow 
                else self.default_handler_timeout
            )
        try:
            return await asyncio.wait_for(
                self._invoke_and_commit(registration, flow),
                timeout=timeout,
            )
        except TimeoutError:
            self.logger.warning(
                "Event handler timed out after %.1f seconds: %s (owner=%s)",
                timeout,
                registration.spec.handler_id,
                registration.spec.owner_id,
            )
        except asyncio.CancelledError:
            flow._discard()
            raise
        except Exception as e:
            self.logger.exception(
                "Error in event handler %s (owner=%s): %s",
                registration.spec.handler_id,
                registration.spec.owner_id,
                e,
            )
        flow._discard()
        return None
        
    
    @staticmethod
    async def _invoke_and_commit(
        registration: HandlerRegistration,
        flow: EventFlow,
    ) -> tuple[EventEnvelope, bool, tuple[EventEnvelope, ...]]:
        """调用事件处理器并提交结果"""
        await registration.handler(flow)
        return flow._commit()
    
    
    def _validate_envelope(self, envelope: EventEnvelope) -> EventSpec:
        spec = self.registry.event_spec(envelope.event_type)
        if spec is None:
            raise EventError(
                "event_not_registered",
                f"Event is not registered: {envelope.event_type}",
            )
        self._validate_payload(spec, envelope.payload)
        return spec
    
    
    @staticmethod
    def _validate_payload(spec: EventSpec, payload: object) -> None:
        """验证 payload 是否符合 event 定义"""
        if spec.payload_type is not None and not isinstance(payload, spec.payload_type):
            raise EventError(
                "payload_invalid",
                f"Payload type does not match {spec.event_type}.",
                {
                    "expected": spec.payload_type.__name__,
                    "actual": type(payload).__name__,
                },
            )
    
    
    def _build_derived(
        self,
        parent: EventEnvelope,
        event_type: str,
        payload: object,
        metadata: Mapping[str, object] | None,
        *,
        source_owner_id: str,
    ) -> EventEnvelope:
        """创建派生事件"""
        
        spec = self.registry.event_spec(event_type)
        if spec is None:
            raise EventError(
                "event_not_registered",
                f"Derived event is not registered: {event_type}",
            )
        self._validate_payload(spec, payload)
        child_metadata = dict(parent.metadata)
        if metadata is not None:
            child_metadata.update(metadata)
        return EventEnvelope(
            event_id=new_id("event"),
            event_type=event_type,
            occurred_at=utc_now(),
            emitted_at=utc_now(),
            source_owner_id=source_owner_id,
            trace=TraceInfo(parent.trace.trace_id, parent.event_id),
            payload=payload,
            metadata=child_metadata,
        )
