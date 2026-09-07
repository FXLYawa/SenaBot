"""Memory 原始记录提取进度的 SQLite 存取。"""

from core.data.database import SQLiteDatabase


class SQLiteMemoryExtractionProgress:
    """只保存已完成的连续原始范围，不记录触发次数或模型调用状态。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self._database = database

    def load_processed_sequence(self, memory_space_id: str, session_id: str) -> int:
        row = self._database.connection.execute(
            "SELECT processed_through_sequence FROM memory_extraction_progress "
            "WHERE memory_space_id = ? AND session_id = ?",
            (memory_space_id, session_id),
        ).fetchone()
        return 0 if row is None else row["processed_through_sequence"]

    def save_processed_sequence(
        self, memory_space_id: str, session_id: str, through_sequence: int,
    ) -> None:
        with self._database.transaction() as connection:
            connection.execute(
                "INSERT INTO memory_extraction_progress "
                "(memory_space_id, session_id, processed_through_sequence) VALUES (?, ?, ?) "
                "ON CONFLICT(memory_space_id, session_id) DO UPDATE SET "
                "processed_through_sequence = max("
                "memory_extraction_progress.processed_through_sequence, excluded.processed_through_sequence)",
                (memory_space_id, session_id, through_sequence),
            )
