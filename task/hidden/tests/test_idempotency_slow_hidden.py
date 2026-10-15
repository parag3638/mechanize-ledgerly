"""Hidden tests: one Idempotency-Key, one charge, when the first request is slow (grader-owned).

Two replicas of the agent's app, as in production. For each key the test holds
the customer's row lock from an admin session, so the first request (replica 1)
blocks inside its transaction; three seconds later a repeat with the same key
goes to replica 2; then the row is released and both finish. One key must still
map to one charge (ARCHITECTURE.md, "Idempotency": "whichever replica it lands
on and however long the first request takes").

The redis-loss variant also empties the app's Redis database while the first
request is blocked ("Nothing in Redis is authoritative ... a failover can lose
the most recent writes").

Sequencing follows pg_stat_activity, not timers, and these replicas get a 10 s
statement timeout so the deliberate stall never trips the app's own 2 s limit.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import psycopg
import pytest
from conftest import ADMIN_DSN, make_customer

TREE = os.environ["LEDGERLY_TREE"]
REDIS_URL = os.environ["LEDGERLY_REDIS_URL"]
HOLD_S = 3.0  # how long the first request is kept blocked before the repeat arrives
KEYS_PER_TEST = 3
ADMIN_APP = "hidden-admin"


def _wait(seconds: float) -> None:
    threading.Event().wait(seconds)  # time.sleep is patched in the hidden tests


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def replicas() -> Iterator[list[str]]:
    env = {**os.environ, "LEDGERLY_DB_STATEMENT_TIMEOUT_MS": "10000"}
    procs: list[subprocess.Popen[bytes]] = []
    urls: list[str] = []
    for _ in range(2):
        port = _free_port()
        procs.append(
            subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "ledgerly.api.main:app"]
                + ["--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
                cwd=TREE,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        urls.append(f"http://127.0.0.1:{port}")
    deadline = time.monotonic() + 30
    for url in urls:
        while True:
            try:
                if httpx.get(f"{url}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("agent API did not start")
            _wait(0.2)
    yield urls
    for p in procs:
        p.terminate()
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()


class Post(threading.Thread):
    def __init__(self, url: str, key: str, customer: str) -> None:
        super().__init__(daemon=True)
        self.url, self.key, self.customer = url, key, customer
        self.status: int | None = None
        self.charge_id: str | None = None

    def run(self) -> None:
        body = {"customer_id": self.customer, "amount_cents": 4200, "currency": "USD"}
        try:
            r = httpx.post(
                f"{self.url}/charges", json=body, headers={"Idempotency-Key": self.key}, timeout=20
            )
        except httpx.HTTPError:
            return
        self.status = r.status_code
        if r.status_code in (200, 201):
            self.charge_id = str(r.json().get("id"))


def _lock_waiters(watch: psycopg.Connection[Any]) -> int:
    row = watch.execute(
        """
        SELECT count(*) FROM pg_stat_activity
        WHERE datname = current_database() AND wait_event_type = 'Lock'
          AND application_name <> %s AND pid <> pg_backend_pid()
        """,
        (ADMIN_APP,),
    ).fetchone()
    return int(row[0]) if row else 0


def _blocked_or_done(
    watch: psycopg.Connection[Any], post: Post, waiters: int, timeout: float
) -> None:
    """Wait until `waiters` requests are blocked on a lock, or `post` has finished."""
    end = time.monotonic() + timeout
    while time.monotonic() < end and post.is_alive() and _lock_waiters(watch) < waiters:
        _wait(0.05)


def _one_key(
    replicas: list[str], admin: Any, watch: psycopg.Connection[Any], key: str, lose_redis: bool
) -> None:
    customer = make_customer(admin)
    holder = psycopg.connect(ADMIN_DSN, application_name=ADMIN_APP)
    first = Post(replicas[0], key, customer)
    repeat = Post(replicas[1], key, customer)
    try:
        holder.execute("SELECT 1 FROM customers WHERE id = %s FOR UPDATE", (customer,))
        first.start()
        # The first request is inside its transaction, waiting for the customer row.
        _blocked_or_done(watch, first, 1, 8)
        if lose_redis:
            import redis

            redis.Redis.from_url(REDIS_URL).flushdb()
        _wait(HOLD_S)
        repeat.start()
        _blocked_or_done(watch, repeat, 2, 1)
    finally:
        holder.commit()
        holder.close()
    first.join(15)
    if repeat.ident is not None:  # started
        repeat.join(15)
    ok = [p for p in (first, repeat) if p.charge_id]
    assert ok, f"{key}: no successful response ({first.status}, {repeat.status})"
    assert len({p.charge_id for p in ok}) == 1, f"{key}: two different charges returned"
    row = admin.execute(
        "SELECT count(*) AS n FROM charges WHERE idempotency_key = %s", (key,)
    ).fetchone()
    assert row["n"] == 1, f"{key}: {row['n']} charges for one key"


def _slow_first(replicas: list[str], admin: Any, prefix: str, lose_redis: bool) -> None:
    run = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True, application_name=ADMIN_APP) as watch:
        for n in range(KEYS_PER_TEST):
            _one_key(replicas, admin, watch, f"{prefix}-{run}-{n}", lose_redis)


@pytest.mark.check("hidden.idempotency_slow_first")
def test_repeat_while_first_request_is_blocked(replicas: list[str], admin: Any) -> None:
    _slow_first(replicas, admin, "hslow", lose_redis=False)


@pytest.mark.check("hidden.idempotency_redis_loss")
def test_repeat_after_redis_loses_its_data(replicas: list[str], admin: Any) -> None:
    _slow_first(replicas, admin, "hloss", lose_redis=True)
