"""带业务前缀的随机标识。"""

from uuid import uuid4


def new_id(prefix: str) -> str:
    """生成带前缀的随机标识，适合用于业务对象的唯一标识."""
    return f"{prefix}_{uuid4().hex}"
