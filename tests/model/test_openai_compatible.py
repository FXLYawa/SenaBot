import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OpenAIError,
    RateLimitError,
)

import adapter.model.openai_compatible as provider_module
from adapter.model import OpenAICompatibleProvider
from core.model import (
    ModelAuthError,
    ModelError,
    ModelMessage,
    ModelRateLimitError,
    ModelRequest,
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    ModelUsage,
)


@pytest.fixture
def client() -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock()),
        ),
        close=AsyncMock(),
    )


@pytest.fixture
def provider(
    monkeypatch: pytest.MonkeyPatch, client: SimpleNamespace
) -> OpenAICompatibleProvider:
    monkeypatch.setattr(provider_module, "AsyncOpenAI", lambda **_: client)
    return OpenAICompatibleProvider(
        api_key="secret",
        base_url="https://llm.example/v1",
        model="example-model",
        timeout_seconds=10,
    )


def test_build_request_maps_optional_parameters(
    provider: OpenAICompatibleProvider,
) -> None:
    request = ModelRequest(
        messages=(
            ModelMessage("system", "instructions"),
            ModelMessage("user", "hello"),
        ),
        temperature=0.4,
        max_output_tokens=256,
    )

    assert provider._build_request(request) == {
        "model": "example-model",
        "messages": [
            {"role": "system", "content": "instructions"},
            {"role": "user", "content": "hello"},
        ],
        "temperature": 0.4,
        "max_completion_tokens": 256,
    }


def test_build_request_omits_unset_optional_parameters(
    provider: OpenAICompatibleProvider,
) -> None:
    payload = provider._build_request(
        ModelRequest(messages=(ModelMessage("user", "hello"),))
    )

    assert "temperature" not in payload
    assert "max_completion_tokens" not in payload
    assert "max_tokens" not in payload


def test_parse_response_maps_first_choice_and_usage(
    provider: OpenAICompatibleProvider,
) -> None:
    raw_response = SimpleNamespace(
        model="served-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer"),
                finish_reason="length",
            ),
            SimpleNamespace(
                message=SimpleNamespace(content="ignored"),
                finish_reason="stop",
            ),
        ],
        usage=SimpleNamespace(
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
        ),
    )

    response = provider._parse_response(raw_response)

    assert response.text == "answer"
    assert response.model == "served-model"
    assert response.finish_reason == "length"
    assert response.usage == ModelUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
    )


def test_parse_response_preserves_unknown_finish_reason_and_allows_missing_usage(
    provider: OpenAICompatibleProvider,
) -> None:
    raw_response = SimpleNamespace(
        model="served-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer"),
                finish_reason=None,
            )
        ],
        usage=None,
    )

    response = provider._parse_response(raw_response)

    assert response.finish_reason == "unknown"
    assert response.usage is None


@pytest.mark.parametrize(
    "raw_response",
    [
        SimpleNamespace(model="served-model", choices=[], usage=None),
        SimpleNamespace(
            model="served-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="  "), finish_reason="stop"
                )
            ],
            usage=None,
        ),
        SimpleNamespace(
            model=None,
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="answer"), finish_reason="stop"
                )
            ],
            usage=None,
        ),
    ],
)
def test_parse_response_rejects_invalid_responses(
    provider: OpenAICompatibleProvider, raw_response: SimpleNamespace
) -> None:
    with pytest.raises(ModelResponseError):
        provider._parse_response(raw_response)


def _status_error(error_type: type[APIStatusError], status: int) -> APIStatusError:
    request = httpx.Request("POST", "https://llm.example/v1/chat/completions")
    response = httpx.Response(status, request=request)
    return error_type("failed", response=response, body=None)


@pytest.mark.parametrize(
    ("sdk_error", "expected_error"),
    [
        (_status_error(AuthenticationError, 401), ModelAuthError),
        (_status_error(RateLimitError, 429), ModelRateLimitError),
        (
            APITimeoutError(httpx.Request("POST", "https://llm.example")),
            ModelTimeoutError,
        ),
        (
            APIConnectionError(
                request=httpx.Request("POST", "https://llm.example")
            ),
            ModelUnavailableError,
        ),
        (_status_error(APIStatusError, 503), ModelUnavailableError),
        (_status_error(APIStatusError, 400), ModelError),
        (OpenAIError("failed"), ModelError),
    ],
)
def test_generate_maps_sdk_errors(
    provider: OpenAICompatibleProvider,
    client: SimpleNamespace,
    sdk_error: OpenAIError,
    expected_error: type[ModelError],
) -> None:
    client.chat.completions.create.side_effect = sdk_error
    request = ModelRequest(messages=(ModelMessage("user", "hello"),))

    with pytest.raises(expected_error) as caught:
        asyncio.run(provider.generate(request))

    assert type(caught.value) is expected_error


def test_generate_calls_sdk_and_parses_response(
    provider: OpenAICompatibleProvider, client: SimpleNamespace
) -> None:
    client.chat.completions.create.return_value = SimpleNamespace(
        model="served-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="answer"), finish_reason="stop"
            )
        ],
        usage=None,
    )
    request = ModelRequest(messages=(ModelMessage("user", "hello"),))

    response = asyncio.run(provider.generate(request))

    assert response.text == "answer"
    client.chat.completions.create.assert_awaited_once_with(
        model="example-model",
        messages=[{"role": "user", "content": "hello"}],
    )


def test_close_releases_sdk_client(
    provider: OpenAICompatibleProvider, client: SimpleNamespace
) -> None:
    asyncio.run(provider.close())

    client.close.assert_awaited_once_with()
