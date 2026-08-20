from __future__ import annotations

from dataclasses import dataclass



@dataclass(frozen=True, slots=True)
class EventSpec:
    """事件定义
    ``owner_id`` 表示事件定义的拥有者
    """
    
    event_type: str
    owner_id: str
    # payload 运行时类型, 由eventbus在运行时检查与注册内容是否一致, None表示不检查
    payload_type: type | None = None 


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
    timeout: float | None = None  # 处理器超时时间，单位为秒，None表示默认
    controls_flow: bool = False  # 是否控制事件流，若为 True，则该处理器会阻塞事件流
    max_attempts: int = 1  # 总执行次数；1 表示失败后不重试，大于 1 表示失败后重试