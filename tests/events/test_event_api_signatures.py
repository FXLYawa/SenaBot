from __future__ import annotations

import unittest
from inspect import signature
from datetime import UTC, datetime

from core.event import EventBus, EventClient, EventEnvelope, EventFlow, TraceInfo


class EventClientSignatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_metadata_is_keyword_only(self) -> None:
        client = EventClient(EventBus(), "caller")

        with self.assertRaises(TypeError):
            await client.publish("demo.started", object(), {"source": "test"})


class EventFlowSignatureTests(unittest.TestCase):
    def _envelope(self) -> EventEnvelope:
        now = datetime.now(UTC)
        return EventEnvelope(
            "event_1",
            "demo.started",
            now,
            now,
            "caller",
            TraceInfo("trace_1"),
            object(),
        )

    def test_default_flow_denies_control_operations_without_changing_state(self) -> None:
        envelope = self._envelope()
        validated: list[object] = []
        flow = EventFlow(
            envelope,
            validated.append,
            lambda _parent, _event_type, _payload, _metadata: envelope,
        )

        self.assertIs(signature(EventFlow).parameters["controls_flow"].default, False)
        with self.assertRaisesRegex(RuntimeError, "controls_flow=True"):
            flow.replace_payload("replacement")
        with self.assertRaisesRegex(RuntimeError, "controls_flow=True"):
            flow.stop_propagation()

        self.assertIs(flow.payload, envelope.payload)
        self.assertEqual(validated, [])
        committed, stopped, derived = flow._commit()
        self.assertIs(committed, envelope)
        self.assertFalse(stopped)
        self.assertEqual(derived, ())

    def test_explicit_flow_control_replaces_payload_and_stops_propagation(self) -> None:
        envelope = self._envelope()
        validated: list[object] = []
        flow = EventFlow(
            envelope,
            validated.append,
            lambda _parent, _event_type, _payload, _metadata: envelope,
            controls_flow=True,
        )

        flow.replace_payload("replacement")
        flow.stop_propagation()

        self.assertEqual(validated, ["replacement"])
        self.assertEqual(flow.payload, "replacement")
        self.assertIsNot(flow.envelope, envelope)
        committed, stopped, derived = flow._commit()
        self.assertEqual(committed, envelope.with_payload("replacement"))
        self.assertTrue(stopped)
        self.assertEqual(derived, ())


if __name__ == "__main__":
    unittest.main()
