from dataclasses import dataclass
from datetime import datetime

from .models import MemoryItem

Memory = MemoryItem


@dataclass
class MemoryQueryRequest:
    """其他层发送给 Memory 层的查询请求。"""

    # 确认该数据结构的唯一ID
    query_id: str

    # 记忆所属的长期 Memory Space，当前通常对应一个 Bot 的长期记忆空间。
    memory_space_id: str

    # 群聊ID
    group_id: str
    # 会话ID
    session_id: str
    user_id: str

    # 具体query内容
    query_text: str

    def __post_init__(self) -> None:
        if not self.memory_space_id.strip():
            raise ValueError("memory_space_id must not be blank")


@dataclass
class MemoryQueryResult:
    """Memory 层返回的查询结果。"""

    # 标识该数据结构的唯一ID
    query_id: str

    memory_space_id: str

    user_id: str
    # 会话ID
    session_id: str
    # 群聊ID
    group_id: str

    # 返回的记忆
    memories: list[MemoryItem]


@dataclass(frozen=True)
class MemoryWriteMessage:
    """
    Memory 写入事件中的公开消息结构。
    表明一条消息的发起者和具体内容

    只描述上游可以确定的消息事实，
    不暴露 Memory 内部 Extraction 模型。
    """

    # 唯一ID
    message_id: str

    # 由什么角色发起
    role: str

    # 具体内容
    content: str

    def __post_init__(self) -> None:
        if not self.message_id.strip():
            raise ValueError("message_id must not be blank")
        if not self.role.strip():
            raise ValueError("role must not be blank")
        if not self.content.strip():
            raise ValueError("content must not be blank")


@dataclass(frozen=True)
class MemoryWriteSummary:
    """
    Memory 写入事件中的公开摘要结构。

    形状对齐 Context 的多级 Summary，但不直接依赖 Context 模块实现。
    """

    summary_id: str
    level: int
    first_sequence: int
    last_sequence: int
    text: str

    def __post_init__(self) -> None:
        if not self.summary_id.strip():
            raise ValueError("summary_id must not be blank")
        if self.level < 1:
            raise ValueError("summary level must be positive")
        if self.first_sequence < 1 or self.last_sequence < self.first_sequence:
            raise ValueError("summary sequence range is invalid")
        if not self.text.strip():
            raise ValueError("summary text must not be blank")


@dataclass(frozen=True)
class MemoryWriteRequest:
    """
    触发一次完整 Memory 写入流程的公开请求。

    Memory 内部会自行完成：
    Extraction -> Candidate -> Formation -> Change Execution。
    """

    # 用于关联整个写入流程及上游 PendingOperation。
    operation_id: str

    # 当前长期 Memory Space。
    # 当前接口暂时由上游提供；persona_id / bot_id 到
    # memory_space_id 的映射责任可继续单独确认。
    memory_space_id: str

    # 当前交互场景中的客观身份信息。
    user_id: str
    session_id: str
    group_id: str

    # 具体作为长期记忆的写入消息。
    messages: tuple[MemoryWriteMessage, ...]

    # Extraction 可以参考但不能直接作为本轮新记忆来源的上下文。
    recent_messages: tuple[MemoryWriteMessage, ...] = ()
    # 对齐 Context 活动前沿中的多级摘要。
    summaries: tuple[MemoryWriteSummary, ...] = ()

    # 本轮写入来源事件。
    # Memory 内部据此构造 Provenance。
    source_event_id: str = ""

    # 本轮信息被 Memory 记录的时间。
    recorded_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.operation_id.strip():
            raise ValueError("operation_id must not be blank")
        if not self.memory_space_id.strip():
            raise ValueError("memory_space_id must not be blank")
        if not self.user_id.strip():
            raise ValueError("user_id must not be blank")
        if not self.session_id.strip():
            raise ValueError("session_id must not be blank")
        if not self.source_event_id.strip():
            raise ValueError("source_event_id must not be blank")
        if not self.messages:
            raise ValueError("messages must not be empty")


@dataclass(frozen=True)
class MemoryWriteResult:
    """
    一次完整 Memory 写入流程的公开结果。

    只暴露最终受到影响的正式 MemoryItem 标识，
    不暴露 Candidate、ChangePlan、ExecutionResult 等内部模型。
    """

    operation_id: str
    memory_space_id: str

    added_item_ids: tuple[str, ...] = ()
    updated_item_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryErrorInfo:
    """Memory 事件链路中的失败信息。"""

    code: str
    message: str


@dataclass(frozen=True)
class MemoryQueryFailedEventData:
    """Memory 查询事件处理失败。"""

    query_id: str
    memory_space_id: str
    error: MemoryErrorInfo


@dataclass(frozen=True)
class MemoryWriteFailedEventData:
    """Memory 写入事件处理失败。"""

    operation_id: str
    memory_space_id: str
    error: MemoryErrorInfo
