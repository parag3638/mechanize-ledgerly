"""Index charges by customer and time, built without locking writes.

`charges` is written to continuously, so the index is built with
CREATE INDEX CONCURRENTLY. Postgres refuses to run that inside a transaction,
hence the autocommit block.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-29 11:02:53
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_charges_customer_created",
            "charges",
            ["customer_id", "created_at"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_charges_customer_created",
            table_name="charges",
            postgresql_concurrently=True,
            if_exists=True,
        )
