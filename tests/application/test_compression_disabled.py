from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock

from core.common import Content
from core.context.contracts import ContextEntryDraft, ContextActorRef, ContextActorType
from core.context.factory import create_context_module
from core.context.store import ContextStateStore
from core.context.window import ContextWindowPolicy
from core.context.compaction import CompactionFlow


class CompressionTests(IsolatedAsyncioTestCase):
    def snapshot(self, store):
        initial, _ = store.resolve_work("task", "test")
        draft = ContextEntryDraft("user_message", ContextActorRef(ContextActorType.USER, "u"), Content.from_text("message"))
        return store.append_entries(initial.session.session_id, (draft,) * 45).snapshot

    async def test_disabled_compression_keeps_all_entries_even_with_injected_compressor(self):
        compressor = Mock(compress=AsyncMock())
        module = create_context_module(Mock(), compressor=compressor, enable_compression=False)
        snapshot = self.snapshot(module._store)
        self.assertIsNone(module._compaction.schedule(snapshot))
        compressor.compress.assert_not_called()
        self.assertEqual(len(snapshot.entries), 45)

    async def test_empty_summary_does_not_consume_entries(self):
        store = ContextStateStore()
        snapshot = self.snapshot(store)
        compaction = CompactionFlow(store, ContextWindowPolicy(), Mock(compress=AsyncMock(return_value="  ")))
        request = compaction.schedule(snapshot)
        flow = Mock(payload=request)
        await compaction.handle_request(flow)
        flow.emit.assert_not_called()
        after, _ = store.resolve_work("task", "test")
        self.assertEqual(after, snapshot)
