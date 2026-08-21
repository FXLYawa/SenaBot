import json
from dataclasses import asdict
from pathlib import Path
from datetime import datetime
from .errors import MemoryPersistenceError
from . import models
from .models import Memory,MemoryQueryCriteria


class FileMemoryRepository:
    """第一版暂时使用 JSON 文件保存和查询记忆。"""

    def __init__(self, file_path:Path):
        self.file_path = file_path

        #确保文件所在目录存在
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

        #不存在创建空数组
        if not self.file_path.exists():
                self.file_path.write_text("[]",encoding="utf-8")

    async def query(self,criteria:MemoryQueryCriteria) -> list[Memory]:

        """查询记忆的集合"""

        data = self._read_data()

        memories = []

        ##json不支持datetime,转为字符串存储,因此读取时需要转换回来,实现Data层后可删除此转换
        for item in data:
            item["created_at"] = datetime.fromisoformat(
                item["created_at"]
            )
            item["updated_at"] = datetime.fromisoformat(
                item["updated_at"]
            )

            memories.append(models.Memory(**item))

        return [
            memory
            for memory in memories
            if memory.user_id == criteria.user_id
               and memory.session_id == criteria.session_id
               and memory.group_id == criteria.group_id
               and criteria.query_text in memory.content
        ]

    async def find_by_source_event_id(
            self,
            source_event_id: str,
    ) -> models.Memory | None:
        """根据来源事件 ID 查询已经写入的记忆。"""

        data = self._read_data()

        for item in data:
            if item.get("source_event_id") == source_event_id:
                memory_data = item.copy()

                memory_data["created_at"] = datetime.fromisoformat(
                    memory_data["created_at"]
                )
                memory_data["updated_at"] = datetime.fromisoformat(
                    memory_data["updated_at"]
                )

                return models.Memory(**memory_data)

        return None

    async def find_by_operation_id(
            self,
            operation_id: str,
    ) -> models.Memory | None:
        """根据操作 ID 查询已经写入的记忆。"""

        data = self._read_data()

        for item in data:
            if item.get("operation_id") == operation_id:
                memory_data = item.copy()

                memory_data["created_at"] = datetime.fromisoformat(
                    memory_data["created_at"]
                )
                memory_data["updated_at"] = datetime.fromisoformat(
                    memory_data["updated_at"]
                )

                return models.Memory(**memory_data)

        return None

    async def save(
        self,
        memory: models.Memory,
    ) -> models.Memory:
        """写入记忆"""

        data = self._read_data()

        memory_data = asdict(memory)

        #json不支持datetime,转为字符串存储,实现Data层后可删除此转换
        memory_data["created_at"] = memory.created_at.isoformat()
        memory_data["updated_at"] = memory.updated_at.isoformat()

        data.append(memory_data)

        self._write_data(data)

        return memory

    def _read_data(self) -> list[dict]:
        """读取 JSON 文件，并将底层错误转换为 Memory 异常。"""

        try:
            content = self.file_path.read_text(encoding="utf-8")
            return json.loads(content)

        except (OSError, json.JSONDecodeError) as error:
            raise MemoryPersistenceError(
                "记忆文件读取失败"
            ) from error

    def _write_data(self, data: list[dict]) -> None:
        """写入 JSON 文件，并将底层错误转换为 Memory 异常。"""

        try:
            self.file_path.write_text(
                json.dumps(
                    data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        except OSError as error:
            raise MemoryPersistenceError(
                "记忆文件写入失败"
            ) from error

    async def update(
        self,
        memory: models.Memory,
    ) -> models.Memory:
        """更新已有记忆。"""

        data = self._read_data()

        memory_data = asdict(memory)
        memory_data["created_at"] = memory.created_at.isoformat()
        memory_data["updated_at"] = memory.updated_at.isoformat()

        for index, item in enumerate(data):
            if item.get("memory_id") == memory.memory_id:
                data[index] = memory_data
                self._write_data(data)
                return memory

        raise MemoryPersistenceError(
            f"未找到需要更新的记忆: {memory.memory_id}"
        )

    async def delete(
        self,
        memory_id: str,
    ) -> None:
        """删除已有记忆。"""

        data = self._read_data()

        for index, item in enumerate(data):
            if item.get("memory_id") == memory_id:
                del data[index]
                self._write_data(data)
                return

        raise MemoryPersistenceError(
            f"未找到需要删除的记忆: {memory_id}"
        )
