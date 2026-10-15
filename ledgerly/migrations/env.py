"""Alembic environment. Migrations run as the migrator role (`migrator_dsn`)."""

from alembic import context
from sqlalchemy import create_engine, pool

from ledgerly.config import get_settings


def _url() -> str:
    dsn = context.get_x_argument(as_dictionary=True).get("dsn") or get_settings().migrator_dsn
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
