"""业务模块共享的文本模板加载与单次渲染工具。"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=None)
def load_prompt(package: str, name: str) -> str:
    """读取固定提示词文本；缺失资源属于发布错误，应直接抛出异常。"""

    return files(package).joinpath(name).read_text(encoding="utf-8").strip()


def render_prompt(package: str, name: str, /, **values: object) -> str:
    """按命名变量渲染一次；文件名参数不占用模板变量 name。"""

    return load_prompt(package, name).format_map(values)
