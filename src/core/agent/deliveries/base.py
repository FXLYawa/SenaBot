"""Agent Effect 交付适配器的最小接口"""

from __future__ import annotations

from typing import Protocol, TypeVar

from core.event import EventFlow


EffectT = TypeVar("EffectT", contravariant=True)


class EffectDelivery(Protocol[EffectT]):
    """把一种外部副作用 Effect 转换为公开事件。

    返回关联 ID 表示 Run 需要等待结果；返回 None 表示
    事件发出后无需等待。Dispatcher 统一维护等待/恢复不变量。
    """

    def pending_operation_id(self, effect: EffectT) -> str | None:
        """返回需要等待的操作 ID; 不等待时返回 None。"""

        ...

    def emit(
        self,
        flow: EventFlow,
        effect: EffectT,
    ) -> None:
        """发布执行该 Effect 所需的公开事件。"""

        ...
