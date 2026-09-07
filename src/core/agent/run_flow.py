"""AgentRun 启动、外部结果恢复与终态分发的事件 Adapter。"""

from __future__ import annotations

from core.agent.contracts import AgentObservation, AgentObservationType
from core.agent.dispatcher import AgentDispatcher
from core.agent.runtime import AgentRuntime, AgentTransition
from core.event import EventFlow
from core.memory import (
    MemoryQueryFailedEventData,
    MemoryQueryResult,
)


class RunFlow:
    """处理 AgentRun 的启动和外部结果恢复，不解释业务触发来源。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        dispatcher: AgentDispatcher,
    ) -> None:
        self._runtime = runtime # 控制 Run 生命周期的 Runtime
        self._dispatcher = dispatcher # 负责校验 Step、维护 Run 等待关系，并委托 Delivery 发布业务事件

    async def handle_run_requested(self, flow: EventFlow) -> None:
        """启动一个 Run，并立即分发它的首个状态迁移。
        处理 agent.run.requested 事件
        """

        await self._dispatch(flow, await self._runtime.start(flow.payload))

    async def handle_memory_query_result(self, flow: EventFlow) -> None:
        """用 Memory 查询结果恢复等待中的 Run。
        处理 memory.query.completed 事件
        """

        result: MemoryQueryResult = flow.payload
        await self._resume(flow, result.query_id, result, "completed")

    async def handle_memory_query_failed(self, flow: EventFlow) -> None:
        """用 Memory 查询失败结果恢复等待中的 Run。"""

        result: MemoryQueryFailedEventData = flow.payload
        await self._resume(flow, result.query_id, result, "failed")

    async def _resume(
        self,
        flow: EventFlow,
        operation_id: str,
        payload: object,
        resolution_status: str,
    ) -> None:
        """恢复等待中的 Run，并分发它的状态迁移。"""
        
        transition = await self._runtime.resume(
            operation_id,
            AgentObservation(
                kind=AgentObservationType.EXTERNAL_RESULT,
                payload=payload,
                resolution_status=resolution_status,
            ),
        )
        if transition is not None:
            await self._dispatch(flow, transition)

    async def _dispatch(
        self,
        flow: EventFlow,
        transition: AgentTransition,
    ) -> None:
        self._dispatcher.dispatch(flow, transition)
