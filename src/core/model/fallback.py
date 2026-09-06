"""显式备用模型的单次降级策略。"""

from __future__ import annotations

from .contracts import (
    ModelProvider,
    ModelRateLimitError,
    ModelRequest,
    ModelResponse,
    ModelTimeoutError,
    ModelUnavailableError,
)


class FallbackModelProvider:
    """主模型暂时不可用时调用备用模型；两个客户端都由外部创建方管理。"""

    def __init__(
        self,
        primary: ModelProvider,
        fallback: ModelProvider,
    ) -> None:
        if primary is fallback:
            raise ValueError("fallback provider must differ from primary provider")
        self._primary = primary
        self._fallback = fallback

    async def generate(self, request: ModelRequest) -> ModelResponse:
        """只对超时、限流和不可用降级，备用模型接收同一请求且不再重试。"""
        try:
            return await self._primary.generate(request)
        except (ModelTimeoutError, ModelRateLimitError, ModelUnavailableError):
            return await self._fallback.generate(request)

    async def close(self) -> None:
        """不关闭借用的客户端，避免共享 Provider 被重复或提前释放。"""
        return None
