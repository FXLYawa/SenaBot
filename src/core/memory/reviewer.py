import json
from typing import Any

from .change_plan import (
    AddMemoryItem,
    EndFactValidity,
    MemoryChangeOperation,
    MemoryChangePlan,
    NoMemoryChange,
    SupersedeMemoryItem,
    validate_memory_change_plan,
)
from .models import (
    Entity,
    Experience,
    Fact,
    MemoryItem,
    MemoryPayload,
    MemoryReviewInput,
)
from .prompts.review import MEMORY_REVIEW_PROMPT
from .protocols import MemoryLLMProtocol


class LLMMemoryReviewer:
    """基于 LLM 判断已成形 Payload 与已有记忆的关系。"""

    def __init__(self, llm: MemoryLLMProtocol) -> None:
        self._llm = llm

    async def review(
        self,
        input_data: MemoryReviewInput,
    ) -> MemoryChangePlan:
        prompt = self._build_prompt(input_data)
        response = await self._llm.generate(prompt)

        plan = self._parse_response(response, input_data.payload)
        validate_memory_change_plan(plan, input_data.related_items)

        return plan

    @classmethod
    def _build_prompt(cls, input_data: MemoryReviewInput) -> str:
        return MEMORY_REVIEW_PROMPT.format(
            payload=json.dumps(
                cls._payload_data(input_data.payload),
                ensure_ascii=False,
                indent=2,
            ),
            related_items=json.dumps(
                [
                    {
                        "item_id": item.item_id,
                        **cls._payload_data(item.payload),
                    }
                    for item in input_data.related_items
                ],
                ensure_ascii=False,
                indent=2,
            ),
        )

    @staticmethod
    def _payload_data(payload: MemoryPayload) -> dict[str, Any]:
        if isinstance(payload, Fact):
            return {
                "domain": payload.DOMAIN.value,
                "content": payload.content,
                "valid_from": (
                    payload.valid_from.isoformat()
                    if payload.valid_from is not None
                    else None
                ),
                "valid_to": (
                    payload.valid_to.isoformat()
                    if payload.valid_to is not None
                    else None
                ),
                "recorded_at": payload.recorded_at.isoformat(),
            }

        if isinstance(payload, Experience):
            return {
                "domain": payload.DOMAIN.value,
                "summary": payload.summary,
                "participants": [
                    LLMMemoryReviewer._entity_data(participant)
                    for participant in payload.participants
                ],
                "occurred_from": (
                    payload.occurred_from.isoformat()
                    if payload.occurred_from is not None
                    else None
                ),
                "occurred_to": (
                    payload.occurred_to.isoformat()
                    if payload.occurred_to is not None
                    else None
                ),
                "recorded_at": payload.recorded_at.isoformat(),
            }

        return {
            "domain": payload.DOMAIN.value,
            "content": payload.content,
            "recorded_at": payload.recorded_at.isoformat(),
        }

    @staticmethod
    def _entity_data(entity: Entity) -> dict[str, str]:
        return {
            "entity_type": entity.entity_type,
            "entity_id": entity.entity_id,
        }

    @classmethod
    def _parse_response(
        cls,
        response: str,
        payload: MemoryPayload,
    ) -> MemoryChangePlan:
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError("memory review response must be a JSON object")

        operations_data = data.get("operations")
        if not isinstance(operations_data, list):
            raise ValueError("memory review operations must be a list")

        operations = tuple(
            cls._parse_operation(operation_data, payload)
            for operation_data in operations_data
        )
        plan = MemoryChangePlan(operations=operations)
        cls._validate_payload_operations(plan, payload)

        return plan

    @classmethod
    def _parse_operation(
        cls,
        data: Any,
        payload: MemoryPayload,
    ) -> MemoryChangeOperation:
        if not isinstance(data, dict):
            raise ValueError(
                "memory review operation must be a JSON object"
            )

        operation_type = data.get("type")
        if not isinstance(operation_type, str):
            raise ValueError("memory review operation type must be a string")

        allowed_fields = {
            "add": {"type"},
            "end_fact_validity": {"type", "target_item_id"},
            "supersede": {"type", "target_item_id"},
            "no_change": {"type", "reason"},
        }
        operation_fields = allowed_fields.get(operation_type)

        if operation_fields is None:
            raise ValueError("invalid memory review operation type")

        if set(data) - operation_fields:
            raise ValueError(
                "memory review operation contains unsupported fields"
            )

        if operation_type == "add":
            return AddMemoryItem(payload=payload)

        if operation_type == "end_fact_validity":
            if not isinstance(payload, Fact):
                raise ValueError(
                    "end_fact_validity requires a Fact payload"
                )

            return EndFactValidity(
                target_item_id=cls._require_text(
                    data.get("target_item_id"),
                    "target_item_id",
                ),
                valid_to=payload.valid_from or payload.recorded_at,
            )

        if operation_type == "supersede":
            return SupersedeMemoryItem(
                target_item_id=cls._require_text(
                    data.get("target_item_id"),
                    "target_item_id",
                ),
                replacement=payload,
            )

        reason = data.get("reason")
        if reason is not None:
            reason = cls._require_text(reason, "reason")

        return NoMemoryChange(reason=reason)

    @staticmethod
    def _validate_payload_operations(
        plan: MemoryChangePlan,
        payload: MemoryPayload,
    ) -> None:
        add_count = sum(
            isinstance(operation, AddMemoryItem)
            for operation in plan.operations
        )
        supersede_count = sum(
            isinstance(operation, SupersedeMemoryItem)
            for operation in plan.operations
        )

        if add_count > 1:
            raise ValueError("memory review plan must not add payload twice")

        if supersede_count > 1:
            raise ValueError(
                "memory review plan must not supersede with payload twice"
            )

        if isinstance(payload, Fact):
            allowed_types = (
                AddMemoryItem,
                EndFactValidity,
                NoMemoryChange,
            )
        elif isinstance(payload, Experience):
            allowed_types = (AddMemoryItem, NoMemoryChange)
        else:
            allowed_types = (
                AddMemoryItem,
                SupersedeMemoryItem,
                NoMemoryChange,
            )

        if any(
            not isinstance(operation, allowed_types)
            for operation in plan.operations
        ):
            raise ValueError(
                "memory review operation is not allowed for payload domain"
            )

        if supersede_count and add_count:
            raise ValueError(
                "memory review plan must not combine supersede and add"
            )

    @staticmethod
    def _require_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

        return value.strip()
