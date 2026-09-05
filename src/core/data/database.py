"""SQLite 连接、初始迁移及 sqlite-vec 表的显式初始化。

此模块只管理数据库基础设施，业务存取与跨行领域校验由 Repository 实现。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import sqlite_vec


class SQLiteDatabase:
    """
    管理数据库连接和使用周期。

    1.连接指定的数据库文件
    2.启用外键、加载 sqlite-vec，首次使用时创建普通表。
    3.管理事务,一组操作全部成功就提交，出错就回滚
    4.关闭连接
    """

    def __init__(self, path: str | Path, *, timeout_seconds: float = 5.0) -> None:
        self.connection = sqlite3.connect(
            str(path), timeout=timeout_seconds, isolation_level=None
        )

        # sqlite3.Row让查询结果既能按位置访问，也能按字段名访问
        self.connection.row_factory = sqlite3.Row
        try:
            # 启用外键检查，让表之间的关联约束生效
            self.connection.execute("PRAGMA foreign_keys = ON")

            # 临时允许加载扩展
            self.connection.enable_load_extension(True)
            try:
                sqlite_vec.load(self.connection)
            finally:
                self.connection.enable_load_extension(False)
            # 检查数据库版本,必要时建表
            self._migrate()
        except BaseException:
            self.connection.close()
            raise

    def _migrate(self) -> None:
        """检查数据库结构版本，首次使用时执行建表。"""

        # 开启事务
        with self.transaction():
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            # 1代表已经初始化
            if version == 1:
                return
            # 0代表未初始化,不是0直接报错
            if version != 0:
                raise ValueError(f"unsupported database schema version: {version}")

            # 找到执行SQL语句的路径
            migration_path = Path(__file__).parent / "migrations" / "001_initial.sql"
            sql = migration_path.read_text(encoding="utf-8")
            # 逐条执行SQL语句.
            statement = ""
            for line in sql.splitlines(keepends=True):
                statement += line
                if sqlite3.complete_statement(statement):
                    self.connection.execute(statement)
                    statement = ""
            # 检查文件尾部并标记完成
            if any(
                line.strip() and not line.lstrip().startswith("--")
                for line in statement.splitlines()
            ):
                raise ValueError("incomplete database migration statement")
            self.connection.execute("PRAGMA user_version = 1")

    def initialize_vectors(self, dimensions: int) -> None:
        """显式设置固定向量维度；重开可复用同维度表，不自动重建已有向量。"""

        # 检查维度必须为正整数,且不能为bool
        if (
            isinstance(dimensions, bool)
            or not isinstance(dimensions, int)
            or dimensions <= 0
        ):
            raise ValueError("vector dimensions must be a positive integer")

        # 显式构造建表语句
        table_sql = (
            "CREATE VIRTUAL TABLE memory_vectors USING vec0("
            "embedding_id INTEGER PRIMARY KEY, "
            f"embedding float[{dimensions}] distance_metric=cosine)"
        )
        # 在事务表里检查是否存在memory_vectors
        with self.transaction():
            existing = self.connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'memory_vectors'"
            ).fetchone()
            if existing is not None:
                # Only reuse the schema this initializer owns: checking one column
                # could accidentally accept a different primary key or non-vec0 table.
                actual_sql = " ".join(existing[0].split()).casefold()
                if actual_sql != " ".join(table_sql.split()).casefold():
                    raise ValueError("existing vector table does not match the requested schema")
                return
            self.connection.execute(table_sql)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """把一组数据库操作包成一个“要么全部成功，要么全部失败”的事务。"""

        # 禁止嵌套事务
        if self.connection.in_transaction:
            raise RuntimeError("nested transactions are not supported")

        # IMMEDIATE表明事务开始时就拿到写锁
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            # 暂时把执行权交给transaction里面的代码
            yield self.connection
            # 执行完里面的代码之后,提交
            self.connection.commit()
        except BaseException:
            # 如果出现错误则回滚
            self.connection.rollback()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> SQLiteDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
