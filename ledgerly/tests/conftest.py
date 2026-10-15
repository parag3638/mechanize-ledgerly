"""Shared fixtures. Tests run against the `ledgerly_test` database, never `ledgerly`."""

from collections.abc import Iterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from ledgerly import db
from ledgerly.config import get_settings

TABLES = ("refunds", "charges", "customers")


@pytest.fixture(scope="session", autouse=True)
def test_database() -> Iterator[None]:
    """Point the app at the test database and bring its schema to head."""
    settings = get_settings()
    mp = pytest.MonkeyPatch()
    mp.setenv("LEDGERLY_APP_DSN", settings.test_app_dsn)
    mp.setenv("LEDGERLY_MIGRATOR_DSN", settings.test_migrator_dsn)
    mp.setenv("LEDGERLY_STREAM_NAME", "charges.created.test")
    get_settings.cache_clear()

    cfg = Config("alembic.ini")
    cfg.cmd_opts = None
    command.upgrade(cfg, "head")
    yield
    db.close_pool()
    mp.undo()
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    with psycopg.connect(get_settings().test_migrator_dsn) as conn:
        for table in TABLES:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608 - fixed table names


@pytest.fixture
def pool() -> Iterator[None]:
    settings = get_settings()
    db.init_pool(settings.app_dsn, 4, name="tests")
    yield
    db.close_pool()


@pytest.fixture
def customer() -> str:
    from tests.factories import make_customer

    return make_customer()
