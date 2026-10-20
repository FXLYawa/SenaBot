"""从事件提取诊断标量；不新增观察事件，不读取业务正文。"""

from core.event.envelope import EventEnvelope


def _field(value: object, name: str) -> object:
    try:
        return getattr(value, name, None)
    except Exception:
        return None


def event_log_fields(envelope: EventEnvelope) -> dict[str, object]:
    fields: dict[str, object] = {
        "trace_id": envelope.trace.trace_id,
        "event_id": envelope.event_id,
        "parent_event_id": envelope.trace.parent_event_id,
        "event_type": envelope.event_type,
    }
    # 后台批次日志独立关联，不修改 EventEnvelope.trace 的既有业务语义。
    for source, target in (("log_trace_id", "trace_id"), ("parent_trace_id", "parent_trace_id")):
        value = envelope.metadata.get(source)
        if type(value) is str:
            fields[target] = value
    for key in ("session_id", "user_id", "operation_id", "memory_space_id"):
        value = _field(envelope.payload, key)
        if value is None:
            value = envelope.metadata.get(key)
        if type(value) is str:
            fields[key] = value
    session = _field(envelope.payload, "session")
    if "session_id" not in fields and session is not None:
        value = _field(session, "session_id")
        if type(value) is str:
            fields["session_id"] = value
    return fields
