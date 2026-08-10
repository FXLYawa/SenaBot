from dataclasses import dataclass
from typing import Any
from datetime import datetime

@dataclass
class Memory:
    """
    记忆本身在Memory层的表现形式
    用于查询,写入,遗忘
    注意和Data层的记忆存储数据结构作区分
    Data层的记忆结构是用于存储的
    Memory层的则是用于业务流转
    两者之间需要进行转换
    """

    memory_id: str
    content: str
    created_at: datetime
    updated_at: datetime
    operation_id:str

    user_id: str
    session_id: str
    group_id: str
    source_event_id: str

    metadata: dict[str, Any]

@dataclass
class MemoryQueryCriteria:
    """Memory 层查询 Data 层时使用的查询条件。"""

    query_text: str

    user_id: str
    session_id: str
    group_id: str
