"""Test data. Rows are written with the migrator role, which owns the tables."""

import itertools
from typing import Any

import psycopg

from ledgerly import ids
from ledgerly.config import get_settings

_seq = itertools.count(1)


def make_customer(daily_cap_cents: int = 10_000_000) -> str:
    customer_id = f"cust_t{next(_seq):04d}"
    with psycopg.connect(get_settings().test_migrator_dsn) as conn:
        conn.execute(
            "INSERT INTO customers (id, name, daily_cap_cents) VALUES (%s, %s, %s)",
            (customer_id, f"Test customer {customer_id}", daily_cap_cents),
        )
    return customer_id


def make_charge(customer_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": ids.new_id(),
        "idempotency_key": f"key-{next(_seq)}",
        "customer_id": customer_id,
        "amount_cents": 1250,
        "currency": "USD",
        "status": "pending",
        **overrides,
    }
    with psycopg.connect(get_settings().test_migrator_dsn) as conn:
        conn.execute(
            """
            INSERT INTO charges (id, idempotency_key, customer_id, amount_cents, currency, status)
            VALUES (%(id)s, %(idempotency_key)s, %(customer_id)s, %(amount_cents)s,
                    %(currency)s, %(status)s)
            """,
            row,
        )
    return row


def fetch_charge(charge_id: str) -> dict[str, Any]:
    with psycopg.connect(
        get_settings().test_migrator_dsn, row_factory=psycopg.rows.dict_row
    ) as conn:
        row = conn.execute("SELECT * FROM charges WHERE id = %s", (charge_id,)).fetchone()
    assert row is not None
    return row
