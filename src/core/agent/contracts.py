"""Agent 行为运行、观察和语义 Effect 契约"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol, TypeAlias

from core.common import (
    OutputRoute,
    SceneInfo,
    SourceInfo,
    Summary,
)
from core.context import ContextEntryRecord


"""Agent 内部运行模型"""


# Behavior 类型标识符
CONVERSATION_BEHAVIOR = "conversation"


class AgentObservationType(StrEnum):
    """告知 Behavior 调用是为什么发生的"""

    STARTED = "started"  # Behavior 被 Runtime 创建并首次调用 step
    EXTERNAL_RESULT = "external_result" # Behavior 的上次 step 产生了一个外部请求，现在外部请求反馈结果回来


@dataclass(frozen=True, slots=True)
class AgentObservation:
    """Runtime 交给 Behavior 的单次 step 调用的输入数据。"""

    kind: AgentObservationType  # 标识当前调用的原因
    payload: object | None = None # 外部调用的结果数据，Behavior 自行解析
    resolution_status: str = "completed" # 外部结果的状态（completed, failed, etc.）


@dataclass(frozen=True, slots=True)
class PendingOperation:
    """AgentRun 当前正在等待外部结果的操作"""

    operation_id: str  # 用于把外部结果重新关联到原 Run 
    # 当前同一个 Run 同时只有一个PendingOperation，后续可能可以考虑添加并行的PendingOperation列表


@dataclass(slots=True)
class AgentRun:
    """Behavior 的一次运行实例; Runtime 不负责解释 behavior_state。"""

    run_id: str # 单次运行的 id
    session_id: str | None  # 发起 Run 的会话关联，不限定 Behavior 的工作存储位置。
    behavior_type: str  # 指定 Behavior 的类型，Runtime 只负责路由到对应的 Behavior 实现。
    behavior_state: object # Behavior 的私有状态，Runtime 不解释负责解释
    pending_operation: PendingOperation | None = None # 是否在等待外部行为，没有的话为 None
    step_count: int = 0 # 记录 Behavior step 的次数


"""
Behavior 通过 Effect 向 Runtime 传达语义工作结果
然后Dispatcher将这些Effect转化为Event,交给EventBus处理
Effect是Behavior到Dispatcher的语义契约
"""


@dataclass(frozen=True, slots=True)
class ReplyEffect:
    """表示sena想要回复用户的消息"""

    text: str # 回复文本
    session_id: str # 回复的会话id
    trigger_event_id: str # 触发本次回复的事件id
    output_route: OutputRoute # 回复的输出路由
    scene: SceneInfo # 当前的交互场景
    reply_to_message_id: str | None = None  # 是否要引用某条消息进行回复


@dataclass(frozen=True, slots=True)
class MemoryQueryEffect:
    """Behavior 想要请求记忆查询"""

    operation_id: str # 用于把外部结果重新关联到当前 AgentRun
    query: str # 检索内容
    requester: SourceInfo # 请求者信息
    session_id: str # 会话id
    scene: SceneInfo # 当前交互场景
    persona_id: str # 角色id


@dataclass(frozen=True, slots=True)
class MemoryWriteEffect:
    """希望 Memory 从一组 Context 消息中形成长期记忆。"""

    operation_id: str
    messages: tuple[ContextEntryRecord, ...]
    requester: SourceInfo
    session_id: str
    scene: SceneInfo
    persona_id: str
    source_event_id: str
    recent_messages: tuple[ContextEntryRecord, ...] = ()
    summaries: tuple[Summary, ...] = ()
    recorded_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FinishEffect:
    """Behavior 已完成语义工作。"""
    # 无需字段，只需要表达这一结果即可


@dataclass(frozen=True, slots=True)
class FailEffect:
    """Behavior 无法继续而返回失败"""

    code: str
    message: str


# 合法 Effect 的联合类型
AgentEffect: TypeAlias = (
    ReplyEffect
    | MemoryQueryEffect
    | MemoryWriteEffect
    | FinishEffect
    | FailEffect
)


"""Behavior 接口"""


@dataclass(frozen=True, slots=True)
class AgentStepResult:
    """一次 Behavior.step 的输出"""

    next_state: object # Behavior 下一步使用的状态
    effects: tuple[AgentEffect, ...] # 本次希望系统执行的动作


class Behavior(Protocol):
    """角色行为的唯一 Interface。"""

    async def step(
        self,
        state: object,
        observation: AgentObservation,
    ) -> AgentStepResult: ...


"""Event 契约"""


@dataclass(frozen=True, slots=True)
class AgentRunRequestEventData:
    """向agent请求创建一个新的agent run"""

    run_id: str # 单次运行的 id
    session_id: str | None
    behavior_type: str 
    behavior_state: object


@dataclass(frozen=True, slots=True)
class AgentInteractionIgnoredEventData:
    """InteractionPolicy 决定不参与当前输入。"""

    session_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class AgentRunCompletedEventData:
    """表示一个 AgentRun 结束了任务"""

    agent_run_id: str # AgentRun 的id
    session_id: str | None
    behavior_type: str
    outcome: str = "completed"


@dataclass(frozen=True, slots=True)
class AgentRunFailedEventData:
    """表示一个 AgentRun 失败了"""

    agent_run_id: str # AgentRun 的id
    session_id: str | None
    behavior_type: str
    code: str
    message: str
