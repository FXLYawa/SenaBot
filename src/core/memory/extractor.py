import json

from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionMessage,
)
from .prompts import MEMORY_EXTRACTION_PROMPT
from .protocols import MemoryLLMProtocol


class LLMMemoryExtractor:
    """基于 LLM 的长期记忆候选提取器。"""

    def __init__(self, llm: MemoryLLMProtocol) -> None:
        self._llm = llm

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        """调用 LLM，从当前消息中提取候选长期记忆。"""

        prompt = self._build_prompt(context)
        response = await self._llm.generate(prompt)

        return self._parse_response(response)

    def _build_prompt(
        self,
        context: MemoryExtractionContext,
    ) -> str:
        """将提取上下文填充到记忆提取 Prompt 中。"""

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
            f"{message.role}: {message.content}"
            for message in messages
        )

    def _parse_response(
        self,
        response: str,
    ) -> list[MemoryCandidate]:
        """将 LLM 返回的 JSON 转换为候选记忆。"""

        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError(
                "memory extraction response must be a JSON object"
            )

        memories = data.get("memories", [])

        return [
            MemoryCandidate(
                content=item["content"].strip(),
            )
            for item in memories
            if isinstance(item, dict)
            and isinstance(item.get("content"), str)
            and item["content"].strip()
        ]
