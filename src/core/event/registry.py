from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from core.common.types import new_id
from core.event.contracts import EventSpec, HandlerSpec
from core.event.errors import EventError
from core.event.patterns import event_pattern_matches
from core.event.protocols import EventHandler


async def _noop() -> None:
    """为 dataclass 提供无副作用的默认回调"""

    return


@dataclass(frozen=True, slots=True)
class RegistrationToken:
    """调用方持有的注册凭据"""
    registration_id: str 
    owner_id: str
    
    # RegistrationToken 内部使用的注销函数, 不对外暴露
    _unregister: Callable[[str], Awaitable[None]] = field(repr=False, compare=False)
    
    async def unregister(self) -> None:
        """注销注册的 Handler 或 event 定义"""

        await self._unregister(self.registration_id)


@dataclass(slots=True)
class HandlerRegistration:
    """Registry内部记录"""
    
    spec: HandlerSpec # Handler 定义
    handler: EventHandler
    order: int # 单调递增注册序号
    


class EventRegistry:
    """ event 注册表: 维护 event 定义和 Handler 注册信息"""
    
    def __init__(self) -> None:
        self._events: dict[str, tuple[str, EventSpec]] = {} #  event 类型 -> (注册 ID, EventSpec)
        self._handlers: dict[str, HandlerRegistration] = {} # 注册 ID -> Handler记录
        self._handler_keys: dict[tuple[str, str], str] = {} # (owner_id, handler_id) -> 注册 ID
        self._owner_registrations: dict[str, set[str]] = {} # owner_id -> 注册 ID集合
        self._order = 0
        
        
    def register(self, spec: EventSpec) -> RegistrationToken:
        """注册 event 定义"""
        self._validate_event_type(spec.event_type)
        if spec.event_type in self._events:
            existing = self._events[spec.event_type][1]
            raise EventError(
                "registration_conflict",
                f"Event is already registered: {spec.event_type}",
                {"owner_id": existing.owner_id},
            )
            
        registration_id = new_id("event_reg")
        self._events[spec.event_type] = (registration_id, spec)
        self._remember_owner(registration_id, spec.owner_id)
        return RegistrationToken(registration_id, spec.owner_id, self.unregister)
    
    def subscribe(self, spec: HandlerSpec, handler: EventHandler) -> RegistrationToken:
        """注册 event 处理器"""
        self._validate_event_pattern(spec.event_pattern)
        
        key = (spec.owner_id, spec.handler_id)
        if key in self._handler_keys:
            raise EventError(
                "registration_conflict",
                f"Handler is already registered: {spec.handler_id}",
                {"owner_id": spec.owner_id},
            )
        registration_id = new_id("handler_reg")
        self._order += 1
        self._handlers[registration_id] = HandlerRegistration(spec, handler, self._order)
        self._handler_keys[key] = registration_id
        self._remember_owner(registration_id, spec.owner_id)
        return RegistrationToken(registration_id, spec.owner_id, self.unregister)
    
    def event_spec(self, event_type: str) -> EventSpec | None:
        """获取 event 定义"""
        registered = self._events.get(event_type)
        return registered[1] if registered else None
    
    def matching_handlers(self, event_type: str) -> list[HandlerRegistration]:
        """获取匹配 event 类型的 Handler 列表"""
        matched = [
            reg for reg in self._handlers.values()
            if event_pattern_matches(reg.spec.event_pattern, event_type)
        ]
        return sorted(matched, key=lambda r: (r.spec.priority, r.order))

    async def unregister(self, registration_id: str) -> None:
        """注销注册的 Handler 或 event 定义"""
        
        handler = self._handlers.pop(registration_id, None)
        if handler is not None:
            self._handler_keys.pop((handler.spec.owner_id, handler.spec.handler_id), None)
            self._forget_owner(registration_id, handler.spec.owner_id)
            return
        for event_type, (reg_id, spec) in list(self._events.items()):
            if reg_id == registration_id:
                self._events.pop(event_type, None)
                self._forget_owner(registration_id, spec.owner_id)
                return
        
    async def unregister_owner(self, owner_id: str) -> None:       
        """注销指定 owner_id 的所有注册"""
        for registration_id in list(self._owner_registrations.get(owner_id, [])):
            await self.unregister(registration_id)
        self._owner_registrations.pop(owner_id, None)
        
    
    def _remember_owner(self, registration_id: str, owner_id: str) -> None:
        """记录注册 ID 与 owner_id 的关系"""
        self._owner_registrations.setdefault(owner_id, set()).add(registration_id)
        
    def _forget_owner(self, registration_id: str, owner_id: str) -> None:
        """移除注册 ID 与 owner_id 的关系"""
        registration_ids = self._owner_registrations.get(owner_id)
        if registration_ids is None:
            return
        registration_ids.discard(registration_id)
        if not registration_ids:
            self._owner_registrations.pop(owner_id, None)
    
    
    @staticmethod
    def _validate_event_pattern(pattern: str) -> None:
        
        if pattern == "*":
            return
        if "*" in pattern and (not pattern.endswith(".*") or pattern.count("*") != 1):
            raise EventError(
                "registration_conflict",
                "Only an exact event type or a trailing wildcard is supported.",
                {"event_pattern": pattern},
            )
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            parts = prefix.split(".")
            if any(
                not part or not part.replace("_", "").isalnum()
                for part in parts
            ):
                raise EventError(
                    "registration_conflict",
                    f"Invalid event pattern: {pattern}",
                )
            return
        EventRegistry._validate_event_type(pattern)
    
    
    @staticmethod
    def _validate_event_type(event_type: str) -> None:
        """事件至少应该包含 domain.action 两端"""
        parts = event_type.split(".")
        if len(parts) < 2 or any(not part or not part.replace("_", "").isalnum() for part in parts):
            raise EventError(
                "registration_conflict",
                f"Invalid event type: {event_type}",
            )
