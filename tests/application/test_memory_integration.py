"""Memory success paths across the real application graph and SQLite."""

import asyncio
import json
import re
from datetime import UTC, datetime

import pytest

from core.application.bootstrap import SenaBotConfig, SenaBotDependencies, create_senabot_app
from core.body import AdapterInboundMessage, BodyOutputItemResult, OperationStatus
from core.common import Content, OutputRoute, SceneInfo, SceneType
from core.context.identity import conversation_session_id
from core.data import SQLiteDatabase, SQLiteMemoryRepository, SQLiteMemorySpaceRouter
from core.event import EventBus, ModuleEventAPI
from core.memory.extraction_flow import MemoryExtractionPolicy
from core.memory.models import (
    Fact, MemoryIndexEmbedding, MemoryItem, MemoryRecallContext, MemoryScopeKind,
    MemoryScopeRef, MemoryWriteEnvelope, Provenance,
)
from core.model import EmbeddingRequest, EmbeddingResponse, ModelRequest, ModelResponse


MEMORY_TEXT = "Owner prefers jasmine tea."
REPLY = "I remember your preference."
USER_SCOPE = MemoryScopeRef(MemoryScopeKind.USER, "local-owner")


class Model:
    def __init__(self, extraction=False):
        self.requests = []
        self.extraction = extraction

    async def generate(self, request: ModelRequest) -> ModelResponse:
        assert isinstance(request, ModelRequest)
        self.requests.append(request)
        text = REPLY
        if self.extraction:
            if len(self.requests) == 1:
                # Select the source ID from the actual extraction prompt, never
                # from a fabricated ContextReadView or a patched internal object.
                sources = re.findall(r"^\[([^\]]+)\] user\b", request.messages[0].content, re.M)
                assert len(sources) == 1
                text = json.dumps({"memories": [{
                    "content": MEMORY_TEXT, "source_message_ids": sources,
                }]})
            elif len(self.requests) == 2:
                text = json.dumps({"domain": "fact", "payload": {"content": MEMORY_TEXT}})
            elif len(self.requests) == 3:
                text = '{"operations": [{"type": "add"}]}'
            else:
                raise AssertionError("Unexpected extra extraction/model call")
        return ModelResponse(text=text, model="integration-model", finish_reason="stop")


class Embedding:
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        assert isinstance(request, EmbeddingRequest)
        return EmbeddingResponse((1.0, 0.0), "integration-embedding")


class Adapter:
    adapter_type = platform = "desktop"

    def __init__(self, publish):
        self.publish = publish
        self.outputs = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def send(self, message):
        self.outputs.append(message)
        return [BodyOutputItemResult(0, OperationStatus.COMPLETED)]


def observe(bus, names, terminal):
    recorded = {name: [] for name in names}
    done = asyncio.Event()

    async def record(flow):
        recorded[flow.envelope.event_type].append(flow.payload)
        if flow.envelope.event_type in terminal:
            done.set()

    api = ModuleEventAPI(bus, "integration.observer")
    for name in names:
        api.subscribe(name, record, handler_id=f"observe.{name}")
    return recorded, done


def input_message(text):
    return AdapterInboundMessage(
        adapter_type="desktop", platform="desktop", message_id="input-001",
        user_id="local-owner", display_name="Owner", scene_type=SceneType.DESKTOP,
        scene_id="desktop", content=Content.from_text(text),
    )


@pytest.mark.asyncio
async def test_non_empty_memory_query_success_reaches_agent_and_routed_reply(tmp_path):
    bus = EventBus()
    model = Model()
    adapters = []

    def factory(publish):
        adapters.append(Adapter(publish))
        return adapters[-1]

    config = SenaBotConfig(desktop=None, enable_context_compression=False)
    scene = SceneInfo(platform="desktop", scene_type=SceneType.DESKTOP, scene_id="desktop")
    with SQLiteDatabase(tmp_path / "query.db") as database:
        repository = SQLiteMemoryRepository(database)
        wanted = MemoryItem(
            "memory-tea", config.persona.persona_id, frozenset({USER_SCOPE}),
            Fact(MEMORY_TEXT, (Provenance("event", "seed-event"),), datetime(2026, 1, 1, tzinfo=UTC)),
        )
        # Same vector, but inaccessible user/space: catch lost scope filtering.
        hidden = MemoryItem("hidden-user", wanted.memory_space_id,
                            frozenset({MemoryScopeRef(MemoryScopeKind.USER, "other-user")}), wanted.payload)
        other_space = MemoryItem("hidden-space", "other-persona", wanted.scopes, wanted.payload)
        for item in (wanted, hidden, other_space):
            await repository.add(MemoryWriteEnvelope(
                f"seed-{item.item_id}", item,
                MemoryIndexEmbedding((1.0, 0.0), "integration-embedding"),
            ))
        app = create_senabot_app(SenaBotDependencies(
            model_provider=model, memory_model_provider=Model(), embedding_provider=Embedding(),
            database=database, event_bus=bus, adapter_factories=(factory,),
        ), config)
        events, done = observe(bus, ("memory.query.requested", "memory.query.completed",
                               "memory.query.failed", "body.output.requested", "body.output.completed"),
                               ("body.output.completed",))
        async with app:
            inbound = await adapters[0].publish(input_message("What drink do I prefer?"))
            await asyncio.wait_for(done.wait(), 5)
        assert events["memory.query.failed"] == []
        request, = events["memory.query.requested"]
        result, = events["memory.query.completed"]
        assert request.memory_space_id == config.persona.persona_id
        assert request.user_id == "local-owner"
        assert request.session_id == conversation_session_id(scene)
        assert request.group_id == ""
        assert request.query_text == "What drink do I prefer?"
        assert (result.query_id, result.memory_space_id, result.user_id, result.session_id, result.group_id) == (
            request.query_id, request.memory_space_id, request.user_id, request.session_id, request.group_id)
        assert result.memories == [wanted]
        model_request, = model.requests
        assert any(m.role == "system" and MEMORY_TEXT in m.content for m in model_request.messages)
        output, = events["body.output.requested"]
        assert output.scene == inbound.scene == scene
        assert output.route == inbound.output_route == OutputRoute("desktop", "desktop", "desktop")
        assert output.reply_to.platform_event_id == inbound.reply_target_id == "input-001"
        sent, = adapters[0].outputs
        assert sent.content.text_value() == REPLY
        assert output.content.text_value() == REPLY
        assert (sent.adapter_type, sent.platform) == ("desktop", "desktop")
        assert sent.scene == scene
        assert sent.reply_to == output.reply_to


