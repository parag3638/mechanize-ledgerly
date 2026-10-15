"""Postgres access: one connection pool per process.

Call `init_pool()` once at startup, then borrow connections with `get_conn()`.
Borrowing waits at most `db_acquire_timeout_s`; when the pool is exhausted it
raises `psycopg_pool.PoolTimeout`, which the API turns into a 503. Every
statement (including waits for row locks) is cancelled after
`db_statement_timeout_ms`.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from ledgerly.config import get_settings
from ledgerly.log import get_logger

log = get_logger(__name__)

_pool: ConnectionPool[Connection[DictRow]] | None = None


def init_pool(dsn: str, max_size: int, name: str) -> ConnectionPool[Connection[DictRow]]:
    global _pool
    if _pool is not None:
        return _pool
    kwargs: dict[str, Any] = {
        "row_factory": dict_row,
        "application_name": name,
        "options": f"-c statement_timeout={get_settings().db_statement_timeout_ms}",
    }
    _pool = ConnectionPool(
        dsn,
        min_size=1,
        max_size=max_size,
        kwargs=kwargs,
        connection_class=Connection[DictRow],
        name=name,
        open=True,
    )
    log.info("db pool opened", pool=name, max_size=max_size)
    return _pool


def get_pool() -> ConnectionPool[Connection[DictRow]]:
    if _pool is None:
        raise RuntimeError("db pool not initialised; call init_pool() at startup")
    return _pool


@contextmanager
def get_conn() -> Iterator[Connection[DictRow]]:
    timeout = get_settings().db_acquire_timeout_s
    with get_pool().connection(timeout=timeout) as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
