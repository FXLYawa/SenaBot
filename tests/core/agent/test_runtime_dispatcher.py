"""AgentRuntime 与 AgentDispatcher 的生命周期测试。"""

from __future__ import annotations

import unittest
from dataclasses import dataclass

from core.agent.contracts import (
    AgentObservation,
    AgentObservationType,
    AgentRunCompletedEventData,
    AgentRunFailedEventData,
    AgentRunRequestEventData,
    AgentStepResult,
    FinishEffect,
    MemoryQueryEffect,
)
from core.agent.dispatcher import AgentDispatcher
from core.agent.deliveries.base import PreparedDelivery
from core.agent.deliveries.memory import MemoryDelivery, MemoryQueryBinding
from core.agent.runtime import AgentRuntime
from core.common import SceneInfo, SceneType, SourceInfo
from core.memory import MemoryQueryRequest


@dataclass(frozen=True, slots=True)
class CounterState:
    value: int


@dataclass(frozen=True, slots=True)
class WaitEffect:
    operation_id: str


@dataclass(frozen=True, slots=True)
class ImmediateEffect:
    value: str


class SequenceBehavior:
    def __init__(self, *results: AgentStepResult) -> None:
        self._results = list(results)
        self.observations: list[AgentObservation] = []

    async def step(
        self,
        state: object,
        observation: AgentObservation,
    ) -> AgentStepResult:
        self.observations.append(observation)
        return self._results.pop(0)


class RaisingBehavior:
    async def step(
        self,
        state: object,
        observation: AgentObservation,
    ) -> AgentStepResult:
        raise RuntimeError("model unavailable")


class RecordingDelivery:
    binding_type = None

    @staticmethod
    def prepare(effect: WaitEffect, binding: None) -> PreparedDelivery:
        return PreparedDelivery(
            events=(("test.effect.requested", effect),),
            pending_operation_id=effect.operation_id,
        )


class ImmediateDelivery:
    binding_type = None

    @staticmethod
    def prepare(effect: ImmediateEffect, binding: None) -> PreparedDelivery:
        return PreparedDelivery(events=(("test.immediate.requested", effect),))


class RecordingFlow:
    def __init__(self, payload: object | None = None) -> None:
        self.payload = payload
        self.emitted: list[tuple[str, object]] = []

    def emit(self, event_type: str, payload: object) -> None:
        self.emitted.append((event_type, payload))


def _request(run_id: str = "run_1") -> AgentRunRequestEventData:
    return AgentRunRequestEventData(
        run_id=run_id,
        session_id="session_1",
        behavior_type="test",
        behavior_state=CounterState(0),
    )


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_invokes_behavior_with_started_observation(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(
                next_state=CounterState(1),
                effects=(WaitEffect("operation_1"),),
            )
        )
        runtime = AgentRuntime({"test": behavior})

        transition = await runtime.start(_request())

        self.assertFalse(transition.terminal)
        self.assertEqual(transition.run.behavior_state, CounterState(1))
        self.assertEqual(transition.run.step_count, 1)
        self.assertEqual(
            [observation.kind for observation in behavior.observations],
            [AgentObservationType.STARTED],
        )

    async def test_resume_invokes_the_next_behavior_step(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(
                next_state=CounterState(1),
                effects=(WaitEffect("operation_1"),),
            ),
            AgentStepResult(
                next_state=CounterState(2),
                effects=(FinishEffect(),),
            ),
        )
        runtime = AgentRuntime({"test": behavior})
        transition = await runtime.start(_request())
        runtime.wait_for(transition.run.run_id, "operation_1")

        resumed = await runtime.resume(
            "operation_1",
            AgentObservation(
                kind=AgentObservationType.EXTERNAL_RESULT,
                payload={"ok": True},
                resolution_status="completed",
            ),
        )

        self.assertIsNotNone(resumed)
        assert resumed is not None
        self.assertFalse(resumed.terminal)
        self.assertEqual(resumed.run.behavior_state, CounterState(2))
        self.assertEqual(resumed.run.step_count, 2)
        self.assertIsNotNone(resumed.step)
        assert resumed.step is not None
        self.assertEqual(resumed.step.effects, (FinishEffect(),))
        self.assertEqual(len(behavior.observations), 2)
        self.assertIsNone(
            await runtime.resume(
                "operation_1",
                AgentObservation(AgentObservationType.EXTERNAL_RESULT),
            )
        )

    async def test_unknown_behavior_returns_structured_failure(self) -> None:
        runtime = AgentRuntime({})

        transition = await runtime.start(_request())

        self.assertTrue(transition.terminal)
        self.assertIsNotNone(transition.failure)
        assert transition.failure is not None
        self.assertEqual(transition.failure.code, "behavior_not_found")

    async def test_behavior_exception_terminates_run(self) -> None:
        runtime = AgentRuntime({"test": RaisingBehavior()})

        transition = await runtime.start(_request())

        self.assertTrue(transition.terminal)
        self.assertIsNotNone(transition.failure)
        assert transition.failure is not None
        self.assertEqual(transition.failure.code, "behavior_failed")
        self.assertIn("RuntimeError: model unavailable", transition.failure.message)


class AgentDispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_query_uses_run_binding_to_prepare_scoped_request(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(CounterState(1), (MemoryQueryEffect("咖啡"),))
        )
        runtime = AgentRuntime({"test": behavior})
        dispatcher = AgentDispatcher(runtime, {MemoryQueryEffect: MemoryDelivery("sena")})
        binding = MemoryQueryBinding(
            requester=SourceInfo("user_platform_1", "Alice", False, "user_1"),
            session_id="session_1",
            scene=SceneInfo("discord", SceneType.GROUP, "group_1", "sena_bot"),
        )
        request = AgentRunRequestEventData(
            run_id="run_1",
            session_id="session_1",
            behavior_type="test",
            behavior_state=CounterState(0),
            delivery_bindings=(binding,),
        )
        flow = RecordingFlow()

        dispatcher.dispatch(flow, await runtime.start(request))

        self.assertEqual(len(flow.emitted), 1)
        event_type, payload = flow.emitted[0]
        self.assertEqual(event_type, "memory.query.requested")
        self.assertIsInstance(payload, MemoryQueryRequest)
        self.assertEqual(payload.query_text, "咖啡")
        self.assertEqual(payload.memory_space_id, "sena")
        self.assertEqual(payload.user_id, "user_1")
        self.assertEqual(payload.session_id, "session_1")
        self.assertEqual(payload.group_id, "group_1")
        self.assertTrue(payload.query_id.startswith("op_memory_query_"))

    async def test_missing_query_binding_fails_without_publishing_request(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(CounterState(1), (MemoryQueryEffect("咖啡"),))
        )
        runtime = AgentRuntime({"test": behavior})
        dispatcher = AgentDispatcher(runtime, {MemoryQueryEffect: MemoryDelivery("sena")})
        flow = RecordingFlow()

        dispatcher.dispatch(flow, await runtime.start(_request()))

        self.assertEqual(len(flow.emitted), 1)
        event_type, failure = flow.emitted[0]
        self.assertEqual(event_type, "agent.run.failed")
        self.assertIsInstance(failure, AgentRunFailedEventData)
        self.assertEqual(failure.code, "delivery_binding_invalid")

    async def test_waiting_effect_cannot_be_combined_with_finish(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(
                next_state=CounterState(1),
                effects=(WaitEffect("operation_1"), FinishEffect()),
            )
        )
        runtime = AgentRuntime({"test": behavior})
        dispatcher = AgentDispatcher(runtime, {WaitEffect: RecordingDelivery()})
        flow = RecordingFlow()

        dispatcher.dispatch(flow, await runtime.start(_request()))

        self.assertEqual(len(flow.emitted), 1)
        event_type, failure = flow.emitted[0]
        self.assertEqual(event_type, "agent.run.failed")
        self.assertIsInstance(failure, AgentRunFailedEventData)
        self.assertEqual(failure.code, "step_invalid")

    async def test_non_waiting_effect_with_finish_completes_immediately(self) -> None:
        effect = ImmediateEffect("reply")
        behavior = SequenceBehavior(
            AgentStepResult(
                next_state=CounterState(1),
                effects=(effect, FinishEffect()),
            )
        )
        runtime = AgentRuntime({"test": behavior})
        dispatcher = AgentDispatcher(
            runtime,
            {ImmediateEffect: ImmediateDelivery()},
        )
        flow = RecordingFlow()

        dispatcher.dispatch(flow, await runtime.start(_request()))

        self.assertEqual(flow.emitted[0], ("test.immediate.requested", effect))
        self.assertEqual(flow.emitted[1][0], "agent.run.completed")
        completion = flow.emitted[1][1]
        self.assertIsInstance(completion, AgentRunCompletedEventData)
        self.assertEqual(completion.agent_run_id, "run_1")

    async def test_missing_delivery_fails_run_without_emitting_effect(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(
                next_state=CounterState(1),
                effects=(WaitEffect("operation_1"),),
            )
        )
        runtime = AgentRuntime({"test": behavior})
        dispatcher = AgentDispatcher(runtime, {})
        flow = RecordingFlow()

        dispatcher.dispatch(flow, await runtime.start(_request()))

        self.assertEqual(len(flow.emitted), 1)
        event_type, failure = flow.emitted[0]
        self.assertEqual(event_type, "agent.run.failed")
        self.assertIsInstance(failure, AgentRunFailedEventData)
        self.assertEqual(failure.code, "effect_not_supported")

    async def test_step_cannot_wait_for_multiple_operations(self) -> None:
        behavior = SequenceBehavior(
            AgentStepResult(
                next_state=CounterState(1),
                effects=(WaitEffect("operation_1"), WaitEffect("operation_2")),
            )
        )
        runtime = AgentRuntime({"test": behavior})
        dispatcher = AgentDispatcher(runtime, {WaitEffect: RecordingDelivery()})
        flow = RecordingFlow()

        dispatcher.dispatch(flow, await runtime.start(_request()))

        self.assertEqual(len(flow.emitted), 1)
        event_type, failure = flow.emitted[0]
        self.assertEqual(event_type, "agent.run.failed")
        self.assertIsInstance(failure, AgentRunFailedEventData)
        self.assertEqual(failure.code, "step_invalid")


if __name__ == "__main__":
    unittest.main()
