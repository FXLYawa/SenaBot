from dataclasses import dataclass

from .models import Memory


@dataclass
class MemoryQueryRequest:
    """其他层发送给 Memory 层的查询请求。"""

    query_id: str

    group_id: str
    session_id: str
    user_id: str

    query_text: str


@dataclass
class MemoryQueryResult:
    """Memory 层返回的查询结果。"""

    query_id: str

    user_id: str
    session_id: str
    group_id: str

    memories: list[Memory]


@dataclass
class MemoryWriteRequest:
    """其他层发送给 Memory 层的写入请求。"""

    operation_id: str

    group_id: str
    session_id: str
    user_id: str
    source_event_id: str

    write_text: str


@dataclass
class MemoryWriteResult:
    """Memory 层返回的写入结果。"""

    operation_id: str

    group_id: str
    session_id: str
    user_id: str

    memory_id: str
