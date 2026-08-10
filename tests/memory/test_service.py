import pytest

from core.memory.contracts import (
    MemoryQueryRequest,
    MemoryWriteRequest,
)
from pathlib import Path

from core.memory.errors import MemoryPersistenceError
from core.memory.repository import FileMemoryRepository
from core.memory.service import MemoryService


@pytest.mark.asyncio
async def test_write_and_query_memory(tmp_path):
    """测试基本的记忆写入和查询。"""

    file_path = tmp_path / "memories.json"

    repository = FileMemoryRepository(file_path)
    service = MemoryService(repository)

    write_request = MemoryWriteRequest(
        operation_id="operation-001",
        source_event_id="event-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        write_text="用户喜欢跑步",
    )

    write_result = await service.write(write_request)

    assert write_result.operation_id == "operation-001"
    assert write_result.memory_id != ""

    query_request = MemoryQueryRequest(
        query_id="query-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        query_text="跑步",
    )

    query_result = await service.query(query_request)

    assert query_result.query_id == "query-001"
    assert len(query_result.memories) == 1
    assert query_result.memories[0].content == "用户喜欢跑步"
    assert query_result.memories[0].memory_id == write_result.memory_id


@pytest.mark.asyncio
async def test_query_memory_isolation(tmp_path):
    """测试 User、Session 和 Group 之间的记忆隔离。"""

    file_path = tmp_path / "memories.json"

    repository = FileMemoryRepository(file_path)
    service = MemoryService(repository)

    write_requests = [
        # 查询时应该查到这一条
        MemoryWriteRequest(
            operation_id="operation-001",
            source_event_id="event-001",
            group_id="group-001",
            session_id="session-001",
            user_id="user-001",
            write_text="用户喜欢跑步",
        ),

        # Session 不同，不应该查到
        MemoryWriteRequest(
            operation_id="operation-002",
            source_event_id="event-002",
            group_id="group-001",
            session_id="session-002",
            user_id="user-001",
            write_text="用户喜欢跑步",
        ),

        # User 不同，不应该查到
        MemoryWriteRequest(
            operation_id="operation-003",
            source_event_id="event-003",
            group_id="group-001",
            session_id="session-001",
            user_id="user-002",
            write_text="用户喜欢跑步",
        ),

        # Group 不同，不应该查到
        MemoryWriteRequest(
            operation_id="operation-004",
            source_event_id="event-004",
            group_id="group-002",
            session_id="session-001",
            user_id="user-001",
            write_text="用户喜欢跑步",
        ),
    ]

    for write_request in write_requests:
        await service.write(write_request)

    query_request = MemoryQueryRequest(
        query_id="query-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        query_text="跑步",
    )

    query_result = await service.query(query_request)

    assert len(query_result.memories) == 1

    memory = query_result.memories[0]

    assert memory.user_id == "user-001"
    assert memory.session_id == "session-001"
    assert memory.group_id == "group-001"


@pytest.mark.asyncio
async def test_source_event_id_deduplication(tmp_path):
    """测试相同 source_event_id 不会重复创建记忆。"""

    file_path = tmp_path / "memories.json"

    repository = FileMemoryRepository(file_path)
    service = MemoryService(repository)

    first_request = MemoryWriteRequest(
        operation_id="operation-001",
        source_event_id="event-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        write_text="用户喜欢跑步",
    )

    second_request = MemoryWriteRequest(
        operation_id="operation-002",
        source_event_id="event-001",  # 与第一次相同
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        write_text="用户喜欢跑步",
    )

    first_result = await service.write(first_request)
    second_result = await service.write(second_request)

    # 相同来源事件应该返回同一个 Memory ID
    assert first_result.memory_id == second_result.memory_id

    query_request = MemoryQueryRequest(
        query_id="query-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        query_text="跑步",
    )

    query_result = await service.query(query_request)

    # 最终只能保存一条记忆
    assert len(query_result.memories) == 1


@pytest.mark.asyncio
async def test_operation_id_idempotency(tmp_path):
    """测试相同 operation_id 不会重复执行写入操作。"""

    file_path = tmp_path / "memories.json"

    repository = FileMemoryRepository(file_path)
    service = MemoryService(repository)

    first_request = MemoryWriteRequest(
        operation_id="operation-001",
        source_event_id="event-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        write_text="用户喜欢跑步",
    )

    second_request = MemoryWriteRequest(
        operation_id="operation-001",  # 与第一次相同
        source_event_id="event-002",   # 来源事件不同
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        write_text="用户喜欢跑步",
    )

    first_result = await service.write(first_request)
    second_result = await service.write(second_request)

    # 相同操作应该返回同一个 Memory ID
    assert first_result.memory_id == second_result.memory_id

    query_request = MemoryQueryRequest(
        query_id="query-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        query_text="跑步",
    )

    query_result = await service.query(query_request)

    # 相同操作执行两次，最终只能保存一条记忆
    assert len(query_result.memories) == 1

@pytest.mark.asyncio
async def test_persistence_write_failure(tmp_path, monkeypatch):
    """测试文件写入失败时抛出 MemoryPersistenceError。"""

    file_path = tmp_path / "memories.json"

    repository = FileMemoryRepository(file_path)
    service = MemoryService(repository)

    def raise_write_error(*args, **kwargs):
        raise OSError("模拟文件写入失败")

    # Repository 创建完成后，再模拟 Path.write_text 失败
    monkeypatch.setattr(
        Path,
        "write_text",
        raise_write_error,
    )

    request = MemoryWriteRequest(
        operation_id="operation-001",
        source_event_id="event-001",
        group_id="group-001",
        session_id="session-001",
        user_id="user-001",
        write_text="用户喜欢跑步",
    )

    with pytest.raises(MemoryPersistenceError):
        await service.write(request)