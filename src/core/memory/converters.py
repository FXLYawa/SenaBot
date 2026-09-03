"""Memory 公开 DTO 与内部模型之间的转换函数。"""

from __future__ import annotations

from core.memory.contracts import (
    MemoryWriteMessage,
    MemoryWriteRequest,
    MemoryWriteResult,
)
from core.memory.executor import MemoryChangeExecutionResult
from core.memory.models import (
    MemoryExtractionMessage,
    MemoryRecallContext,
    MemoryScopeKind,
    MemoryScopeRef,
    Provenance,
)


def to_extraction_messages(
    messages: tuple[MemoryWriteMessage, ...],
) -> list[MemoryExtractionMessage]:
    """把公开写入消息转换为 Extraction 内部消息。"""

    return [
        MemoryExtractionMessage(
            message_id=message.message_id,
            role=message.role,
            content=message.content,
        )
        for message in messages
    ]


def to_provenance(request: MemoryWriteRequest) -> tuple[Provenance, ...]:
    """根据写入请求构造记忆来源信息。"""

    return (
        Provenance(
            source_type="event",
            source_id=request.source_event_id,
        ),
    )


def build_recall_context(request: MemoryWriteRequest) -> MemoryRecallContext:
    """根据写入请求构造 Formation 阶段召回相关记忆的边界。即查旧记忆时的检索边界"""

    return MemoryRecallContext(scopes=_scopes_from_request(request))


def build_candidate_scopes(request: MemoryWriteRequest) -> frozenset[MemoryScopeRef]:
    """根据写入请求构造新 MemoryItem 的长期归属范围。即写新记忆的新记忆归属"""

    return _scopes_from_request(request)


def to_write_result(
    request: MemoryWriteRequest,
    execution_results: list[MemoryChangeExecutionResult],
) -> MemoryWriteResult:
    """把内部执行结果转换为公开写入结果。"""

    added_item_ids: list[str] = []
    updated_item_ids: list[str] = []
    for result in execution_results:
        added_item_ids.extend(item.item_id for item in result.added_items)
        updated_item_ids.extend(item.item_id for item in result.updated_items)

    return MemoryWriteResult(
        operation_id=request.operation_id,
        memory_space_id=request.memory_space_id,
        added_item_ids=tuple(added_item_ids),
        updated_item_ids=tuple(updated_item_ids),
    )


def _scopes_from_request(request: MemoryWriteRequest) -> frozenset[MemoryScopeRef]:
    scopes = {
        MemoryScopeRef(
            kind=MemoryScopeKind.USER,
            scope_id=request.user_id,
        ),
        MemoryScopeRef(
            kind=MemoryScopeKind.SESSION,
            scope_id=request.session_id,
        ),
    }
    if request.group_id.strip():
        scopes.add(
            MemoryScopeRef(
                kind=MemoryScopeKind.GROUP,
                scope_id=request.group_id,
            )
        )
    return frozenset(scopes)
