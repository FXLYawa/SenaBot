"""统一 Persona Prompt"""

from __future__ import annotations

from collections.abc import Sequence

from core.agent.others import PersonaConfig
from core.agent.common import render_prompt
from core.model import ModelMessage, ModelProvider, ModelResponse, ModelRequest


class PersonaResponder:
    """Agent Behavior 共用的角色回复生成入口。

    角色相关内容又这里配置, Behavior 不负责相关逻辑
    """

    def __init__(
        self,
        provider: ModelProvider,
        fallback_provider: ModelProvider,
        config: PersonaConfig,
    ) -> None:
        self._provider = provider
        self._fallback_provider = fallback_provider
        self._config = config

    @property
    def persona_id(self) -> str:
        """当前稳定角色设定的 ID。"""

        return self._config.persona_id

    @property
    def name(self) -> str:
        """当前角色的展示名称。"""

        return self._config.name

    async def generate(
        self,
        messages: Sequence[ModelMessage],
        *,
        temperature: float | None = None,
    ) -> ModelResponse:
        """根据 Persona 配置和上下文消息生成回复。"""
        
        request = ModelRequest(
            (ModelMessage("system", self._build_system_prompt()), *messages),
            temperature=temperature,
        )
        try:
            return await self._provider.generate(request)
        except Exception:
            return await self._fallback_provider.generate(request)

    def _build_system_prompt(self) -> str:
        """把 Persona 配置渲染为 Agent 唯一的角色系统提示。"""

        return render_prompt(
            "core.agent.prompts",
            "persona_system.txt",
            name=self._config.name,
            identity=self._config.identity,
            traits="、".join(self._config.traits),
            speaking_style=self._config.speaking_style,
            values="；".join(self._config.values),
            relationship_mode=self._config.relationship_mode,
        )
