"""任务局部标量上下文；reset=True 用于消费边界或独立后台工作。"""

from contextlib import contextmanager
from contextvars import ContextVar
from collections.abc import Iterator

_context: ContextVar[dict[str, object]] = ContextVar("senabot_log_context", default={})
CONTEXT_FIELDS = frozenset({
    "trace_id", "event_id", "session_id", "user_id", "operation_id",
    "parent_trace_id", "parent_event_id", "handler_id", "owner_id", "event_type",
    "memory_space_id", "run_id", "attempt",
})


def current_context() -> dict[str, object]:
    return dict(_context.get())


@contextmanager
def log_context(*, reset: bool = False, **fields: object) -> Iterator[None]:
    context = {} if reset else current_context()
    context.update({key: value for key, value in fields.items()
                    if key in CONTEXT_FIELDS and type(value) in (str, int, bool, type(None))})
    token = _context.set(context)
    try:
        yield
    finally:
        _context.reset(token)
