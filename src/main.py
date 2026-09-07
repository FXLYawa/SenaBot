"""SenaBot 进程入口。"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path

from adapter.model import OpenAICompatibleEmbeddingProvider, OpenAICompatibleProvider
from adapter.model.reranker import MemoryReranker
from config import load_model_config, load_reranker_config
from core.application.bootstrap import (
    SenaBotConfig,
    SenaBotDependencies,
    create_senabot_app,
)
from core.data import SQLiteDatabase


__all__ = ["main", "run"]


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
    embedding_config = load_model_config(project_root / "config" / "embedding.toml")
    reranker_path = project_root / "config" / "reranker.toml"
    reranker_config = (
        load_reranker_config(reranker_path) if reranker_path.exists() else None
    )
    data_directory = project_root / "data"
    data_directory.mkdir(parents=True, exist_ok=True)
    async with AsyncExitStack() as resources:
        provider = OpenAICompatibleProvider(
            api_key=model_config.api_key,
            base_url=model_config.base_url,
            model=model_config.model,
            timeout_seconds=model_config.timeout_seconds,
        )
        resources.push_async_callback(provider.close)
        embedding_provider = OpenAICompatibleEmbeddingProvider(
            api_key=embedding_config.api_key,
            base_url=embedding_config.base_url,
            model=embedding_config.model,
            timeout_seconds=embedding_config.timeout_seconds,
        )
        resources.push_async_callback(embedding_provider.close)
        reranker = None
        if reranker_config is not None:
            reranker = MemoryReranker(
                api_key=reranker_config.api_key,
                base_url=reranker_config.base_url,
                model=reranker_config.model,
                timeout_seconds=reranker_config.timeout_seconds,
                endpoint=reranker_config.endpoint,
            )
            resources.push_async_callback(reranker.close)
        database = resources.enter_context(
            SQLiteDatabase(data_directory / "senabot.db")
        )
        await run(
            SenaBotDependencies(
                model_provider=provider,
                memory_model_provider=provider,
                embedding_provider=embedding_provider,
                database=database,
                memory_reranker=reranker,
            )
        )


if __name__ == "__main__":
    try:
        asyncio.run(run_from_config())
    except KeyboardInterrupt:
        pass
