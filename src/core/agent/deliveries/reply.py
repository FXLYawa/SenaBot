"""Agent 用户回复的 Context 记录与 Body 交付。"""

from __future__ import annotations

from core.agent.contracts import ReplyEffect
from core.agent.others import (
    BodyOutputOptions,
    BodyOutputRequestData,
    OutputReplyInfo,
)
from core.common import Content, new_id
from core.context import (
    ContextActorRef,
    ContextActorType,
    ContextAppendRequestData,
    ContextEntryDraft,
    ContextEntryType,
)
from core.event import EventFlow


class ReplyDelivery:
    """保证一条角色回复同时进入主 Context 和目标 Body
    简单来说就是把 ReplyEffect 转换为两个事件：
    - context.append.requested: 角色回复的 ContextEntryDraft
    - body.output.requested: 角色回复的 BodyOutputRequestData
    """

    def __init__(self, character_id: str, display_name: str) -> None:
        # 这两个字段主要供 Context 记录说话人(Sena)
        self._character_id = character_id
        self._display_name = display_name

    @staticmethod
    def pending_operation_id(effect: ReplyEffect) -> None:
        """无需等待，所以直接返回None"""

        return None


    def emit(
        self,
        flow: EventFlow,
        effect: ReplyEffect,
    ) -> None:
        """发布角色回复的 Context 记录和 Body 输出请求事件"""
        
        output_id = new_id("output")
        content = Content.from_text(effect.text)
        # 发布 Context 追加请求事件，确保角色回复被记录在主对话中
        flow.emit(
            "context.append.requested",
            ContextAppendRequestData(
                session_id=effect.session_id,
                entries=(
                    ContextEntryDraft(
                        entry_type=ContextEntryType.SENA_MESSAGE,
                        actor=ContextActorRef(
                            actor_type=ContextActorType.SENA,
                            actor_id=self._character_id,
                            display_name=self._display_name,
                        ),
                        content=content,
                        source_event_id=effect.trigger_event_id,
                    ),
                ),
            ),
        )
        # 发布 Body 输出请求事件，确保角色回复被交付到目标输出
        flow.emit(
            "body.output.requested",
            BodyOutputRequestData(
                output_id=output_id,
                route=effect.output_route,
                scene=effect.scene,
                content=content,
                reply_to=OutputReplyInfo(effect.reply_to_message_id)
                if effect.reply_to_message_id
                else None,
                options=BodyOutputOptions(),
                metadata={"presentation": {"state": "speaking"}},
            ),
        )
