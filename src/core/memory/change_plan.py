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


@dataclass(frozen=True)
class SupersedeMemoryItem:
    """表示旧版本的Understanding或knowledge被新版本替代"""

    target_item_id: str
    replacement: MemoryPayload

    def __post_init__(self) -> None:
        _require_target_item_id(self.target_item_id)


@dataclass(frozen=True)
class NoMemoryChange:
    """表示候选已经被现有Memory覆盖,或者不值得形成正式记忆"""

    reason: str | None = None

    def __post_init__(self) -> None:
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank")


MemoryChangeOperation: TypeAlias = (
    AddMemoryItem
    | EndFactValidity
    | SupersedeMemoryItem
    | NoMemoryChange
)


@dataclass(frozen=True)
class MemoryChangePlan:
    """根据最终决定的操作执行"""

    operations: tuple[MemoryChangeOperation, ...]

    def __post_init__(self) -> None:
        if not self.operations:
            raise ValueError(
                "memory change plan operations must not be empty"
            )

        no_change_count = sum(
            isinstance(operation, NoMemoryChange)
            for operation in self.operations
        )

        if no_change_count and len(self.operations) != 1:
            raise ValueError(
                "NoMemoryChange cannot be combined with other operations"
            )


def validate_memory_change_plan(
    plan: MemoryChangePlan,
    related_items: tuple[MemoryItem, ...],
) -> None:
    """校验变更计划引用的目标及领域生命周期是否合法。"""

    related_by_id = {
        item.item_id: item
        for item in related_items
    }
    operated_target_ids: set[str] = set()

    for operation in plan.operations:
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
        target = related_by_id.get(operation.target_item_id)

        if target is None:
            raise ValueError(
                "memory change operation target must reference "
                "a related item"
            )

        if isinstance(operation, EndFactValidity):
            _validate_end_fact_validity(operation, target)
            continue

        _validate_supersede(operation, target)


def _validate_end_fact_validity(
    operation: EndFactValidity,
    target: MemoryItem,
) -> None:
    if not isinstance(target.payload, Fact):
        raise ValueError("EndFactValidity target must be a Fact")

    valid_from = target.payload.valid_from
    if valid_from is None:
        return

    try:
        precedes_valid_from = operation.valid_to < valid_from
    except TypeError as error:
        raise ValueError(
            "EndFactValidity valid_to must use a datetime compatible "
            "with the target Fact"
        ) from error

    if precedes_valid_from:
        raise ValueError(
            "EndFactValidity valid_to must not precede Fact valid_from"
        )


def _validate_supersede(
    operation: SupersedeMemoryItem,
    target: MemoryItem,
) -> None:
    if not isinstance(target.payload, (Understanding, Knowledge)):
        raise ValueError(
            "SupersedeMemoryItem target must be an Understanding "
            "or Knowledge"
        )

    if type(operation.replacement) is not type(target.payload):
        raise ValueError(
            "SupersedeMemoryItem replacement must have the same "
            "domain as its target"
        )
