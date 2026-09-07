"""Context 原始记录到 Memory 文本输入、来源和作用域的边界转换。"""

from __future__ import annotations

from core.common import SceneType, Summary
from core.context import ContextActorType, ContextEntryRecord, SessionRecord
from core.memory.models import (
    MemoryExtractionMessage,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
)


def to_extraction_messages(
    entries: tuple[ContextEntryRecord, ...],
) -> list[MemoryExtractionMessage]:
    """将 Context 条目转换为提取器消息，保留原文 ID、发言者和时间。"""

    # 将 Context 发言者类型映射成提取器的消息角色，具体身份仍单独保留。
    roles = {
        ContextActorType.USER: "user",
        ContextActorType.SENA: "assistant",
        ContextActorType.SYSTEM: "system",
        ContextActorType.TOOL: "tool",
        ContextActorType.EXTENSION: "system",
    }
    # 提取 Content 的文本表示，与原文 ID、发言者和时间一起构造消息。
    return [
        MemoryExtractionMessage(
            message_id=entry.entry_id,
            role=roles[entry.actor.actor_type],
            content=entry.content.text_value(),
            actor_id=entry.actor.actor_id,
            display_name=entry.actor.display_name,
            created_at=entry.created_at,
        )
        for entry in entries
    ]


def context_entry_provenance(
    entries: tuple[ContextEntryRecord, ...],
) -> tuple[Provenance, ...]:
    """从传入的原始条目构造条目级和事件级的来源集合。"""

    # 为整批目标条目或候选引用的条目子集，逐条生成原文来源标识。
    sources = [Provenance("context_entry", entry.entry_id) for entry in entries]
    # 同一个输入事件可能产生多条记录：条目分别保留，事件来源按首次出现顺序去重。
    sources.extend(
        Provenance("event", source_id)
        for source_id in dict.fromkeys(entry.source_event_id for entry in entries)
        if source_id is not None
    )
    return tuple(sources)


def to_extraction_summary(
    summaries: tuple[Summary, ...],
) -> str | None:
    """把多级公开摘要渲染为 Extraction 当前消费的摘要文本。"""

    # 空文本摘要保留历史展开关系，但不参与语义提取。
    semantic_summaries = tuple(summary for summary in summaries if summary.text.strip())
    if not semantic_summaries:
        return None

    ordered = sorted(
        semantic_summaries,
        key=lambda summary: (
            summary.first_sequence,
            summary.level,
            summary.last_sequence,
        ),
    )
    return "\n\n".join(
        f"[level={summary.level} "
        f"range={summary.first_sequence}-{summary.last_sequence}]\n"
        f"{summary.text}"
        for summary in ordered
    )


def extraction_scopes(user_id: str, session: SessionRecord) -> frozenset[MemoryScopeRef]:
    """提取来源的记忆归属和 Formation 查重范围。"""

    # 使用配置绑定的用户和当前会话构造归属范围，群组或频道场景再加入群组范围。
    scopes = {
        MemoryScopeRef(
            kind=MemoryScopeKind.USER,
            scope_id=user_id,
        ),
        MemoryScopeRef(
            kind=MemoryScopeKind.SESSION,
            scope_id=session.session_id,
        ),
    }
    if session.scene is not None and session.scene.scene_type in (SceneType.GROUP, SceneType.CHANNEL):
        scopes.add(
            MemoryScopeRef(
                kind=MemoryScopeKind.GROUP,
                scope_id=session.scene.scene_id,
            )
        )
    return frozenset(scopes)
