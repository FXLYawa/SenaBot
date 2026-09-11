"""Agent Effect 到公开事件的 Delivery 测试。"""

from __future__ import annotations

import unittest

from core.agent.contracts import MemoryQueryEffect, ReplyEffect
from core.agent.deliveries.memory import MemoryDelivery
from core.agent.deliveries.reply import ReplyDelivery
from core.body import BodyOutputRequestData
from core.common import OutputRoute, SceneInfo, SceneType, SourceInfo
from core.context import ContextAppendRequestData, ContextEntryType
from core.memory.contracts import MemoryQueryRequest


class RecordingFlow:
    def __init__(self) -> None:
        self.emitted: list[tuple[str, object]] = []

    def emit(self, event_type: str, payload: object) -> None:
        self.emitted.append((event_type, payload))


def _source() -> SourceInfo:
    return SourceInfo(
        platform_user_id="platform_user_1",
        display_name="Alice",
        principal_id="user_1",
    )


class MemoryDeliveryTests(unittest.TestCase):
    def test_query_effect_maps_scene_and_persona_to_memory_scope(self) -> None:
        effect = MemoryQueryEffect(
            operation_id="query_1",
            query="用户喜欢什么？",
            requester=_source(),
            session_id="session_1",
            scene=SceneInfo(
                platform="discord", scene_type=SceneType.GROUP,
                scene_id="group_1", account_namespace="sena_bot",
            ),
            persona_id="sena",
        )
        flow = RecordingFlow()

        operation_id = MemoryDelivery.pending_operation_id(effect)
        MemoryDelivery.emit(flow, effect)

        self.assertEqual(operation_id, "query_1")
        self.assertEqual(len(flow.emitted), 1)
        self.assertEqual(flow.emitted[0][0], "memory.query.requested")
        request = flow.emitted[0][1]
        self.assertIsInstance(request, MemoryQueryRequest)
        self.assertEqual(request.query_id, "query_1")
        self.assertEqual(request.memory_space_id, "sena")
        self.assertEqual(request.query_text, "用户喜欢什么？")
        self.assertEqual(request.user_id, "user_1")
        self.assertEqual(request.session_id, "session_1")
        self.assertEqual(request.group_id, "group_1")


class ReplyDeliveryTests(unittest.TestCase):
    def test_reply_is_written_to_context_and_sent_to_body(self) -> None:
        effect = ReplyEffect(
            text="你好",
            session_id="session_1",
            trigger_event_id="event_1",
            output_route=OutputRoute(
                adapter_type="desktop", platform="desktop", body_id="body_1",
            ),
            scene=SceneInfo(
                platform="desktop", scene_type=SceneType.DESKTOP,
                scene_id="desktop_1",
            ),
            reply_to_message_id="message_1",
        )
        flow = RecordingFlow()
        delivery = ReplyDelivery(character_id="sena", display_name="Sena")

        operation_id = delivery.pending_operation_id(effect)
        delivery.emit(flow, effect)

        self.assertIsNone(operation_id)

        self.assertEqual(
            [event_type for event_type, _ in flow.emitted],
            ["context.append.requested", "body.output.requested"],
        )
        context_request = flow.emitted[0][1]
        self.assertIsInstance(context_request, ContextAppendRequestData)
        self.assertEqual(context_request.session_id, "session_1")
        self.assertEqual(len(context_request.entries), 1)
        entry = context_request.entries[0]
        self.assertEqual(entry.entry_type, ContextEntryType.SENA_MESSAGE)
        self.assertEqual(entry.actor.actor_id, "sena")
        self.assertEqual(entry.source_event_id, "event_1")
        self.assertEqual(entry.content.text_value(), "你好")

        output_request = flow.emitted[1][1]
        self.assertIsInstance(output_request, BodyOutputRequestData)
        self.assertTrue(output_request.output_id.startswith("output_"))
        self.assertEqual(output_request.route, effect.output_route)
        self.assertEqual(output_request.scene, effect.scene)
        self.assertEqual(output_request.content.text_value(), "你好")
        self.assertEqual(output_request.reply_to.platform_event_id, "message_1")
        self.assertEqual(output_request.state, "speaking")


if __name__ == "__main__":
    unittest.main()
