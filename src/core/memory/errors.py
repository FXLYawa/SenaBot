class MemoryError(Exception):
    """Memory 层异常的基础类型。"""


class MemoryPersistenceError(MemoryError):
    """记忆持久化读取或写入失败。"""