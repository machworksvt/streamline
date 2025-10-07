from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

LOG_NAMESPACE = "streamline"


class _ContextFormatter(logging.Formatter):
    """Formatter that renders structured context dictionaries."""

    def format(self, record: logging.LogRecord) -> str:  # pragma: no cover - exercised via logging
        context = getattr(record, "context", None)
        hint = getattr(record, "hint", None)
        code = getattr(record, "error_code", None)
        parts: list[str] = []
        if isinstance(context, Mapping) and context:
            rendered = " ".join(f"{key}={context[key]!r}" for key in sorted(context))
            parts.append(rendered)
        elif context:
            parts.append(str(context))
        if hint:
            parts.append(f"hint={hint}")
        if code:
            parts.append(f"code={code}")
        record.streamline_context = f" | {' '.join(parts)}" if parts else ""
        return super().format(record)


@dataclass
class LoggingConfig:
    """Configuration for :func:`setup_logging`."""

    level: int | str = logging.INFO
    console: bool = True
    logfile: Optional[Path] = None
    propagate: bool = False

    def resolved_level(self) -> int:
        if isinstance(self.level, str):
            return logging.getLevelName(self.level.upper())  # type: ignore[return-value]
        return int(self.level)


class StreamlineLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that carries structured context information."""

    def __init__(self, logger: logging.Logger, context: Optional[Mapping[str, Any]] = None) -> None:
        super().__init__(logger, {"context": dict(context or {})})

    # ------------------------------------------------------------------
    # Adapter helpers
    # ------------------------------------------------------------------
    def bind(self, **context: Any) -> "StreamlineLoggerAdapter":
        merged = dict(self.extra.get("context") or {})
        for key, value in context.items():
            if value is not None:
                merged[key] = value
        return self.__class__(self.logger, merged)

    def unbind(self, *keys: str) -> "StreamlineLoggerAdapter":
        merged = dict(self.extra.get("context") or {})
        for key in keys:
            merged.pop(key, None)
        return self.__class__(self.logger, merged)

    # ------------------------------------------------------------------
    # Logging API
    # ------------------------------------------------------------------
    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
        kwargs = dict(kwargs)
        context = kwargs.pop("context", None)
        hint = kwargs.pop("hint", None)
        code = kwargs.pop("code", None)
        extra = dict(self.extra)
        merged_context = dict(extra.get("context") or {})
        if isinstance(context, Mapping):
            merged_context.update({k: v for k, v in context.items() if v is not None})
        elif context is not None:
            merged_context["detail"] = context
        if merged_context:
            extra["context"] = merged_context
        else:
            extra.pop("context", None)
        if hint is not None:
            extra["hint"] = hint
        if code is not None:
            extra["error_code"] = code
        kwargs.setdefault("extra", {}).update(extra)
        return msg, kwargs


def get_logger(name: Optional[str] = None, **context: Any) -> StreamlineLoggerAdapter:
    """Return a logger under the Streamline namespace with optional bound context."""

    full_name = LOG_NAMESPACE if name is None else f"{LOG_NAMESPACE}.{name}"
    base_logger = logging.getLogger(full_name)
    return StreamlineLoggerAdapter(base_logger, context)


_initialized = False


def setup_logging(config: Optional[LoggingConfig] = None, *, force: bool = False) -> None:
    """Configure the application logging hierarchy."""

    global _initialized

    config = config or LoggingConfig()
    level = config.resolved_level()

    if _initialized and not force:
        logging.getLogger(LOG_NAMESPACE).setLevel(level)
        return

    root_logger = logging.getLogger(LOG_NAMESPACE)
    root_logger.handlers.clear()
    root_logger.setLevel(level)
    root_logger.propagate = config.propagate

    formatter = _ContextFormatter("[%(levelname)s] %(message)s%(streamline_context)s")

    if config.console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    if config.logfile is not None:
        logfile_path = Path(config.logfile)
        logfile_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(logfile_path, encoding="utf-8")
        file_formatter = _ContextFormatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s%(streamline_context)s")
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(level)
        root_logger.addHandler(file_handler)

    logging.captureWarnings(True)

    _initialized = True


def setup_logging_from_env(*, default_level: int | str = logging.INFO) -> None:
    """Configure logging using environment variables."""

    level = os.environ.get("STREAMLINE_LOG_LEVEL", str(default_level))
    logfile = os.environ.get("STREAMLINE_LOG_FILE")
    setup_logging(LoggingConfig(level=level, logfile=Path(logfile) if logfile else None))
