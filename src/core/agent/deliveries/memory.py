"""Agent Memory Effect 到 Memory 公开事件的适配。"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.contracts import MemoryQueryEffect, PendingOperation
from core.agent.deliveries.base import PreparedDelivery
from core.common import SceneInfo, SceneType, SourceInfo, new_id
from core.memory import MemoryQueryRequest


@dataclass(frozen=True, slots=True)
class MemoryQueryBinding:
    """本次运行查询记忆时使用的请求者身份、会话和场景范围。"""

    requester: SourceInfo
    session_id: str
    scene: SceneInfo


class MemoryDelivery:
    """将 Agent 的记忆查询意图交给 Memory，不负责触发原始记录提取。"""

    binding_type = MemoryQueryBinding

    def __init__(self, memory_space_id: str) -> None:
        self._memory_space_id = memory_space_id

    def prepare(
        self,
        effect: MemoryQueryEffect,
        binding: MemoryQueryBinding,
    ) -> PreparedDelivery:
        """按查询绑定构造检索范围，使用同一查询 ID 关联请求与等待。"""

        if not binding.session_id:
            raise ValueError("memory query binding requires a session")
        operation_id = new_id("op_memory_query")
        request = MemoryQueryRequest(
            query_id=operation_id,
            memory_space_id=self._memory_space_id,
            group_id=_group_id(binding.scene),
            session_id=binding.session_id,
            user_id=binding.requester.user_id,
            query_text=effect.query,
        )
        return PreparedDelivery(
            events=(("memory.query.requested", request),),
            pending_operation=PendingOperation(
                operation_id=operation_id,
                request_key=effect.request_key,
            ),
        )


def _group_id(scene: SceneInfo) -> str:
    if scene.scene_type in (SceneType.GROUP, SceneType.CHANNEL):
        return scene.scene_id
    return ""
