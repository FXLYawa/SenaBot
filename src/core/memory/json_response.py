"""Memory LLM 响应的统一 JSON 解析入口。"""

from __future__ import annotations

import json
from typing import Any


def parse_json_response(response: str) -> Any:
    """解析纯 JSON，兼容模型常见的完整 Markdown JSON 代码块。"""

    text = response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].strip().casefold() not in {"```", "```json"}:
            raise ValueError("memory model response contains an invalid JSON code block")
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("memory model response JSON code block is not closed")
        text = "\n".join(lines[1:-1]).strip()

    return json.loads(text)
