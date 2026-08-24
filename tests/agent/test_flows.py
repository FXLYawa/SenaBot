"""Agent 交互、Conversation Behavior 与 RunFlow 测试。"""

from __future__ import annotations

import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from core.agent.behaviors.conversation import ConversationBehavior
from core.agent.common import SceneInfo, SceneType, SourceInfo
from core.agent.contracts import (
    AgentObservation,
    AgentObservationType,
    AgentRunRequestEventData,
    AgentStepResult,
    MemoryQueryEffect,
)
from core.agent.interaction import InteractionPolicy
from core.agent.interaction_flow import InteractionFlow
from core.agent.run_flow import RunFlow
from core.agent.runtime import AgentTransition
from core.agent.state import ConversationState
from core.memory.contracts import MemoryQueryResult
from core.model import ModelResponse


@dataclass(frozen=True, slots=True)
class TriggerEntry:
    entry_id: str
    value: str

    def text(self) -> str:
        return self.value


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
) -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session_1",
        trigger_event_id="event_1",
        trigger_entry_id="entry_1",
        entries=(TriggerEntry("entry_1", "你好"),),
        summaries=(),
        output_route=SimpleNamespace(),
        source=SourceInfo(
            platform_user_id="platform_user_1",
            display_name="Alice",
            principal_id="user_1",
            is_bot=is_bot,
        ),
        scene=SceneInfo(scene_type=scene_type, scene_id="scene_1"),
        interaction=SimpleNamespace(directed_to_agent=directed_to_agent),
        reply_to_message_id=None,
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
        self.assertEqual(effect.scene_id, "scene_1")
        self.assertEqual(effect.persona_id, "sena")

    async def test_memory_result_continues_to_reply_generation(self) -> None:
        responder = StubResponder()
        behavior = ConversationBehavior(responder)
        state = ConversationState(prepared=_prepared(), user_text="你好")
        memory_result = MemoryQueryResult(
            query_id="query_1",
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
        self.assertEqual(result.effects[0].text, "你好")
        self.assertEqual(result.effects[0].session_id, "session_1")


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
