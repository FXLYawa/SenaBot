"""独立命名空间、分类分流与显式生命周期；不接管第三方日志。"""

import logging
from logging.handlers import RotatingFileHandler
import sys
from threading import RLock
import time

from .config import LEVELS, LoggingConfig
from .formatter import JsonFormatter, TextFormatter

_lock = RLock()
_last_diagnostic = float("-inf")
_owned: list[logging.Handler] = []


def diagnostic() -> None:
    """固定文本限频出口，绝不输出失败记录或底层异常正文。"""
    global _last_diagnostic
    with _lock:
        now = time.monotonic()
        if now - _last_diagnostic < 30:
            return
        _last_diagnostic = now
    try:
        sys.stderr.write("SenaBot logging output unavailable; check logging configuration and storage.\n")
    except Exception:
        pass


class SafeLogger(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        # LoggerAdapter 默认会丢弃每次调用的 extra，必须保留它。
        return msg, kwargs

    def log(self, level, msg, *args, **kwargs):
        try:
            super().log(level, msg, *args, **kwargs)
        except Exception:
            diagnostic()


def get_logger(name: str) -> SafeLogger:
    name = name if name == "senabot" or name.startswith("senabot.") else "senabot." + name
    return SafeLogger(logging.getLogger(name), {})


class _Route(logging.Filter):
    def __init__(self, kind: str):
        super().__init__()
        self.kind = kind

    def filter(self, record: logging.LogRecord) -> bool:
        kind = getattr(record, "log_kind", "runtime")
        if kind not in ("runtime", "trace", "both"):
            kind = "runtime"
        return kind == self.kind or kind == "both"


class _SafeOutput:
    def handleError(self, record):
        diagnostic()


class _StreamHandler(_SafeOutput, logging.StreamHandler):
    pass


class _FileHandler(_SafeOutput, RotatingFileHandler):
    pass


def _replace(handlers: list[logging.Handler]) -> None:
    root = logging.getLogger("senabot")
    root.setLevel(logging.DEBUG)
    root.propagate = False
    # 先装新出口，再释放旧出口；NullHandler 也由本设施拥有。
    old = list(_owned)
    for handler in handlers:
        root.addHandler(handler)
    _owned[:] = handlers
    for handler in old:
        root.removeHandler(handler)
        try:
            handler.flush()
        except Exception:
            diagnostic()
        try:
            handler.close()
        except Exception:
            diagnostic()


def _console(level: int) -> logging.Handler:
    handler = _StreamHandler()
    handler.setLevel(level)
    handler.addFilter(_Route("runtime"))
    handler.setFormatter(TextFormatter())
    return handler


def configure_logging(config: LoggingConfig) -> None:
    if not isinstance(config, LoggingConfig):
        raise TypeError("expected LoggingConfig")
    with _lock:
        handlers: list[logging.Handler] = [logging.NullHandler()]
        if config.console:
            handlers.append(_console(LEVELS[config.level]))
        if config.file:
            try:
                config.path.mkdir(parents=True, exist_ok=True)
                routes = [("runtime", "senabot.log", 20, 5, config.level)]
                if config.trace:
                    routes.append(("trace", "senabot.trace.log", 50, 3, config.trace_level))
                for kind, filename, mib, backups, level in routes:
                    handler = _FileHandler(config.path / filename, maxBytes=mib * 1024 * 1024,
                                           backupCount=backups, encoding="utf-8")
                    handler.setLevel(LEVELS[level])
                    handler.addFilter(_Route(kind))
                    handler.setFormatter(JsonFormatter())
                    handlers.append(handler)
            except (OSError, ValueError):
                diagnostic()
                if not config.console:
                    handlers.append(_console(LEVELS[config.level]))
        _replace(handlers)


def shutdown_logging() -> None:
    with _lock:
        _replace([logging.NullHandler()])
