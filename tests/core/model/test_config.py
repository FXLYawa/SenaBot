from pathlib import Path

import pytest

from config import ConfigError, load_model_config


def test_load_model_config_resolves_api_key_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "model.toml"
    path.write_text(
        '\n'.join(
            [
                'provider = "openai_compatible"',
                'base_url = "https://llm.example/v1"',
                'model = "example-model"',
                'api_key_env = "TEST_LLM_API_KEY"',
                'timeout_seconds = 12',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_LLM_API_KEY", "secret")

    config = load_model_config(path)

    assert config.provider == "openai_compatible"
    assert config.base_url == "https://llm.example/v1"
    assert config.model == "example-model"
    assert config.api_key == "secret"
    assert config.timeout_seconds == 12.0


@pytest.mark.parametrize(
    "content",
    [
        "provider = 'unknown'",
        "provider = 'openai_compatible'",
        "provider = 1",
        "not valid toml =",
    ],
)
def test_load_model_config_normalizes_invalid_config_errors(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "model.toml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_model_config(path)


def test_load_model_config_normalizes_missing_file_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_model_config(tmp_path / "missing.toml")


def test_reranker_config_has_its_own_endpoint(tmp_path, monkeypatch):
    from config import RerankerConfig, ModelConfig, load_reranker_config
    from dataclasses import fields
    path = tmp_path / "reranker.toml"
    path.write_text('provider="rerank_compatible"\nbase_url="https://example.com/v2"\nmodel="test"\napi_key_env="TEST_RERANK_KEY"\ntimeout_seconds=10\nendpoint="rank"\n')
    monkeypatch.setenv("TEST_RERANK_KEY", "test")
    result = load_reranker_config(path)
    assert isinstance(result, RerankerConfig)
    assert result.endpoint == "rank"
    assert "endpoint" not in {field.name for field in fields(ModelConfig)}
    path.write_text(path.read_text().replace('endpoint="rank"', 'endpoint=""'))
    with pytest.raises(ConfigError):
        load_reranker_config(path)
