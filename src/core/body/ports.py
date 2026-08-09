"""Body 与具体消息平台实现之间的 Adapter Interface。"""

from __future__ import annotations

from typing import Protocol

from core.body.contracts import AdapterOutboundMessage, BodyOutputItemResult


class BodyAdapter(Protocol):
    """具体平台只需接收标准 AdapterOutboundMessage 并返回逐项结果。"""

    adapter_type: str
    platform: str

    async def send(self, outbound: AdapterOutboundMessage) -> list[BodyOutputItemResult]:
        """发送一条标准 Body 出站消息并返回逐项发送结果。"""
        ...


class AdapterRegistry:
    """按 adapter_type/platform 选择实现，不包含对话或权限策略。"""

    def __init__(self) -> None:
        """初始化空的 adapter_type/platform Adapter 注册表。"""
        # 注册表：路由键 (adapter_type, platform) → Adapter 实现。
        self._adapter_map: dict[tuple[str, str], BodyAdapter] = {}

    def register(self, adapter: BodyAdapter) -> None:
        """注册 Adapter；同一 (adapter_type, platform) 键重复注册时，以最后一次为准。"""
        # 同键覆盖是刻意为之：组合根（启动时装配依赖的地方）可借此显式替换默认实现；
        # 运行期不提供动态更换 Adapter 的入口。
        self._adapter_map[(adapter.adapter_type, adapter.platform)] = adapter

    def get(self, adapter_type: str, platform: str) -> BodyAdapter:
        """按 adapter_type/platform 查找 Adapter，未注册时抛出 LookupError。"""
        try:
            return self._adapter_map[(adapter_type, platform)]
        except KeyError as exc:
            raise LookupError(f"Body adapter not registered: {adapter_type}/{platform}") from exc
