from __future__ import annotations

import unittest
from datetime import UTC, datetime

from core.event import (
    EventBus, EventEnvelope, EventError, EventFlow, EventRegistry,
    EventSpec, HandlerSpec, TraceInfo,
)


def _envelope(event_type: str = "demo.started", payload: object = "input") -> EventEnvelope:
    now = datetime.now(UTC)
    return EventEnvelope(
        event_id="event_1", event_type=event_type,
        occurred_at=now, emitted_at=now, source_owner_id="demo",
        trace=TraceInfo("trace_1"), payload=payload,
    )


class EventErrorTests(unittest.TestCase):
    def test_error_preserves_fields_and_copies_details(self) -> None:
        details = {"owner_id": "demo"}
        error = EventError("registration_conflict", "Duplicate event", details)

        self.assertIsInstance(error, ValueError)
        self.assertEqual(error.code, "registration_conflict")
        self.assertEqual(error.message, "Duplicate event")
        self.assertEqual(error.details, details)
        self.assertEqual(str(error), "registration_conflict: Duplicate event")
        details["owner_id"] = "other"
        self.assertEqual(error.details, {"owner_id": "demo"})

    def test_error_details_default_to_empty_mapping(self) -> None:
        self.assertEqual(EventError("payload_invalid", "Invalid payload").details, {})


class EventRegistrationTests(unittest.TestCase):
    def test_duplicate_event_raises_event_error(self) -> None:
        registry = EventRegistry()
        spec = EventSpec("demo.started", "demo")
        registry.register(spec)

        with self.assertRaises(EventError) as caught:
            registry.register(EventSpec("demo.started", "other"))

        self.assertEqual(caught.exception.code, "registration_conflict")
        self.assertEqual(caught.exception.details, {"owner_id": "demo"})
        self.assertEqual(registry.event_spec("demo.started"), spec)

    def test_invalid_handler_pattern_raises_event_error(self) -> None:
        registry = EventRegistry()

        async def handler(_flow: EventFlow) -> None:
            pass

        with self.assertRaises(EventError) as caught:
            registry.subscribe(HandlerSpec("handler", "demo", "demo.*.invalid"), handler)

        self.assertEqual(caught.exception.code, "registration_conflict")
        self.assertEqual(caught.exception.details, {"event_pattern": "demo.*.invalid"})
        self.assertEqual(registry.matching_handlers("demo.started"), [])


class RegistrationTokenTests(unittest.IsolatedAsyncioTestCase):
    async def test_unregister_is_idempotent(self) -> None:
        registry = EventRegistry()
        token = registry.register(EventSpec("demo.started", "demo"))

        await token.unregister()
        await token.unregister()

        self.assertIsNone(registry.event_spec("demo.started"))
        replacement = EventSpec("demo.started", "other")
        registry.register(replacement)
        await token.unregister()
        self.assertEqual(registry.event_spec("demo.started"), replacement)


class EventDispatchErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_unhandled_event_is_drained_without_error(self) -> None:
        bus = EventBus()
        bus.register(EventSpec("demo.started", "demo"))

        with self.assertNoLogs("senabot.event", level="WARNING"):
            await bus.start()
            try:
                self.assertIsNone(await bus.publish(_envelope()))
            finally:
                # Current Bus has no wait_idle(); stop drains queued work.
                await bus.stop()

    async def test_publish_rejects_stopped_bus(self) -> None:
        bus = EventBus()
        bus.register(EventSpec("demo.started", "demo"))

        with self.assertRaises(EventError) as caught:
            await bus.publish(_envelope())
        self.assertEqual(caught.exception.code, "event_bus_unavailable")
        self.assertEqual(caught.exception.details, {"state": "stopped"})

        await bus.start()
        await bus.stop()
        with self.assertRaises(EventError) as caught:
            await bus.publish(_envelope())
        self.assertEqual(caught.exception.code, "event_bus_unavailable")
        self.assertEqual(caught.exception.details, {"state": "stopped"})

    async def test_publish_rejects_unregistered_event_and_invalid_payload(self) -> None:
        bus = EventBus()
        bus.register(EventSpec("demo.started", "demo", payload_type=str))
        await bus.start()
        try:
            with self.assertRaises(EventError) as caught:
                await bus.publish(_envelope("other.started"))
            self.assertEqual(caught.exception.code, "event_not_registered")

            with self.assertRaises(EventError) as caught:
                await bus.publish(_envelope(payload=42))
            self.assertEqual(caught.exception.code, "payload_invalid")
            self.assertEqual(caught.exception.details, {"expected": "str", "actual": "int"})
        finally:
            await bus.stop()

    async def test_handler_exception_is_logged_and_isolated(self) -> None:
        # Cover concurrent handlers and a controlling handler that fails before
        # the next handler is scheduled. Failed staged events must be discarded.
        for controls_flow in (False, True):
            with self.subTest(controls_flow=controls_flow):
                bus = EventBus(dispatch_concurrency=1)
                bus.register(EventSpec("demo.started", "demo"))
                bus.register(EventSpec("demo.child", "demo"))
                calls: list[tuple[str, object]] = []
                children: list[object] = []

                async def failing_handler(flow: EventFlow) -> None:
                    calls.append(("failing", flow.payload))
                    flow.emit("demo.child", "must be discarded")
                    if controls_flow:
                        flow.replace_payload("must not reach next handler")
                        flow.stop_propagation()
                    raise RuntimeError("handler failure")

                async def successful_handler(flow: EventFlow) -> None:
                    calls.append(("successful", flow.payload))

                async def child_handler(flow: EventFlow) -> None:
                    children.append(flow.payload)

                bus.subscribe(
                    HandlerSpec("failing", "first", "demo.started", controls_flow=controls_flow),
                    failing_handler,
                )
                bus.subscribe(HandlerSpec("successful", "second", "demo.started"), successful_handler)
                bus.subscribe(HandlerSpec("child", "demo", "demo.child"), child_handler)

                with self.assertLogs("senabot.event", level="ERROR") as logs:
                    await bus.start()
                    try:
                        self.assertIsNone(await bus.publish(_envelope(payload="first input")))
                        self.assertIsNone(await bus.publish(_envelope(payload="second input")))
                    finally:
                        await bus.stop()

                self.assertCountEqual(calls, [
                    ("failing", "first input"), ("successful", "first input"),
                    ("failing", "second input"), ("successful", "second input"),
                ])
                self.assertEqual(children, [])
                self.assertEqual(len(logs.records), 2)
                for record in logs.records:
                    self.assertIn("Error in event handler failing", record.getMessage())
                    self.assertIn("owner=first, attempt=1/1", record.getMessage())
                    self.assertIsNotNone(record.exc_info)
                    self.assertIs(record.exc_info[0], RuntimeError)
                    self.assertEqual(str(record.exc_info[1]), "handler failure")


if __name__ == "__main__":
    unittest.main()
