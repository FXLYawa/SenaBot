"""已加载 Context 的进程内集合与 Session 生命周期入口"""

from __future__ import annotations

from core.context.common import utc_now, ConversationScope
from core.context.compression import CompactionRequestData
from core.context.contracts import (
    ContextEntryDraft,
    ContextSnapshot,
    SessionRecord,
)
from core.context.identity import conversation_session_id, work_session_id
from core.context.state import AppendResult, CompactionResult, SessionState


class ContextStateStore:
    """Context 状态的公开写入 Interface
    
    Store 管理当前进程已经加载的 Session 集合以及创建、恢复入口
    """
    def __init__(self) -> None:
        # session_id 同时标识隔离 Session 及其 Context
        self._sessions: dict[str, SessionState] = {}
        
    def is_loaded(self, session_id: str) -> bool:
        """检查指定会话是否已加载"""
        return session_id in self._sessions
        
    def initialize_conversation(self, scope: ConversationScope) -> None:
        """初始化尚不存在的 Conversation Session"""

        session_id = conversation_session_id(scope)
        if session_id in self._sessions:
            return
        self._sessions[session_id] = self._new_session(
            session_id,
            purpose="conversation",
            conversation_scope=scope,
        )

    def resolve_work(
        self,
        purpose: str,
        work_id: str,
        parent_session_id: str | None = None,
    ) -> tuple[ContextSnapshot, bool]:
        """确定性解析或创建 Work Session, 返回快照及本次是否创建。"""

        # 创建稳定的 Session ID
        purpose = purpose.strip().casefold()
        work_id = work_id.strip()
        session_id = work_session_id(purpose, work_id)
        state = self._sessions.get(session_id)
        created = state is None
        if state is None: # 首次创建
            state = self._new_session(
                session_id,
                purpose=purpose,
                work_id=work_id,
                parent_session_id=parent_session_id,
            )
            self._sessions[session_id] = state
        elif state.session.parent_session_id != parent_session_id:
            raise ValueError("work session parent conflict")
        if state.session.is_closed:
            raise LookupError("session_closed")
        return state.snapshot(), created

    def append_entries(
        self,
        session_id: str,
        drafts: tuple[ContextEntryDraft, ...],
        *,
        close_after: bool = False, # 是否在追加后关闭会话
    ) -> AppendResult:
        """在指定 Session 中原子追加一批条目"""

        state = self._sessions.get(session_id)
        if state is None:
            raise LookupError("session_not_found")
        return state.append(drafts, close_after=close_after)

    def install_conversation_snapshot(
        self,
        snapshot: ContextSnapshot,
        scope: ConversationScope,
    ) -> bool:
        """校验并安装 Data 返回的 Conversation Session 快照, 用于重启恢复"""

        session = snapshot.session
        if (
            session.session_id != conversation_session_id(scope)
            or session.purpose != "conversation"
            or session.conversation_scope != scope
        ):
            return False
        return self._install_snapshot(snapshot)

    def install_work_snapshot(
        self,
        snapshot: ContextSnapshot,
        purpose: str,
        work_id: str,
        parent_session_id: str | None,
    ) -> bool:
        """校验并安装 Data 返回的 Work Session 快照, 用于重启恢复"""

        normalized_purpose = purpose.strip().casefold()
        normalized_work_id = work_id.strip()
        session = snapshot.session
        if (
            session.session_id
            != work_session_id(normalized_purpose, normalized_work_id)
            or session.purpose != normalized_purpose
            or session.work_id != normalized_work_id
            or session.parent_session_id != parent_session_id
            or session.conversation_scope is not None
        ):
            return False
        return self._install_snapshot(snapshot)

    def apply_compaction(
        self,
        request: CompactionRequestData,
        text: str,
    ) -> CompactionResult | None:
        """向已加载 Session 提交摘要；状态不存在或任务过期时返回 ``None``。"""

        state = self._sessions.get(request.session_id)
        if state is None:
            return None
        return state.compact(request, text)

    def _install_snapshot(self, snapshot: ContextSnapshot) -> bool:
        """安装已经通过对应身份校验的单 Session 快照。"""

        session_id = snapshot.session.session_id
        if session_id in self._sessions:
            return False
        self._sessions[session_id] = SessionState.from_snapshot(snapshot)
        return True

    @staticmethod
    def _new_session(
        session_id: str,
        purpose: str,
        conversation_scope: ConversationScope | None = None,
        work_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> SessionState:
        """构造一个已经解析稳定身份的新 Session 状态。"""

        now = utc_now()
        return SessionState(
            SessionRecord(
                session_id=session_id,
                created_at=now,
                updated_at=now,
                purpose=purpose,
                conversation_scope=conversation_scope,
                work_id=work_id,
                parent_session_id=parent_session_id,
            ),
            0,
            [],
            [],
        )
