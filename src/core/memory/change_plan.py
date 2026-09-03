from dataclasses import dataclass
from datetime import datetime
from typing import TypeAlias

from .models import (
    Fact,
    Knowledge,
    MemoryItem,
    MemoryPayload,
    Understanding,
)


def _require_target_item_id(target_item_id: str) -> None:
    if not target_item_id.strip():
        raise ValueError("target_item_id must not be blank")


@dataclass(frozen=True)
class AddMemoryItem:
    """表示是全新的Memory"""

    payload: MemoryPayload


@dataclass(frozen=True)
class EndFactValidity:
    """表示旧Fact有效,当前不再有效"""

    target_item_id: str
    valid_to: datetime

    def __post_init__(self) -> None:
        _require_target_item_id(self.target_item_id)

        if not isinstance(self.valid_to, datetime):
            raise ValueError("valid_to must be a datetime")

    def validate_target(self, target: MemoryItem) -> None:
        """校验该操作能否作用在目标 MemoryItem 上。"""

        if not isinstance(target.payload, Fact):
            raise ValueError("EndFactValidity target must be a Fact")

        valid_from = target.payload.valid_from
        if valid_from is None:
            return

        try:
            precedes_valid_from = self.valid_to < valid_from
        except TypeError as error:
            raise ValueError(
                "EndFactValidity valid_to must use a datetime compatible "
                "with the target Fact"
            ) from error

        if precedes_valid_from:
            raise ValueError(
                "EndFactValidity valid_to must not precede Fact valid_from"
            )


@dataclass(frozen=True)
class SupersedeMemoryItem:
    """表示旧版本的Understanding或knowledge被新版本替代"""

    target_item_id: str
    replacement: MemoryPayload

    def __post_init__(self) -> None:
        _require_target_item_id(self.target_item_id)

    def validate_target(self, target: MemoryItem) -> None:
        """校验该操作能否替代目标 MemoryItem。"""

        if not isinstance(target.payload, (Understanding, Knowledge)):
            raise ValueError(
                "SupersedeMemoryItem target must be an Understanding " "or Knowledge"
            )

        if type(self.replacement) is not type(target.payload):
            raise ValueError(
                "SupersedeMemoryItem replacement must have the same "
                "domain as its target"
            )


@dataclass(frozen=True)
class NoMemoryChange:
    """表示候选已经被现有Memory覆盖,或者不值得形成正式记忆"""

    reason: str | None = None

    def __post_init__(self) -> None:
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank")


MemoryChangeOperation: TypeAlias = (
    AddMemoryItem | EndFactValidity | SupersedeMemoryItem | NoMemoryChange
)


@dataclass(frozen=True)
class MemoryChangePlan:
    """根据最终决定的操作执行"""

    operations: tuple[MemoryChangeOperation, ...]

    def __post_init__(self) -> None:
        self._validate_structure()

    def _validate_structure(self) -> None:
        """校验只依赖 plan 自身的结构不变量。"""

        if not self.operations:
            raise ValueError("memory change plan operations must not be empty")

        add_count = sum(
            isinstance(operation, AddMemoryItem) for operation in self.operations
        )
        supersede_count = sum(
            isinstance(operation, SupersedeMemoryItem) for operation in self.operations
        )
        no_change_count = sum(
            isinstance(operation, NoMemoryChange) for operation in self.operations
        )

        if add_count > 1:
            raise ValueError("memory review plan must not add payload twice")

        if supersede_count > 1:
            raise ValueError("memory review plan must not supersede with payload twice")

        if supersede_count and add_count:
            raise ValueError("memory review plan must not combine supersede and add")

        if no_change_count and len(self.operations) != 1:
            raise ValueError("NoMemoryChange cannot be combined with other operations")

        operated_target_ids: set[str] = set()
        for operation in self.operations:
            if not isinstance(
                operation,
                (EndFactValidity, SupersedeMemoryItem),
            ):
                continue
            if operation.target_item_id in operated_target_ids:
                raise ValueError(
                    "memory change plan must not operate on the same "
                    "target more than once"
                )
            operated_target_ids.add(operation.target_item_id)

    def validate_against(
        self,
        related_items: tuple[MemoryItem, ...],
    ) -> None:
        """校验变更计划引用的已有 Memory 是否存在且领域匹配。"""

        related_by_id = {item.item_id: item for item in related_items}

        for operation in self.operations:
            if not isinstance(
                operation,
                (EndFactValidity, SupersedeMemoryItem),
            ):
                continue

            target = related_by_id.get(operation.target_item_id)

            if target is None:
                raise ValueError(
                    "memory change operation target must reference " "a related item"
                )

            operation.validate_target(target)

