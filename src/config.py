"""SenaBot 进程级配置读取。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from os import PathLike
from typing import Literal, overload


class ConfigError(Exception):
    """配置缺失、无效或无法读取。"""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """内部向外界请求模型调用时所需的参数,承载读取并已经校验好的模型配置"""
    # 模型提供商
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class RerankerConfig(ModelConfig):
    """重排专用配置，接口路径由配置文件提供。"""

    endpoint: str


def load_model_config(path: str | PathLike[str]) -> ModelConfig:
    return _load_config(path, "openai_compatible")


def load_reranker_config(path: str | PathLike[str]) -> RerankerConfig:
    return _load_config(path, "rerank_compatible")


@overload
def _load_config(path: str | PathLike[str], expected_provider: Literal["openai_compatible"]) -> ModelConfig: ...


@overload
def _load_config(path: str | PathLike[str], expected_provider: Literal["rerank_compatible"]) -> RerankerConfig: ...


def _load_config(path: str | PathLike[str], expected_provider: str) -> ModelConfig:
    """读取并校验模型 TOML 配置，同时解析 API Key 环境变量。"""
    try:
        # 读取TOML文件
        with open(path, "rb") as config_file:
            raw = tomllib.load(config_file)

        provider = _required_string(raw, "provider")
        if provider != expected_provider:
            raise ValueError(f"unsupported model provider: {provider}")

        base_url = _required_string(raw, "base_url")
        model = _required_string(raw, "model")
        api_key_env = _required_string(raw, "api_key_env")
        api_key = os.environ[api_key_env]
        if not api_key.strip():
            raise ValueError(f"environment variable {api_key_env} must not be empty")

        raw_timeout = raw["timeout_seconds"]
        if isinstance(raw_timeout, bool) or not isinstance(raw_timeout, (int, float)):
            raise TypeError("timeout_seconds must be a number")
        timeout_seconds = float(raw_timeout)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")

        values = dict(
            provider=provider,
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )
        if expected_provider == "rerank_compatible":
            return RerankerConfig(**values, endpoint=_required_string(raw, "endpoint"))
        return ModelConfig(**values)
    except ConfigError:
        raise
    except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"failed to load model config from {path}: {exc}") from exc


def _required_string(config: dict[str, object], field: str) -> str:
    """功能辅助函数,用来判断字段是否存在,是否为字符串,且不为空值"""
    value = config[field]
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    if not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value
