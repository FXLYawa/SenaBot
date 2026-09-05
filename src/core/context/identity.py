"""Context 拥有的稳定 Session 身份规则"""

from __future__ import annotations

import json
from uuid import UUID, uuid5

from core.common import ConversationScope


_SESSION_NAMESPACE = UUID("4ef8a6e5-2f0f-5a2a-b19f-87d62ebc4c2d")


def conversation_session_id(scope: ConversationScope) -> str:
    """从稳定交互范围确定性生成 Conversation Session ID。"""

    return _session_id(
        "conversation",
        scope.account_namespace,
        scope.platform,
        scope.scene_type.value,
        scope.scene_id,
    )


def work_session_id(purpose: str, work_id: str) -> str:
    """从稳定 Work 身份确定性生成隔离 Session ID。"""

    purpose = purpose.strip().casefold()
    work_id = work_id.strip()
    if not purpose or purpose == "conversation" or not work_id:
        raise ValueError("valid work purpose and work_id are required")
    return _session_id("work", purpose, work_id)


def _session_id(kind: str, *parts: str) -> str:
    """使用固定 UUIDv5 namespace"""

    canonical = json.dumps((kind, *parts), ensure_ascii=False, separators=(",", ":"))
    return f"session_{uuid5(_SESSION_NAMESPACE, canonical).hex}"
