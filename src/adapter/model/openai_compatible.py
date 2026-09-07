"""基于 OpenAI Chat Completions 协议的模型 Provider。"""

from __future__ import annotations

from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

from core.model import (
    ModelAuthError,
    ModelError,
    ModelRateLimitError,
    ModelRequest,
    ModelResponse,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    ModelUsage,
)


class OpenAICompatibleProvider:
    """将公共模型协议映射到 OpenAI 兼容的 Chat Completions API。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_seconds,
            # 重试与备用模型切换由显式调用策略决定。
            max_retries=0,
        )

    def _build_request(self, request: ModelRequest) -> dict[str, Any]:

        """把SenaBot的统一请求,转换为OpenAI-compatible SDK 需要的参数字典"""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in request.messages
            ],
        }
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_completion_tokens"] = request.max_output_tokens
        return payload

    def _parse_response(self, response: Any) -> ModelResponse:

        """把 OpenAI SDK 的返回对象转成 SenaBot 的 ModelResponse"""

        # OpenAI-compatible SDK会返回多个choice,从对象中拿到choices
        choices = getattr(response, "choices", None)
        if not choices:
            raise ModelResponseError("model response contains no choices")

        #只使用第一个候选
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise ModelResponseError("model response content must not be empty")

        model = getattr(response, "model", None)
        if not isinstance(model, str) or not model.strip():
            raise ModelResponseError("model response does not contain a model")

        raw_usage = getattr(response, "usage", None)
        usage = None
        if raw_usage is not None:
            usage = ModelUsage(
                input_tokens=getattr(raw_usage, "prompt_tokens", None),
                output_tokens=getattr(raw_usage, "completion_tokens", None),
                total_tokens=getattr(raw_usage, "total_tokens", None),
            )

        return ModelResponse(
            text=content,
            model=model,
            finish_reason=getattr(first_choice, "finish_reason", None) or "unknown",
            usage=usage,
        )

    async def generate(self, request: ModelRequest) -> ModelResponse:

        """发起模型调用"""
        try:
            # 先调用self._build_request(request)把内部结构转换为SDK参数,然后 self._client.chat.completions.create(...)真正发起请求
            response = await self._client.chat.completions.create(
                **self._build_request(request)
            )
        except AuthenticationError as exc:
            raise ModelAuthError("model service authentication failed") from exc
        except RateLimitError as exc:
            raise ModelRateLimitError("model service rate limit exceeded") from exc
        except APITimeoutError as exc:
            raise ModelTimeoutError("model service request timed out") from exc
        except APIConnectionError as exc:
            raise ModelUnavailableError("model service is unavailable") from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelUnavailableError("model service is unavailable") from exc
            raise ModelError(
                f"model service request failed with status {exc.status_code}"
            ) from exc
        except OpenAIError as exc:
            raise ModelError("model service request failed") from exc

        # 返回经_parse_response转换后的结果
        return self._parse_response(response)

    async def close(self) -> None:
        """关闭客户端"""
        await self._client.close()
