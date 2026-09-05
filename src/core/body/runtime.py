"""Body 模块运行入口：输入过滤/归一化/去重与输出 Adapter 路由。"""

from __future__ import annotations

from collections import OrderedDict

from core.body.common import ErrorInfo, OperationStatus
from core.body.contracts import (
    AdapterInboundMessage,
    AdapterOutboundMessage,
    BodyInputEventData,
    BodyOutputItemResult,
    BodyOutputRequestData,
    BodyOutputResultEventData,
)
from core.body.ports import AdapterRegistry
from core.common import (
    ContentType,
    ConversationScope,
    OutputRoute,
    SceneInfo,
    SourceInfo,
    UserRole,
)

# 只保留最近 N 条去重/幂等记录，避免长期运行后缓存无限增长。
_MAX_TRACKED = 1024


class AdapterNotFoundError(LookupError):
    """会话路由有效，但对应的 Adapter 未注册。"""


class BodyRuntime:
    """负责平台输入归一化、去重与输出 Adapter 路由；不持有 Session。"""

    def __init__(self, owner_user_id: str, adapters: AdapterRegistry) -> None:
        """保存属主配置，并初始化输入去重、会话路由与输出结果缓存。"""
        self.owner_user_id = owner_user_id
        self.adapters = adapters
        # 输入去重键：(adapter_type, platform, message_id) → None；只保留最近 _MAX_TRACKED 条。
        self._seen_input_keys: OrderedDict[tuple[str, str, str], None] = OrderedDict()
        # 输出结果缓存：output_id → 最近一次发送结果，用于幂等返回；只保留最近 _MAX_TRACKED 条。
        self._output_result_cache: OrderedDict[str, BodyOutputResultEventData] = OrderedDict()

    async def handle_adapter_input(
        self, message: AdapterInboundMessage
    ) -> BodyInputEventData | None:
        """过滤空输入并按平台消息 ID 去重，再绑定会话并生成标准 Body 输入。"""

        # 无文本且无非文本段（图片/语音等）时视为空输入。
        if not message.content.text_value() and not any(
            segment.type != ContentType.TEXT for segment in message.content.segments
        ):
            return None
        input_key = (message.adapter_type, message.platform, message.message_id)
        if input_key in self._seen_input_keys:
            return None
        self._mark_seen(input_key)
        return self._normalize(message)

    async def handle_output_request(
        self, request: BodyOutputRequestData
    ) -> BodyOutputResultEventData:
        """按 output_id 保证发送幂等，并把 Adapter 异常映射为稳定结果。"""

        if not isinstance(request, BodyOutputRequestData):
            raise TypeError("Body expects BodyOutputRequestData")
        cached = self._output_result_cache.get(request.output_id)
        if cached is not None:
            return cached
        try:
            items = await self._dispatch(request)
        except AdapterNotFoundError as exc:
            result = BodyOutputResultEventData(
                output_id=request.output_id,
                items=[],
                error=ErrorInfo("adapter_not_found", str(exc)),
            )
            self._cache_output(request.output_id, result)
            return result
        except Exception as exc:
            # Adapter 边界：发送异常必须转成稳定的失败结果事件，不能穿透到 EventBus。
            result = BodyOutputResultEventData(
                output_id=request.output_id,
                items=[],
                error=ErrorInfo("adapter_send_failed", str(exc)),
            )
            self._cache_output(request.output_id, result)
            return result
        successes = sum(item.status == OperationStatus.COMPLETED for item in items)
        result = BodyOutputResultEventData(
            output_id=request.output_id,
            items=items,
            error=None
            if successes
            else ErrorInfo("adapter_send_failed", "The adapter did not send any item."),
        )
        self._cache_output(request.output_id, result)
        return result

    def _normalize(self, message: AdapterInboundMessage) -> BodyInputEventData:
        """把 Adapter 入站消息转换为不含 Session 的标准 Body 输入。"""
        # 角色只依据可信 Adapter 身份和配置解析，绝不从消息正文推断。
        role = self._resolve_role(message.user_id, message.scene_type.value)
        scene = SceneInfo(message.scene_type, message.scene_id)
        return BodyInputEventData(
            conversation_scope=ConversationScope(
                message.platform,
                message.scene_type,
                message.scene_id,
            ),
            source=SourceInfo(
                platform_user_id=message.user_id,
                display_name=message.display_name,
                principal_id=message.user_id,
                role=role,
            ),
            scene=scene,
            content=message.content,
            output_route=OutputRoute(
                message.adapter_type,
                message.platform,
                message.scene_id,
            ),
            reply_target_id=message.message_id,
        )

    def _resolve_role(self, user_id: str, scene_type: str) -> UserRole:
        """按属主身份与场景类型解析用户角色。"""
        if user_id == self.owner_user_id:
            return UserRole.OWNER
        return UserRole.GROUP_MEMBER if scene_type == "group" else UserRole.PRIVATE_USER

    async def _dispatch(self, request: BodyOutputRequestData) -> list[BodyOutputItemResult]:
        """按请求携带的显式路由选择 Adapter，返回逐项发送结果。"""
        try:
            adapter = self.adapters.get(request.route.adapter_type, request.route.platform)
        except LookupError as exc:
            raise AdapterNotFoundError(str(exc)) from exc
        return await adapter.send(
            AdapterOutboundMessage(
                adapter_type=request.route.adapter_type,
                platform=request.route.platform,
                scene=request.scene,
                content=request.content,
                reply_to_message_id=request.reply_to_message_id,
                metadata=dict(request.metadata),
            )
        )

    def _mark_seen(self, input_key: tuple[str, str, str]) -> None:
        """记录输入去重键，并清理超过上限的最旧记录。"""
        self._seen_input_keys[input_key] = None
        self._seen_input_keys.move_to_end(input_key)
        if len(self._seen_input_keys) > _MAX_TRACKED:
            self._seen_input_keys.popitem(last=False)

    def _cache_output(self, output_id: str, result: BodyOutputResultEventData) -> None:
        """缓存输出结果以实现幂等，并清理超过上限的最旧记录。"""
        self._output_result_cache[output_id] = result
        self._output_result_cache.move_to_end(output_id)
        if len(self._output_result_cache) > _MAX_TRACKED:
            self._output_result_cache.popitem(last=False)
