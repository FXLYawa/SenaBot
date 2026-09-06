"""Agent Memory Effect 到 Memory 公开事件的适配。"""

from __future__ import annotations

from core.agent.contracts import MemoryQueryEffect, MemoryWriteEffect
from core.common import SceneInfo, SceneType
from core.context import ContextActorType, ContextEntryRecord
from core.event import EventFlow
from core.memory.contracts import (
    MemoryQueryRequest,
    MemoryWriteMessage,
    MemoryWriteRequest,
)


MemoryEffect = MemoryQueryEffect | MemoryWriteEffect


class MemoryDelivery:
    """按 Effect 类型发布 Memory 查询或写入请求。"""

    @staticmethod
    def pending_operation_id(effect: MemoryEffect) -> str:
        _request(effect)
        return effect.operation_id

    @staticmethod
    def emit(
        flow: EventFlow,
        effect: MemoryEffect,
    ) -> None:
        event_type = (
            "memory.query.requested"
            if isinstance(effect, MemoryQueryEffect)
            else "memory.write.requested"
        )
        flow.emit(event_type, _request(effect))


def _request(effect: MemoryEffect) -> MemoryQueryRequest | MemoryWriteRequest:
    """把 Agent 的 Memory Effect 转换为 Memory 公开请求。"""

    if isinstance(effect, MemoryQueryEffect):
        return MemoryQueryRequest(
            query_id=effect.operation_id,
            memory_space_id=effect.persona_id,
            group_id=_group_id(effect.scene),
            session_id=effect.session_id,
            user_id=effect.requester.user_id,
            query_text=effect.query,
        )
    return MemoryWriteRequest(
        operation_id=effect.operation_id,
        memory_space_id=effect.persona_id,
        group_id=_group_id(effect.scene),
        session_id=effect.session_id,
        user_id=effect.requester.user_id,
        messages=tuple(_message(entry) for entry in effect.messages),
        recent_messages=tuple(
            _message(entry) for entry in effect.recent_messages
        ),
        summaries=effect.summaries,
        source_event_id=effect.source_event_id,
        recorded_at=effect.recorded_at,
    )


def _group_id(scene: SceneInfo) -> str:
    if scene.scene_type in (SceneType.GROUP, SceneType.CHANNEL):
        return scene.scene_id
    return ""


def _message(entry: ContextEntryRecord) -> MemoryWriteMessage:
    roles = {
        ContextActorType.USER: "user",
        ContextActorType.SENA: "assistant",
        ContextActorType.SYSTEM: "system",
        ContextActorType.TOOL: "tool",
        ContextActorType.EXTENSION: "system",
    }
    return MemoryWriteMessage(
        message_id=entry.entry_id,
        role=roles[entry.actor.actor_type],
        content=entry.content,
    )
