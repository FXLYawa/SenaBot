"""Context 的公开数据契约。

本文件只描述跨组件传递的数据形状
Session 是隔离工作边界; 每个 Session 始终对应一个 Context. Body 只提供稳定的
ConversationScope, Context 统一解析普通对话和内部 Work Session 的身份。
"""


from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from core.context.body import InteractionSignals, BodyRouteInfo
from core.context.common import Content, ConversationScope,SceneInfo, SourceInfo



class ContextEntryType(StrEnum):
    """上下文条目类型, 主要供调用, 也可以直接使用自定义类型"""

    USER_MESSAGE = "user_message" # 用户消息
    SENA_MESSAGE = "sena_message" # Sena 消息
    SYSTEM_NOTE = "system_note" # 系统消息
    
    
class ContextActorType(StrEnum):
    """上下文条目的生产者类型, 只标识来源"""

    USER = "user" # 用户
    SENA = "sena" # Sena
    SYSTEM = "system" # 系统
    TOOL = "tool" # 工具
    EXTENSION = "extension" # 扩展
    
    
@dataclass(frozen=True, slots=True)
class ContextActorRef:
    """用来标记谁说的话, 可以标记每句话的说话人"""

    actor_type: ContextActorType
    actor_id: str  # 生产者唯一标识
    display_name: str=""  # 生产者显示名称
    

@dataclass(frozen=True, slots=True)
class SessionRecord:
    """Context 系统内维护的 Session 生命周期快照"""
    
    session_id: str # 系统内会话ID
    created_at: datetime # 会话创建时间
    updated_at: datetime # 会话更新时间
    closed_at: datetime | None = None # 会话关闭时间
    purpose: str = "conversation" # 会话目的，默认是对话
    # 下面几个主要用于生成session_id时的来源信息，方便追溯和对应
    conversation_scope: ConversationScope | None = None # session 对应的 conversation 来源
    work_id: str | None = None # Session 对应的work agent id
    parent_session_id: str | None = None # 派生Session关联的父Session标识
    
    @property
    def is_closed(self) -> bool:
        """判断会话是否已关闭"""
        return self.closed_at is not None
    

@dataclass(frozen=True, slots=True)
class ContextEntryDraft:
    """待写入系统的上下文条目草稿"""
    
    entry_type: str # 上下文条目类型(可以使用 ContextEntryType 枚举, 也可以使用自定义类型)
    actor: ContextActorRef # 上下文条目的生产者（说话的主体）
    content: Content # 结构化的上下文正文
    source_event_id: str | None = None # 上下文条目来源事件标识，主要用于追溯
    
    
@dataclass(frozen=True, slots=True)
class ContextEntryRecord:
    """已经写入系统的上下文条目记录"""
    
    entry_id: str # 系统内上下文条目ID
    session_id: str # 所属会话ID
    sequence: int # 上下文条目递增序列号(只表达条目先后顺序)
    entry_type: str # 上下文条目类型
    actor: ContextActorRef # 上下文条目的生产者（说话的主体）
    content: Content # 结构化的上下文正文
    source_event_id: str | None # 上下文条目来源事件标识，主要用于追溯
    created_at: datetime  # 上下文条目创建时间
    
    def text(self) -> str:
        """获取条目内容的文本表示"""
        return self.content.text_value()
    
    
@dataclass(frozen=True, slots=True)
class ContextSummary:
    """上下文摘要信息"""
    
    summary_id: str # 系统内上下文摘要ID
    session_id: str # 所属会话ID
    level: int # 摘要层级，1覆盖原始条目，更高级摘要覆盖下一级摘要
    first_sequence: int # 覆盖的第一条原始 Context Entry 序号（含）
    last_sequence: int # 覆盖的最后一条原始 Context Entry 序号（含）
    text: str # 语义摘要
    created_at: datetime # 摘要产生时间
    source_summary_ids: tuple[str, ...] = () # 参与本次摘要的原始摘要 ID 列表
    
    def __post_init__(self) -> None:
        """验证摘要的层级和覆盖范围是否合法"""
        if self.level < 1:
            raise ValueError("summary level must be positive")
        if self.first_sequence < 1 or self.last_sequence < self.first_sequence:
            raise ValueError("summary sequence range is invalid")
        if self.level == 1 and self.source_summary_ids:
            raise ValueError("level-one summary cannot contain child summaries")
        if self.level > 1 and not self.source_summary_ids:
            raise ValueError("higher-level summary requires child summaries")
    
    
