"""Customers and charges.

Revision ID: 0001
Revises:
Create Date: 2026-01-12 10:04:11
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE customers (
            id                  text PRIMARY KEY,
            name                text NOT NULL,
            daily_cap_cents     bigint NOT NULL CHECK (daily_cap_cents > 0),
            charged_today_cents bigint NOT NULL DEFAULT 0,
            in_flight_cents     bigint NOT NULL DEFAULT 0,
            created_at          timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE charges (
            id              uuid PRIMARY KEY,
            idempotency_key text NOT NULL,
            customer_id     text NOT NULL REFERENCES customers (id),
            amount_cents    bigint NOT NULL CHECK (amount_cents > 0),
            currency        char(3) NOT NULL,
            status          text NOT NULL
                CHECK (status IN ('pending', 'processing', 'succeeded', 'failed', 'refunded')),
            processor_ref   text,
            failure_reason  text,
            created_at      timestamptz NOT NULL DEFAULT now(),
            updated_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_charges_idempotency_key ON charges (idempotency_key)")
    op.execute("CREATE INDEX ix_charges_status ON charges (status)")


def downgrade() -> None:
    op.execute("DROP TABLE charges")
    op.execute("DROP TABLE customers")
