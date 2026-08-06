"""Body 模块运行入口：输入过滤/归一化/去重与输出 Adapter 路由。"""

from __future__ import annotations

from collections import OrderedDict

from core.body.contracts import (
    AdapterInboundMessage,
    BodyInputEventData,
    BodyOutputItemResult,
    BodyOutputRequestData,
    BodyOutputResultEventData,
    ContentType,
    SceneInfo,
    SourceInfo,
)
from core.body.ports import AdapterRegistry
from core.common.contracts import ErrorInfo, OperationStatus
from core.common.types import UserRole

# 只保留最近 N 条去重/幂等记录，避免长期运行后缓存无限增长。
_MAX_TRACKED = 1024


class BodyRuntime:
    """负责平台输入归一化、去重和输出 Adapter 选择；不含对话或权限策略。"""

    def __init__(self, owner_user_id: str, adapters: AdapterRegistry) -> None:
        self.owner_user_id = owner_user_id
        self.adapters = adapters
        self._seen_inputs: OrderedDict[tuple[str, str, str], None] = OrderedDict()
        self._output_results: OrderedDict[str, BodyOutputResultEventData] = OrderedDict()

    async def handle_adapter_input(
        self, message: AdapterInboundMessage
    ) -> BodyInputEventData | None:
        """过滤空输入并按平台消息 ID 去重，再生成标准 Body 输入。"""

        # 无文本且无非文本段（图片/语音等）时视为空输入。
        if not message.content.text_value() and not any(
            segment.type != ContentType.TEXT for segment in message.content.segments
        ):
            return None
        input_key = (message.adapter_type, message.platform, message.message_id)
        if input_key in self._seen_inputs:
            return None
        self._mark_seen(input_key)
        return self._normalize(message)

    async def handle_output_request(
        self, request: BodyOutputRequestData
    ) -> BodyOutputResultEventData:
        """按 output_id 保证发送幂等，并把 Adapter 异常映射为稳定结果。"""

        if not isinstance(request, BodyOutputRequestData):
            raise TypeError("Body expects BodyOutputRequestData")
        cached = self._output_results.get(request.output_id)
        if cached is not None:
            return cached
        try:
            items = await self._dispatch(request)
        except LookupError as exc:
            result = BodyOutputResultEventData(
                output_id=request.output_id,
                items=[],
                error=ErrorInfo("body_route_missing", str(exc)),
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
        # 角色只依据可信 Adapter 身份和配置解析，绝不从消息正文推断。
        role = self._resolve_role(message.user_id, message.scene_type.value)
        return BodyInputEventData(
            adapter_type=message.adapter_type,
            platform=message.platform,
            body_id=message.body_id,
            platform_message_id=message.message_id,
            source=SourceInfo(
                platform_user_id=message.user_id,
                display_name=message.display_name,
                principal_id=message.user_id,
                role=role,
            ),
            scene=SceneInfo(message.scene_type, message.scene_id),
            content=message.content,
            reply_to_message_id=message.reply_to_message_id,
        )

    def _resolve_role(self, user_id: str, scene_type: str) -> UserRole:
        if user_id == self.owner_user_id:
            return UserRole.OWNER
        return UserRole.GROUP_MEMBER if scene_type == "group" else UserRole.PRIVATE_USER

    async def _dispatch(self, request: BodyOutputRequestData) -> list[BodyOutputItemResult]:
        # 路由信息由 Payload 字段携带：adapter_type/platform 直接选择注册的 Adapter。
        if not request.adapter_type or not request.platform:
            raise LookupError("body_route_missing")
        adapter = self.adapters.get(request.adapter_type, request.platform)
        return await adapter.send(request)

    def _mark_seen(self, input_key: tuple[str, str, str]) -> None:
        self._seen_inputs[input_key] = None
        self._seen_inputs.move_to_end(input_key)
        if len(self._seen_inputs) > _MAX_TRACKED:
            self._seen_inputs.popitem(last=False)

    def _cache_output(self, output_id: str, result: BodyOutputResultEventData) -> None:
        self._output_results[output_id] = result
        self._output_results.move_to_end(output_id)
        if len(self._output_results) > _MAX_TRACKED:
            self._output_results.popitem(last=False)
