"""业务无关的 AgentRun 生命周期与事件恢复。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping, Sequence, Set
from contextlib import asynccontextmanager
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
        self._run_locks: dict[str, asyncio.Lock] = {}  # 串行化资源随 Run 创建和释放。

    @asynccontextmanager
    async def start(
        self, request: AgentRunRequestEventData,
    ) -> AsyncGenerator[AgentTransition | None, None]:
        """创建 Run，并执行首次 step"""

        if request.run_id in self._runs:
            yield self._failed_request(request, "run_conflict", "AgentRun already exists.")
            return
        if request.behavior_type not in self._behaviors:
            yield self._failed_request(
                request,
                "behavior_not_found",
                f"Behavior is not available: {request.behavior_type}",
            )
            return
        _require_pure_data(request.behavior_state) # 数据校验，确保只有纯数据内容
        _require_pure_data(request.delivery_bindings)
        # 保存本次运行的行为状态和交付绑定。每个 Run 使用自己的锁，分别处理各自的结果。
        run = AgentRun(
            run_id=request.run_id,
            session_id=request.session_id,
            behavior_type=request.behavior_type,
            behavior_state=request.behavior_state,
            delivery_bindings=request.delivery_bindings,
        )
        self._runs[run.run_id] = run
        lock = self._run_locks[run.run_id] = asyncio.Lock()
        try:
            async with lock:
                # 首次 step 完成后，通过 yield 将结果交给 RunFlow 调用 Dispatcher。
                # 此时仍持有锁；等 Dispatcher 处理完、RunFlow 退出 async with 后才释放。
                yield await self._step(run, AgentObservation(AgentObservationType.STARTED))
        except (Exception, asyncio.CancelledError):
            # 本步未能完成交付时终止等待；异常继续交给事件层记录和处理。
            if self._runs.get(run.run_id) is run:
                self._remove(run.run_id)
            raise

    @asynccontextmanager
    async def resume(
        self,
        operation_id: str,
        observation: AgentObservation,
    ) -> AsyncGenerator[AgentTransition | None, None]:
        """串行消费单个结果，锁覆盖 Behavior 的 step，以及 plan 的应用"""

        # 根据返回结果的 operation_id 找到正在等待它的 Run；找不到就忽略这个结果。
        run_id = self._operation_to_run.get(operation_id)
        if run_id is None:
            yield None
            return
        run = self._require_run(run_id)
        lock = self._run_locks[run_id]
        consumed = False  # 记录本次调用是否已经取走了对应的 pending，供异常处理时判断。
        try:
            async with lock:
                # 排队期间 Run 可能结束，或同一操作的另一个结果已被消费。
                if self._runs.get(run_id) is not run or operation_id not in run.pending_operations:
                    yield None
                    return
                # 这个操作已经返回结果，从 Run 的等待列表和操作到 Run 的映射中移除它。
                # 其他操作照常等待；同一个结果再次到达时会被忽略。
                pending = run.pending_operations.pop(operation_id)
                self._operation_to_run.pop(operation_id)
                consumed = True
                # 将 pending 中的 request_key 交给 Behavior，让它知道是哪项请求返回了。
                # 等本次 step 及 Dispatcher 的处理都完成后，同一 Run 才能处理下一个结果。
                yield await self._step(
                    run, replace(observation, request_key=pending.request_key),
                )
        except (Exception, asyncio.CancelledError):
            # 若本次处理出错或被取消，而结果已由本次调用取走、或仍在等待处理，就清理整个 Run。
            # is run 确保清理的是原来的运行；若另一调用已取走重复结果，则保留 Run。
            if self._runs.get(run_id) is run and (
                consumed or operation_id in run.pending_operations
            ):
                self._remove(run_id)
            raise

    def wait_for(
        self,
        run_id: str,
        operations: Sequence[PendingOperation],
    ) -> None:
        """完整校验本批操作后追加等待，保留此 Run 已登记的其他请求。"""

        run = self._require_run(run_id) # 查找对应的 AgentRun
        # 先检查整批新请求，再登记。operation_id 不能与任何 Run 正在等待的操作重复；
        # request_key 只需在当前 Run 的未完成请求中唯一，本批请求之间也要检查。
        additions: dict[str, PendingOperation] = {}
        request_keys = {pending.request_key for pending in run.pending_operations.values()}
        for pending in operations:
            if not pending.operation_id.strip() or not pending.request_key.strip():
                raise ValueError("Agent operation ID and request key must not be blank")
            if pending.operation_id in self._operation_to_run or pending.operation_id in additions:
                raise ValueError(f"Agent operation already exists: {pending.operation_id}")
            if pending.request_key in request_keys:
                raise ValueError(f"Agent request key already pending: {pending.request_key}")
            additions[pending.operation_id] = pending
            request_keys.add(pending.request_key)
        # 检查通过后，一起保存新 pending 和操作到 Run 的映射，后续结果就能找到对应的 Run。
        run.pending_operations.update(additions)
        self._operation_to_run.update((operation_id, run_id) for operation_id in additions)

    def complete(self, run_id: str, outcome: str = "completed") -> AgentTransition:
        """结束 Run 并返回完成终态。"""
        run = self._require_run(run_id)
        # 先保存结束时的状态，供 Dispatcher 发布完成事件，再清理 Run 和剩余 pending。
        snapshot = _snapshot(run)
        self._remove(run_id)
        return AgentTransition(snapshot, outcome=outcome)

    def fail(self, run_id: str, failure: FailEffect) -> AgentTransition:
        """结束 Run 并返回失败终态。"""
        run = self._require_run(run_id)
        # 保存失败时的状态，并清理 Run 和剩余 pending；之后返回的结果会被忽略。
        snapshot = _snapshot(run)
        self._remove(run_id)
        return AgentTransition(snapshot, failure=failure)

    async def _step(
        self,
        run: AgentRun,
        observation: AgentObservation, # Behavior.step() 的输入数据
    ) -> AgentTransition | None:
        """执行一次 Behavior.step() 并返回下一步的状态和 Effect。"""
        if run.step_count >= self.max_steps:
            return self.fail(
                run.run_id,
                FailEffect("step_limit_exceeded", "AgentRun exceeded its step limit."),
            )
        # 将当前状态和本次结果交给 Behavior。它可以发出新的 Effect，也可以只保存结果、继续等待。
        # 检查返回的状态是否为纯数据，再保存到 Run 中。
        behavior = self._behaviors[run.behavior_type]
        try:
            result = await behavior.step(run.behavior_state, observation)
            _require_pure_data(result.next_state)
        except Exception as exc:
            if self._runs.get(run.run_id) is not run:
                return None
            return self.fail(
                run.run_id,
                FailEffect("behavior_failed", f"{type(exc).__name__}: {exc}"),
            )
        # 其他结果在排队时被取消可能已终止此 Run，旧步骤返回后只丢弃其结果。
        if self._runs.get(run.run_id) is not run:
            return None
        # 保存新状态，step 次数加一，再把当前状态的快照和本步 Effect 交给 Dispatcher。
        run.behavior_state = result.next_state
        run.step_count += 1
        return AgentTransition(_snapshot(run), step=result)

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
            delivery_bindings=request.delivery_bindings,
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
        # 移除 Run 和它的锁记录，并删除剩余操作到这个 Run 的映射。
        # 已发出的外部操作仍会继续执行，但它们返回结果后，resume 会直接忽略。
        run = self._runs.pop(run_id, None)
        self._run_locks.pop(run_id, None)
        if run is not None:
            for operation_id in run.pending_operations:
                self._operation_to_run.pop(operation_id, None)


def _snapshot(run: AgentRun) -> AgentRun:
    """固定当前等待集合，交付计划和终态读取独立的运行快照。"""

    return replace(run, pending_operations=dict(run.pending_operations))


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
