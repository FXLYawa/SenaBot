from dataclasses import dataclass

from .models import MemoryItem


@dataclass
class MemoryQueryRequest:
    """其他层发送给 Memory 层的查询请求。"""

    #确认该数据结构的唯一ID
    query_id: str

    #群聊ID
    group_id: str
    #会话ID
    session_id: str
    user_id: str

    #具体query内容
    query_text: str


@dataclass
class MemoryQueryResult:
    """Memory 层返回的查询结果。"""

    #标识该数据结构的唯一ID
    query_id: str

    user_id: str
    #会话ID
    session_id: str
    #群聊ID
    group_id: str

    #返回的记忆
    memories: list[MemoryItem]


@dataclass
class MemoryWriteRequest:
    """其他层发送给 Memory 层的写入请求。"""

    #一次写入操作的唯一标识
    operation_id: str

    #群聊ID
    group_id: str

    #会话ID
    session_id: str
    user_id: str

    #来源的event_id
    source_event_id: str

    write_text: str


@dataclass
class MemoryWriteResult:
    """Memory 层返回的写入结果。"""

    #一次写入操作的唯一标识
    operation_id: str

    #群聊ID
    group_id: str

    #会话ID
    session_id: str

    user_id: str

    #返回的Memory标识
    memory_id: str
