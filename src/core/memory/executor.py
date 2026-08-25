from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from .change_plan import (
    AddMemoryItem,
    EndFactValidity,
    MemoryChangePlan,
    NoMemoryChange,
    SupersedeMemoryItem,
    validate_memory_change_plan,
)
from .models import (
    MemoryItem,
    MemoryPayload,
    MemoryScopeKind,
    MemoryScopeRef,
    MemorySupersedeResult,
    MemoryWriteEnvelope,
)
from .protocols import MemoryChangeRepositoryProtocol


def _new_item_id() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class MemoryChangeExecutionInput:
    """将变更计划转换为正式写入命令所需的上下文。"""

    plan: MemoryChangePlan
    related_items: tuple[MemoryItem, ...]
    memory_space_id: str
    scopes: frozenset[MemoryScopeRef]
    operation_id: str

    def __post_init__(self) -> None:
        """拒绝明显无效的上下文"""
        if not self.memory_space_id.strip():
            raise ValueError("memory_space_id must not be blank")

        if not self.scopes:
            raise ValueError("memory scopes must not be empty")

        has_global_scope = any(
            scope.kind is MemoryScopeKind.GLOBAL
            for scope in self.scopes
        )
        if has_global_scope and len(self.scopes) != 1:
            raise ValueError(
                "global scope cannot be combined with other scopes"
            )

        if not self.operation_id.strip():
            raise ValueError("operation_id must not be blank")


@dataclass(frozen=True)
class MemoryChangeExecutionResult:
    """变更计划经 Repository 端口执行后的领域结果。"""

    added_items: tuple[MemoryItem, ...] = ()
    updated_items: tuple[MemoryItem, ...] = ()


class MemoryChangeExecutor:
    """校验变更计划并通过 Repository 端口执行领域操作。"""

    def __init__(
        self,
        repository: MemoryChangeRepositoryProtocol,
        item_id_factory: Callable[[], str] = _new_item_id,
    ) -> None:
        self._repository = repository
        self._item_id_factory = item_id_factory

    async def execute(
        self,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryChangeExecutionResult:
        """主逻辑,负责将执行最终入库操作"""

        validate_memory_change_plan(
            input_data.plan,
            input_data.related_items,
        )

        added_items: list[MemoryItem] = []
        updated_items: list[MemoryItem] = []

        for operation in input_data.plan.operations:

            # 不值得写入或者已经被已有记忆覆盖。
            if isinstance(operation, NoMemoryChange):
                continue

            # 直接添加正式 MemoryItem。
            if isinstance(operation, AddMemoryItem):
                added_items.append(
                    await self._execute_add(operation, input_data)
                )
                continue

            # 结束旧 Fact 的有效期。
            if isinstance(operation, EndFactValidity):
                updated_items.append(
                    await self._execute_end_fact_validity(
                        operation,
                        input_data,
                    )
                )
                continue
            # 使用新 Understanding 或 Knowledge 替代旧版本。
            if isinstance(operation, SupersedeMemoryItem):
                result = await self._execute_supersede(
                    operation,
                    input_data,
                )
                updated_items.append(result.previous_item)
                added_items.append(result.replacement_item)
                continue

            raise TypeError(
                f"unsupported memory change operation: {type(operation)!r}"
            )

        return MemoryChangeExecutionResult(
            added_items=tuple(added_items),
            updated_items=tuple(updated_items),
        )

    async def _execute_add(
        self,
        operation: AddMemoryItem,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryItem:
        """组装新增记忆并交给持久化端口。"""
        return await self._repository.add(
            self._build_envelope(operation.payload, input_data)
        )

    async def _execute_end_fact_validity(
        self,
        operation: EndFactValidity,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryItem:
        return await self._repository.end_fact_validity(
            operation_id=input_data.operation_id,
            target_item_id=operation.target_item_id,
            valid_to=operation.valid_to,
        )

    async def _execute_supersede(
        self,
        operation: SupersedeMemoryItem,
        input_data: MemoryChangeExecutionInput,
    ) -> MemorySupersedeResult:
        return await self._repository.supersede(
            operation_id=input_data.operation_id,
            target_item_id=operation.target_item_id,
            replacement=self._build_envelope(
                operation.replacement,
                input_data,
            ),
        )

    def _build_envelope(
        self,
        payload: MemoryPayload,
        input_data: MemoryChangeExecutionInput,
    ) -> MemoryWriteEnvelope:
        return MemoryWriteEnvelope(
            operation_id=input_data.operation_id,
            item=MemoryItem(
                item_id=self._item_id_factory(),
                memory_space_id=input_data.memory_space_id,
                scopes=input_data.scopes,
                payload=payload,
            ),
        )
