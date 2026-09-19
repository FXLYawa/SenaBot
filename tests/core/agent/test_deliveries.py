"""Agent Effect 到公开事件的 Delivery 测试。"""

from __future__ import annotations

import unittest

from core.agent.contracts import MemoryQueryEffect, ReplyEffect
from core.agent.deliveries.memory import MemoryDelivery, MemoryQueryBinding
from core.agent.deliveries.reply import ReplyBinding, ReplyDelivery
from core.body import BodyOutputRequestData
from core.common import OutputRoute, SceneInfo, SceneType, SourceInfo
from core.context import ContextAppendRequestData, ContextEntryType
from core.memory.contracts import MemoryQueryRequest


def _source() -> SourceInfo:
    return SourceInfo(
        platform_user_id="platform_user_1",
        display_name="Alice",
        principal_id="user_1",
    )


class MemoryDeliveryTests(unittest.TestCase):
    def test_query_binding_maps_scene_and_memory_space_to_request(self) -> None:
        effect = MemoryQueryEffect(query="用户喜欢什么？")
        binding = MemoryQueryBinding(
            requester=_source(),
            session_id="session_1",
            scene=SceneInfo(
                platform="discord", scene_type=SceneType.GROUP,
                scene_id="group_1", account_namespace="sena_bot",
            ),
        )
        prepared = MemoryDelivery(memory_space_id="sena").prepare(effect, binding)

        self.assertEqual(len(prepared.events), 1)
        self.assertEqual(prepared.events[0][0], "memory.query.requested")
        request = prepared.events[0][1]
        self.assertIsInstance(request, MemoryQueryRequest)
        self.assertTrue(request.query_id.startswith("op_memory_query_"))
        self.assertEqual(prepared.pending_operation_id, request.query_id)
        self.assertEqual(request.memory_space_id, "sena")
        self.assertEqual(request.query_text, "用户喜欢什么？")
        self.assertEqual(request.user_id, "user_1")
        self.assertEqual(request.session_id, "session_1")
        self.assertEqual(request.group_id, "group_1")


class ReplyDeliveryTests(unittest.TestCase):
    def test_reply_is_written_to_context_and_sent_to_body(self) -> None:
        effect = ReplyEffect(text="你好", reply_to_message_id="message_1")
        binding = ReplyBinding(
            context_session_id="session_1",
            source_event_id="event_1",
            route=OutputRoute(
                adapter_type="desktop", platform="desktop", body_id="body_1",
            ),
            scene=SceneInfo(
                platform="desktop", scene_type=SceneType.DESKTOP,
                scene_id="desktop_1",
            ),
        )
        delivery = ReplyDelivery(character_id="sena", display_name="Sena")

        prepared = delivery.prepare(effect, binding)

        self.assertIsNone(prepared.pending_operation_id)

        self.assertEqual(
            [event_type for event_type, _ in prepared.events],
            ["context.append.requested", "body.output.requested"],
        )
        context_request = prepared.events[0][1]
        self.assertIsInstance(context_request, ContextAppendRequestData)
        self.assertEqual(context_request.session_id, "session_1")
        self.assertEqual(len(context_request.entries), 1)
        entry = context_request.entries[0]
        self.assertEqual(entry.entry_type, ContextEntryType.SENA_MESSAGE)
        self.assertEqual(entry.actor.actor_id, "sena")
        self.assertEqual(entry.source_event_id, "event_1")
        self.assertEqual(entry.content.text_value(), "你好")

        output_request = prepared.events[1][1]
        self.assertIsInstance(output_request, BodyOutputRequestData)
        self.assertTrue(output_request.output_id.startswith("output_"))
        self.assertEqual(output_request.route, binding.route)
        self.assertEqual(output_request.scene, binding.scene)
        self.assertEqual(output_request.content.text_value(), "你好")
        self.assertEqual(output_request.reply_to.platform_event_id, "message_1")
        self.assertEqual(output_request.state, "speaking")


if __name__ == "__main__":
    unittest.main()
