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
