import json
from .prompts.extraction import MEMORY_EXTRACTION_PROMPT

from .models import (
    MemoryCandidate,
    MemoryExtractionContext,
    MemoryExtractionMessage,
)
from .protocols import MemoryLLMProtocol


class LLMMemoryExtractor:
    """基于 LLM 的长期记忆候选提取器。"""

    def __init__(self, llm: MemoryLLMProtocol) -> None:
        self._llm = llm

    async def extract(
        self,
        context: MemoryExtractionContext,
    ) -> list[MemoryCandidate]:
        """
        llm返回总结结果
        """
        prompt = self._build_prompt(context)
        response = await self._llm.generate(prompt)

        return self._parse_response(response)

    def _build_prompt(
            self,
            context: MemoryExtractionContext,
    ) -> str:
        """
        负责将上下文填充到 Memory extraction prompt
        """
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

        """输入适配"""
        if not messages:
            return "无"

        return "\n".join(f"{message.role}: {message.content}" for message in messages)

    def _parse_response(
        self,
        response: str,
    ) -> list[MemoryCandidate]:

        """
        输出适配
        """
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError("memory extraction response must be a JSON object")

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
