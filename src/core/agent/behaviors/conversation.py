"""对话 Behavior"""

from __future__ import annotations

from core.agent.contracts import (
    AgentObservation,
    AgentObservationType,
    AgentStepResult,
    FailEffect,
    FinishEffect,
    MemoryQueryEffect,
    ReplyEffect,
)
from core.agent.persona import PersonaResponder
from core.agent.state import ConversationState
from core.agent.common import render_prompt, new_id
from core.context import ContextEntryType, ContextPreparedEventData, ContextSummary
from core.memory.contracts import MemoryQueryFailedEventData, MemoryQueryResult
from core.memory.models import Experience, Fact, Knowledge, MemoryItem, Understanding
from core.model import ModelMessage


class ConversationBehavior:
    """对话 Behavior"""

    def __init__(self, responder: PersonaResponder) -> None:
        self._responder = responder # 人格配置

    async def step(
        self,
        state: object,
        observation: AgentObservation, # 单次 step 的交互数据
    ) -> AgentStepResult:
        """对话行为的入口, 每轮交互都是一个 step"""
        current = _require_state(state)
        if observation.kind is AgentObservationType.STARTED:
            return AgentStepResult(current, (self._memory_query(current),))
        # 对记忆查询结果的处理
        if isinstance(observation.payload, MemoryQueryResult):
            return await self._reply_with_context(
                current.with_memories(observation.payload.memories)
            )
        if isinstance(observation.payload, MemoryQueryFailedEventData):
            return await self._reply_with_context(current.with_memories([]))
        return AgentStepResult(
            next_state=current,
            effects=(
                FailEffect(
                    code="observation_unsupported",
                    message="Conversation cannot handle observation.",
                ),
            ),
        )

    def _memory_query(self, state: ConversationState) -> MemoryQueryEffect:
        return MemoryQueryEffect(
            operation_id=new_id("op_memory_query"),
            query=state.user_text,
            requester=state.prepared.source,
            session_id=state.prepared.session_id,
            scene=state.prepared.scene,
            persona_id=self._responder.persona_id,
        )

    async def _reply_with_context(self, state: ConversationState) -> AgentStepResult:
        """根据当前对话上下文和记忆查询结果生成回复"""
        # 先组装消息，然后调用 PersonaResponder 生成回复，并使用对应的 ReplyEffect 返回
        response = await self._responder.generate(_messages(state), temperature=0.7)
        return AgentStepResult(
            next_state=state,
            effects=(_reply_effect(state.prepared, response.text), FinishEffect()),
        )


def _require_state(state: object) -> ConversationState:
    """验证当前状态是否为 ConversationState, 并返回该对象"""
    if not isinstance(state, ConversationState):
        raise TypeError(
            f"ConversationBehavior expected ConversationState, got {type(state).__name__}"
        )
    return state


def _reply_effect(
    prepared: ContextPreparedEventData,
    text: str,
) -> ReplyEffect:
    """根据当前对话上下文和生成的文本构造 ReplyEffect"""
    return ReplyEffect(
        text=text,
        session_id=prepared.session_id,
        trigger_event_id=prepared.trigger_event_id,
        output_route=prepared.output_route,
        scene=prepared.scene,
        reply_to_message_id=prepared.reply_to_message_id,
    )


def _messages(state: ConversationState) -> tuple[ModelMessage, ...]:
    """组装当前 Conversation 的模型输入; Context 只提供上下文快照"""

    prepared = state.prepared
    messages: list[ModelMessage] = []
    history = _render_summaries(prepared.summaries)
    # 加入历史摘要
    if history:
        messages.append(
            ModelMessage(
                "system",
                render_prompt(
                    "core.agent.prompts",
                    "context_summary_system.txt",
                    history=history,
                ),
            )
        )
    # 加入记忆查询结果
    if state.memories:
        messages.append(
            ModelMessage(
                "system",
                render_prompt(
                    "core.agent.prompts",
                    "authorized_memories_system.txt",
                    memories="\n".join(
                        f"- {_memory_text(item)}" for item in state.memories
                    ),
                ),
            )
        )
    # 加入当前对话条目
    for entry in prepared.entries:
        if entry.entry_type == ContextEntryType.USER_MESSAGE:
            messages.append(ModelMessage("user", entry.text()))
        elif entry.entry_type == ContextEntryType.SENA_MESSAGE:
            messages.append(ModelMessage("assistant", entry.text()))
        elif entry.entry_type == ContextEntryType.SYSTEM_NOTE:
            messages.append(ModelMessage("system", entry.text()))
    return tuple(messages)


def _render_summaries(summaries: tuple[ContextSummary, ...]) -> str:
    """按顺序渲染 Context 已提供的摘要，不主动读取更早的原始历史。"""

    return "\n\n".join(
        f"[level={summary.level} "
        f"range={summary.first_sequence}-{summary.last_sequence}]\n"
        f"{summary.text or '[无语义摘要]'}"
        for summary in sorted(summaries, key=lambda item: item.first_sequence)
    )


def _memory_text(item: MemoryItem) -> str:
    payload = item.payload
    if isinstance(payload, Experience):
        return payload.summary
    if isinstance(payload, (Fact, Understanding, Knowledge)):
        return payload.content
    raise TypeError(f"Unsupported Memory payload: {type(payload).__name__}")
