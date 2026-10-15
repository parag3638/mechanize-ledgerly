"""Refunds.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-18 15:40:27
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE refunds (
            id            uuid PRIMARY KEY,
            charge_id     uuid NOT NULL REFERENCES charges (id),
            amount_cents  bigint NOT NULL CHECK (amount_cents > 0),
            reason        text NOT NULL,
            status        text NOT NULL CHECK (status IN ('pending', 'succeeded', 'failed')),
            processor_ref text,
            created_at    timestamptz NOT NULL DEFAULT now(),
            updated_at    timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_refunds_charge_id ON refunds (charge_id)")


def downgrade() -> None:
    op.execute("DROP TABLE refunds")
