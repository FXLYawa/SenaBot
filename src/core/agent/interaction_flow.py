"""将外部交互转换为具体 Behavior Run。"""

from __future__ import annotations

from core.agent.contracts import (
    CONVERSATION_BEHAVIOR,
    AgentInteractionIgnoredEventData,
    AgentRunRequestEventData,
)
from core.agent.interaction import InteractionPolicy
from core.agent.state import ConversationState
from core.agent.common import new_id
from core.context import ContextEntryRecord, ContextPreparedEventData
from core.event import EventFlow


class InteractionFlow:
    """把 Context 交互转换为 AgentRun 请求，不处理 Run 生命周期。"""

    def __init__(
        self,
        interaction: InteractionPolicy,
    ) -> None:
        self._interaction = interaction # 交互策略

    async def handle_context_prepared(self, flow: EventFlow) -> None:
        """参与当前输入时创建主对话 Behavior 的初始 State。
        context.prepared 事件处理器
        """

        prepared: ContextPreparedEventData = flow.payload
        # 决定是否进行交互
        participation = self._interaction.decide(prepared)
        # 不参与交互
        if not participation.participate:
            flow.emit(
                "agent.interaction.ignored",
                AgentInteractionIgnoredEventData(
                    session_id=prepared.session_id,
                    reason=participation.reason,
                ),
            )
            return
        # 参与交互，创建主对话 Run 请求
        user_text = _trigger_entry(prepared).text() # 获取触发当前交互的 ContextEntryRecord
        flow.emit(
            "agent.run.requested",
            _run_request(prepared, user_text),
        )


def _trigger_entry(prepared: ContextPreparedEventData) -> ContextEntryRecord:
    """获取触发当前交互的 ContextEntryRecord"""
    for entry in reversed(prepared.entries):
        if entry.entry_id == prepared.trigger_entry_id:
            return entry
    raise ValueError(f"Context trigger entry is missing: {prepared.trigger_entry_id}")


def _run_request(
    prepared: ContextPreparedEventData,
    user_text: str,
) -> AgentRunRequestEventData:
    """构造主对话 State；其他触发来源仍可创建其他 Behavior Run。"""

    return AgentRunRequestEventData(
        run_id=new_id("run"),
        session_id=prepared.session_id,
        behavior_type=CONVERSATION_BEHAVIOR,
        behavior_state=ConversationState(
            prepared=prepared,
            user_text=user_text,
        ),
    )
