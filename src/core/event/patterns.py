from __future__ import annotations


def event_pattern_matches(pattern: str, event_type: str) -> bool:
    """判断 ``pattern`` 是否允许或匹配 ``event_type``。
    """

    if pattern == "*":
        return True
    if pattern.endswith(".*"):
        return event_type.startswith(pattern[:-1])
    return pattern == event_type
