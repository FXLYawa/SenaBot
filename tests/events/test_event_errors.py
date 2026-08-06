from __future__ import annotations

import unittest
from datetime import UTC, datetime

from core.event import (
    EventBus,
    EventClient,
    EventEnvelope,
    EventHandlerResult,
    EventMode,
    EventPermissionError,
    EventRegistrationError,
    EventRegistry,
    EventSpec,
    HandlerSpec,
    TraceInfo,
)


class EventRegistrationErrorTests(unittest.TestCase):
    def test_duplicate_event_raises_structured_registration_error(self) -> None:
        registry = EventRegistry()
        registry.register(EventSpec("demo.started", "demo"))

        with self.assertRaises(EventRegistrationError) as caught:
            registry.register(EventSpec("demo.started", "other"))

        self.assertEqual(caught.exception.error.code, "registration_conflict")
        self.assertEqual(
            caught.exception.error.details,
            {"event_type": "demo.started", "owner_id": "demo"},
        )

    def test_invalid_handler_pattern_raises_registration_error(self) -> None:
        registry = EventRegistry()

        async def handler(_envelope: object) -> EventHandlerResult:
            return EventHandlerResult()

        with self.assertRaises(EventRegistrationError) as caught:
            registry.subscribe(HandlerSpec("handler", "demo", "demo.*.invalid"), handler)

        self.assertEqual(caught.exception.error.code, "registration_conflict")


class EventPermissionErrorTests(unittest.TestCase):
    def test_client_rejects_unauthorized_publish_request(self) -> None:
        client = EventClient(EventBus(), "caller")

        with self.assertRaises(EventPermissionError) as caught:
            client.derived("other.started", object())

        self.assertEqual(caught.exception.error.code, "permission_denied")


class RegistrationTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_unregister_is_idempotent(self) -> None:
        registry = EventRegistry()
        token = registry.register(EventSpec("demo.started", "demo"))

        await token.unregister()
        await token.unregister()

        self.assertFalse(token.active)
        self.assertIsNone(registry.event_spec("demo.started"))


class EventDispatchErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_handler_is_returned_in_dispatch_result(self) -> None:
        bus = EventBus()
        bus.register_event(EventSpec("demo.started", "demo"))
        now = datetime.now(UTC)
        envelope = EventEnvelope(
            event_id="event_1",
            event_type="demo.started",
            occurred_at=now,
            emitted_at=now,
            source_owner_id="demo",
            target_owner_id=None,
            trace=TraceInfo("trace_1"),
            payload=object(),
        )

        result = await bus.publish(envelope)

        self.assertEqual(result.envelopes, [envelope])
        self.assertEqual([error.code for error in result.errors], ["handler_not_found"])

    async def test_handler_exception_is_isolated_and_sanitized(self) -> None:
        class SilentLogger:
            def exception(self, _message: str, *_args: object) -> None:
                return None

        bus = EventBus(logger=SilentLogger())
        bus.register_event(
            EventSpec("demo.started", "demo", mode=EventMode.BROADCAST)
        )
        calls: list[str] = []

        async def failing_handler(_envelope: EventEnvelope) -> EventHandlerResult:
            raise RuntimeError("secret-value")

        async def successful_handler(_envelope: EventEnvelope) -> EventHandlerResult:
            calls.append("successful")
            return EventHandlerResult()

        bus.subscribe(HandlerSpec("failing", "first", "demo.started"), failing_handler)
        bus.subscribe(
            HandlerSpec("successful", "second", "demo.started"), successful_handler
        )
        now = datetime.now(UTC)
        envelope = EventEnvelope(
            "event_1",
            "demo.started",
            now,
            now,
            "demo",
            None,
            TraceInfo("trace_1"),
            object(),
        )

        result = await bus.publish(envelope)

        self.assertEqual(calls, ["successful"])
        self.assertEqual([error.code for error in result.errors], ["handler_failed"])
        self.assertNotIn("secret-value", result.errors[0].message)
        self.assertEqual(result.errors[0].details["exception_type"], "RuntimeError")


if __name__ == "__main__":
    unittest.main()
