"""Grader-owned fixtures for the hidden tests. Never shipped to the agent.

Runs in the grader container against a fresh `ledgerly_hidden` database that
the grader migrated with the agent's own migrations. The agent's package is
importable from LEDGERLY_TREE (set by the grader); the agent's tests/ and
conftest.py are never loaded.
"""

import json
import os
import signal
import time
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

APP_DSN = os.environ["HIDDEN_APP_DSN"]
ADMIN_DSN = os.environ["HIDDEN_ADMIN_DSN"]
RESULTS = os.environ["HIDDEN_RESULTS"]
TEST_DEADLINE_S = 30


class TestDeadline(BaseException):
    """Raised by the alarm; a BaseException so retry loops catching Exception can't swallow it."""


@pytest.fixture(autouse=True)
def deadline() -> Iterator[None]:
    def expire(_signum: int, _frame: object) -> None:
        raise TestDeadline(f"test exceeded {TEST_DEADLINE_S}s (unbounded retries?)")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(TEST_DEADLINE_S)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]
    marker = item.get_closest_marker("check")
    if report.when == "setup" and report.passed:
        # Written first, so a test that dies without reporting still counts (as a failure).
        record = {
            "test": item.nodeid,
            "check": marker.args[0] if marker else None,
            "outcome": "started",
            "detail": "",
        }
    elif report.when == "call" or (report.when == "setup" and not report.passed):
        record = {
            "test": item.nodeid,
            "check": marker.args[0] if marker else None,
            "outcome": report.outcome,
            "detail": str(report.longrepr)[-500:] if report.failed else "",
        }
    else:
        return
    with open(RESULTS, "a") as fh:
        fh.write(json.dumps(record) + "\n")


@pytest.fixture(scope="session", autouse=True)
def configure() -> Iterator[None]:
    from ledgerly.config import get_settings

    clear = getattr(get_settings, "cache_clear", None)
    if clear is not None:
        clear()
    yield


@pytest.fixture
def admin() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    with psycopg.connect(ADMIN_DSN, autocommit=True, row_factory=dict_row) as conn:
        yield conn


@pytest.fixture
def pool() -> Iterator[None]:
    from ledgerly.config import get_settings

    from ledgerly import db

    db.close_pool()
    db.init_pool(get_settings().app_dsn, 8, name="hidden-tests")
    yield
    db.close_pool()


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Record every wait instead of sleeping, whether the code uses resilience.sleep or time.sleep."""
    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(float(seconds))

    from ledgerly import resilience

    if hasattr(resilience, "sleep"):
        monkeypatch.setattr(resilience, "sleep", fake_sleep)
    monkeypatch.setattr(time, "sleep", fake_sleep)
    return slept


def make_customer(admin: psycopg.Connection[dict[str, Any]]) -> str:
    import uuid

    cid = f"hcust_{uuid.uuid4().hex[:12]}"
    admin.execute(
        "INSERT INTO customers (id, name, daily_cap_cents) VALUES (%s, %s, %s)",
        (cid, "hidden", 10**12),
    )
    return cid


def make_charge(admin: psycopg.Connection[dict[str, Any]], customer: str) -> dict[str, Any]:
    import uuid

    charge = {
        "id": str(uuid.uuid4()),
        "key": f"hkey-{uuid.uuid4().hex[:16]}",
        "customer": customer,
    }
    admin.execute(
        """
        INSERT INTO charges (id, idempotency_key, customer_id, amount_cents, currency, status)
        VALUES (%(id)s, %(key)s, %(customer)s, 1500, 'USD', 'pending')
        """,
        charge,
    )
    return charge


def charge_status(admin: psycopg.Connection[dict[str, Any]], charge_id: str) -> str:
    row = admin.execute("SELECT status FROM charges WHERE id = %s", (charge_id,)).fetchone()
    assert row is not None
    return str(row["status"])
