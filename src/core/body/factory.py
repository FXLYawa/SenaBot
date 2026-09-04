"""Body 模块的创建接口。"""

from __future__ import annotations

from core.body.events import BodyModule
from core.body.ports import AdapterRegistry
from core.body.runtime import BodyRuntime


def create_body_module(
    owner_user_id: str,
    *,
    adapters: AdapterRegistry | None = None,
) -> BodyModule:
    """创建完整的 Body 模块。"""

    resolved_adapters = adapters if adapters is not None else AdapterRegistry()
    runtime = BodyRuntime(owner_user_id, resolved_adapters)
    return BodyModule(runtime)
