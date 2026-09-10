"""Context 条目追加与后台压缩链路测试。"""

from __future__ import annotations

import asyncio
import unittest

from core.context.common import Content
from core.context.compression import (
    CompactionInput,
    CompressionItem,
    LLMCompressor,
)
from core.context.contracts import (
    ContextActorRef,
    ContextActorType,
    ContextAppendRequestData,
    ContextEntryDraft,
    ContextEntryType,
    ContextRestoreRequestData,
    ContextRestoreResultEventData,
    ContextRestoreStatus,
    ContextStateChangedEventData,
    ContextWorkReadyEventData,
    ContextWorkRequestData,
)
from core.context.events import ContextModule
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.event import EventBus, EventClient, EventFlow, ModuleEventAPI
from core.model import ModelRequest, ModelResponse


class RecordingCompressor:
    """用固定摘要替代真实模型，并保留收到的压缩输入。"""

    def __init__(self) -> None:
        self.inputs: list[CompactionInput] = []

    async def compress(self, compaction_input: CompactionInput) -> str:
        self.inputs.append(compaction_input)
        return "第一轮对话摘要"


class RecordingModelProvider:
    def __init__(self, response: ModelResponse) -> None:
        self.response = response
        self.requests: list[ModelRequest] = []

    async def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return self.response


class LLMCompressorTests(unittest.IsolatedAsyncioTestCase):
    async def test_long_item_is_bounded_before_calling_model(self) -> None:
        provider = RecordingModelProvider(ModelResponse("压缩结果", "test-model"))
        compressor = LLMCompressor(provider, entry_char_limit=50)
        long_text = "开头" + "中" * 100 + "结尾"

        result = await compressor.compress(
            CompactionInput(
                target_level=1,
                items=(CompressionItem(1, 1, "user", long_text),),
            )
        )

        self.assertEqual(result, "压缩结果")
        self.assertEqual(len(provider.requests), 1)
        user_prompt = provider.requests[0].messages[1].content
        rendered = user_prompt.split("待归纳内容：\n", 1)[1].split(
            "\n\n后置参考上下文", 1
        )[0]
        rendered_text = rendered.removeprefix("1-1 | user: ")
        self.assertLessEqual(len(rendered_text), 50)
        self.assertIn("中间内容超过摘要输入上限", rendered_text)


class ContextCompactionChainTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_over_limit_publishes_level_one_summary(self) -> None:
        bus = EventBus()
        compressor = RecordingCompressor()
        context = ContextModule(
            ContextStateStore(),
            ContextWindowPolicy(
                recent_entries=2,
                compression_trigger_entries=3,
                summary_fanout=2,
            ),
            compressor,
        )
        context.register(ModuleEventAPI(bus, "context"))

        test_api = ModuleEventAPI(bus, "test")
        work_ready = asyncio.Event()
        summary_created = asyncio.Event()
        ready_payloads: list[ContextWorkReadyEventData] = []
        state_changes: list[ContextStateChangedEventData] = []

        async def restore_not_found(flow: EventFlow) -> None:
            request: ContextRestoreRequestData = flow.payload
            flow.emit(
                "context.restore.resolved",
                ContextRestoreResultEventData(
                    session_id=request.session_id,
                    status=ContextRestoreStatus.NOT_FOUND,
                ),
            )

        async def observe_ready(flow: EventFlow) -> None:
            ready_payloads.append(flow.payload)
            work_ready.set()

        async def observe_state(flow: EventFlow) -> None:
            payload: ContextStateChangedEventData = flow.payload
            state_changes.append(payload)
            if payload.created_summary is not None:
                summary_created.set()

        test_api.subscribe(
            "context.restore.requested",
            restore_not_found,
            handler_id="test.restore_not_found",
        )
        test_api.subscribe(
            "context.work.ready",
            observe_ready,
            handler_id="test.observe_work_ready",
        )
        test_api.subscribe(
            "context.state.changed",
            observe_state,
            handler_id="test.observe_state",
        )

        await bus.start()
        try:
            client = EventClient(bus, "agent")
            await client.publish(
                "context.work.requested",
                ContextWorkRequestData("operation_1", "task_1", "task"),
            )
            await asyncio.wait_for(work_ready.wait(), timeout=1)
            session_id = ready_payloads[0].session_id

            drafts = tuple(
                ContextEntryDraft(
                    ContextEntryType.USER_MESSAGE,
                    ContextActorRef(ContextActorType.USER, "user_1"),
                    Content.from_text(f"消息 {index}"),
                )
                for index in range(1, 5)
            )
            await client.publish(
                "context.append.requested",
                ContextAppendRequestData(session_id, drafts),
            )
            await asyncio.wait_for(summary_created.wait(), timeout=1)
        finally:
            await bus.stop()

        self.assertEqual(len(compressor.inputs), 1)
        self.assertEqual(compressor.inputs[0].target_level, 1)
        self.assertEqual(
            [(item.first_sequence, item.last_sequence) for item in compressor.inputs[0].items],
            [(1, 1), (2, 2)],
        )
        summary_change = next(
            change for change in state_changes if change.created_summary is not None
        )
        self.assertEqual(summary_change.latest_sequence, 4)
        self.assertEqual(summary_change.appended_entries, ())
        self.assertEqual(summary_change.created_summary.level, 1)
        self.assertEqual(
            (
                summary_change.created_summary.first_sequence,
                summary_change.created_summary.last_sequence,
            ),
            (1, 2),
        )
        self.assertEqual(summary_change.created_summary.text, "第一轮对话摘要")


if __name__ == "__main__":
    unittest.main()
