"""Memory 根据系统事件触发原始记录提取的策略与流程。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from core.common import SceneInfo, SceneType, new_id
from core.context import (
    ContextActorType,
    ContextReadRequestData,
    ContextReadResultEventData,
    ContextStateChangedEventData,
    SessionRecord,
)
from core.event import EventFlow
from core.memory.contracts import MemoryErrorInfo, MemoryExtractionFailedEventData
from core.memory.protocols import MemoryExtractionProgressProtocol
from core.memory.service import MemoryService


@dataclass(frozen=True, slots=True)
class MemoryExtractionPolicy:
    """数量按原始条目序号跨度计算；触发阈值与单批上限相互独立。"""

    enabled: bool = True
    # 按原始条目数设置触发阈值和单批处理上限。
    entry_threshold: int = 20
    batch_size: int = 40
    processing_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        for value in (self.entry_threshold, self.batch_size):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("memory extraction sequence limits must be positive integers")
        if not 0 < self.processing_timeout_seconds < float("inf"):
            raise ValueError("memory extraction timeout must be positive and finite")


@dataclass(frozen=True, slots=True)
class MemoryExtractionConfig:
    """绑定对话来源、记忆空间和用户，并指定该来源的提取策略。"""

    memory_space_id: str
    user_id: str
    scene: SceneInfo = field(default_factory=lambda: SceneInfo(
        platform="desktop", scene_type=SceneType.DESKTOP, scene_id="desktop",
    ))
    policy: MemoryExtractionPolicy = field(default_factory=MemoryExtractionPolicy)

    def __post_init__(self) -> None:
        if not self.memory_space_id.strip() or not self.user_id.strip():
            raise ValueError("memory extraction identity must not be blank")
        if self.scene.scene_type != SceneType.DESKTOP:
            raise ValueError("automatic extraction currently requires an owner desktop scene")


@dataclass(slots=True)
class _ExtractionState:
    """一个会话的提取进度和在途批次；只有成功处理边界需要持久化。"""

    # 记录最新观察到的原始序号，用于计算待处理条目数。
    latest_sequence: int
    # 连续成功处理到的序号，0 表示尚未处理任何条目。
    processed_through_sequence: int
    # 保存从上下文读取到提取结束的在途请求，标识该会话当前处理的批次。
    pending: ContextReadRequestData | None = None
    # 标记当前批次已收到上下文，正在执行提取与落库。
    processing: bool = False


class MemoryExtractionFlow:
    """根据系统事件判断提取时机，协调上下文读取、记忆处理和进度更新。"""

    def __init__(
        self,
        service: MemoryService,
        progress: MemoryExtractionProgressProtocol,
        config: MemoryExtractionConfig,
    ) -> None:
        self._service = service
        self._progress = progress
        self._config = config
        # 一个实例绑定一个来源配置；持久化键仍包含 memory_space_id 和 session_id。
        self._states: dict[str, _ExtractionState] = {}

    def _accepts(self, session: SessionRecord) -> bool:
        return session.purpose == "conversation" and session.scene == self._config.scene

    async def handle_context_changed(self, flow: EventFlow) -> None:
        """观察来源变化，加载或更新进度，再由数量策略决定是否创建批次。"""

        change: ContextStateChangedEventData = flow.payload
        if not self._accepts(change.session):
            return
        session_id = change.session.session_id
        state = self._states.get(session_id)
        if state is None:
            # 第一次收到该来源的变化才加载持久化进度；没有进度记录时端口返回 0。
            state = _ExtractionState(
                latest_sequence=change.latest_sequence,
                processed_through_sequence=self._progress.load_processed_sequence(
                    self._config.memory_space_id, session_id,
                ),
            )
            self._states[session_id] = state
        state.latest_sequence = max(state.latest_sequence, change.latest_sequence)
        self._consider_quantity(flow, session_id, state)

    def _consider_quantity(self, flow: EventFlow, session_id: str, state: _ExtractionState) -> None:
        """用最新序号减去已处理序号，达到数量阈值后尝试创建批次。"""

        if state.latest_sequence - state.processed_through_sequence < self._config.policy.entry_threshold:
            return
        self._schedule_batch(flow, session_id, state)

    def _schedule_batch(self, flow: EventFlow, session_id: str, state: _ExtractionState) -> None:
        """占用来源槽位，并按当前进度固定本批次原始范围。"""

        if state.pending is not None or state.latest_sequence <= state.processed_through_sequence:
            return
        # 从已处理序号之后取一批原文，以最新序号和单批上限确定终点。
        request = ContextReadRequestData(
            operation_id=new_id("memory_extraction"),
            session_id=session_id,
            after_sequence=state.processed_through_sequence,
            through_sequence=min(
                state.latest_sequence, state.processed_through_sequence + self._config.policy.batch_size,
            ),
        )
        # emit 暂存派生事件，处理器返回后才发布；届时 pending 已记录本次请求。
        flow.emit("context.read.requested", request)
        state.pending = request

    async def handle_context_read(self, flow: EventFlow) -> None:
        """匹配读取结果，完成提取与落库，成功后推进进度并判断下一批。"""

        # 按会话和 operation_id 找到当前等待的批次，并标记为处理中。
        result: ContextReadResultEventData = flow.payload
        state = self._states.get(result.session_id)
        if state is None or state.pending is None or state.processing:
            return
        request = state.pending
        if request.operation_id != result.operation_id:
            return
        state.processing = True
        try:
            if result.error is not None:
                self._fail(flow, request, result.error.code, result.error.message)
                return
            # 校验返回视图的来源和序号范围与本批请求一致。
            view = result.view
            if view is None or not self._accepts(view.session) or (
                view.after_sequence != request.after_sequence
                or view.through_sequence != request.through_sequence
            ):
                raise ValueError("context read does not match extraction batch")
            # 核对目标原文和前置原文中的用户身份，确认属于配置绑定的用户。
            if any(
                entry.actor.actor_type == ContextActorType.USER
                and entry.actor.actor_id != self._config.user_id
                for entry in (*view.preceding_entries, *view.entries)
            ):
                raise ValueError("context contains a user outside the configured extraction source")
            # 将完整视图交给 Service，在批次时限内完成候选提取、形成和落库。
            async with asyncio.timeout(self._config.policy.processing_timeout_seconds):
                extraction = await self._service.extract_and_store(
                    operation_id=request.operation_id,
                    memory_space_id=self._config.memory_space_id,
                    user_id=self._config.user_id,
                    context=view,
                )
            # 处理成功后保存本批终点、更新内存进度并发布结果；空候选和 no_change 也算成功。
            self._progress.save_processed_sequence(
                self._config.memory_space_id, request.session_id, request.through_sequence,
            )
            state.processed_through_sequence = request.through_sequence
            flow.emit("memory.extraction.completed", extraction)
        except Exception as error:
            self._fail(flow, request, type(error).__name__, "Automatic memory extraction failed.")
            return
        finally:
            # 失败也释放槽位，但保留原进度，等待后续来源变化重新判断。
            state.pending = None
            state.processing = False
        # 提取期间的新条目只更新上界，批次成功后重新按同一策略判断。
        self._consider_quantity(flow, request.session_id, state)

    def _fail(
        self, flow: EventFlow, request: ContextReadRequestData, code: str, message: str,
    ) -> None:
        flow.emit(
            "memory.extraction.failed",
            MemoryExtractionFailedEventData(
                operation_id=request.operation_id,
                memory_space_id=self._config.memory_space_id,
                session_id=request.session_id,
                error=MemoryErrorInfo(code, message),
            ),
        )
