"""SenaBot 进程入口。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from adapter.model.openai_compatible import OpenAICompatibleProvider
from config import load_model_config
from core.application.bootstrap import (
    SenaBotConfig,
    SenaBotDependencies,
    create_senabot_app,
)
from core.model import ModelMessage, ModelProvider, ModelRequest


__all__ = ["main", "run"]


class MemoryLLMAdapter:
    """让 Memory 的字符串接口复用通用模型 Provider。"""

    def __init__(self, provider: ModelProvider) -> None:
        self._provider = provider

    async def generate(self, prompt: str) -> str:
        response = await self._provider.generate(
            ModelRequest(messages=(ModelMessage(role="user", content=prompt),))
        )
        return response.text


async def run(
    dependencies: SenaBotDependencies,
    config: SenaBotConfig | None = None,
) -> None:
    """创建应用并运行，直到当前任务被取消。"""

    app = create_senabot_app(dependencies, config)
    await app.run_forever()


def main(
    dependencies: SenaBotDependencies,
    config: SenaBotConfig | None = None,
) -> None:
    """在独立事件循环中运行 SenaBot，并正常处理终端中断"""

    try:
        asyncio.run(run(dependencies, config))
    except KeyboardInterrupt:
        pass


async def run_from_config() -> None:
    """读取项目配置，创建模型依赖，并在退出时释放客户端。"""

    project_root = Path(__file__).resolve().parent.parent
    model_config = load_model_config(project_root / "config" / "model.toml")
    provider = OpenAICompatibleProvider(
        api_key=model_config.api_key,
        base_url=model_config.base_url,
        model=model_config.model,
        timeout_seconds=model_config.timeout_seconds,
    )
    try:
        await run(
            SenaBotDependencies(
                model_provider=provider,
                memory_llm=MemoryLLMAdapter(provider),
            )
        )
    finally:
        await provider.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_from_config())
    except KeyboardInterrupt:
        pass