@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    """会话上下文快照"""
    
    session: SessionRecord # 会话记录
    latest_sequence: int # 上下文条目最新序列号
    entries: tuple[ContextEntryRecord, ...] # 上下文条目记录
    summaries: tuple[ContextSummary, ...] = ()  # 未被更高层覆盖的活动摘要
    
    
@dataclass(frozen=True, slots=True)
class ContextRestoreRequestData:
    """上下文恢复请求数据"""
    
    operation_id: str # 恢复操作唯一标识，避免重复恢复
    session_id: str # 会话ID
    
    
class ContextRestoreStatus(StrEnum):
    """Context 冷恢复的状态"""
    COMPLETED = "completed"
    NOT_FOUND = "not_found"
    FAILED = "failed"
    
    
@dataclass(frozen=True, slots=True)
class ContextRestoreResultEventData:
    """上下文恢复响应数据"""
    
    operation_id: str # 恢复操作唯一ID
    session_id: str # 会话ID
    status: ContextRestoreStatus # 恢复状态，completed/failed/not_found
    snapshot: ContextSnapshot | None = None # 会话上下文快照, 用于恢复成功时提供上下文信息
    error: ContextErrorInfo | None = None # 恢复失败时的错误信息
    
    def __post_init__(self) -> None:
        """在契约边界保证恢复结果只有一种明确终态"""
        if not isinstance(self.status, ContextRestoreStatus):
            raise TypeError("status must be ContextRestoreStatus")
        
        if self.status == ContextRestoreStatus.COMPLETED:
            if self.snapshot is None or self.error is not None:
                raise ValueError("completed restore requires only a snapshot")
            if self.snapshot.session.session_id != self.session_id:
                raise ValueError("restored snapshot session does not match result")
        elif self.status == ContextRestoreStatus.FAILED:
            if self.error is None or self.snapshot is not None:
                raise ValueError("failed restore requires only an error")
        elif self.snapshot is not None or self.error is not None:
            raise ValueError("not_found restore cannot contain snapshot or error")
    
    
@dataclass(frozen=True, slots=True)
class ContextPreparedEventData:
    """上下文准备完成事件数据"""
    
    session_id: str # 会话ID
    trigger_event_id: str # 触发上下文准备的事件标识
    trigger_entry_id: str # 触发上下文准备的条目标识
    entries: tuple[ContextEntryRecord, ...] # 上下文条目记录
    summaries: tuple[ContextSummary, ...]  # 按时间排列、可逐层展开的活动摘要
    output_route: BodyRouteInfo  # 长期任务恢复后仍可使用的 Body 输出路由。
    source: SourceInfo  # 原始主体信息
    scene: SceneInfo  # 原始场景信息
    interaction: InteractionSignals # 交互信号
    reply_to_message_id: str | None = None  # 回复目标的ID(用于回复特定语句)
    
    
@dataclass(frozen=True, slots=True)
class ContextAppendRequestData:
    """其他模块请求向指定 Session 追加一组有序条目"""
    
    session_id: str # 会话标识
    entries: tuple[ContextEntryDraft, ...]  # 按顺序追加的不可变条目的草稿
    close_after: bool = False # 是否在追加后关闭会话


@dataclass(frozen=True, slots=True)
class ContextWorkRequestData:
    """Work Agent请求的消息返回"""

    operation_id: str  # AgentRun 使用的操作 ID。
    work_id: str  # 稳定业务身份（主要是agent层的）
    purpose: str  # Work Session 的目的
    parent_session_id: str | None = None  # 可选来源 Conversation Session。


