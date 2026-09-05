"""Memory 领域对象的 SQLite 持久化与向量检索实现。"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime

from sqlite_vec import serialize_float32

from core.data.database import SQLiteDatabase
from core.embedding import EmbeddingProvider, EmbeddingRequest
from core.memory.models import (
    Entity, Experience, Fact, Knowledge, MemoryItem, MemoryRecallContext,
    MemoryRetrievalCandidate, MemoryScopeKind, MemoryScopeRef,
    MemorySupersedeResult, MemoryWriteEnvelope, Provenance, Understanding,
)
from core.memory.protocols import MemoryRetrieverProtocol


def _format_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _search_text(item: MemoryItem) -> str:
    return item.payload.summary if isinstance(item.payload, Experience) else item.payload.content


def _payload_json(item: MemoryItem) -> str:
    payload = item.payload
    if isinstance(payload, Fact):
        data: dict[str, object] = {"content": payload.content}
    elif isinstance(payload, Experience):
        data = {
            "summary": payload.summary,
            "participants": [
                {"entity_type": value.entity_type, "entity_id": value.entity_id}
                for value in payload.participants
            ],
            "occurred_from": _format_datetime(payload.occurred_from),
            "occurred_to": _format_datetime(payload.occurred_to),
        }
    elif isinstance(payload, Understanding):
        data = {"content": payload.content, "evidence_item_ids": list(payload.evidence_item_ids)}
    elif isinstance(payload, Knowledge):
        data = {"content": payload.content}
    else:
        raise TypeError(f"unsupported memory payload: {type(payload)!r}")
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class SQLiteMemoryRepository:
    """把 MemoryItem、来源、Scope 和检索向量原子写入 SQLite。"""

    def __init__(self, database: SQLiteDatabase, embedding_provider: EmbeddingProvider) -> None:
        self._database = database
        self._embedding_provider = embedding_provider

    async def add(self, envelope: MemoryWriteEnvelope) -> MemoryItem:
        embedding = await self._embedding_provider.embed(EmbeddingRequest(_search_text(envelope.item)))
        self._database.initialize_vectors(embedding.dimensions)
        with self._database.transaction() as connection:
            self._insert_item(connection, envelope.item, embedding.model, embedding.vector)
        return envelope.item

    async def end_fact_validity(
        self, *, operation_id: str, target_item_id: str, valid_to: datetime,
    ) -> MemoryItem:
        del operation_id
        with self._database.transaction() as connection:
            item = self._load_item(connection, target_item_id)
            if not isinstance(item.payload, Fact):
                raise ValueError("target memory item must be a Fact")
            updated = MemoryItem(
                item_id=item.item_id,
                memory_space_id=item.memory_space_id,
                scopes=item.scopes,
                payload=replace(item.payload, valid_to=valid_to),
            )
            connection.execute(
                "UPDATE memory_items SET valid_to = ? WHERE item_id = ?",
                (_format_datetime(valid_to), target_item_id),
            )
        return updated

    async def supersede(
        self, *, operation_id: str, target_item_id: str,
        replacement: MemoryWriteEnvelope,
    ) -> MemorySupersedeResult:
        embedding = await self._embedding_provider.embed(EmbeddingRequest(_search_text(replacement.item)))
        self._database.initialize_vectors(embedding.dimensions)
        with self._database.transaction() as connection:
            previous = self._load_item(connection, target_item_id)
            self._insert_item(connection, replacement.item, embedding.model, embedding.vector)
            connection.execute(
                "INSERT INTO memory_replacements "
                "(previous_item_id, replacement_item_id, operation_id) VALUES (?, ?, ?)",
                (target_item_id, replacement.item.item_id, operation_id),
            )
        return MemorySupersedeResult(previous, replacement.item)

    def _insert_item(
        self, connection: sqlite3.Connection, item: MemoryItem,
        model: str, vector: tuple[float, ...],
    ) -> None:
        payload = item.payload
        valid_from = payload.valid_from if isinstance(payload, Fact) else None
        valid_to = payload.valid_to if isinstance(payload, Fact) else None
        connection.execute(
            "INSERT INTO memory_items "
            "(item_id, memory_space_id, domain, payload_json, recorded_at, valid_from, valid_to) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.item_id, item.memory_space_id, item.domain.value, _payload_json(item),
                _format_datetime(payload.recorded_at), _format_datetime(valid_from),
                _format_datetime(valid_to),
            ),
        )
        connection.executemany(
            "INSERT INTO memory_scopes (item_id, scope_kind, scope_id) VALUES (?, ?, ?)",
            [
                (item.item_id, scope.kind.value, scope.scope_id)
                for scope in sorted(item.scopes, key=lambda value: (value.kind.value, value.scope_id or ""))
            ],
        )
        connection.executemany(
            "INSERT INTO memory_provenances "
            "(item_id, position, source_type, source_id) VALUES (?, ?, ?, ?)",
            [
                (item.item_id, position, value.source_type, value.source_id)
                for position, value in enumerate(payload.provenance)
            ],
        )
        cursor = connection.execute(
            "INSERT INTO memory_embeddings (item_id, model, dimensions, created_at) "
            "VALUES (?, ?, ?, ?)",
            (item.item_id, model, len(vector), datetime.now(UTC).isoformat()),
        )
        connection.execute(
            "INSERT INTO memory_vectors (embedding_id, embedding) VALUES (?, ?)",
            (cursor.lastrowid, serialize_float32(vector)),
        )

    def _load_item(self, connection: sqlite3.Connection, item_id: str) -> MemoryItem:
        row = connection.execute("SELECT * FROM memory_items WHERE item_id = ?", (item_id,)).fetchone()
        if row is None:
            raise ValueError(f"memory item not found: {item_id}")
        return _item_from_row(connection, row)


class SQLiteMemoryRetriever:
    """在 Memory Space 和 Scope 粗筛后按余弦距离召回当前记忆。"""

    def __init__(
        self, database: SQLiteDatabase, memory_space_id: str, *, limit: int = 20,
    ) -> None:
        if not memory_space_id.strip():
            raise ValueError("memory_space_id must not be blank")
        if limit <= 0:
            raise ValueError("retrieval limit must be positive")
        self._database = database
        self._memory_space_id = memory_space_id
        self._limit = limit

    async def retrieve(
        self, query_embedding: list[float], *, context: MemoryRecallContext,
    ) -> list[MemoryRetrievalCandidate]:
        self._database.initialize_vectors(len(query_embedding))
        scope_terms = [
            (scope.kind.value, scope.scope_id)
            for scope in context.scopes
            if scope.kind is not MemoryScopeKind.GLOBAL
        ]
        scope_sql = ""
        parameters: list[object] = [serialize_float32(query_embedding), self._memory_space_id]
        if scope_terms:
            clauses = " OR ".join("(s.scope_kind = ? AND s.scope_id = ?)" for _ in scope_terms)
            scope_sql = (
                "OR EXISTS (SELECT 1 FROM memory_scopes s "
                f"WHERE s.item_id = i.item_id AND ({clauses}))"
            )
            for kind, scope_id in scope_terms:
                parameters.extend((kind, scope_id))
        parameters.append(self._limit)
        rows = self._database.connection.execute(
            "SELECT i.*, vec_distance_cosine(v.embedding, ?) AS distance "
            "FROM memory_items i "
            "JOIN memory_embeddings e ON e.item_id = i.item_id "
            "JOIN memory_vectors v ON v.embedding_id = e.embedding_id "
            "WHERE i.memory_space_id = ? "
            "AND (i.domain <> 'fact' OR i.valid_to IS NULL) "
            "AND NOT EXISTS (SELECT 1 FROM memory_replacements r "
            "                WHERE r.previous_item_id = i.item_id) "
            "AND (EXISTS (SELECT 1 FROM memory_scopes g "
            "             WHERE g.item_id = i.item_id AND g.scope_kind = 'global') "
            f"{scope_sql}) ORDER BY distance ASC LIMIT ?",
            parameters,
        ).fetchall()
        return [
            MemoryRetrievalCandidate(
                memory=_item_from_row(self._database.connection, row),
                score=1.0 - float(row["distance"]),
            )
            for row in rows
        ]


class SQLiteMemorySpaceRouter:
    """为指定 Memory Space 创建共享同一 SQLite 连接的 Retriever。"""

    def __init__(self, database: SQLiteDatabase, *, limit: int = 20) -> None:
        self._database = database
        self._limit = limit

    def for_space(self, memory_space_id: str) -> MemoryRetrieverProtocol:
        return SQLiteMemoryRetriever(self._database, memory_space_id, limit=self._limit)


def _item_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> MemoryItem:
    item_id = row["item_id"]
    data = json.loads(row["payload_json"])
    provenance = tuple(
        Provenance(value["source_type"], value["source_id"])
        for value in connection.execute(
            "SELECT source_type, source_id FROM memory_provenances "
            "WHERE item_id = ? ORDER BY position", (item_id,),
        )
    )
    recorded_at = _parse_datetime(row["recorded_at"])
    assert recorded_at is not None
    domain = row["domain"]
    if domain == "fact":
        payload = Fact(
            content=data["content"], provenance=provenance, recorded_at=recorded_at,
            valid_from=_parse_datetime(row["valid_from"]),
            valid_to=_parse_datetime(row["valid_to"]),
        )
    elif domain == "experience":
        payload = Experience(
            summary=data["summary"], provenance=provenance,
            participants=tuple(Entity(**value) for value in data["participants"]),
            occurred_from=_parse_datetime(data["occurred_from"]),
            occurred_to=_parse_datetime(data["occurred_to"]), recorded_at=recorded_at,
        )
    elif domain == "understanding":
        payload = Understanding(
            content=data["content"], provenance=provenance,
            evidence_item_ids=tuple(data["evidence_item_ids"]), recorded_at=recorded_at,
        )
    elif domain == "knowledge":
        payload = Knowledge(content=data["content"], provenance=provenance, recorded_at=recorded_at)
    else:
        raise ValueError(f"unsupported memory domain: {domain}")
    scopes = frozenset(
        MemoryScopeRef(MemoryScopeKind(value["scope_kind"]), value["scope_id"])
        for value in connection.execute(
            "SELECT scope_kind, scope_id FROM memory_scopes WHERE item_id = ?", (item_id,),
        )
    )
    return MemoryItem(item_id, row["memory_space_id"], scopes, payload)
