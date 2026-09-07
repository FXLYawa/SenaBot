"""共享模型技术接口；模板内容和业务解释仍由各业务模块负责。"""

from .contracts import (
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    ModelAuthError,
    ModelError,
    ModelMessage,
    ModelProvider,
    ModelRateLimitError,
    ModelRequest,
    ModelRequestError,
    ModelResponse,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    ModelUsage,
)
from .fallback import FallbackModelProvider
from .prompts import load_prompt, render_prompt
from .responses import (
    is_response_complete,
    parse_json_response,
    require_complete_response,
)

__all__ = [
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "ModelAuthError",
    "ModelError",
    "ModelMessage",
    "ModelProvider",
    "ModelRateLimitError",
    "ModelRequest",
    "ModelRequestError",
    "ModelResponse",
    "ModelResponseError",
    "ModelTimeoutError",
    "ModelUnavailableError",
    "ModelUsage",
    "FallbackModelProvider",
    "is_response_complete",
    "load_prompt",
    "parse_json_response",
    "render_prompt",
    "require_complete_response",
]
