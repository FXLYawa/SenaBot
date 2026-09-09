"""Agent 用户回复的 Context 记录与 Body 交付。"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.contracts import ReplyEffect
from core.agent.deliveries.base import PreparedDelivery
from core.body import (
    BodyOutputOptions,
    BodyOutputRequestData,
    OutputReplyInfo,
)
from core.common import Content, OutputRoute, SceneInfo, new_id
from core.context import (
    ContextActorRef,
    ContextActorType,
    ContextAppendRequestData,
    ContextEntryDraft,
    ContextEntryType,
)


@dataclass(frozen=True, slots=True)
class ReplyBinding:
    """回复的输出地址、场景、Context 记录位置及原始事件来源。"""

    route: OutputRoute
    scene: SceneInfo
    context_session_id: str
    source_event_id: str


class ReplyDelivery:
    """保证一条角色回复同时进入主 Context 和目标 Body
    简单来说就是把 ReplyEffect 转换为两个事件：
    - context.append.requested: 角色回复的 ContextEntryDraft
    - body.output.requested: 角色回复的 BodyOutputRequestData
    """

    binding_type = ReplyBinding

    def __init__(self, character_id: str, display_name: str) -> None:
        # 这两个字段主要供 Context 记录说话人(Sena)
        self._character_id = character_id
        self._display_name = display_name

    def prepare(
        self,
        effect: ReplyEffect,
        binding: ReplyBinding,
    ) -> PreparedDelivery:
        """为原始交互构造 Context 记录及 Body 输出，保留 Effect 的引用选择。"""

        if not binding.context_session_id:
            raise ValueError("reply binding requires a context session")
        output_id = new_id("output")
        content = Content.from_text(effect.text)
        # 按回复绑定指定的位置追加原文，并保留此次回复对应的原始事件来源。
        append_request = ContextAppendRequestData(
            session_id=binding.context_session_id,
            entries=(
                ContextEntryDraft(
                    entry_type=ContextEntryType.SENA_MESSAGE,
                    actor=ContextActorRef(
                        actor_type=ContextActorType.SENA,
                        actor_id=self._character_id,
                        display_name=self._display_name,
                    ),
                    content=content,
                    source_event_id=binding.source_event_id,
                ),
            ),
        )
        # Body 使用输入时绑定的回复地址；引用为空时按普通消息输出。
        output_request = BodyOutputRequestData(
            output_id=output_id,
            route=binding.route,
            scene=binding.scene,
            content=content,
            reply_to=OutputReplyInfo(effect.reply_to_message_id)
            if effect.reply_to_message_id
            else None,
            options=BodyOutputOptions(),
            metadata={"presentation": {"state": "speaking"}},
        )
        return PreparedDelivery(
            events=(
                ("context.append.requested", append_request),
                ("body.output.requested", output_request),
            ),
        )
