"""Data Repository 共用的值序列化规则。"""

from __future__ import annotations

from datetime import UTC, datetime


def format_datetime(value: datetime | None) -> str | None:
    """把带时区时间统一成可排序的 UTC 文本。"""

    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def parse_datetime(value: str | None) -> datetime | None:
    """把 SQLite 时间文本恢复成 datetime。"""

    return None if value is None else datetime.fromisoformat(value)
