"""SenaBot 应用装配与运行生命周期的公开入口。"""

from application.app import SenaBotApp
from application.bootstrap import (
    AdapterFactory,
    DesktopConfig,
    SenaBotConfig,
    SenaBotDependencies,
    create_senabot_app,
)

__all__ = [
    "AdapterFactory",
    "DesktopConfig",
    "SenaBotApp",
    "SenaBotConfig",
    "SenaBotDependencies",
    "create_senabot_app",
]
