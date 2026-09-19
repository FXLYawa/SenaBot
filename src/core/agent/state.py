"""Behavior 使用的数据状态, 一个 Behavior 对应一个 State"""

from __future__ import annotations

from dataclasses import dataclass, replace

from core.common import SceneInfo, SourceInfo, Summary
from core.context import ContextEntryRecord
from core.memory import MemoryItem


@dataclass(frozen=True, slots=True)
class ConversationState:
    """ConversationBehavior 使用的对话数据"""

    user_text: str  # 本轮触发条目的归一化文本
    entries: tuple[ContextEntryRecord, ...]
    summaries: tuple[Summary, ...]
    source: SourceInfo  # 供行为理解发言者身份。
    scene: SceneInfo  # 供行为理解交互场景。
    reply_to_message_id: str | None = None
    memories: tuple[MemoryItem, ...] = ()  # 本轮相关记忆

    def with_memories(self, memories: list[MemoryItem]) -> ConversationState:
        return replace(self, memories=tuple(memories))
