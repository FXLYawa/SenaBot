"""模型响应的技术检查，不包含业务结果的字段校验。"""

from __future__ import annotations

import json
from typing import Any

from .contracts import ModelResponse, ModelResponseError


def is_response_complete(response: ModelResponse) -> bool:
    """仅接受正常结束的非空文本，截断、过滤和未知结束原因均不视为完整。"""
    return (
        isinstance(response.finish_reason, str)
        and response.finish_reason.strip().lower() == "stop"
        and isinstance(response.text, str)
        and bool(response.text.strip())
    )


def require_complete_response(response: ModelResponse) -> None:
    """需要完整文本的调用方在消费前检查；失败不触发重试或模型降级。"""
    if not is_response_complete(response):
        raise ModelResponseError("model response is incomplete or empty")


def parse_json_response(response: str) -> Any:
    """解析纯 JSON 或完整的 Markdown JSON 代码块，不修复或截取模型输出。"""
    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().casefold() not in {"```", "```json"}:
            raise ModelResponseError("model response contains an invalid JSON code block")
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ModelResponseError("model response JSON code block is not closed")
        text = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ModelResponseError("model response is not valid JSON") from exc