@dataclass(frozen=True, slots=True)
class ContextWorkReadyEventData:
    """Context 已解析 Work Session 的事实。"""

    operation_id: str  # 对应 ContextWorkRequestData的 operation_id。
    work_id: str  # 对应请求中的稳定 Work 身份。
    session_id: str  # Context 确定性生成或恢复的 Work Session ID。


@dataclass(frozen=True, slots=True)
class ContextWorkFailedEventData:
    """Context 无法解析 Work Session 的可观察结果。"""

    operation_id: str # 对应 ContextWorkRequestData的 operation_id。
    work_id: str # 同 ContextWorkReadyEventData
    error: ContextErrorInfo # 错误附加信息
    
    
@dataclass(frozen=True, slots=True)
class ContextErrorInfo:
    """跨事件传播的 Context 错误，不携带完整对话内容。"""

    code: str  # 稳定机器可读错误码。
    message: str  # 不含完整上下文正文的诊断消息。
    

@dataclass(frozen=True, slots=True)
class ContextInputFailedEventData:
    """输入因 Session 恢复或状态错误而未进入 Context。"""

    session_id: str  # 根据 ConversationScope 确定性解析的 Session ID。
    trigger_event_id: str  # 未被接纳的事件 ID。
    error: ContextErrorInfo  # 可观察的结构化失败，不包含完整输入正文。


@dataclass(frozen=True, slots=True)
class ContextHistoryRequestData:
    """请求读取某个摘要节点的直接下一层"""

    operation_id: str  # AgentRun 使用的操作 ID。
    session_id: str  # 当前 Run 已绑定的 Session，由 Dispatcher 填写。
    summary_id: str  # 要展开的当前可见摘要节点。
    

@dataclass(frozen=True, slots=True)
class ContextHistoryLevel:
    """摘要展开的内容; 高层摘要返回子摘要, Level 1 返回原始条目"""
    
    summary: ContextSummary  # 本次被展开的父摘要。
    summaries: tuple[ContextSummary, ...] = ()  # level - 1 的直接子摘要。
    entries: tuple[ContextEntryRecord, ...] = ()  # Level 1 覆盖的原始条目。

    def __post_init__(self) -> None:
        """约束结构用的校验"""

        if self.summary.level == 1 and self.summaries:
            raise ValueError("level-one history cannot contain summaries")
        if self.summary.level > 1 and self.entries:
            raise ValueError("higher-level history cannot contain raw entries")


@dataclass(frozen=True, slots=True)
class ContextHistoryResultEventData:
    """一次逐层历史读取的成功或失败结果。"""

    operation_id: str  # AgentRun 使用的操作 ID。
    history: ContextHistoryLevel | None = None  # 成功时返回的直接下一层。
    error: ContextErrorInfo | None = None  # 失败时返回的最小错误信息。

    def __post_init__(self) -> None:
        # 判断是否两者同时出现或同时不存在
        if (self.history is None) == (self.error is None):
            raise ValueError("context history result requires history or error")


@dataclass(frozen=True, slots=True)
class ContextStateChangedEventData:
    """上下文追加事件响应数据"""
    
    session: SessionRecord # 会话记录
    latest_sequence: int # 上下文条目最新序列号
    appended_entries: tuple[ContextEntryRecord, ...] # 新增的上下文条目记录
    created_summary: ContextSummary | None = None # 本次新建的上下文摘要
    
    @classmethod
    def from_snapshot(
        cls,
        snapshot: ContextSnapshot,
        appended_entries: tuple[ContextEntryRecord, ...] = (),
        created_summary: ContextSummary | None = None,
    ) -> ContextStateChangedEventData:
        """从当前只读快照构造可持久化的状态变化事实。"""

        return cls(
            snapshot.session,
            snapshot.latest_sequence,
            appended_entries,
            created_summary,
        )
