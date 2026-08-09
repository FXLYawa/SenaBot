from __future__ import annotations

from collections.abc import Mapping

class EventError(ValueError):
    """可直接抛出的机器可读 Event 异常，不携带 Payload 或凭证。"""

    def __init__(
        self,
        code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = dict(details or {})