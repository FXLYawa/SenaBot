"""Agent Memory Effect 到 Memory 公开事件的适配。"""

from __future__ import annotations

from core.agent.contracts import MemoryQueryEffect
from core.common import SceneInfo, SceneType
from core.event import EventFlow
from core.memory import MemoryQueryRequest


class MemoryDelivery:
    """将 Agent 的记忆查询意图交给 Memory，不负责触发原始记录提取。"""

    @staticmethod
    def pending_operation_id(effect: MemoryQueryEffect) -> str:
        _request(effect)
        return effect.operation_id

    @staticmethod
    def emit(
        flow: EventFlow,
        effect: MemoryQueryEffect,
    ) -> None:
        flow.emit("memory.query.requested", _request(effect))


def _request(effect: MemoryQueryEffect) -> MemoryQueryRequest:
    """把 Agent 的 Memory Effect 转换为 Memory 公开请求。"""

    return MemoryQueryRequest(
        query_id=effect.operation_id,
        memory_space_id=effect.persona_id,
        group_id=_group_id(effect.scene),
        session_id=effect.session_id,
        user_id=effect.requester.user_id,
        query_text=effect.query,
    )


def _group_id(scene: SceneInfo) -> str:
    if scene.scene_type in (SceneType.GROUP, SceneType.CHANNEL):
        return scene.scene_id
    return ""
