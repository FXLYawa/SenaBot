from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


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
    operation_id: str

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


@dataclass
class MemoryExtractionMessage:
    """
    用户与AI的原始聊天消息
    """

    # 角色,一般只有user和AI两个字段,设计数据库时需要加上字段约束
    role: str
    content: str


@dataclass
class MemoryExtractionInput:
    """
    原始消息的合集
    通常为一对对话
     当前用户消息
    对应的最终 Agent 回复

    不包含历史摘要和最近历史消息；
    这些由 Extraction 阶段自行获取并作为辅助上下文。
    """

    messages: list[MemoryExtractionMessage]
    # 预留给后续来源信息贯穿（如 source_event_id 和作用域标识）。
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryExtractionContext:
    new_messages: list[MemoryExtractionMessage]
    summary: str | None
    recent_messages: list[MemoryExtractionMessage]


@dataclass
class MemoryCandidate:
    """
    从对话或其他输入提取出的候选长期记忆

    Candidate仅表示"可能值得形成长期记忆"的信息
    尚未经过后续筛选,去重,冲突判断和正式写入
    """

    content: str
    # 一些候选的额外信息,如果没有传metadata,自动创建一个新的空字典
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryUpdateAction(str, Enum):
    """
    操作行为的枚举类,分别表示:
    ADD:完全新内容
    UPDATE:存在旧记忆，但旧记忆需要被补充
    DELETE:旧记忆已经被推翻,不再有效
    NONE:不需要入库
    """

    ADD = "add"
    UPDATE = "update"

    # MVP 暂按物理删除处理；若想保证人格变化,未来可演化为失效标记以保留历史状态。
    DELETE = "delete"
    NONE = "none"


@dataclass
class MemoryUpdateDecision:
    """
    对于某条长期记忆候选,最终决定对已有记忆执行什么操作
    """
    action: MemoryUpdateAction

    candidate: MemoryCandidate

    # 要更新或删除的memory_id,ADD和None操作固定为None
    target_memory_id: str | None = None

    # 新记忆或者更新后的内容
    content: str | None = None


@dataclass
class MemoryUpdateInput:
    """候选记忆进入审查、更新与正式入库流程时所需的业务上下文。"""

    candidate: MemoryCandidate

    user_id: str
    session_id: str
    group_id: str

    source_event_id: str
    operation_id: str
