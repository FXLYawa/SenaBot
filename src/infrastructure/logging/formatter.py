"""只序列化允许的标量字段；异常不包含原文、源代码行或局部变量。"""

from datetime import datetime, timezone
import json
import logging
import math
from pathlib import Path
import re

from .context import CONTEXT_FIELDS, current_context

ALLOWED_FIELDS = CONTEXT_FIELDS | frozenset({
    "action", "body_id", "platform", "message_length", "task_id", "memory_id",
    "scope", "provider", "model", "result_count", "duration_ms", "status",
    "fallback", "error_type", "effect_type", "entry_count", "summary_count",
    "after_sequence", "through_sequence", "processed_through_sequence",
    "latest_sequence", "candidate_count", "change_type", "replacement_id",
    "input_tokens", "output_tokens", "total_tokens", "adapter_type", "outcome",
    "operation", "count", "behavior_type",
})
_CREDENTIAL = re.compile(
    r"(?i)(?:authorization|cookie|api[_-]?key|access[_-]?token|password|secret)"
    r"[\s\"']*[:=][\s\"']*[^\r\n,}]+|\b(?:Bearer|Basic)\s+\S+|\bsk-[\w-]+"
)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def clean_text(value: str) -> str:
    # URL 可能携带 userinfo、路径凭据、查询参数，整段替换。
    return _CREDENTIAL.sub("[REDACTED]", _URL.sub("[URL]", value))[:512]


def scalar(value: object) -> object:
    if type(value) is str:
        return clean_text(value)
    if value is None or type(value) is bool:
        return value
    if type(value) is int:
        return value if value.bit_length() < 64 else "[oversized integer]"
    if type(value) is float and math.isfinite(value):
        return value
    return "[unsupported]"


def record_data(record: logging.LogRecord) -> dict[str, object]:
    name = record.name.removeprefix("senabot.")
    parts = name.split(".")
    module = parts[1] if len(parts) > 1 and parts[0] in ("core", "adapter") else parts[0]
    data = {
        "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": record.levelname,
        "logger": clean_text(record.name),
        "module": clean_text(module),
        "log_kind": getattr(record, "log_kind", "runtime"),
        "message": clean_text(record.getMessage()),
    }
    context = current_context()
    for key in ALLOWED_FIELDS:
        if key in record.__dict__ or key in context:
            data[key] = scalar(record.__dict__.get(key, context.get(key)))
    if record.exc_info:
        data["error_type"] = clean_text(record.exc_info[0].__name__)
        frames = []
        tb = record.exc_info[2]
        while tb is not None and len(frames) < 24:
            code = tb.tb_frame.f_code
            frames.append({"file": clean_text(Path(code.co_filename).name),
                           "line": tb.tb_lineno, "function": clean_text(code.co_name)})
            tb = tb.tb_next
        data["exception"] = {"type": data["error_type"], "frames": frames}
    # stack_info/exc_text 和未知 extra 一律不序列化。
    return data


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record_data(record), ensure_ascii=False, allow_nan=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = record_data(record)
        head = f"{data.pop('timestamp')} {data.pop('level')} {data.pop('logger')}"
        return head + " " + json.dumps(data, ensure_ascii=False, allow_nan=False)
