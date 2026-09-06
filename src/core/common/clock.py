"""统一使用带时区的 UTC 时间。"""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """返回当前 UTC 时间。"""
    return datetime.now(UTC)
