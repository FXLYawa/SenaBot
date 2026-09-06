"""各模块共享的基础值对象与工具。"""

from core.common.clock import utc_now
from core.common.content import Content, ContentSegment, ContentType
from core.common.identifiers import new_id
from core.common.interaction import (
    ConversationScope,
    InteractionSignals,
    OutputRoute,
    SceneInfo,
    SceneType,
    SourceInfo,
    UserRole,
)
from core.common.summary import Summary

__all__ = [
    "Content",
    "ContentSegment",
    "ContentType",
    "ConversationScope",
    "InteractionSignals",
    "OutputRoute",
    "SceneInfo",
    "SceneType",
    "SourceInfo",
    "Summary",
    "UserRole",
    "new_id",
    "utc_now",
]
