"""Context 和 Memory 共享的分层摘要。"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Summary:
    """保留会话、原始条目覆盖范围和来源关系的摘要节点。"""

    summary_id: str
    session_id: str
    level: int  # 一级覆盖原始条目，更高层覆盖下一级摘要。
    first_sequence: int  # 原始条目覆盖范围的起点，包含该条目。
    last_sequence: int  # 原始条目覆盖范围的终点，包含该条目。
    text: str  # 未启用语义压缩时可为空，节点仍可用于展开历史。
    created_at: datetime
    source_summary_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.summary_id.strip():
            raise ValueError("summary_id must not be blank")
        if self.level < 1:
            raise ValueError("summary level must be positive")
        if self.first_sequence < 1 or self.last_sequence < self.first_sequence:
            raise ValueError("summary sequence range is invalid")
        if self.level == 1 and self.source_summary_ids:
            raise ValueError("level-one summary cannot contain child summaries")
        if self.level > 1 and not self.source_summary_ids:
            raise ValueError("higher-level summary requires child summaries")
