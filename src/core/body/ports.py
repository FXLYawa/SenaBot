"""Body 与具体消息平台实现之间的 Adapter Interface。"""

from __future__ import annotations

from typing import Protocol

from core.body.contracts import BodyOutputItemResult, BodyOutputRequestData


class BodyAdapter(Protocol):
    """具体平台只需接收标准 BodyOutputRequest 并返回逐项结果。"""

    adapter_type: str
    platform: str

    async def send(self, request: BodyOutputRequestData) -> list[BodyOutputItemResult]: ...


class AdapterRegistry:
    """按 adapter_type/platform 选择实现，不包含对话或权限策略。"""

    def __init__(self) -> None:
        self._adapters: dict[tuple[str, str], BodyAdapter] = {}

    def register(self, adapter: BodyAdapter) -> None:
        # 同键后注册用于组合根显式替换；运行期不提供动态覆盖入口。
        self._adapters[(adapter.adapter_type, adapter.platform)] = adapter

    def get(self, adapter_type: str, platform: str) -> BodyAdapter:
        try:
            return self._adapters[(adapter_type, platform)]
        except KeyError as exc:
            raise LookupError(f"Body adapter not registered: {adapter_type}/{platform}") from exc
