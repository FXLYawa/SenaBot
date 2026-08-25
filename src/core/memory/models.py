from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar, TypeAlias


def _require_non_blank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _require_provenance(
    provenance: tuple["Provenance", ...],
) -> None:
    if not provenance:
        raise ValueError("provenance must not be empty")


def _validate_time_range(
    start: datetime | None,
    end: datetime | None,
    field_name: str,
) -> None:
    if start is None or end is None:
        return

    try:
        is_reversed = end < start
    except TypeError as error:
        raise ValueError(
            f"{field_name} must use compatible datetimes"
        ) from error

    if is_reversed:
        raise ValueError(f"{field_name} end must not precede start")


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

@dataclass(frozen=True)
class Entity:
    entity_type: str
    entity_id: str

@dataclass(frozen=True)
class Provenance:
    """信息来源"""

    source_type: str
    source_id: str

    def __post_init__(self) -> None:
        _require_non_blank(self.source_type, "source_type")
        _require_non_blank(self.source_id, "source_id")


class MemoryScopeKind(str, Enum):
    GLOBAL = "global"
    USER = "user"
    GROUP = "group"
    SESSION = "session"


@dataclass(frozen=True)
class MemoryScopeRef:
    """
    记忆可供召回的范围,表明当前记忆允许在哪些场景使用
    只作为第一级的召回边界检查
    """
    kind: MemoryScopeKind
    scope_id: str | None

    def __post_init__(self) -> None:
        """类型约束"""
        if self.kind is MemoryScopeKind.GLOBAL:
            if self.scope_id is not None:
                raise ValueError("global scope_id must be None")
            return

        if self.scope_id is None or not self.scope_id.strip():
            raise ValueError(
                f"{self.kind.value} scope_id must not be blank"
            )


class MemoryDomain(str, Enum):
    """具体业务上的 Memory 类型。"""

    FACT = "fact"
    EXPERIENCE = "experience"
    UNDERSTANDING = "understanding"
    KNOWLEDGE = "knowledge"


@dataclass(frozen=True)
class Fact:
    """
    关于用户的事实,不带有任何主观意见的事实,如生日,性别等
    不包含专业性强的知识
    """

    DOMAIN: ClassVar[MemoryDomain] = MemoryDomain.FACT

    #暂时先用自然语言,后续可扩展为多类型
    content: str

    provenance: tuple[Provenance, ...]

    recorded_at: datetime

    valid_from:datetime | None = None
    valid_to:datetime | None = None

    def __post_init__(self) -> None:
        _require_non_blank(self.content, "fact content")
        _require_provenance(self.provenance)
        _validate_time_range(
            self.valid_from,
            self.valid_to,
            "fact validity",
        )


@dataclass(frozen=True)
class Experience:
    """Bot和用户经历了什么"""

    DOMAIN: ClassVar[MemoryDomain] = MemoryDomain.EXPERIENCE

    summary: str
    provenance: tuple[Provenance, ...]
    participants: tuple[Entity, ...]
    occurred_from: datetime | None
    occurred_to: datetime | None
    recorded_at: datetime

    def __post_init__(self) -> None:

        """类型约束"""
        _require_non_blank(self.summary, "experience summary")
        _require_provenance(self.provenance)
        _validate_time_range(
            self.occurred_from,
            self.occurred_to,
            "experience occurrence",
        )


@dataclass(frozen=True)
class Understanding:

    """Bot形成的对于用户的长期认知和理解"""

    DOMAIN: ClassVar[MemoryDomain] = MemoryDomain.UNDERSTANDING

    content: str
    provenance: tuple[Provenance, ...]
    evidence_item_ids: tuple[str, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.content, "understanding content")
        _require_provenance(self.provenance)

        if not self.evidence_item_ids:
            raise ValueError("evidence_item_ids must not be empty")

        for evidence_item_id in self.evidence_item_ids:
            _require_non_blank(evidence_item_id, "evidence_item_id")


@dataclass(frozen=True)
class Knowledge:

    """Sena学会的专业性的知识内容"""

    DOMAIN: ClassVar[MemoryDomain] = MemoryDomain.KNOWLEDGE

    content: str
    provenance: tuple[Provenance, ...]
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require_non_blank(self.content, "knowledge content")
        _require_provenance(self.provenance)

MemoryPayload: TypeAlias = Fact | Experience | Understanding | Knowledge

@dataclass
class MemoryItem:
    """
    Memory总字段,用于和外界模块交互
    payload负责封装具体的业务结构
    公共字段放置外界模块需要频繁获得的字段
    """
    item_id: str
    memory_space_id: str
    scopes: frozenset[MemoryScopeRef]
    payload: MemoryPayload

    def __post_init__(self) -> None:
        if not self.scopes:
            raise ValueError("memory scopes must not be empty")

        has_global_scope = any(
            scope.kind is MemoryScopeKind.GLOBAL
            for scope in self.scopes
        )
        if has_global_scope and len(self.scopes) != 1:
            raise ValueError(
                "global scope cannot be combined with other scopes"
            )

    @property
    def domain(self) -> MemoryDomain:
        """根据 payload 类型返回唯一的业务领域。"""

        return self.payload.DOMAIN


@dataclass(frozen=True)
class MemoryQueryContext:
    """一次记忆查询可以访问的空间和作用域"""

    scopes: frozenset[MemoryScopeRef]

@dataclass
class MemoryQueryCriteria:
    """Memory 层查询 Data 层时使用的查询条件。"""

    query_text: str

    user_id: str
    session_id: str
    group_id: str


@dataclass
class MemoryRetrievalCandidate:
    memory: Memory
    score: float


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


@dataclass(frozen=True)
class MemoryMaterializationInput:
    """将原始候选转换为领域 Payload 所需的信息。"""

    candidate: MemoryCandidate
    provenance: tuple[Provenance, ...]
    recorded_at: datetime
    related_items: tuple[MemoryItem, ...] = ()

    def __post_init__(self) -> None:
        _require_provenance(self.provenance)


@dataclass(frozen=True)
class MemoryWriteEnvelope:
    """正式 MemoryItem 及其写入操作上下文。"""

    operation_id: str
    item: MemoryItem

    def __post_init__(self) -> None:
        _require_non_blank(self.operation_id, "operation_id")


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
