"""配置启动入口及其模型资源生命周期。"""

import asyncio
from pathlib import Path
import runpy
import unittest
from unittest.mock import AsyncMock, patch

import main as entry
from config import ModelConfig
from core.model import ModelMessage, ModelResponse


CONFIG = ModelConfig("openai_compatible", "https://example.invalid", "test", "test", 30)


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_adapter_preserves_prompt_and_returns_text(self):
        provider = AsyncMock()
        provider.generate.return_value = ModelResponse(text="answer", model="test")
        result = await entry.MemoryLLMAdapter(provider).generate("remember this")
        self.assertEqual(result, "answer")
        request = provider.generate.call_args.args[0]
        self.assertEqual(request.messages, (ModelMessage("user", "remember this"),))

    async def test_provider_closes_on_completion_failure_and_cancellation(self):
        for error in (None, RuntimeError("startup failed"), asyncio.CancelledError()):
            with self.subTest(error=type(error).__name__):
                provider = AsyncMock()
                with patch.object(entry, "load_model_config", return_value=CONFIG) as load, patch.object(
                    entry, "OpenAICompatibleProvider", return_value=provider
                ), patch.object(entry, "run", new_callable=AsyncMock) as run:
                    run.side_effect = error
                    if error is None:
                        await entry.run_from_config()
                    else:
                        with self.assertRaises(type(error)):
                            await entry.run_from_config()
                    provider.close.assert_awaited_once()
                    self.assertIs(run.call_args.args[0].model_provider, provider)
                    load.assert_called_once_with(
                        Path(entry.__file__).resolve().parent.parent / "config" / "model.toml"
                    )


class DirectExecutionTests(unittest.TestCase):
    def test_direct_execution_runs_application_and_closes_provider(self):
        provider = AsyncMock()
        with patch("config.load_model_config", return_value=CONFIG), patch(
            "adapter.model.openai_compatible.OpenAICompatibleProvider", return_value=provider
        ), patch(
            "core.application.bootstrap.create_senabot_app"
        ) as create_app:
            create_app.return_value.run_forever = AsyncMock()
            runpy.run_path(entry.__file__, run_name="__main__")
            create_app.return_value.run_forever.assert_awaited_once()
            provider.close.assert_awaited_once()
