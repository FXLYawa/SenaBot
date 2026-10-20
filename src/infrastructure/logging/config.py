"""单进程日志配置，相对路径固定以项目根目录解析。"""

from dataclasses import dataclass, fields
from pathlib import Path
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


class LoggingConfigError(ValueError):
    """消息只由本模块生成，可安全用于启动诊断。"""


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    console: bool = True
    file: bool = True
    trace: bool = False
    trace_level: str = "INFO"
    directory: str = "logs"

    def __post_init__(self) -> None:
        for name in ("level", "trace_level"):
            value = getattr(self, name)
            if not isinstance(value, str) or value not in LEVELS:
                raise LoggingConfigError(f"logging.{name}: expected DEBUG/INFO/WARNING/ERROR/CRITICAL")
        for name in ("console", "file", "trace"):
            if type(getattr(self, name)) is not bool:
                raise LoggingConfigError(f"logging.{name}: expected boolean")
        if not isinstance(self.directory, str) or not self.directory.strip():
            raise LoggingConfigError("logging.directory: expected non-empty path")

    @property
    def path(self) -> Path:
        return PROJECT_ROOT / self.directory


def load_logging_config(path: Path | None = None) -> LoggingConfig:
    path = path or PROJECT_ROOT / "config" / "logging.toml"
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except tomllib.TOMLDecodeError:
        raise LoggingConfigError("logging.toml: invalid TOML syntax") from None
    except OSError:
        raise LoggingConfigError("logging.toml: configuration file is not readable") from None
    if set(document) != {"logging"} or not isinstance(document["logging"], dict):
        raise LoggingConfigError("logging: expected a single [logging] table")
    values = document["logging"]
    if set(values) - {item.name for item in fields(LoggingConfig)}:
        raise LoggingConfigError("logging: unknown configuration field")
    return LoggingConfig(**values)
