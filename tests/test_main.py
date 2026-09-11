"""进程入口的配置装配与资源生命周期。"""

import asyncio
from pathlib import Path
import runpy
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

import main as entry
from config import ModelConfig, RerankerConfig


MODEL_CONFIG = ModelConfig(
    provider="openai_compatible",
    base_url="https://chat.example.invalid/v1",
    model="chat-model",
    api_key="chat-key",
    timeout_seconds=30,
)
EMBEDDING_CONFIG = ModelConfig(
    provider="openai_compatible",
    base_url="https://embedding.example.invalid/v1",
    model="embedding-model",
    api_key="embedding-key",
    timeout_seconds=20,
)
RERANKER_CONFIG = RerankerConfig(
    provider="rerank_compatible",
    base_url="https://reranker.example.invalid/v1",
    model="reranker-model",
    api_key="reranker-key",
    timeout_seconds=10,
    endpoint="rerank",
)


class EntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_creates_application_and_runs_it(self):
        dependencies = MagicMock()
        config = MagicMock()
        app = MagicMock()
        app.run_forever = AsyncMock()

        with patch.object(entry, "create_senabot_app", return_value=app) as create_app:
            await entry.run(dependencies, config)

        create_app.assert_called_once_with(dependencies, config)
        app.run_forever.assert_awaited_once_with()

    async def test_configured_resources_close_on_success_failure_and_cancellation(self):
        outcomes = (None, RuntimeError("startup failed"), asyncio.CancelledError())

        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                await self._assert_configured_run(outcome)

    async def test_run_from_config_without_reranker_skips_optional_resource(self):
        project_root = Path(entry.__file__).resolve().parent.parent
        provider = MagicMock(spec_set=entry.OpenAICompatibleProvider)
        embedding_provider = MagicMock(
            spec_set=entry.OpenAICompatibleEmbeddingProvider
        )
        database = MagicMock(spec_set=entry.SQLiteDatabase)
        database.__enter__.return_value = database

        with (
            patch.object(
                entry,
                "load_model_config",
                side_effect=(MODEL_CONFIG, EMBEDDING_CONFIG),
            ) as load_model,
            patch.object(entry, "load_reranker_config") as load_reranker,
            patch.object(entry.Path, "exists", return_value=False),
            patch.object(entry.Path, "mkdir"),
            patch.object(
                entry, "OpenAICompatibleProvider", return_value=provider
            ),
            patch.object(
                entry,
                "OpenAICompatibleEmbeddingProvider",
                return_value=embedding_provider,
            ),
            patch.object(entry, "MemoryReranker") as create_reranker,
            patch.object(entry, "SQLiteDatabase", return_value=database),
            patch.object(entry, "run", new_callable=AsyncMock) as run,
        ):
            await entry.run_from_config()

        self.assertEqual(
            load_model.call_args_list,
            [
                call(project_root / "config" / "model.toml"),
                call(project_root / "config" / "embedding.toml"),
            ],
        )
        load_reranker.assert_not_called()
        create_reranker.assert_not_called()
        run.assert_awaited_once()
        dependencies = run.call_args.args[0]
        self.assertIsNone(dependencies.memory_reranker)
        provider.close.assert_awaited_once_with()
        embedding_provider.close.assert_awaited_once_with()
        database.__exit__.assert_called_once()

    async def _assert_configured_run(self, outcome: BaseException | None) -> None:
        project_root = Path(entry.__file__).resolve().parent.parent
        provider = MagicMock(spec_set=entry.OpenAICompatibleProvider)
        embedding_provider = MagicMock(
            spec_set=entry.OpenAICompatibleEmbeddingProvider
        )
        reranker = MagicMock(spec_set=entry.MemoryReranker)
        database = MagicMock(spec_set=entry.SQLiteDatabase)
        database.__enter__.return_value = database

        with (
            patch.object(
                entry,
                "load_model_config",
                side_effect=(MODEL_CONFIG, EMBEDDING_CONFIG),
            ) as load_model,
            patch.object(
                entry, "load_reranker_config", return_value=RERANKER_CONFIG
            ) as load_reranker,
            patch.object(entry.Path, "exists", return_value=True),
            patch.object(entry.Path, "mkdir") as mkdir,
            patch.object(
                entry, "OpenAICompatibleProvider", return_value=provider
            ) as create_provider,
            patch.object(
                entry,
                "OpenAICompatibleEmbeddingProvider",
                return_value=embedding_provider,
            ) as create_embedding_provider,
            patch.object(
                entry, "MemoryReranker", return_value=reranker
            ) as create_reranker,
            patch.object(
                entry, "SQLiteDatabase", return_value=database
            ) as create_database,
            patch.object(entry, "run", new_callable=AsyncMock) as run,
        ):
            run.side_effect = outcome
            if outcome is None:
                await entry.run_from_config()
            else:
                with self.assertRaises(type(outcome)):
                    await entry.run_from_config()

        self.assertEqual(
            load_model.call_args_list,
            [
                call(project_root / "config" / "model.toml"),
                call(project_root / "config" / "embedding.toml"),
            ],
        )
        load_reranker.assert_called_once_with(
            project_root / "config" / "reranker.toml"
        )
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        create_provider.assert_called_once_with(
            api_key="chat-key",
            base_url="https://chat.example.invalid/v1",
            model="chat-model",
            timeout_seconds=30,
        )
        create_embedding_provider.assert_called_once_with(
            api_key="embedding-key",
            base_url="https://embedding.example.invalid/v1",
            model="embedding-model",
            timeout_seconds=20,
        )
        create_reranker.assert_called_once_with(
            api_key="reranker-key",
            base_url="https://reranker.example.invalid/v1",
            model="reranker-model",
            timeout_seconds=10,
            endpoint="rerank",
        )
        create_database.assert_called_once_with(project_root / "data" / "senabot.db")

        run.assert_awaited_once()
        dependencies = run.call_args.args[0]
        self.assertIs(dependencies.model_provider, provider)
        self.assertIs(dependencies.memory_model_provider, provider)
        self.assertIs(dependencies.embedding_provider, embedding_provider)
        self.assertIs(dependencies.memory_reranker, reranker)
        self.assertIs(dependencies.database, database)
        provider.close.assert_awaited_once_with()
        embedding_provider.close.assert_awaited_once_with()
        reranker.close.assert_awaited_once_with()
        database.__enter__.assert_called_once()
        database.__exit__.assert_called_once()


class DirectExecutionTests(unittest.TestCase):
    def test_direct_execution_calls_run_from_config_once(self):
        invoked_coroutines: list[str] = []

        def run_coroutine(coroutine):
            invoked_coroutines.append(coroutine.cr_code.co_name)
            coroutine.close()

        with patch.object(asyncio, "run", side_effect=run_coroutine) as asyncio_run:
            runpy.run_path(entry.__file__, run_name="__main__")

        asyncio_run.assert_called_once()
        self.assertEqual(invoked_coroutines, ["run_from_config"])
