"""Agent 交互、Conversation Behavior 与 RunFlow 测试。"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from core.agent.behaviors.conversation import ConversationBehavior
from core.agent.contracts import (
    AgentObservation,
    AgentObservationType,
    AgentRunRequestEventData,
    AgentStepResult,
    FinishEffect,
    MemoryQueryEffect,
    ReplyEffect,
)
from core.agent.interaction import InteractionPolicy
from core.agent.interaction_flow import InteractionFlow
from core.agent.run_flow import RunFlow
from core.agent.runtime import AgentTransition
from core.agent.state import ConversationState
from core.common import (
    Content, InteractionSignals, OutputRoute, SceneInfo, SceneType, SourceInfo,
)
from core.context import (
    ContextActorRef, ContextActorType, ContextEntryRecord, ContextEntryType,
    ContextPreparedEventData,
)
from core.memory.contracts import (
    MemoryErrorInfo, MemoryQueryFailedEventData, MemoryQueryResult,
)
from core.memory.models import Fact, MemoryItem, MemoryScopeKind, MemoryScopeRef, Provenance
from core.model import ModelMessage, ModelResponse


class RecordingFlow:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.emitted: list[tuple[str, object]] = []

    def emit(self, event_type: str, payload: object) -> None:
        self.emitted.append((event_type, payload))


class StubResponder:
    persona_id = "sena"

    def __init__(self) -> None:
        self.messages: tuple[object, ...] = ()

    async def generate(
        self,
        messages: tuple[object, ...],
        *,
        temperature: float | None = None,
    ) -> ModelResponse:
        self.messages = messages
        return ModelResponse(text="你好", model="test-model")


class StubRuntime:
    def __init__(self, transition: AgentTransition) -> None:
        self.transition = transition
        self.requests: list[object] = []

    async def start(self, request: object) -> AgentTransition:
        self.requests.append(request)
        return self.transition


class StubDispatcher:
    def __init__(self) -> None:
        self.transitions: list[AgentTransition] = []

    def dispatch(self, flow: RecordingFlow, transition: AgentTransition) -> None:
        self.transitions.append(transition)


def _prepared(
    *,
    scene_type: SceneType = SceneType.PRIVATE,
    directed_to_agent: bool = False,
    is_bot: bool = False,
) -> ContextPreparedEventData:
    return ContextPreparedEventData(
        session_id="session_1",
        trigger_event_id="event_1",
        trigger_entry_id="entry_1",
        entries=(ContextEntryRecord(
            entry_id="entry_1", session_id="session_1", sequence=1,
            entry_type=ContextEntryType.USER_MESSAGE,
            actor=ContextActorRef(ContextActorType.USER, "user_1", "Alice"),
            content=Content.from_text("你好"), source_event_id="event_1",
            created_at=datetime(2026, 9, 10, tzinfo=timezone.utc),
        ),),
        summaries=(),
        output_route=OutputRoute(
            adapter_type="discord", platform="discord", body_id="discord_bot",
        ),
        source=SourceInfo(
            platform_user_id="platform_user_1",
            display_name="Alice",
            principal_id="user_1",
            is_bot=is_bot,
        ),
        scene=SceneInfo(
            platform="discord", scene_type=scene_type, scene_id="scene_1",
            account_namespace="sena_bot", scene_name="Alice 的聊天",
        ),
        interaction=InteractionSignals(mentioned_agent=directed_to_agent),
        reply_to_message_id="message_1",
    )


class InteractionTests(unittest.IsolatedAsyncioTestCase):
    def test_policy_handles_bot_direct_and_group_inputs(self) -> None:
        policy = InteractionPolicy()

        self.assertFalse(policy.decide(_prepared(is_bot=True)).participate)
        self.assertTrue(policy.decide(_prepared()).participate)
        self.assertFalse(
            policy.decide(_prepared(scene_type=SceneType.GROUP)).participate
        )
        self.assertTrue(
            policy.decide(
                _prepared(
                    scene_type=SceneType.GROUP,
                    directed_to_agent=True,
                )
            ).participate
        )

    async def test_participating_input_creates_conversation_run(self) -> None:
        prepared = _prepared()
        flow = RecordingFlow(prepared)

        await InteractionFlow(InteractionPolicy()).handle_context_prepared(flow)

        self.assertEqual(len(flow.emitted), 1)
        event_type, request = flow.emitted[0]
        self.assertEqual(event_type, "agent.run.requested")
        self.assertIsInstance(request, AgentRunRequestEventData)
        self.assertEqual(request.session_id, "session_1")
        self.assertEqual(request.behavior_type, "conversation")
        self.assertEqual(request.behavior_state.user_text, "你好")
        self.assertEqual(request.behavior_state.prepared, prepared)


class ConversationBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_started_observation_requests_scoped_memory(self) -> None:
        responder = StubResponder()
        behavior = ConversationBehavior(responder)
        state = ConversationState(prepared=_prepared(), user_text="你好")

        result = await behavior.step(
            state,
            AgentObservation(kind=AgentObservationType.STARTED),
        )

        self.assertEqual(len(result.effects), 1)
        effect = result.effects[0]
        self.assertIsInstance(effect, MemoryQueryEffect)
        self.assertEqual(effect.query, "你好")
        self.assertEqual(effect.requester.user_id, "user_1")
        self.assertEqual(effect.session_id, "session_1")
        self.assertEqual(effect.scene, state.prepared.scene)
        self.assertEqual(effect.scene.scene_id, "scene_1")
        self.assertEqual(effect.scene.platform, "discord")
        self.assertEqual(effect.scene.scene_type, SceneType.PRIVATE)
        self.assertEqual(effect.scene.account_namespace, "sena_bot")
        self.assertEqual(effect.scene.scene_name, "Alice 的聊天")
        self.assertEqual(effect.requester, state.prepared.source)
        self.assertTrue(effect.operation_id.startswith("op_memory_query_"))
        self.assertEqual(result.next_state, state)
        self.assertEqual(effect.persona_id, "sena")

    async def test_empty_memory_result_continues_to_routed_reply(self) -> None:
        responder = StubResponder()
        behavior = ConversationBehavior(responder)
        state = ConversationState(prepared=_prepared(), user_text="你好")
        memory_result = MemoryQueryResult(
            query_id="query_1",
            memory_space_id="sena",
            user_id="user_1",
            session_id="session_1",
            group_id="",
            memories=[],
        )

        result = await behavior.step(
            state,
            AgentObservation(
                kind=AgentObservationType.EXTERNAL_RESULT,
                payload=memory_result,
            ),
        )

        self.assertEqual(result.next_state.memories, ())
        self.assertEqual(result.next_state.prepared, state.prepared)
        self.assertEqual(responder.messages, (ModelMessage("user", "你好"),))
        self.assertEqual(len(result.effects), 2)
        self.assertIsInstance(result.effects[0], ReplyEffect)
        self.assertEqual(result.effects[0].text, "你好")
        self.assertEqual(result.effects[0].session_id, "session_1")
        self.assertEqual(result.effects[0].output_route, state.prepared.output_route)
        self.assertEqual(result.effects[0].scene, state.prepared.scene)
        self.assertEqual(result.effects[0].trigger_event_id, "event_1")
        self.assertEqual(result.effects[0].reply_to_message_id, "message_1")
        self.assertIsInstance(result.effects[1], FinishEffect)

    async def test_memory_result_preserves_items_and_supplies_model_context(self) -> None:
        responder = StubResponder()
        state = ConversationState(prepared=_prepared(), user_text="你好")
        memory = MemoryItem(
            item_id="alice_coffee_preference", memory_space_id="sena",
            scopes=frozenset({MemoryScopeRef(MemoryScopeKind.USER, "user_1")}),
            payload=Fact(
                content="Alice 喜欢咖啡",
                provenance=(Provenance("context_entry", "entry_coffee"),),
                recorded_at=datetime(2026, 9, 9, tzinfo=timezone.utc),
            ),
        )
        memory_result = MemoryQueryResult(
            query_id="query_1", memory_space_id="sena", user_id="user_1",
            session_id="session_1", group_id="", memories=[memory],
        )

        result = await ConversationBehavior(responder).step(
            state,
            AgentObservation(
                kind=AgentObservationType.EXTERNAL_RESULT, payload=memory_result,
            ),
        )

        self.assertEqual(result.next_state.memories, (memory,))
        self.assertEqual(result.next_state.prepared, state.prepared)
        self.assertEqual(len(responder.messages), 2)
        self.assertEqual(responder.messages[0].role, "system")
        self.assertIn("Alice 喜欢咖啡", responder.messages[0].content)
        self.assertEqual(responder.messages[1], ModelMessage("user", "你好"))
        self.assertEqual(len(result.effects), 2)
        self.assertIsInstance(result.effects[0], ReplyEffect)
        self.assertEqual(result.effects[0].text, "你好")
        self.assertIsInstance(result.effects[1], FinishEffect)

    async def test_memory_query_failure_still_generates_reply(self) -> None:
        responder = StubResponder()
        state = ConversationState(prepared=_prepared(), user_text="你好")
        failure = MemoryQueryFailedEventData(
            query_id="query_1", memory_space_id="sena",
            error=MemoryErrorInfo(code="query_failed", message="查询失败"),
        )

        result = await ConversationBehavior(responder).step(
            state,
            AgentObservation(
                kind=AgentObservationType.EXTERNAL_RESULT,
                payload=failure, resolution_status="failed",
            ),
        )

        self.assertEqual(result.next_state.memories, ())
        self.assertEqual(responder.messages, (ModelMessage("user", "你好"),))
        self.assertEqual(result.effects, (
            ReplyEffect(
                text="你好", session_id="session_1", trigger_event_id="event_1",
                output_route=state.prepared.output_route, scene=state.prepared.scene,
                reply_to_message_id="message_1",
            ),
            FinishEffect(),
        ))


class RunFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_request_is_started_then_dispatched(self) -> None:
        request = AgentRunRequestEventData(
            run_id="run_1",
            session_id="session_1",
            behavior_type="test",
            behavior_state={"value": 1},
        )
        transition = AgentTransition(
            run=SimpleNamespace(run_id="run_1"),
            step=AgentStepResult(next_state={"value": 2}, effects=()),
        )
        runtime = StubRuntime(transition)
        dispatcher = StubDispatcher()
        flow = RecordingFlow(request)

        await RunFlow(runtime, dispatcher).handle_run_requested(flow)

        self.assertEqual(runtime.requests, [request])
        self.assertEqual(dispatcher.transitions, [transition])


if __name__ == "__main__":
    unittest.main()
