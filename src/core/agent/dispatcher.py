"""AgentDispatcher 负责校验 Behavior 产生的 Effect
调用对应 Delivery 执行副作用
并协调 AgentRun 的等待、完成与失败
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.agent.contracts import (
    AgentRunCompletedEventData,
    AgentRunFailedEventData,
    AgentStepResult,
    FailEffect,
    FinishEffect,
)
from core.agent.deliveries import EffectDelivery
from core.agent.runtime import AgentRuntime, AgentTransition
from core.event import EventFlow


@dataclass(frozen=True, slots=True)
class _DeliveryCall:
    """一个已经解析完成、可以安全执行的副作用。"""

    effect: object # Behavior 产生的原始副作用
    delivery: EffectDelivery[Any] # 负责把它转换成公开事件的适配器


@dataclass(frozen=True, slots=True)
class _DispatchPlan:
    """一个 Step 通过校验后得到的完整执行计划。"""

    calls: tuple[_DeliveryCall, ...] # 按声明顺序执行的副作用列表
    pending_operation_id: str | None # 需要等待结果时使用的关联 ID；不等待时为空


class AgentDispatcher:
    """校验 Step、维护 Run 等待关系，并委托 Delivery 发布业务事件。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        deliveries: Mapping[type[object], EffectDelivery[Any]],
    ) -> None:
        self._runtime = runtime # 控制 Run 生命周期的 Runtime
        self._deliveries = dict(deliveries) # 保存 Effect 类型到交付适配器的映射

    def dispatch(self, flow: EventFlow, transition: AgentTransition) -> None:
        """根据transition的状态, 调用对应的交付适配器, 并协调 AgentRun 的等待、完成与失败。
        AgentTransitions 是单次 Behavior.step() 的结果, 可能是终态、等待外部结果或继续执行下一步。"""

        # 如果是终态, 直接发布终态事件
        if transition.terminal:
            self._emit_terminal(flow, transition)
            return
        # 如果是非终态却没有 Step，说明runtime返回了不完整状态，直接终止 Run 并发布失败事件
        step = transition.step
        if step is None:
            self._fail(
                flow,
                transition.run.run_id,
                FailEffect("empty_step", "Behavior returned no step result."),
            )
            return

        # 校验 Step 并生成执行计划
        plan = self._plan_step(step)
        # 如果校验失败, 直接终止 Run 并发布失败事件
        if isinstance(plan, FailEffect):
            self._fail(flow, transition.run.run_id, plan)
            return
        # 执行计划
        self._execute_plan(flow, transition.run.run_id, plan)

    def _plan_step(self, step: AgentStepResult) -> _DispatchPlan | FailEffect:
        """校验控制 Effect, 并把所有副作用解析成不产生事件的执行计划。"""

        # 1. 检查是否有失败 Effect, 如果有则直接返回失败
        failures = [effect for effect in step.effects if isinstance(effect, FailEffect)]
        if failures:
            return failures[0]
        
        # 2. 检查是否有 Finish Effect, 如果有则记录下来, 但不影响后续的副作用处理
        finishes = [effect for effect in step.effects if isinstance(effect, FinishEffect)]
        if len(finishes) > 1:
            return FailEffect(
                "step_invalid",
                "A step may contain at most one FinishEffect.",
            )

        # 3. 检查是否有外部副作用 Effect, 并生成对应的交付调用计划
        external_effects = [
            effect
            for effect in step.effects
            if not isinstance(effect, (FailEffect, FinishEffect))
        ]
        
        # 4. 对每个外部副作用 Effect, 查找对应的交付适配器, 并生成执行计划
        calls: list[_DeliveryCall] = []
        pending_operation_ids: list[str] = []
        for effect in external_effects:
            delivery = self._deliveries.get(type(effect))
            if delivery is None:
                return FailEffect(
                    "effect_not_supported",
                    f"No delivery is installed for {type(effect).__name__}.",
                )
            operation_id = delivery.pending_operation_id(effect)
            calls.append(_DeliveryCall(effect, delivery))
            if operation_id is not None:
                pending_operation_ids.append(operation_id)

        # 5. 校验等待关系, 确保最多只有一个需要等待的外部副作用 Effect
        if len(pending_operation_ids) > 1:
            return FailEffect(
                "step_invalid",
                "A step may wait for at most one external result.",
            )
        pending_operation_id = (
            pending_operation_ids[0] if pending_operation_ids else None
        )
        # 如果没有需要等待的 operation_id，且没有 Finish Effect
        finish_requested = bool(finishes)
        if pending_operation_id is not None and finish_requested:
            return FailEffect(
                "step_invalid",
                "A waiting effect cannot be combined with FinishEffect.",
            )
        if pending_operation_id is None and not finish_requested:
            return FailEffect(
                "step_stalled",
                "Behavior neither waited for an operation nor finished the run.",
            )
        return _DispatchPlan(tuple(calls), pending_operation_id)

    def _execute_plan(
        self,
        flow: EventFlow,
        run_id: str,
        plan: _DispatchPlan,
    ) -> None:
        """先登记可选等待，再按声明顺序发布计划中的所有副作用。"""

        # 先登记可选等待
        if plan.pending_operation_id is not None:
            self._runtime.wait_for(run_id, plan.pending_operation_id,)
        # 按声明顺序发布计划中的所有副作用
        for call in plan.calls:
            call.delivery.emit(flow, call.effect)
        # 如果没有需要等待的 operation_id，且没有 Finish Effect，则直接完成 Run
        if plan.pending_operation_id is None:
            self._complete(flow, run_id)

    def _complete(self, flow: EventFlow, run_id: str) -> None:
        """完成 Run 并发布终态事实。"""

        self._emit_terminal(flow, self._runtime.complete(run_id))

    def _fail(self, flow: EventFlow, run_id: str, failure: FailEffect) -> None:
        """终止 Run 并发布结构化失败事实。"""

        self._emit_terminal(flow, self._runtime.fail(run_id, failure))

    @staticmethod
    def _emit_terminal(flow: EventFlow, transition: AgentTransition) -> None:
        """把 Runtime 终态转换为 Agent 公开事件。"""

        run = transition.run
        if transition.failure is not None:
            failure = transition.failure
            flow.emit(
                "agent.run.failed",
                AgentRunFailedEventData(
                    agent_run_id=run.run_id,
                    session_id=run.session_id,
                    behavior_type=run.behavior_type,
                    code=failure.code,
                    message=failure.message,
                ),
            )
            return
        flow.emit(
            "agent.run.completed",
            AgentRunCompletedEventData(
                agent_run_id=run.run_id,
                session_id=run.session_id,
                behavior_type=run.behavior_type,
                outcome=transition.outcome or "completed",
            ),
        )
