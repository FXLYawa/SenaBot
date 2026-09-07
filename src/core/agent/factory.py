"""Agent 模块的装配入口。"""

from __future__ import annotations

from core.agent.behaviors import ConversationBehavior
from core.agent.contracts import (
    CONVERSATION_BEHAVIOR,
    MemoryQueryEffect,
    ReplyEffect,
)
from core.agent.deliveries import MemoryDelivery, ReplyDelivery
from core.agent.dispatcher import AgentDispatcher
from core.agent.events import AgentModule
from core.agent.interaction import InteractionPolicy
from core.agent.others import PersonaConfig
from core.agent.persona import PersonaResponder
from core.agent.runtime import AgentRuntime
from core.model import FallbackModelProvider, ModelProvider


def create_agent_module(
    model_provider: ModelProvider,
    persona: PersonaConfig,
    *,
    fallback_model_provider: ModelProvider | None = None,
) -> AgentModule:
    """创建包含默认对话行为和 Effect 交付器的 Agent 模块。"""

    provider = model_provider
    if (
        fallback_model_provider is not None
        and fallback_model_provider is not model_provider
    ):
        provider = FallbackModelProvider(model_provider, fallback_model_provider)
    responder = PersonaResponder(provider, persona)
    runtime = AgentRuntime(
        {CONVERSATION_BEHAVIOR: ConversationBehavior(responder)}
    )
    memory_delivery = MemoryDelivery()
    dispatcher = AgentDispatcher(
        runtime,
        {
            MemoryQueryEffect: memory_delivery,
            ReplyEffect: ReplyDelivery(persona.persona_id, persona.name),
        },
    )
    return AgentModule(runtime, dispatcher, InteractionPolicy())
