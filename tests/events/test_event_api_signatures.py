from __future__ import annotations

import unittest
from datetime import UTC, datetime

from core.event import EventBus, EventClient, EventEnvelope, EventFlow, TraceInfo


class EventClientSignatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_metadata_is_keyword_only(self) -> None:
        client = EventClient(EventBus(), "caller")

        with self.assertRaises(TypeError):
            await client.publish("demo.started", object(), {"source": "test"})


class EventFlowSignatureTests(unittest.TestCase):
    def test_flow_control_capability_must_be_explicit(self) -> None:
        now = datetime.now(UTC)
        envelope = EventEnvelope(
            "event_1",
            "demo.started",
            now,
            now,
            "caller",
            TraceInfo("trace_1"),
            object(),
        )

        with self.assertRaises(TypeError):
            EventFlow(
                envelope,
                lambda _payload: None,
                lambda _parent, _event_type, _payload, _metadata: envelope,
            )


if __name__ == "__main__":
    unittest.main()
