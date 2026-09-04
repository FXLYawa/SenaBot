"""SenaBot 进程入口。"""

from __future__ import annotations

import asyncio

from core.application.bootstrap import (
    SenaBotConfig,
    SenaBotDependencies,
    create_senabot_app,
)


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
