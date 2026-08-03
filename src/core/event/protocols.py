from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from core.event.contracts import EventEnvelope, EventHandlerResult

EventHandler = Callable[[EventEnvelope], Awaitable[EventHandlerResult]]

class Logger(Protocol):
    """日志记录器协议: 定义日志记录器的接口"""
    
    def debug(self, msg: str, *args) -> None:
        ...
    
    def info(self, msg: str, *args) -> None:
        ...
    
    def warning(self, msg: str, *args,) -> None:
        ...
    
    def exception(self, msg: str, *args) -> None:
        ...
    
