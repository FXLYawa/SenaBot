"""日志的隔离、路由、隐私、故障容忍与生命周期验收。"""

import asyncio
from contextlib import redirect_stderr
import io
import json
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from infrastructure.logging import (
    LoggingConfig, configure_logging, get_logger, load_logging_config,
    log_context, shutdown_logging,
)
from infrastructure.logging.context import current_context
from infrastructure.logging import logger as implementation
from infrastructure.logging.formatter import JsonFormatter


class LoggingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.logger = get_logger("core.memory.test")
        implementation._last_diagnostic = float("-inf")

    def tearDown(self):
        shutdown_logging()
        self.temp.cleanup()

    def configure(self, **options):
        configure_logging(LoggingConfig(directory=str(self.directory), console=False, **options))

    def read(self, filename="senabot.log"):
        return [json.loads(line) for line in (self.directory / filename).read_text(encoding="utf-8").splitlines()]

    def test_independent_levels_both_routes_and_console(self):
        stream = io.StringIO()
        with redirect_stderr(stream):
            configure_logging(LoggingConfig(directory=str(self.directory), trace=True, trace_level="DEBUG"))
            self.logger.debug("trace debug", extra={"log_kind": "trace"})
            self.logger.debug("runtime debug")
            self.logger.info("shared", extra={"log_kind": "both"})
            self.logger.info("runtime")
        self.assertEqual([r["message"] for r in self.read()], ["shared", "runtime"])
        self.assertEqual([r["message"] for r in self.read("senabot.trace.log")], ["trace debug", "shared"])
        self.assertNotIn("trace debug", stream.getvalue())
        self.assertEqual(stream.getvalue().count("shared"), 1)
        row = self.read()[0]
        self.assertEqual(row["module"], "memory")
        self.assertRegex(row["timestamp"], r"\.\d{3}Z$")

    def test_trace_disabled_and_file_disabled(self):
        self.configure()
        self.logger.info("hidden", extra={"log_kind": "trace"})
        self.assertFalse((self.directory / "senabot.trace.log").exists())
        self.assertEqual(self.read(), [])
        shutdown_logging()
        other = self.directory / "absent"
        configure_logging(LoggingConfig(console=False, file=False, trace=True, directory=str(other)))
        with redirect_stderr(io.StringIO()) as stream:
            self.logger.error("silent")
        self.assertEqual(stream.getvalue(), "")
        self.assertFalse(other.exists())

    def test_reconfigure_does_not_duplicate_or_remove_other_handlers(self):
        managed = logging.getLogger("senabot")
        foreign = logging.NullHandler()
        root_foreign = logging.NullHandler()
        managed.addHandler(foreign)
        logging.getLogger().addHandler(root_foreign)
        try:
            self.configure()
            old = list(implementation._owned)
            self.configure()
            self.logger.info("once")
            self.assertEqual(len(self.read()), 1)
            self.assertTrue(all(h not in managed.handlers for h in old))
            shutdown_logging()
            self.assertIn(foreign, managed.handlers)
            self.assertIn(root_foreign, logging.getLogger().handlers)
            self.assertTrue(all(getattr(h, "stream", None) is None for h in old))
        finally:
            managed.removeHandler(foreign)
            logging.getLogger().removeHandler(root_foreign)

    def test_privacy_and_unknown_or_oversized_fields(self):
        self.configure()
        try:
            raise ValueError("PRIVATE SDK RESPONSE sk-secret response body")
        except ValueError:
            self.logger.exception("Authorization: Bearer secret-token", extra={
                "action": "test.failed", "payload": {"content": "PRIVATE CHAT"},
                "prompt": "PRIVATE PROMPT", "api_key": "secret-key",
                "model": "https://name:password@host/private?token=secret",
                "operation_id": "x" * 10000, "scope": object(),
                "result_count": 10 ** 5000,
            })
        text = (self.directory / "senabot.log").read_text(encoding="utf-8")
        for secret in ("PRIVATE", "secret-token", "secret-key", "password", "sk-secret"):
            self.assertNotIn(secret, text)
        row = self.read()[0]
        self.assertEqual(row["exception"]["type"], "ValueError")
        self.assertTrue(row["exception"]["frames"])
        self.assertLessEqual(len(row["operation_id"]), 512)
        self.assertEqual(row["scope"], "[unsupported]")
        self.assertNotIn("payload", row)

    def test_bad_extra_and_formatter_do_not_break_caller(self):
        self.configure()
        with redirect_stderr(io.StringIO()) as stream:
            self.logger.info("invalid reserved field", extra={"module": "bad"})
            with patch.object(JsonFormatter, "format", side_effect=RuntimeError("PRIVATE")):
                self.logger.info("format error")
                self.logger.info("format error again")
        self.assertEqual(stream.getvalue().count("unavailable"), 1)
        self.assertNotIn("PRIVATE", stream.getvalue())
        self.logger.info("still works")
        self.assertEqual(self.read()[0]["message"], "still works")

    def test_unwritable_directory_falls_back_to_stderr(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError("PRIVATE PATH")):
            with redirect_stderr(io.StringIO()) as stream:
                self.configure()
                self.logger.error("runtime remains visible")
        self.assertIn("unavailable", stream.getvalue())
        self.assertIn("runtime remains visible", stream.getvalue())
        self.assertNotIn("PRIVATE", stream.getvalue())

    def test_runtime_write_failure_is_non_recursive_and_rate_limited(self):
        self.configure()
        handler = next(h for h in implementation._owned if isinstance(h, implementation._FileHandler))
        with patch.object(handler, "shouldRollover", side_effect=OSError("PRIVATE")):
            with redirect_stderr(io.StringIO()) as stream:
                for _ in range(3):
                    self.logger.info("still running")
        self.assertEqual(stream.getvalue().count("unavailable"), 1)
        self.assertNotIn("PRIVATE", stream.getvalue())

    def test_rotation_and_shutdown_flush(self):
        self.configure()
        handler = next(h for h in implementation._owned if isinstance(h, implementation._FileHandler))
        self.assertEqual((handler.maxBytes, handler.backupCount), (20 * 1024 * 1024, 5))
        handler.maxBytes, handler.backupCount = 600, 2
        for i in range(20):
            self.logger.info("x" * 200, extra={"count": i})
        shutdown_logging()
        self.assertTrue((self.directory / "senabot.log.2").exists())
        self.assertFalse((self.directory / "senabot.log.3").exists())
        self.assertEqual(self.read()[-1]["count"], 19)

    def test_config_validation_and_project_relative_path(self):
        for values in ({"console": "false"}, {"level": "TRACE"}, {"directory": ""}):
            with self.assertRaises(ValueError):
                LoggingConfig(**values)
        from infrastructure.logging.config import PROJECT_ROOT
        self.assertEqual(LoggingConfig(directory="logs").path, PROJECT_ROOT / "logs")
        config = self.directory / "logging.toml"
        config.write_text('[logging]\ntrace = true\n', encoding="utf-8")
        self.assertTrue(load_logging_config(config).trace)
        config.write_text('[logging]\nunknown = true\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            load_logging_config(config)


class ContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_interleaving_nested_exception_and_cancellation(self):
        async def work(identity):
            with log_context(trace_id=identity, session_id=identity):
                await asyncio.sleep(0)
                self.assertEqual(current_context()["trace_id"], identity)
                with self.assertRaises(ValueError):
                    with log_context(event_id="inner"):
                        raise ValueError()
                self.assertNotIn("event_id", current_context())
                with log_context(reset=True, trace_id="batch", parent_trace_id=identity):
                    self.assertNotIn("session_id", current_context())
                self.assertEqual(current_context()["trace_id"], identity)
        await asyncio.gather(work("one"), work("two"))
        self.assertEqual(current_context(), {})
        try:
            with log_context(trace_id="cancelled"):
                raise asyncio.CancelledError()
        except asyncio.CancelledError:
            pass
        self.assertEqual(current_context(), {})
