from __future__ import annotations

from collections.abc import Callable, Mapping

from core.event.envelope import EventEnvelope

PayloadValidator = Callable[[object], None]
DerivedEventBuilder = Callable[
    [EventEnvelope, str, object, Mapping[str, object] | None], EventEnvelope
]


class EventFlow:
    
    
    __slots__ = (
        "_build_derived",
        "_controls_flow",
        "_derived",
        "_envelope",
        "_finished",
        "_stopped",
        "_validate_payload",
    )
    
    def __init__(
        self,
        envelope: EventEnvelope,
        validate_payload: PayloadValidator,
        build_derived: DerivedEventBuilder,
        *,
        controls_flow: bool = False,
    ) -> None:
        self._envelope = envelope
        self._validate_payload = validate_payload  # 用于验证 payload 的类型, 由EventBus提供
        self._build_derived = build_derived  # 用于构建派生事件的函数, 由EventBus提供
        self._controls_flow = controls_flow  # 标记当前事件是否控制事件流
        self._derived: list[EventEnvelope] = []  # 存储派生事件
        self._stopped: bool = False  # 标记事件是否被停止传播
        self._finished = False  # 
        
        
    @property
    def envelope(self) -> EventEnvelope:
        """获取当前事件信封"""
        
        return self._envelope
    
    
    @property
    def payload(self) -> object:
        """获取当前事件的 payload"""
        
        return self._envelope.payload
    
    
    def replace_payload(self, new_payload: object) -> None:
        """替换当前事件的 payload"""
        
        self._require_active()
        self._require_flow_control("replace_payload")
        self._validate_payload(new_payload)
        self._envelope = self._envelope.with_payload(new_payload)
        
        
    def stop_propagation(self) -> None:
        """停止当前事件的后续传播"""
        
        self._require_active()
        self._require_flow_control("stop propagation")
        self._stopped = True
        
        
    def emit(
        self,
        event_type: str,
        payload: object,
        *,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        """在同一条事件链上发布派生事件, 所有事件会在Flow被提交后统一发布"""
        
        self._require_active()
        self._derived.append(
            self._build_derived(self._envelope, event_type, payload, metadata)
        )
        
    def _commit(self) -> tuple[EventEnvelope, bool, tuple[EventEnvelope, ...]]:
        """提交事件流的结果"""
        
        self._require_active()
        self._finished = True
        derived = tuple(self._derived)
        self._derived.clear()
        return self._envelope, self._stopped, derived
    
    def _discard(self) -> None:
        """丢弃事件流的结果"""
        
        if self._finished:
            return
        self._finished = True
        self._derived.clear()
    
    def _require_active(self) -> None:
        """确保事件流仍然处于活动状态"""
        
        if not self._finished:
            return
        raise RuntimeError(
            "EventFlow actions are unavailable after its Handler has returned. "
            "Use EventClient.publish() or EventClient.emit() in background tasks."
        )
    
    def _require_flow_control(self, action: str) -> None:
        """确保当前 Handler 注册了 controls_flow=True"""
        
        if self._controls_flow:
            return
        raise RuntimeError(
            f"Handler must register controls_flow=True to {action}."
        )
        
