import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import (
    APIConnectionError, APIStatusError, APITimeoutError,
    AuthenticationError, OpenAIError, RateLimitError,
)

import adapter.model.openai_embedding as module
from config import load_model_config
from core.model import EmbeddingRequest, EmbeddingResponse
from core.model import (
    ModelAuthError, ModelError, ModelRateLimitError, ModelRequestError,
    ModelResponseError, ModelTimeoutError, ModelUnavailableError,
)


@pytest.fixture
def pair(monkeypatch):
    client = SimpleNamespace(
        embeddings=SimpleNamespace(create=AsyncMock()), close=AsyncMock()
    )
    monkeypatch.setattr(module, "AsyncOpenAI", lambda **kwargs: client)
    provider = module.OpenAICompatibleEmbeddingProvider(
        api_key="test-key", base_url="https://example.com/v1",
        model="embedding-test", timeout_seconds=10,
    )
    return provider, client


@pytest.mark.parametrize("text", ["", "  ", None, 1])
def test_invalid_input(text):
    with pytest.raises(ModelRequestError):
        EmbeddingRequest(text=text)


@pytest.mark.parametrize("vector", [
    (), (True,), ("1",), (float("nan"),), (float("inf"),), (10**400,),
])
def test_invalid_vector(vector):
    with pytest.raises(ModelResponseError):
        EmbeddingResponse(vector=vector, model="embedding-test")


def test_request_response_and_close(pair):
    provider, client = pair
    client.embeddings.create.return_value = SimpleNamespace(
        model="served-model",
        data=[SimpleNamespace(index=0, embedding=[1, 0.5])],
        usage=SimpleNamespace(prompt_tokens=3, total_tokens=3),
    )

    async def run():
        try:
            return await provider.embed(EmbeddingRequest(text=" hello "))
        finally:
            await provider.close()

    result = asyncio.run(run())
    client.embeddings.create.assert_awaited_once_with(
        model="embedding-test", input=" hello ", encoding_format="float",
    )
    assert result.vector == (1.0, 0.5)
    assert result.dimensions == 2
    assert result.model == "served-model"
    assert result.usage.input_tokens == 3
    assert result.usage.total_tokens == 3
    assert result.usage.output_tokens is None
    client.close.assert_awaited_once()


@pytest.mark.parametrize("data", [
    None, [],
    [SimpleNamespace(index=1, embedding=[1.0])],
    [SimpleNamespace(index=False, embedding=[1.0])],
    [SimpleNamespace(index=0, embedding="base64")],
    [SimpleNamespace(index=0, embedding=[1.0])] * 2,
])
def test_invalid_response_shape(pair, data):
    provider, _ = pair
    with pytest.raises(ModelResponseError):
        provider._parse_response(SimpleNamespace(model="test", data=data))


def test_optional_usage_and_missing_model(pair):
    provider, _ = pair
    raw = SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.5])])
    with pytest.raises(ModelResponseError):
        provider._parse_response(raw)
    raw.model = "test"
    assert provider._parse_response(raw).usage is None


def status_error(kind, status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
    return kind("failed", response=response, body=None)


@pytest.mark.parametrize("error, expected", [
    (status_error(AuthenticationError, 401), ModelAuthError),
    (status_error(RateLimitError, 429), ModelRateLimitError),
    (APITimeoutError(httpx.Request("POST", "https://example.com")), ModelTimeoutError),
    (APIConnectionError(request=httpx.Request("POST", "https://example.com")), ModelUnavailableError),
    (status_error(APIStatusError, 503), ModelUnavailableError),
    (status_error(APIStatusError, 400), ModelError),
    (OpenAIError("failed"), ModelError),
])
def test_error_mapping(pair, error, expected):
    provider, client = pair
    client.embeddings.create.side_effect = error
    with pytest.raises(expected) as caught:
        asyncio.run(provider.embed(EmbeddingRequest("hello")))
    assert type(caught.value) is expected
    assert caught.value.__cause__ is error


def test_cancellation_propagates(pair):
    provider, client = pair
    client.embeddings.create.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(provider.embed(EmbeddingRequest("hello")))


def test_embedding_config_reuses_loader(monkeypatch):
    monkeypatch.setenv("SENABOT_EMBEDDING_API_KEY", "test-key")
    path = Path(__file__).resolve().parents[2] / "config" / "embedding.toml"
    config = load_model_config(path)
    assert config.api_key == "test-key"
    assert config.provider == "openai_compatible"


def test_real_sdk_with_mock_transport(monkeypatch):
    """使用真实 SDK 序列化/解析，但不访问网络。"""
    import json
    from openai import AsyncOpenAI

    def respond(request):
        assert request.url.path == "/v1/embeddings"
        assert json.loads(request.content) == {
            "model": "test", "input": "hello", "encoding_format": "float",
        }
        return httpx.Response(200, json={
            "object": "list", "model": "test",
            "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        })

    async def run():
        http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))

        def build_client(**kwargs):
            assert kwargs["max_retries"] == 0
            assert kwargs["timeout"] == 10
            return AsyncOpenAI(**kwargs, http_client=http_client)

        monkeypatch.setattr(module, "AsyncOpenAI", build_client)
        provider = module.OpenAICompatibleEmbeddingProvider(
            "test-key", "https://example.com/v1", "test", 10,
        )
        try:
            result = await provider.embed(EmbeddingRequest("hello"))
            assert result.vector == (0.1, 0.2)
        finally:
            await provider.close()
        assert http_client.is_closed

    asyncio.run(run())
