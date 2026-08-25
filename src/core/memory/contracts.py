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
