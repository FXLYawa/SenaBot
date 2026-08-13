import json

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
        负责将原始消息,最近m条消息,历史summary，捏合成prompt

        """
        summary = context.summary or "无"

        recent_messages = self._format_messages(context.recent_messages)
        new_messages = self._format_messages(context.new_messages)

        return f"""
你负责从当前的新消息中提取可能值得长期保存的用户信息。

历史摘要和最近消息只用于帮助理解当前消息，
不能直接作为本次新记忆的来源。

要求：
1. 只提取能够由当前新消息支持的信息。
2. 每条记忆只表达一个独立事实。
3. 不进行无依据推断。
4. 没有值得记录的信息时返回空列表。
5. 仅返回 JSON，不要输出其他内容。
6. Assistant 的内容只能用于帮助理解用户消息，不得把 Assistant 的推测、建议或未经用户确认的信息作为用户事实提取。

输出格式：
{{
  "memories": [
    {{
      "content": "..."
    }}
  ]
}}

历史摘要：
{summary}

最近消息：
{recent_messages}

当前新消息：
{new_messages}
""".strip()

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
