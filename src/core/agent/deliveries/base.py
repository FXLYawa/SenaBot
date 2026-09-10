"""Agent Effect 交付适配器的最小接口"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeVar

EffectT = TypeVar("EffectT", contravariant=True)
BindingT = TypeVar("BindingT")


@dataclass(frozen=True, slots=True)
class PreparedDelivery:
    """一次效果交付所需的事件及等待关联，由 Dispatcher 按序发布。
    表示转换出了什么内容，以供交付
    """

    events: tuple[tuple[str, object], ...]
    pending_operation_id: str | None = None


class EffectDelivery(Protocol[EffectT, BindingT]):
    """声明所需的绑定类型，并将语义效果和绑定数据转换为下游请求。
    定义了如何将 Behavior 的 Effect 转化为 Dispatcher 可发布的事件序列，以及如何关联等待外部结果
    """

    @property
    def binding_type(self) -> type[BindingT] | None:
        """Dispatcher 按此类型匹配 Run 绑定；None 表示 prepare 接收空绑定。"""

        ...

    def prepare(
        self,
        effect: EffectT,
        binding: BindingT,
    ) -> PreparedDelivery:
        """构造请求并生成关联 ID，准备完成后由 Dispatcher 登记等待和发布。"""

        ...
