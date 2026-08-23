import json

from .models import (
    Memory,
    MemoryCandidate,
    MemoryUpdateAction,
    MemoryUpdateDecision,
)
from .prompts import MEMORY_UPDATE_PROMPT
from .protocols import MemoryLLMProtocol


class LLMMemoryUpdater:
    """基于 LLM 对候选记忆进行审查并生成更新决策。"""

    def __init__(self, llm: MemoryLLMProtocol) -> None:
        self._llm = llm

    async def decide(
        self,
        candidate: MemoryCandidate,
        existing_memories: list[Memory],
    ) -> MemoryUpdateDecision:
        """负责把检索结果喂给LLM,并生成最终操作的主逻辑"""

        # 生成prompt
        prompt = self._build_prompt(
            candidate,
            existing_memories,
        )

        # 调用LLM生成最终决策
        response = await self._llm.generate(prompt)

        # 格式化结果并返回
        return self._parse_response(
            candidate,
            existing_memories,
            response,
        )

    @staticmethod
    def _build_prompt(
        candidate: MemoryCandidate,
        existing_memories: list[Memory],
    ) -> str:
        """负责组装交给LLM的prompt"""

        memories_text = "\n".join(
            f"- memory_id: {memory.memory_id}\n"
            f"  content: {memory.content}"
            for memory in existing_memories
        ) or "无"

        # 引用配置文件中的prompt
        return MEMORY_UPDATE_PROMPT.format(
            candidate=candidate.content,
            existing_memories=memories_text,
        )

    @staticmethod
    def _parse_response(
        candidate: MemoryCandidate,
        existing_memories: list[Memory],
        response: str,
    ) -> MemoryUpdateDecision:
        """解析JSON,校验是否合法,转换成MemoryUpdateDecision"""

        # 解析JSON结构
        data = json.loads(response)
        if not isinstance(data, dict):
            raise ValueError(
                "memory update response must be a JSON object"
            )

        # 拿到action字符串
        action_value = data.get("action")

        if not isinstance(action_value, str):
            raise ValueError(
                "memory update action must be a string"
            )

        # 自动生成枚举类的字典
        action_map = {action.value: action for action in MemoryUpdateAction}

        # 从枚举类中得到对应的操作
        action = action_map.get(action_value)

        if action is None:
            raise ValueError(
                "invalid memory update action"
            )

        target_memory_id = data.get("target_memory_id")
        content = data.get("content")

        valid_memory_ids = {memory.memory_id for memory in existing_memories}

        # 校验结构,例如ADD必须有target_memory_id字段
        if action is MemoryUpdateAction.ADD:
            if target_memory_id is not None:
                raise ValueError(
                    "ADD target_memory_id must be null"
                )

            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    "ADD requires non-empty content"
                )

        elif action is MemoryUpdateAction.UPDATE:
            if target_memory_id not in valid_memory_ids:
                raise ValueError(
                    "invalid target_memory_id for UPDATE"
                )

            if not isinstance(content, str) or not content.strip():
                raise ValueError(
                    "UPDATE requires non-empty content"
                )

        elif action is MemoryUpdateAction.DELETE:
            if target_memory_id not in valid_memory_ids:
                raise ValueError(
                    "invalid target_memory_id for DELETE"
                )

            if content is not None:
                raise ValueError(
                    "DELETE content must be null"
                )

        elif action is MemoryUpdateAction.NONE:
            if target_memory_id is not None or content is not None:
                raise ValueError(
                    "NONE requires null target_memory_id and content"
                )

        # 返回最终的结果
        return MemoryUpdateDecision(
            action=action,
            candidate=candidate,
            target_memory_id=target_memory_id,
            content=content.strip() if isinstance(content, str) else None,
        )