@pytest.mark.asyncio
async def test_desktop_context_triggers_real_extraction_and_persists_checkpoint(tmp_path):
    path = tmp_path / "extraction.db"
    bus = EventBus()
    memory_model = Model(extraction=True)
    adapters = []

    def factory(publish):
        adapters.append(Adapter(publish))
        return adapters[-1]

    # One complete turn (user + assistant) makes one deterministic batch.
    config = SenaBotConfig(desktop=None, enable_context_compression=False,
                          memory_extraction=MemoryExtractionPolicy(entry_threshold=2, batch_size=2))
    with SQLiteDatabase(path) as database:
        app = create_senabot_app(SenaBotDependencies(
            model_provider=Model(), memory_model_provider=memory_model,
            embedding_provider=Embedding(), database=database, event_bus=bus,
            adapter_factories=(factory,),
        ), config)
        events, done = observe(bus, ("context.state.changed", "context.read.requested",
                               "context.read.resolved", "memory.extraction.completed",
                               "memory.extraction.failed"),
                               ("memory.extraction.completed", "memory.extraction.failed"))
        async with app:
            inbound = await adapters[0].publish(input_message(MEMORY_TEXT))
            await asyncio.wait_for(done.wait(), 5)
        assert events["memory.extraction.failed"] == []
        request, = events["context.read.requested"]
        resolved, = events["context.read.resolved"]
        completed, = events["memory.extraction.completed"]
        assert resolved.error is None
        assert resolved.operation_id == request.operation_id == completed.operation_id
        view = resolved.view
        assert view.session.scene == inbound.scene
        assert view.session.scene == SceneInfo(
            platform="desktop", scene_type=SceneType.DESKTOP, scene_id="desktop")
        assert request.session_id == view.session.session_id == completed.session_id
        assert request.session_id == conversation_session_id(inbound.scene)
        assert (request.after_sequence, request.through_sequence) == (0, 2)
        assert (view.after_sequence, view.through_sequence) == (0, 2)
        assert [e.sequence for e in view.entries] == [1, 2]
        assert [e.content.text_value() for e in view.entries] == [MEMORY_TEXT, REPLY]
        assert any(c.session.session_id == request.session_id and c.latest_sequence == 2
                   for c in events["context.state.changed"])
        assert completed.memory_space_id == config.persona.persona_id
        assert completed.processed_through_sequence == 2
        item_id, = completed.added_item_ids
        assert completed.updated_item_ids == ()
        assert len(memory_model.requests) == 3
        assert view.entries[0].entry_id in memory_model.requests[0].messages[0].content
        assert MEMORY_TEXT in memory_model.requests[1].messages[0].content
        assert MEMORY_TEXT in memory_model.requests[2].messages[0].content
        expected_provenance = (Provenance("context_entry", view.entries[0].entry_id),
                               Provenance("event", view.entries[0].source_event_id))
        checkpoint = database.connection.execute(
            "SELECT memory_space_id, session_id, processed_through_sequence FROM memory_extraction_progress"
        ).fetchone()
        assert tuple(checkpoint) == (config.persona.persona_id, request.session_id, 2)
        persisted = await SQLiteMemorySpaceRouter(database).for_space(config.persona.persona_id).retrieve(
            [1.0, 0.0], context=MemoryRecallContext(frozenset({USER_SCOPE})))
        item, = [candidate.memory for candidate in persisted]
        assert item.item_id == item_id
        assert item.payload.content == MEMORY_TEXT
        assert item.payload.provenance == expected_provenance
        assert item.scopes == frozenset({USER_SCOPE, MemoryScopeRef(MemoryScopeKind.SESSION, request.session_id)})

    with SQLiteDatabase(path) as reopened:
        restored = await SQLiteMemorySpaceRouter(reopened).for_space(config.persona.persona_id).retrieve(
            [1.0, 0.0], context=MemoryRecallContext(frozenset({USER_SCOPE})))
        assert [candidate.memory for candidate in restored] == [item]
        assert tuple(reopened.connection.execute(
            "SELECT memory_space_id, session_id, processed_through_sequence FROM memory_extraction_progress"
        ).fetchone()) == tuple(checkpoint)
