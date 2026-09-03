from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, TypeAlias


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
        raise ValueError(f"{field_name} must use compatible datetimes") from error

    if is_reversed:
        raise ValueError(f"{field_name} end must not precede start")


@dataclass(frozen=True)
class Entity:
    """表示一段记忆中涉及的主体，例如用户、Bot 或其他参与者."""

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


class MemoryScopeKind(StrEnum):
    GLOBAL = "global"
    USER = "user"
    GROUP = "group"
    SESSION = "session"


@dataclass(frozen=True)
class MemoryScopeRef:
    """
    记忆的长期归属边界。

    Scope 表示记忆属于哪个长期主体空间，不是未来使用场景的
    白名单，也不决定 Agent 是否在当前场景披露或发布该信息。

    持久化检索与召回粗筛的重要过滤依据之一
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
            raise ValueError(f"{self.kind.value} scope_id must not be blank")


class MemoryDomain(StrEnum):
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

    # 暂时先用自然语言,后续可扩展为多类型
    content: str

    provenance: tuple[Provenance, ...]

    recorded_at: datetime

    valid_from: datetime | None = None
    valid_to: datetime | None = None

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
    Memory 层对外流转的正式记忆对象。

    payload 封装具体业务内容，
    其余字段保存所有 Memory 类型共享的身份与归属信息。
    """

    # MemoryItem 的唯一标识。
    item_id: str

    # 记忆所属的长期 Memory Space，当前通常对应一个 Bot 的长期记忆空间。
    memory_space_id: str

    # 记忆在 Memory Space 内的长期归属范围，也是召回粗筛的重要依据。
    scopes: frozenset[MemoryScopeRef]

    # 具体的 Memory 业务内容，如 Fact、Experience 等。
    payload: MemoryPayload

    def __post_init__(self) -> None:
        if not self.scopes:
            raise ValueError("memory scopes must not be empty")

        has_global_scope = any(
            scope.kind is MemoryScopeKind.GLOBAL for scope in self.scopes
        )
        if has_global_scope and len(self.scopes) != 1:
            raise ValueError("global scope cannot be combined with other scopes")

    @property
    def domain(self) -> MemoryDomain:
        """根据 payload 类型返回唯一的业务领域。"""

        return self.payload.DOMAIN


@dataclass(frozen=True)
class MemoryRecallContext:
    """
    当前召回场景中可用于粗粒度候选检索的长期主体。

    Memory Space 已经由上层路由完成；这里只判断同一空间内的
    Scope 是否允许 MemoryItem 进入候选集。
    """

    scopes: frozenset[MemoryScopeRef]

    def matches(self, item: MemoryItem) -> bool:
        """
        判断当前召回上下文是否命中 MemoryItem 的长期归属范围。

        GLOBAL 记忆始终可以进入粗候选集；其他记忆只需有一个归属
        Scope 与当前上下文匹配。这里不判断语义相关性、敏感度或是否
        适合向当前参与者披露。
        """

        has_global_scope = any(
            scope.kind is MemoryScopeKind.GLOBAL for scope in item.scopes
        )
        if has_global_scope:
            return True

        return not item.scopes.isdisjoint(self.scopes)


@dataclass
class MemoryRetrievalCandidate:
    """
    Retriever 输出的候选记忆。

    memory 为召回到的正式 MemoryItem，
    score 表示该候选在当前检索阶段的相关性得分。
    """

    memory: MemoryItem
    score: float


@dataclass
class MemoryExtractionMessage:
    """
    Extraction 阶段使用的完整上下文。

    new_messages 是本次允许作为新记忆来源的消息；
    summary 和 recent_messages 只用于辅助理解当前消息；
    provenance 用于记录本次提取结果对应的来源信息。
    """

    message_id: str
    role: str
    content: str

    def __post_init__(self) -> None:
        _require_non_blank(self.message_id, "message_id")
        _require_non_blank(self.role, "message role")
        _require_non_blank(self.content, "message content")


@dataclass
class MemoryExtractionInput:
    """
    原始消息的合集
    通常为一对对话
     当前用户消息
    对应的最终 Agent 回复

    不包含历史摘要和最近历史消息；
    这些由 Extraction 阶段获取并作为辅助上下文。
    """

    messages: list[MemoryExtractionMessage]
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        _require_provenance(self.provenance)


@dataclass
class MemoryExtractionContext:
    """组装后的上下文"""

    new_messages: list[MemoryExtractionMessage]
    summary: str | None
    recent_messages: list[MemoryExtractionMessage]
    provenance: tuple[Provenance, ...]

    def __post_init__(self) -> None:
        _require_provenance(self.provenance)


@dataclass
class MemoryCandidate:
    """
    从对话或其他输入提取出的候选长期记忆

    Candidate仅表示"可能值得形成长期记忆"的信息
    尚未经过后续筛选,去重,冲突判断和正式写入
    """

    candidate_id: str

    # 原始内容
    content: str
    provenance: tuple[Provenance, ...]
    source_message_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_non_blank(self.candidate_id, "candidate_id")
        _require_non_blank(self.content, "candidate content")
        _require_provenance(self.provenance)

        if not self.source_message_ids:
            raise ValueError("source_message_ids must not be empty")

        for source_message_id in self.source_message_ids:
            _require_non_blank(source_message_id, "source_message_id")

        if len(set(self.source_message_ids)) != len(self.source_message_ids):
            raise ValueError("source_message_ids must not contain duplicates")


@dataclass(frozen=True)
class MemoryMaterializationInput:
    """将原始候选转换为领域 Payload 所需的信息。"""

    candidate: MemoryCandidate
    recorded_at: datetime
    related_items: tuple[MemoryItem, ...] = ()


@dataclass(frozen=True)
class MemoryFormationInput:
    """候选记忆进入 Formation 主链路所需的可信上下文。"""

    candidate: MemoryCandidate
    recorded_at: datetime
    recall_context: MemoryRecallContext
    memory_space_id: str
    scopes: frozenset[MemoryScopeRef]
    operation_id: str

    def __post_init__(self) -> None:
        _require_non_blank(self.memory_space_id, "memory_space_id")
        _require_non_blank(self.operation_id, "operation_id")

        if not self.scopes:
            raise ValueError("memory scopes must not be empty")

        has_global_scope = any(
            scope.kind is MemoryScopeKind.GLOBAL for scope in self.scopes
        )
        if has_global_scope and len(self.scopes) != 1:
            raise ValueError("global scope cannot be combined with other scopes")


@dataclass(frozen=True)
class MemoryReviewInput:
    """审查已成形 Payload 及其共享的相关记忆快照。"""

    payload: MemoryPayload
    related_items: tuple[MemoryItem, ...]


@dataclass(frozen=True)
class MemoryWriteEnvelope:
    """正式 MemoryItem 及其写入操作上下文。"""

    operation_id: str
    item: MemoryItem

    def __post_init__(self) -> None:
        _require_non_blank(self.operation_id, "operation_id")


@dataclass(frozen=True)
class MemorySupersedeResult:
    """持久化端口执行替代操作后返回的新旧版本。"""

    previous_item: MemoryItem
    replacement_item: MemoryItem
