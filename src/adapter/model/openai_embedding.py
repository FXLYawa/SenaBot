"""基于 OpenAI-compatible Embeddings API 的 Provider。"""

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
    EmbeddingRequest,
    EmbeddingResponse,
    ModelAuthError,
    ModelError,
    ModelRateLimitError,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    ModelUsage,
)


class OpenAICompatibleEmbeddingProvider:
    """
    复用异步 client，使用模型默认维度，不自动重试。
    负责沟通模型和内部模块,实现数据类型的转换以及embedding的调用
    """

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

            # 关闭SDK自动重试
            max_retries=0,
        )

    def _build_request(self, request: EmbeddingRequest) -> dict[str, Any]:

        """"组装请求参数"""
        return {
            "model": self._model,
            "input": request.text,
            # 要求服务返回数字数组形式的向量
            "encoding_format": "float",
        }

    def _parse_response(self, response: Any) -> EmbeddingResponse:

        """解析响应结果"""
        data = getattr(response, "data", None)

        # 保证data为列表或元组,且里面恰好有一个结果
        if not isinstance(data, (list, tuple)) or len(data) != 1:
            raise ModelResponseError("expected exactly one embedding result")

        #一次只提交一条文本，所以预期 data 只有一个结果
        item = data[0]

        # 保证向量对应第0条输入
        index = getattr(item, "index", None)
        if type(index) is not int or index != 0:
            raise ModelResponseError("invalid embedding result index")
        vector = getattr(item, "embedding", None)
        if not isinstance(vector, (list, tuple)):
            raise ModelResponseError("embedding result must contain a numeric vector")

        raw_usage = getattr(response, "usage", None)
        usage = None
        if raw_usage is not None:
            usage = ModelUsage(
                input_tokens=getattr(raw_usage, "prompt_tokens", None),
                total_tokens=getattr(raw_usage, "total_tokens", None),
            )
        model = getattr(response, "model", None)
        if not isinstance(model, str) or not model.strip():
            raise ModelResponseError("embedding model must not be empty")

        return EmbeddingResponse(
            vector=tuple(vector),
            model=model,
            usage=usage,
        )

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:

        """发起具体的Embedding请求,并通过_parse_response(response)返回解析后的结果"""
        try:
            # self._build_request(request)生成请求结构
            response = await self._client.embeddings.create(
                **self._build_request(request)
            )
        except AuthenticationError as exc:
            raise ModelAuthError("embedding service authentication failed") from exc
        except RateLimitError as exc:
            raise ModelRateLimitError("embedding service rate limit exceeded") from exc
        except APITimeoutError as exc:
            raise ModelTimeoutError("embedding service request timed out") from exc
        except APIConnectionError as exc:
            raise ModelUnavailableError("embedding service is unavailable") from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise ModelUnavailableError("embedding service is unavailable") from exc
            raise ModelError(
                f"embedding service request failed with status {exc.status_code}"
            ) from exc
        except OpenAIError as exc:
            raise ModelError("embedding service request failed") from exc
        return self._parse_response(response)

    async def close(self) -> None:
        """释放本 Provider 创建的异步 client。"""
        await self._client.close()
