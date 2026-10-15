"""Structured JSON logging.

Every module gets its logger here: `log = get_logger(__name__)`, then
`log.info("charge created", charge_id=..., idempotency_key=...)`. Keyword
arguments become top-level JSON fields. One line per event on stdout.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from ledgerly.config import get_settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_configured = False


class _JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        payload: dict[str, Any] = {
            "ts": ts.replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "service": self._service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _configure() -> None:
    global _configured
    if _configured:
        return
    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter(settings.service_name))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True


class Logger:
    """Thin wrapper so call sites pass fields as keyword arguments."""

    def __init__(self, inner: logging.Logger) -> None:
        self._inner = inner

    def _log(self, level: int, msg: str, exc_info: bool, fields: dict[str, Any]) -> None:
        if self._inner.isEnabledFor(level):
            self._inner.log(level, msg, exc_info=exc_info, extra={"fields": fields}, stacklevel=3)

    def debug(self, msg: str, **fields: Any) -> None:
        self._log(logging.DEBUG, msg, False, fields)

    def info(self, msg: str, **fields: Any) -> None:
        self._log(logging.INFO, msg, False, fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._log(logging.WARNING, msg, False, fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._log(logging.ERROR, msg, False, fields)

    def exception(self, msg: str, **fields: Any) -> None:
        self._log(logging.ERROR, msg, True, fields)


def get_logger(name: str) -> Logger:
    _configure()
    return Logger(logging.getLogger(name))
