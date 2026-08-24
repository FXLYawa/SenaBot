"""Agent Memory Effect 到 Memory 公开事件的适配。"""

from __future__ import annotations

from core.agent.contracts import MemoryQueryEffect, MemoryWriteEffect
from core.event import EventFlow
from core.memory.contracts import MemoryQueryRequest, MemoryWriteRequest


MemoryEffect = MemoryQueryEffect | MemoryWriteEffect


class MemoryDelivery:
    """按 Effect 类型发布 Memory 查询或写入请求。"""

    @staticmethod
    def pending_operation_id(effect: MemoryEffect) -> str:
        return effect.operation_id

    @staticmethod
    def emit(
        flow: EventFlow,
        effect: MemoryEffect,
        operation_id: str | None,
    ) -> None:
        if operation_id is None:
            raise ValueError("MemoryEffect requires a pending operation ID")
        if isinstance(effect, MemoryQueryEffect):
            flow.emit(
                "memory.query.requested",
                MemoryQueryRequest(
                    query_id=operation_id,
                    group_id=effect.scene_id or "",
                    session_id=effect.session_id or "",
                    user_id=effect.requester.user_id,
                    query_text=effect.query,
                ),
            )
            return
        flow.emit(
            "memory.write.requested",
            MemoryWriteRequest(
                operation_id=operation_id,
                group_id=effect.scene.scene_id,
                session_id=effect.session_id or "",
                user_id=effect.requester.user_id,
                source_event_id=effect.source_entry_id,
                write_text=effect.text,
            ),
        )
