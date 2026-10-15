"""Create the 60 staging customers if they don't exist. Idempotent; runs after migrations."""

import os

import psycopg

CUSTOMERS = 60


def main() -> None:
    dsn = os.environ["LEDGERLY_MIGRATOR_DSN"]
    with psycopg.connect(dsn) as conn:
        for n in range(1, CUSTOMERS + 1):
            conn.execute(
                """
                INSERT INTO customers (id, name, daily_cap_cents)
                VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING
                """,
                (f"cust_{n:03d}", f"Merchant {n:03d}", 100_000_000_000),
            )
    print(f"devseed: {CUSTOMERS} customers present")


if __name__ == "__main__":
    main()
