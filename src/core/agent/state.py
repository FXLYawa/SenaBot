"""Behavior 使用的数据状态, 一个 Behavior 对应一个 State"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.context import ContextPreparedEventData
from core.memory.contracts import Memory


@dataclass(frozen=True, slots=True)
class ConversationState:
    """ConversationBehavior 使用的对话数据"""

    prepared: ContextPreparedEventData  # 当前对话上下文快照
    user_text: str  # 本轮触发条目的归一化文本
    memories: tuple[Memory, ...] = ()  # 本轮相关记忆

    def with_memories(self, memories: list[Memory]) -> ConversationState:
        return replace(self, memories=tuple(memories))
