from dataclasses import dataclass

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
class MemoryExtractionResult:
    """一批原始记录已完成提取的事实；没有候选时，变更列表可以为空。"""

    operation_id: str
    memory_space_id: str
    session_id: str
    processed_through_sequence: int

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
class MemoryExtractionFailedEventData:
    """本次提取未完成；已成功处理的批次保留其进度。"""

    operation_id: str
    memory_space_id: str
    session_id: str
    error: MemoryErrorInfo
