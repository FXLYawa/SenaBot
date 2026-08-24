"""角色是否参与当前交互的确定性策略"""

from __future__ import annotations

from dataclasses import dataclass

from core.agent.common import SceneType
from core.context import ContextPreparedEventData


@dataclass(frozen=True, slots=True)
class InteractionDecision:
    participate: bool # 角色是否参与当前交互
    reason: str # 参与或不参与的原因，便于调试和日志记录


class InteractionPolicy:
    """只根据 Body 归一化信号决定角色是否参与当前输入。"""

    def decide(self, prepared: ContextPreparedEventData) -> InteractionDecision:
        # 如果是机器人来源的输入，则不参与
        if prepared.source.is_bot:
            return InteractionDecision(False, "bot_source")
        # 如果是私聊或桌面场景，则参与
        if prepared.scene.scene_type in {SceneType.PRIVATE, SceneType.DESKTOP}:
            return InteractionDecision(True, "direct_scene")
        # 如果是群组或频道场景，则仅在明确提及机器人时参与
        if prepared.scene.scene_type in {SceneType.GROUP, SceneType.CHANNEL}:
            if prepared.interaction.directed_to_agent:
                return InteractionDecision(True, "directed_group_message")
            return InteractionDecision(False, "ambient_group_message")
        return InteractionDecision(False, "unsupported_scene")
