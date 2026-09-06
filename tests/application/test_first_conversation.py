import asyncio
import tempfile
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

from core.application.bootstrap import SenaBotConfig, SenaBotDependencies, create_senabot_app
from core.body import AdapterInboundMessage, BodyOutputItemResult, OperationStatus
from core.common import Content, SceneType
from core.data import SQLiteDatabase
from core.embedding import EmbeddingResponse
from core.model import ModelResponse


class Model:
    def __init__(self):
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return ModelResponse(text="reply", model="stub")


class Embedding:
    async def embed(self, request):
        return EmbeddingResponse((1.0, 0.0), "stub")


class Adapter:
    adapter_type = platform = "test"

    def __init__(self, publish):
        self.publish = publish
        self.outputs = asyncio.Queue()

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, message):
        self.outputs.put_nowait(message)
        return [BodyOutputItemResult(0, OperationStatus.COMPLETED)]


class FirstConversationTests(IsolatedAsyncioTestCase):
    async def test_reply_and_history_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.db"
            for phase, texts in enumerate((("first", "second"), ("third",))):
                model = Model()
                adapters = []

                def factory(publish):
                    adapter = Adapter(publish)
                    adapters.append(adapter)
                    return adapter

                with SQLiteDatabase(path) as database:
                    app = create_senabot_app(
                        SenaBotDependencies(
                            model_provider=model, memory_llm=model,
                            embedding_provider=Embedding(), database=database,
                            adapter_factories=(factory,),
                        ),
                        SenaBotConfig(desktop=None, enable_context_compression=False),
                    )
                    async with app:
                        for text in texts:
                            await adapters[0].publish(AdapterInboundMessage(
                                adapter_type="test", platform="test", message_id=text,
                                user_id="local-owner", display_name="Owner",
                                scene_type=SceneType.PRIVATE, scene_id="owner",
                                content=Content.from_text(text),
                            ))
                            output = await asyncio.wait_for(adapters[0].outputs.get(), 3)
                            self.assertEqual(output.content.text_value(), "reply")
                    messages = [m.content for m in model.requests[-1].messages]
                    self.assertIn("first", messages)
                    self.assertIn("second", messages)
                    if phase:
                        self.assertIn("third", messages)
                        self.assertEqual(messages.count("reply"), 2)
                    count = database.connection.execute("SELECT count(*) FROM context_entries").fetchone()[0]
                    self.assertEqual(count, 4 if phase == 0 else 6)
