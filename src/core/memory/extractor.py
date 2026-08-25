import json
from collections.abc import Callable
from uuid import uuid4

from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionMessage,
)
from .prompts.extraction import MEMORY_EXTRACTION_PROMPT
from .protocols import MemoryLLMProtocol


def _new_candidate_id() -> str:
    return str(uuid4())


class LLMMemoryExtractor:
    """基于 LLM 的长期记忆候选提取器。"""

    def __init__(
        self,
        llm: MemoryLLMProtocol,
        candidate_id_factory: Callable[[], str] = _new_candidate_id,
    ) -> None:
        self._llm = llm
        self._candidate_id_factory = candidate_id_factory

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        """调用 LLM，从当前消息中提取候选长期记忆。"""

        prompt = self._build_prompt(context)
        response = await self._llm.generate(prompt)

        return self._parse_response(response, context)

    def _build_prompt(
        self,
        context: MemoryExtractionContext,
    ) -> str:
        """构建用于候选记忆提取的 Prompt。"""

        summary = context.summary or "无"

        recent_messages = self._format_messages(
            context.recent_messages
        )

        new_messages = self._format_messages(
            context.new_messages
        )

        return MEMORY_EXTRACTION_PROMPT.format(
            summary=summary,
            recent_messages=recent_messages,
            new_messages=new_messages,
        )

    def _format_messages(
        self,
        messages: list[MemoryExtractionMessage],
    ) -> str:
        """将消息列表转换为适合放入 Prompt 的文本。"""

        if not messages:
            return "无"

        return "\n".join(
            f"[{message.message_id}] {message.role}: {message.content}"
            for message in messages
        )

    def _parse_response(
        self,
        response: str,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        """将 LLM 返回的 JSON 转换为候选记忆。"""

        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError(
                "memory extraction response must be a JSON object"
            )

        memories = data.get("memories", [])

        if not isinstance(memories, list):
            raise ValueError(
                "memory extraction memories must be a JSON array"
            )

        valid_source_message_ids = {
            message.message_id
            for message in context.new_messages
        }

        candidates = []
        for item in memories:
            if not isinstance(item, dict):
                continue

            content = item.get("content")
            source_message_ids = item.get("source_message_ids")

            if not isinstance(content, str) or not content.strip():
                continue

            if (
                not isinstance(source_message_ids, list)
                or not source_message_ids
                or any(
                    not isinstance(message_id, str)
                    or not message_id.strip()
                    for message_id in source_message_ids
                )
            ):
                continue

            normalized_source_ids = tuple(
                dict.fromkeys(
                    message_id.strip()
                    for message_id in source_message_ids
                )
            )

            if any(
                message_id not in valid_source_message_ids
                for message_id in normalized_source_ids
            ):
                raise ValueError(
                    "memory candidate source_message_ids must reference "
                    "new messages"
                )

            candidates.append(
                MemoryCandidate(
                    candidate_id=self._candidate_id_factory(),
                    content=content.strip(),
                    provenance=context.provenance,
                    source_message_ids=normalized_source_ids,
                )
            )

        return candidates
