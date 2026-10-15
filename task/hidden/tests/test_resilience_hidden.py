"""Hidden tests for the worker's processor calls (grader-owned).

Contract used, all visible to the agent: `ledgerly.worker.processing.process_charge(charge_id,
client)` with a client exposing `.charge(**kwargs)` (as tests/test_worker.py does), the
exceptions in `ledgerly.processor_client`, and `ledgerly.resilience.sleep` / `time.sleep`
for waits. Expectations come from ARCHITECTURE.md ("Calls to dependencies") and
CONTRIBUTING.md ("Never hold a database transaction open across a network call").
"""

import random
from typing import Any

import psycopg
import pytest
from conftest import ADMIN_DSN, charge_status, make_charge, make_customer
from ledgerly.processor_client import ProcessorResult, ProcessorTimeout
from psycopg import errors


class AlwaysTimesOut:
    def __init__(self) -> None:
        self.calls = 0

    def charge(self, **_kwargs: Any) -> ProcessorResult:
        self.calls += 1
        raise ProcessorTimeout("no answer")


class TimesOutThenOk:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def charge(self, **_kwargs: Any) -> ProcessorResult:
        self.calls += 1
        if self.calls <= self.failures:
            raise ProcessorTimeout("slow")
        return ProcessorResult(processor_ref="ch_hidden", status="captured")


def _process(charge_id: str, client: object) -> Any:
    from ledgerly.worker.processing import process_charge

    return process_charge(charge_id, client)  # type: ignore[arg-type]


class AlwaysOk:
    def charge(self, **_kwargs: Any) -> ProcessorResult:
        return ProcessorResult(processor_ref="ch_ok", status="captured")


def _healthy_traffic(admin: Any, customer: str, n: int = 15) -> None:
    """Successful captures before a failure, as in production: lets a call-ratio budget earn retries."""
    ok = AlwaysOk()
    for _ in range(n):
        _process(make_charge(admin, customer)["id"], ok)


@pytest.mark.check("hidden.resilience_bounded")
def test_persistent_timeouts_end_in_a_terminal_state(pool: None, admin) -> None:
    customer = make_customer(admin)
    _healthy_traffic(admin, customer)
    charge = make_charge(admin, customer)
    client = AlwaysTimesOut()
    _process(charge["id"], client)
    assert 2 <= client.calls <= 10, f"{client.calls} attempts for one charge"
    assert charge_status(admin, charge["id"]) in ("failed",)


@pytest.mark.check("hidden.resilience_bounded")
def test_one_timeout_is_retried_and_succeeds(pool: None, admin) -> None:
    customer = make_customer(admin)
    _healthy_traffic(admin, customer)
    charge = make_charge(admin, customer)
    client = TimesOutThenOk(failures=1)
    _process(charge["id"], client)
    assert client.calls == 2
    assert charge_status(admin, charge["id"]) == "succeeded"


@pytest.mark.check("hidden.resilience_backoff_jitter")
def test_waits_grow_between_attempts(pool: None, admin, no_real_sleep: list[float]) -> None:
    """Exponential backoff, on average: accepts equal jitter and full jitter alike.

    `random` is seeded so the outcome is the same on every grading run.
    """
    random.seed(2041)
    customer = make_customer(admin)
    firsts: list[float] = []
    seconds: list[float] = []
    for _ in range(32):
        _healthy_traffic(admin, customer)
        no_real_sleep.clear()
        charge = make_charge(admin, customer)
        _process(charge["id"], TimesOutThenOk(failures=2))
        waits = [w for w in no_real_sleep if w > 0]
        assert waits, f"no wait between attempts: {no_real_sleep}"
        firsts.append(waits[0])
        if len(waits) >= 2:
            seconds.append(waits[1])
    if seconds:  # three or more attempts: the second wait must be clearly longer on average
        assert sum(seconds) / len(seconds) > 1.15 * sum(firsts) / len(firsts), (firsts, seconds)


@pytest.mark.check("hidden.resilience_backoff_jitter")
def test_waits_are_jittered(pool: None, admin, no_real_sleep: list[float]) -> None:
    random.seed(2041)
    customer = make_customer(admin)
    first_waits: list[float] = []
    for _ in range(6):
        _healthy_traffic(admin, customer)
        no_real_sleep.clear()
        charge = make_charge(admin, customer)
        _process(charge["id"], TimesOutThenOk(failures=1))
        waits = [w for w in no_real_sleep if w > 0]
        assert waits, "no wait before the retry"
        first_waits.append(waits[0])
    assert len(set(first_waits)) > 1, f"identical waits every time: {first_waits}"


@pytest.mark.check("hidden.resilience_budget")
def test_retries_stay_within_budget_when_processor_is_down(pool: None, admin) -> None:
    customer = make_customer(admin)
    client = AlwaysTimesOut()
    n = 120
    for _ in range(n):
        charge = make_charge(admin, customer)
        _process(charge["id"], client)
    retries = client.calls - n
    assert retries <= 0.2 * client.calls + 10, f"{retries} retries for {client.calls} calls"


class ChecksLocksDuringCall:
    """While the processor is being called, try to lock the charge and customer rows."""

    def __init__(self, charge_id: str, customer: str) -> None:
        self.charge_id = charge_id
        self.customer = customer
        self.blocked: list[str] = []

    def charge(self, **_kwargs: Any) -> ProcessorResult:
        with psycopg.connect(ADMIN_DSN) as conn:
            for table, key in (("charges", self.charge_id), ("customers", self.customer)):
                try:
                    with conn.transaction():
                        conn.execute(
                            f"SELECT 1 FROM {table} WHERE id = %s FOR UPDATE NOWAIT", (key,)
                        )
                except errors.LockNotAvailable:
                    self.blocked.append(table)
            idle = conn.execute(
                """
                SELECT count(*) FROM pg_stat_activity
                WHERE datname = current_database() AND state LIKE 'idle in transaction%%'
                  AND pid <> pg_backend_pid()
                """
            ).fetchone()
            if idle and idle[0]:
                self.blocked.append("open_transaction")
        return ProcessorResult(processor_ref="ch_locks", status="captured")


@pytest.mark.check("hidden.processor_outside_txn")
def test_no_locks_or_open_transaction_during_processor_call(pool: None, admin) -> None:
    customer = make_customer(admin)
    charge = make_charge(admin, customer)
    client = ChecksLocksDuringCall(charge["id"], customer)
    _process(charge["id"], client)
    assert client.blocked == [], f"held during the processor call: {client.blocked}"
    assert charge_status(admin, charge["id"]) == "succeeded"
