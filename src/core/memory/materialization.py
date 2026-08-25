import json
from datetime import datetime
from typing import Any

from .models import (
    Entity,
    Experience,
    Fact,
    Knowledge,
    MemoryDomain,
    MemoryItem,
    MemoryMaterializationInput,
    MemoryPayload,
    Understanding,
)
from .prompts.materialization import MEMORY_MATERIALIZATION_PROMPT
from .protocols import MemoryLLMProtocol


class LLMMemoryMaterializer:
    """基于 LLM 将候选记忆转换为领域 Payload。"""

    def __init__(self, llm: MemoryLLMProtocol) -> None:
        self._llm = llm

    async def materialize(
        self,
        input_data: MemoryMaterializationInput,
    ) -> MemoryPayload:
        """调用 LLM 判断领域，并构造受领域模型约束的 Payload。"""

        prompt = self._build_prompt(input_data)
        response = await self._llm.generate(prompt)

        return self._parse_response(response, input_data)

    @classmethod
    def _build_prompt(
        cls,
        input_data: MemoryMaterializationInput,
    ) -> str:
        return MEMORY_MATERIALIZATION_PROMPT.format(
            candidate=input_data.candidate.content,
            recorded_at=input_data.recorded_at.isoformat(),
            related_items=cls._format_related_items(
                input_data.related_items
            ),
        )

    @classmethod
    def _format_related_items(
        cls,
        items: tuple[MemoryItem, ...],
    ) -> str:
        if not items:
            return "无"

        return "\n".join(
            f"- item_id: {item.item_id}\n"
            f"  domain: {item.domain.value}\n"
            f"  content: {cls._payload_text(item.payload)}"
            for item in items
        )

    @staticmethod
    def _payload_text(payload: MemoryPayload) -> str:
        if isinstance(payload, Experience):
            return payload.summary

        return payload.content

    @classmethod
    def _parse_response(
        cls,
        response: str,
        input_data: MemoryMaterializationInput,
    ) -> MemoryPayload:
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError(
                "memory materialization response must be a JSON object"
            )

        domain_value = data.get("domain")
        if not isinstance(domain_value, str):
            raise ValueError(
                "memory materialization domain must be a string"
            )

        try:
            domain = MemoryDomain(domain_value)
        except ValueError as error:
            raise ValueError(
                "invalid memory materialization domain"
            ) from error

        payload_data = data.get("payload")
        if not isinstance(payload_data, dict):
            raise ValueError(
                "memory materialization payload must be a JSON object"
            )

        if domain is MemoryDomain.FACT:
            return Fact(
                content=cls._require_text(
                    payload_data.get("content"),
                    "fact content",
                ),
                provenance=input_data.provenance,
                recorded_at=input_data.recorded_at,
                valid_from=cls._parse_optional_datetime(
                    payload_data.get("valid_from"),
                    "fact valid_from",
                ),
                valid_to=cls._parse_optional_datetime(
                    payload_data.get("valid_to"),
                    "fact valid_to",
                ),
            )

        if domain is MemoryDomain.EXPERIENCE:
            return Experience(
                summary=cls._require_text(
                    payload_data.get("summary"),
                    "experience summary",
                ),
                provenance=input_data.provenance,
                participants=cls._parse_participants(
                    payload_data.get("participants")
                ),
                occurred_from=cls._parse_optional_datetime(
                    payload_data.get("occurred_from"),
                    "experience occurred_from",
                ),
                occurred_to=cls._parse_optional_datetime(
                    payload_data.get("occurred_to"),
                    "experience occurred_to",
                ),
                recorded_at=input_data.recorded_at,
            )

        if domain is MemoryDomain.UNDERSTANDING:
            return Understanding(
                content=cls._require_text(
                    payload_data.get("content"),
                    "understanding content",
                ),
                provenance=input_data.provenance,
                evidence_item_ids=cls._parse_evidence_item_ids(
                    payload_data.get("evidence_item_ids"),
                    input_data.related_items,
                ),
                recorded_at=input_data.recorded_at,
            )

        return Knowledge(
            content=cls._require_text(
                payload_data.get("content"),
                "knowledge content",
            ),
            provenance=input_data.provenance,
            recorded_at=input_data.recorded_at,
        )

    @staticmethod
    def _require_text(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

        return value.strip()

    @classmethod
    def _parse_participants(cls, value: Any) -> tuple[Entity, ...]:
        if not isinstance(value, list):
            raise ValueError("experience participants must be a list")

        participants = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError(
                    "experience participant must be a JSON object"
                )

            participants.append(
                Entity(
                    entity_type=cls._require_text(
                        item.get("entity_type"),
                        "participant entity_type",
                    ),
                    entity_id=cls._require_text(
                        item.get("entity_id"),
                        "participant entity_id",
                    ),
                )
            )

        return tuple(participants)

    @classmethod
    def _parse_evidence_item_ids(
        cls,
        value: Any,
        related_items: tuple[MemoryItem, ...],
    ) -> tuple[str, ...]:
        if not isinstance(value, list):
            raise ValueError(
                "understanding evidence_item_ids must be a list"
            )

        evidence_item_ids = tuple(
            cls._require_text(item_id, "evidence_item_id")
            for item_id in value
        )
        valid_item_ids = {item.item_id for item in related_items}

        if any(
            item_id not in valid_item_ids
            for item_id in evidence_item_ids
        ):
            raise ValueError(
                "understanding evidence_item_ids must reference "
                "related items"
            )

        return evidence_item_ids

    @staticmethod
    def _parse_optional_datetime(
        value: Any,
        field_name: str,
    ) -> datetime | None:
        if value is None:
            return None

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field_name} must be an ISO 8601 string or null"
            )

        normalized_value = value.strip()
        if normalized_value.endswith("Z"):
            normalized_value = f"{normalized_value[:-1]}+00:00"

        try:
            return datetime.fromisoformat(normalized_value)
        except ValueError as error:
            raise ValueError(
                f"{field_name} must be an ISO 8601 string or null"
            ) from error
