"""SenaBot 核心模块的统一组合根。"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from adapter import BaseAdapter
from adapter.desktop import DesktopAdapter, DesktopCodec, WebSocketConnector
from core.application.app import SenaBotApp
from core.agent import PersonaConfig, create_agent_module
from core.body import (
    AdapterInboundMessage,
    BodyInputEventData,
    create_body_module,
)
from core.context import ContextCompressor, create_context_module
from core.data import InMemoryDataStore, SQLiteDatabase, create_data_components
from core.embedding import EmbeddingProvider
from core.event import EventBus, EventClient, ModuleEventAPI
from core.memory import MemoryLLMProtocol, create_memory_module
from core.model import ModelProvider


__all__ = [
    "AdapterFactory",
    "DesktopConfig",
    "SenaBotConfig",
    "SenaBotDependencies",
    "create_senabot_app",
]


AdapterFactory = Callable[
    [Callable[[AdapterInboundMessage], Awaitable[BodyInputEventData | None]]],
    BaseAdapter,
]


@dataclass(frozen=True, slots=True)
class DesktopConfig:
    """内置 Desktop Adapter 的运行参数
    之后应该要考虑提取成配置文件
    """

    host: str = "127.0.0.1"
    port: int = 8765

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("desktop host must not be blank")
        if not 1 <= self.port <= 65535:
            raise ValueError("desktop port must be between 1 and 65535")


@dataclass(frozen=True, slots=True)
class SenaBotConfig:
    """创建 SenaBot App 所需的应用级配置"""

    owner_user_id: str = "local-owner"
    owner_display_name: str = "Owner"
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    desktop: DesktopConfig | None = field(default_factory=DesktopConfig)
    enable_context_compression: bool = True

    def __post_init__(self) -> None:
        if not self.owner_user_id.strip():
            raise ValueError("owner_user_id must not be blank")
        if not self.owner_display_name.strip():
            raise ValueError("owner_display_name must not be blank")


@dataclass(slots=True)
class SenaBotDependencies:
    """组合根的显式替换点，供实际基础设施和测试实现注入"""

    model_provider: ModelProvider
    memory_llm: MemoryLLMProtocol
    embedding_provider: EmbeddingProvider
    database: SQLiteDatabase
    fallback_model_provider: ModelProvider | None = None
    event_bus: EventBus | None = None
    data_store: InMemoryDataStore | None = None
    context_compressor: ContextCompressor | None = None
    adapter_factories: tuple[AdapterFactory, ...] | None = None


def create_senabot_app(
    dependencies: SenaBotDependencies,
    config: SenaBotConfig | None = None,
) -> SenaBotApp:
    """创建并连接 SenaBot MVP 的全部核心模块。"""

    # 1. 应用级配置的加载
    app_config = config or SenaBotConfig()
    event_bus = dependencies.event_bus or EventBus()

    # 2. 装配各个模块
    data_components = create_data_components(
        dependencies.database,
        dependencies.embedding_provider,
        dependencies.data_store,
    )
    body_module = create_body_module(app_config.owner_user_id)
    context_module = create_context_module(
        dependencies.model_provider,
        compressor=dependencies.context_compressor,
        enable_compression=app_config.enable_context_compression,
    )
    memory_module = create_memory_module(
        dependencies.memory_llm,
        dependencies.embedding_provider,
        data_components.memory_repository,
        data_components.memory_spaces,
    )
    agent_module = create_agent_module(
        dependencies.model_provider,
        app_config.persona,
        fallback_model_provider=dependencies.fallback_model_provider,
    )

    # 3. 进行 event 的注册和 handler 的订阅
    event_modules = (
        ("body", body_module),
        ("context", context_module),
        ("memory", memory_module),
        ("agent", agent_module),
        ("data", data_components.module),
    )
    for owner_id, module in event_modules:
        module.register(ModuleEventAPI(event_bus, owner_id))

    # 4. Adapter 获取 Body 输入入口
    body_input_publisher = functools.partial(
        body_module.publish_input,
        EventClient(event_bus, "adapter"),
    )
    adapter_factories = dependencies.adapter_factories
    if adapter_factories is None:
        adapter_factories = _default_adapter_factories(app_config)
    adapters = tuple(factory(body_input_publisher) for factory in adapter_factories)
    for adapter in adapters:
        body_module.register_adapter(adapter)

    # 5. 创建 SenaBotApp 并返回
    return SenaBotApp(
        event_bus=event_bus,
        adapters=adapters,
        module_graph=(
            body_module,
            context_module,
            memory_module,
            agent_module,
            data_components,
        ),
    )

def _default_adapter_factories(
    config: SenaBotConfig,
) -> tuple[AdapterFactory, ...]:
    desktop = config.desktop
    if desktop is None:
        return ()

    def create_desktop(
        publish_input: Callable[
            [AdapterInboundMessage],
            Awaitable[BodyInputEventData | None],
        ],
    ) -> BaseAdapter:
        return DesktopAdapter(
            connector=WebSocketConnector(desktop.host, desktop.port),
            codec=DesktopCodec(),
            publish_input=publish_input,
            owner_user_id=config.owner_user_id,
            owner_display_name=config.owner_display_name,
        )

    return (create_desktop,)
