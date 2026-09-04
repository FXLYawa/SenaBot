"""Body 模块的创建接口。"""

from __future__ import annotations

from typing import Protocol

from core.body.contracts import AdapterInboundMessage, BodyInputEventData
from core.body.ports import BodyAdapter
from core.event import EventClient, ModuleEventAPI


class BodyModuleProtocol(Protocol):
    """组合根使用的 Body 模块最小接口。"""

    def register(self, events: ModuleEventAPI) -> None:
        """注册 Body 拥有的事件及订阅关系。"""
        ...

    def register_adapter(self, adapter: BodyAdapter) -> None:
        """向 Body 注册一个平台 Adapter。"""
        ...

    async def publish_input(
        self,
        events: EventClient,
        message: AdapterInboundMessage,
    ) -> BodyInputEventData | None:
        """接收 Adapter 输入并发布标准 Body 输入事件。"""
        ...


def create_body_module(owner_user_id: str) -> BodyModuleProtocol:
    """创建完整的 Body 模块。"""

    pass
