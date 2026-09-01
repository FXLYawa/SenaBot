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
from .prompts import MEMORY_MATERIALIZATION_PROMPT
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

        prompt = _build_prompt(input_data)
        response = await self._llm.generate(prompt)

        #把JSON字符串转换成Payload
        return self._parse_response(response, input_data)

    @classmethod
    def _parse_response(
            cls,
            response: str,
            input_data: MemoryMaterializationInput,
    ) -> MemoryPayload:
        """
        解析 LLM 返回的 Materialization 结果。

        这里只负责校验通用响应结构并根据 domain 分发，
        具体 Payload 的字段解析和对象构造交给对应的私有函数。
        """
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
            return cls._parse_fact(payload_data, input_data)

        if domain is MemoryDomain.EXPERIENCE:
            return cls._parse_experience(payload_data, input_data)

        if domain is MemoryDomain.UNDERSTANDING:
            return cls._parse_understanding(payload_data, input_data)

        return cls._parse_knowledge(payload_data, input_data)

    @staticmethod
    def _require_text(value: Any, field_name: str) -> str:
        """确保输出的部分必须是字符串"""
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

        return value.strip()

    @classmethod
    def _parse_participants(cls, value: Any) -> tuple[Entity, ...]:

        """把参与者的字符串表达转为对象集合"""
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

        """检查evidence_item_ids的格式,收集related_item的ID"""
        if not isinstance(value, list):
            raise ValueError(
                "understanding evidence_item_ids must be a list"
            )

        evidence_item_ids = tuple(
            cls._require_text(item_id, "evidence_item_id")
            for item_id in value
        )

        #收集related_item的ID
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

        """把时间字符串转换为python对象"""
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


    @classmethod
    def _parse_fact(
            cls,
            payload_data: dict[str, Any],
            input_data: MemoryMaterializationInput,
    ) -> Fact:
        """将 LLM 返回的 Fact 字段解析为正式 Fact Payload。"""
        return Fact(
            content=cls._require_text(
                payload_data.get("content"),
                "fact content",
            ),
            provenance=input_data.candidate.provenance,
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

    @classmethod
    def _parse_experience(
            cls,
            payload_data: dict[str, Any],
            input_data: MemoryMaterializationInput,
    ) -> Experience:
        """将 LLM 返回的 Experience 字段解析为正式 Experience Payload。"""
        return Experience(
            summary=cls._require_text(
                payload_data.get("summary"),
                "experience summary",
            ),
            provenance=input_data.candidate.provenance,
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

    @classmethod
    def _parse_understanding(
            cls,
            payload_data: dict[str, Any],
            input_data: MemoryMaterializationInput,
    ) -> Understanding:
        """
        将 LLM 返回的 Understanding 字段解析为正式 Understanding Payload。

        evidence_item_ids 必须引用本次 Materialization 可见的相关记忆，
        具体合法性检查由 _parse_evidence_item_ids 负责。
        """
        return Understanding(
            content=cls._require_text(
                payload_data.get("content"),
                "understanding content",
            ),
            provenance=input_data.candidate.provenance,
            evidence_item_ids=cls._parse_evidence_item_ids(
                payload_data.get("evidence_item_ids"),
                input_data.related_items,
            ),
            recorded_at=input_data.recorded_at,
        )

    @classmethod
    def _parse_knowledge(
            cls,
            payload_data: dict[str, Any],
            input_data: MemoryMaterializationInput,
    ) -> Knowledge:
        """将 LLM 返回的 Knowledge 字段解析为正式 Knowledge Payload。"""
        return Knowledge(
            content=cls._require_text(
                payload_data.get("content"),
                "knowledge content",
            ),
            provenance=input_data.candidate.provenance,
            recorded_at=input_data.recorded_at,
        )

def _build_prompt(
        input_data: MemoryMaterializationInput,
    ) -> str:

        """构造给LLM的上下文,包括候选记忆,记录时间和相关记忆"""
        return MEMORY_MATERIALIZATION_PROMPT.format(
            candidate=input_data.candidate.content,
            recorded_at=input_data.recorded_at.isoformat(),
            related_items=_format_related_items(
                input_data.related_items
            ),
        )

def _format_related_items(
        items: tuple[MemoryItem, ...],
    ) -> str:

        """把related_items转换为给LLM阅读的字符串"""
        if not items:
            return "无"

        return "\n".join(
            f"- item_id: {item.item_id}\n"
            f"  domain: {item.domain.value}\n"
            f"  content: {_payload_text(item.payload)}"
            for item in items
        )

def _payload_text(payload: MemoryPayload) -> str:

    """payload内容适配,Experience的内容是summary,其他是content"""
    if isinstance(payload, Experience):
        return payload.summary

    return payload.content
