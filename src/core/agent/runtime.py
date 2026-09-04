"""业务无关的 AgentRun 生命周期与事件恢复。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import date, datetime, time
from enum import Enum

from core.agent.contracts import (
    AgentObservation,
    AgentObservationType,
    AgentRun,
    AgentRunRequestEventData,
    AgentStepResult,
    Behavior,
    FailEffect,
    PendingOperation,
)


@dataclass(frozen=True, slots=True)
class AgentTransition:
    """Runtime 交给 Dispatcher 的单次运行结果。
    有三种情况, AgentRun 终态、AgentRun 继续等待外部结果、AgentRun 继续执行下一步。
    """

    run: AgentRun
    step: AgentStepResult | None = None # Behavior.step() 的结果，非终态时必有
    outcome: str | None = None # 终态结果的状态，非终态时为 None
    failure: FailEffect | None = None # 终态结果的失败原因，非终态时为 None

    @property
    def terminal(self) -> bool:
        return self.outcome is not None or self.failure is not None


class AgentRuntime:
    """Runtime 只管理 Run、等待关联、恢复和终止。

    Behavior 通过启动时注入的开放字符串映射查找。Runtime 不包含任何业务逻辑, Behavior 也不直接访问 Runtime
    """

    def __init__(
        self,
        behaviors: Mapping[str, Behavior], 
        *,
        max_steps: int = 32, 
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least one")
        self._behaviors = dict(behaviors) # 保存 Behavior 类型到实现对象的映射
        self.max_steps = max_steps # 限制单次 Run 的最大 step 次数, 防止无限循环
        self._runs: dict[str, AgentRun] = {} # 保存当前所有 Run 的运行状态, key 为 run_id
        self._operation_to_run: dict[str, str] = {} # 保存当前所有等待外部结果的操作, key 为 operation_id, value 为 run_id

    async def start(self, request: AgentRunRequestEventData) -> AgentTransition:
        """创建 Run 并执行第一次 Behavior.step()。"""

        if request.run_id in self._runs:
            return self._failed_request(request, "run_conflict", "AgentRun already exists.")
        if request.behavior_type not in self._behaviors:
            return self._failed_request(
                request,
                "behavior_not_found",
                f"Behavior is not available: {request.behavior_type}",
            )
        _require_pure_data(request.behavior_state) # 数据校验，确保只有纯数据内容
        # 构造对应的agentrun
        run = AgentRun(
            run_id=request.run_id,
            session_id=request.session_id,
            behavior_type=request.behavior_type,
            behavior_state=request.behavior_state,
        )
        self._runs[run.run_id] = run
        return await self._step(
            run,
            AgentObservation(AgentObservationType.STARTED),
        )

    async def resume(
        self,
        operation_id: str,
        observation: AgentObservation,
    ) -> AgentTransition | None:
        """用外部结果恢复对应 Run；不属于本 Runtime 的结果直接忽略。"""

        run_id = self._operation_to_run.get(operation_id) # 查找对应的 run_id
        if run_id is None:
            return None
        run = self._runs.get(run_id) # 查找对应的 AgentRun
        if run is None or run.pending_operation is None:
            raise RuntimeError("Agent pending operation state is inconsistent")
        pending = run.pending_operation # 查找对应的 PendingOperation
        if pending.operation_id != operation_id:
            raise RuntimeError("Agent pending operation ID is inconsistent")
        # 清除等待关联，恢复对应的 Run
        self._operation_to_run.pop(operation_id)
        run.pending_operation = None
        return await self._step(run, observation)

    def wait_for(
        self,
        run_id: str,
        operation_id: str,
    ) -> None:
        """将 Run 与唯一外部操作关联。"""

        run = self._require_run(run_id) # 查找对应的 AgentRun
        if run.pending_operation is not None:
            raise RuntimeError("AgentRun already has a pending operation")
        if operation_id in self._operation_to_run:
            raise RuntimeError(f"Agent operation already exists: {operation_id}")
        # 将 Run 与外部操作关联
        run.pending_operation = PendingOperation(operation_id=operation_id,)
        self._operation_to_run[operation_id] = run_id

    def complete(self, run_id: str, outcome: str = "completed") -> AgentTransition:
        """结束 Run 并返回完成终态。"""
        run = self._require_run(run_id)
        snapshot = replace(run)
        self._remove(run_id)
        return AgentTransition(snapshot, outcome=outcome)

    def fail(self, run_id: str, failure: FailEffect) -> AgentTransition:
        """结束 Run 并返回失败终态。"""
        run = self._require_run(run_id)
        snapshot = replace(run)
        self._remove(run_id)
        return AgentTransition(snapshot, failure=failure)

    async def _step(
        self,
        run: AgentRun,
        observation: AgentObservation, # Behavior.step() 的输入数据
    ) -> AgentTransition:
        """执行一次 Behavior.step() 并返回下一步的状态和 Effect。"""
        if run.step_count >= self.max_steps:
            return self.fail(
                run.run_id,
                FailEffect("step_limit_exceeded", "AgentRun exceeded its step limit."),
            )
        # Behavior.step() 的调用，返回下一步的状态和 Effect
        behavior = self._behaviors[run.behavior_type]
        try:
            result = await behavior.step(run.behavior_state, observation)
            _require_pure_data(result.next_state)
        except Exception as exc:
            return self.fail(
                run.run_id,
                FailEffect("behavior_failed", f"{type(exc).__name__}: {exc}"),
            )
        run.behavior_state = result.next_state
        run.step_count += 1
        return AgentTransition(replace(run), step=result)

    def _failed_request(
        self,
        request: AgentRunRequestEventData,
        code: str,
        message: str,
    ) -> AgentTransition:
        """处理失败的请求并返回相应的终态。"""
        run = AgentRun(
            run_id=request.run_id,
            session_id=request.session_id,
            behavior_type=request.behavior_type,
            behavior_state=request.behavior_state,
        )
        return AgentTransition(run, failure=FailEffect(code, message))

    def _require_run(self, run_id: str) -> AgentRun:
        """查找对应的 AgentRun, 如果不存在则抛出 LookupError"""
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise LookupError(f"Unknown AgentRun: {run_id}") from exc

    def _remove(self, run_id: str) -> None:
        """从 Runtime 中移除对应的 AgentRun, 并清理所有等待关联。"""
        self._runs.pop(run_id, None)
        stale = [key for key, value in self._operation_to_run.items() if value == run_id]
        for operation_id in stale:
            self._operation_to_run.pop(operation_id, None)


def _require_pure_data(value: object) -> None:
    """确保只有纯数据类型的对象可以作为 Behavior 的状态
    禁止运行时对象、函数、类、方法、协程、生成器、文件句柄等非数据类型，以便未来序列化或持久化
    """

    def visit(item: object, seen: set[int]) -> bool:
        if item is None or isinstance(item, (str, int, float, bool, datetime, date, time, Enum)):
            return True
        identity = id(item)
        if identity in seen:
            return False
        if is_dataclass(item) and not isinstance(item, type):
            seen.add(identity)
            valid = all(visit(getattr(item, field.name), seen) for field in fields(item))
            seen.remove(identity)
            return valid
        if isinstance(item, Mapping):
            seen.add(identity)
            valid = all(
                visit(key, seen) and visit(entry, seen) for key, entry in item.items()
            )
            seen.remove(identity)
            return valid
        if isinstance(item, Set):
            seen.add(identity)
            valid = all(visit(entry, seen) for entry in item)
            seen.remove(identity)
            return valid
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray)):
            seen.add(identity)
            valid = all(visit(entry, seen) for entry in item)
            seen.remove(identity)
            return valid
        return False

    if not visit(value, set()):
        raise TypeError("behavior_state must contain pure data only")
