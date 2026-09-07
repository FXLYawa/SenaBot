from collections.abc import Callable
from uuid import uuid4

from core.model import (
    ModelMessage,
    ModelProvider,
    ModelRequest,
    parse_json_response,
    render_prompt,
    require_complete_response,
)

from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionMessage,
)


def _new_candidate_id() -> str:
    return str(uuid4())


class LLMMemoryExtractor:
    """基于 LLM 的长期记忆候选提取器。"""

    def __init__(
        self,
        provider: ModelProvider,
        candidate_id_factory: Callable[[], str] = _new_candidate_id,
    ) -> None:
        self._provider = provider
        self._candidate_id_factory = candidate_id_factory

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        """调用 LLM，从当前消息中提取候选长期记忆。"""

        prompt = self._build_prompt(context)
        response = await self._provider.generate(
            ModelRequest(messages=(ModelMessage(role="user", content=prompt),))
        )
        require_complete_response(response)

        return self._parse_response(response.text, context)

    def _build_prompt(
        self,
        context: MemoryExtractionContext,
    ) -> str:
        """构建用于候选记忆提取的 Prompt。"""

        summary = context.summary or "无"

        recent_messages = self._format_messages(context.recent_messages)

        new_messages = self._format_messages(context.new_messages)

        return render_prompt(
            "core.memory.prompts",
            "extraction.txt",
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

        lines = []
        for message in messages:
            facts = []
            if message.actor_id is not None:
                facts.append(f"actor_id={message.actor_id}")
            if message.display_name:
                facts.append(f"name={message.display_name}")
            if message.created_at is not None:
                facts.append(f"created_at={message.created_at.isoformat()}")
            metadata = f" ({', '.join(facts)})" if facts else ""
            lines.append(f"[{message.message_id}] {message.role}{metadata}: {message.content}")
        return "\n".join(lines)

    def _parse_response(
        self,
        response: str,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        """将 LLM 返回的 JSON 转换为候选记忆。"""

        data = parse_json_response(response)

        if not isinstance(data, dict):
            raise ValueError("memory extraction response must be a JSON object")

        memories = data.get("memories")

        if not isinstance(memories, list):
            raise ValueError("memory extraction memories must be a JSON array")

        valid_source_message_ids = {
            message.message_id for message in context.new_messages
        }

        candidates = []
        for item in memories:
            if not isinstance(item, dict):
                raise ValueError("memory extraction candidate must be a JSON object")

            content = item.get("content")
            source_message_ids = item.get("source_message_ids")

            if not isinstance(content, str) or not content.strip():
                raise ValueError("memory extraction candidate content must not be blank")

            if (
                not isinstance(source_message_ids, list)
                or not source_message_ids
                or any(
                    not isinstance(message_id, str) or not message_id.strip()
                    for message_id in source_message_ids
                )
            ):
                raise ValueError("memory extraction candidate requires source_message_ids")

            normalized_source_ids = tuple(
                dict.fromkeys(message_id.strip() for message_id in source_message_ids)
            )

            if any(
                message_id not in valid_source_message_ids
                for message_id in normalized_source_ids
            ):
                raise ValueError(
                    "memory candidate source_message_ids must reference " "new messages"
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
