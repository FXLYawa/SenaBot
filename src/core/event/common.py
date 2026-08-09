from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4




def utc_now() -> datetime:
    return datetime.now(UTC)

def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"