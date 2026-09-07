"""Context 按原始序号读取归档的只读端口。"""

from typing import Protocol

from core.common import Summary
from core.context.contracts import ContextEntryRecord, SessionRecord


class ContextArchiveProtocol(Protocol):
    """提供归档事实；摘要选择和上下文视图组装由 Context 完成。"""

    def load_session(self, session_id: str) -> SessionRecord | None: ...

    def load_entries(
        self, session_id: str, after_sequence: int, through_sequence: int,
    ) -> tuple[ContextEntryRecord, ...]: ...

    def load_summaries(
        self, session_id: str, through_sequence: int,
    ) -> tuple[Summary, ...]: ...
