"""在真实 SQLite/sqlite-vec 上验证迁移、约束、事务及重开。"""

from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from sqlite_vec import serialize_float32

from core.data.database import SQLiteDatabase


NOW = "2026-09-05T00:00:00.000000Z"


def add_session(db, session_id="session-1", scene_id="desktop"):
    db.execute(
        "INSERT INTO context_sessions "
        "(session_id,purpose,platform,account_namespace,scene_type,scene_id,created_at,updated_at) "
        "VALUES (?, 'conversation', 'desktop', 'default', 'desktop', ?, ?, ?)",
        (session_id, scene_id, NOW, NOW),
    )


def add_memory(db, item_id="memory-1"):
    db.execute(
        "INSERT INTO memory_items (item_id,memory_space_id,domain,payload_json,recorded_at) "
        "VALUES (?, 'sena', 'fact', ?, ?)",
        (item_id, '{"content":"coffee"}', NOW),
    )


class DatabaseTests(unittest.TestCase):
    def test_vector_table_with_wrong_primary_key_is_not_reused(self):
        with SQLiteDatabase(":memory:") as database:
            database.connection.execute(
                "CREATE VIRTUAL TABLE memory_vectors USING vec0("
                "wrong_id INTEGER PRIMARY KEY, embedding float[3] distance_metric=cosine)"
            )
            with self.assertRaises(ValueError):
                database.initialize_vectors(3)

    def test_failed_extension_load_closes_connection(self):
        connection = sqlite3.connect(":memory:", isolation_level=None)
        with patch("core.data.database.sqlite3.connect", return_value=connection), patch(
            "core.data.database.sqlite_vec.load", side_effect=RuntimeError("load failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "load failed"):
                SQLiteDatabase(":memory:")
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_nested_transaction_does_not_commit_outer_write(self):
        with SQLiteDatabase(":memory:") as database:
            with self.assertRaisesRegex(RuntimeError, "nested transactions"):
                with database.transaction() as db:
                    add_session(db)
                    with database.transaction():
                        pass
            self.assertEqual(database.connection.execute(
                "SELECT count(*) FROM context_sessions"
            ).fetchone()[0], 0)

    def test_context_manager_closes_connection(self):
        with SQLiteDatabase(":memory:") as database:
            connection = database.connection
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_migration_reopen_and_extension(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sena.db"
            with SQLiteDatabase(path) as database:
                self.assertTrue(database.connection.execute("SELECT vec_version()").fetchone()[0])
                with database.transaction() as db:
                    add_session(db)
            with SQLiteDatabase(path) as database:
                self.assertEqual(database.connection.execute("PRAGMA user_version").fetchone()[0], 1)
                self.assertEqual(database.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertEqual(database.connection.execute("SELECT count(*) FROM context_sessions").fetchone()[0], 1)
                self.assertIsNone(database.connection.execute(
                    "SELECT name FROM sqlite_master WHERE name='memory_vectors'"
                ).fetchone())

    def test_entry_identity_foreign_keys_and_transaction_rollback(self):
        with SQLiteDatabase(":memory:") as database:
            with database.transaction() as db:
                add_session(db)
            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as db:
                    add_session(db, "another-id")
            sql = (
                "INSERT INTO context_entries "
                "(entry_id,session_id,sequence,entry_type,actor_type,actor_id,content_json,created_at) "
                "VALUES (?, ?, 1, 'user_message', 'user', 'owner', '{}', ?)"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as db:
                    db.execute(sql, ("missing", "missing-session", NOW))
            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as db:
                    db.execute(sql, ("entry-1", "session-1", NOW))
                    db.execute(sql, ("entry-2", "session-1", NOW))
            self.assertEqual(database.connection.execute("SELECT count(*) FROM context_entries").fetchone()[0], 0)

    def test_scope_null_uniqueness_and_provenance_cascade(self):
        with SQLiteDatabase(":memory:") as database:
            with database.transaction() as db:
                add_memory(db)
                db.execute("INSERT INTO memory_scopes VALUES ('memory-1', 'global', NULL)")
                db.execute("INSERT INTO memory_provenances VALUES ('memory-1', 0, 'message', 'source-1')")
            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as db:
                    db.execute("INSERT INTO memory_scopes VALUES ('memory-1', 'global', NULL)")
            with self.assertRaises(sqlite3.IntegrityError):
                with database.transaction() as db:
                    db.execute("INSERT INTO memory_scopes VALUES ('memory-1', 'user', NULL)")
            with database.transaction() as db:
                db.execute("DELETE FROM memory_items WHERE item_id='memory-1'")
            for table in ("memory_scopes", "memory_provenances"):
                self.assertEqual(database.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_vector_dimension_persistence_and_real_knn(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sena.db"
            with SQLiteDatabase(path) as database:
                database.initialize_vectors(3)
                with database.transaction() as db:
                    db.execute("INSERT INTO memory_vectors VALUES (?, ?)", (1, serialize_float32([1, 0, 0])))
                    db.execute("INSERT INTO memory_vectors VALUES (?, ?)", (2, serialize_float32([0, 1, 0])))
            with SQLiteDatabase(path) as database:
                database.initialize_vectors(3)
                with self.assertRaises(ValueError):
                    database.initialize_vectors(4)
                row = database.connection.execute(
                    "SELECT embedding_id, distance FROM memory_vectors "
                    "WHERE embedding MATCH ? AND k = 1 ORDER BY distance",
                    (serialize_float32([1, 0, 0]),),
                ).fetchone()
                self.assertEqual(row["embedding_id"], 1)
                self.assertAlmostEqual(row["distance"], 0)
                with self.assertRaises(sqlite3.DatabaseError):
                    with database.transaction() as db:
                        db.execute("INSERT INTO memory_vectors VALUES (?, ?)", (3, serialize_float32([1, 0])))

    def test_vector_metadata_and_vector_rollback_together(self):
        with SQLiteDatabase(":memory:") as database:
            database.initialize_vectors(3)
            with database.transaction() as db:
                add_memory(db)
            with self.assertRaises(RuntimeError):
                with database.transaction() as db:
                    db.execute("INSERT INTO memory_embeddings VALUES (1, 'memory-1', 'test', 3, ?)", (NOW,))
                    db.execute("INSERT INTO memory_vectors VALUES (1, ?)", (serialize_float32([1, 0, 0]),))
                    raise RuntimeError("interrupt write")
            for table in ("memory_embeddings", "memory_vectors"):
                self.assertEqual(database.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0)

    def test_failed_migration_is_atomic(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sena.db"
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE memory_items (existing TEXT)")
            db.close()
            with self.assertRaises(sqlite3.OperationalError):
                SQLiteDatabase(path)
            db = sqlite3.connect(path)
            try:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='context_sessions'").fetchone())
            finally:
                db.close()

    def test_future_schema_rejected_and_invalid_dimension_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sena.db"
            with SQLiteDatabase(path) as database:
                for dimension in (0, -1, True, 3.5, "3"):
                    with self.subTest(dimension=dimension), self.assertRaises(ValueError):
                        database.initialize_vectors(dimension)
                with database.transaction() as db:
                    db.execute("PRAGMA user_version = 2")
            with self.assertRaises(ValueError):
                SQLiteDatabase(path)
