"""Agent 交互触发与 Runtime 事件接入的组合入口。"""

from __future__ import annotations

from core.agent.contracts import (
    AgentInteractionIgnoredEventData,
    AgentRunCompletedEventData,
    AgentRunFailedEventData,
    AgentRunRequestEventData,
)
from core.agent.dispatcher import AgentDispatcher
from core.agent.interaction import InteractionPolicy
from core.agent.interaction_flow import InteractionFlow
from core.agent.runtime import AgentRuntime
from core.agent.run_flow import RunFlow
from core.event import ModuleEventAPI


class AgentModule:
    """组装 Agent 内部流程，并提供唯一的事件注册 Interface。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        dispatcher: AgentDispatcher,
        interaction: InteractionPolicy,
    ) -> None:
        self._runs = RunFlow(runtime, dispatcher)
        self._interactions = InteractionFlow(interaction)

    def register(self, events: ModuleEventAPI) -> None:
        """集中声明 Agent 拥有的事件以及它订阅的公开事件。"""

        event_definitions = (
            ("agent.run.requested", AgentRunRequestEventData),
            ("agent.run.completed", AgentRunCompletedEventData),
            ("agent.run.failed", AgentRunFailedEventData),
            ("agent.interaction.ignored", AgentInteractionIgnoredEventData),
        )
        subscriptions = (
            (
                "context.prepared",
                self._interactions.handle_context_prepared,
                "agent.context_prepared",
            ),
            (
                "agent.run.requested",
                self._runs.handle_run_requested,
                "agent.run_requested",
            ),
            (
                "memory.query.completed",
                self._runs.handle_memory_query_result,
                "agent.memory_query_completed",
            ),
            (
                "memory.write.completed",
                self._runs.handle_memory_write_result,
                "agent.memory_write_completed",
            ),
            (
                "memory.query.failed",
                self._runs.handle_memory_query_failed,
                "agent.memory_query_failed",
            ),
            (
                "memory.write.failed",
                self._runs.handle_memory_write_failed,
                "agent.memory_write_failed",
            ),
        )

        for event_type, payload_type in event_definitions:
            events.register(event_type, payload_type=payload_type)
        for event_pattern, handler, handler_id in subscriptions:
            events.subscribe(event_pattern, handler, handler_id=handler_id)
