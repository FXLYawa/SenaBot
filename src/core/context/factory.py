"""Context 模块的装配入口。"""

from __future__ import annotations

from core.context.compression import ContextCompressor, LLMCompressor
from core.context.events import ContextModule
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.model import ModelProvider


def create_context_module(
    model_provider: ModelProvider,
    *,
    compressor: ContextCompressor | None = None,
    enable_compression: bool = True,
) -> ContextModule:
    """创建 Context 状态、窗口策略和可选压缩能力。"""

    resolved_compressor = compressor
    if resolved_compressor is None and enable_compression:
        resolved_compressor = LLMCompressor(model_provider)
    return ContextModule(
        ContextStateStore(),
        ContextWindowPolicy(),
        resolved_compressor,
    )
