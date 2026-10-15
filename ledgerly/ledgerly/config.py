"""Service configuration.

This is the only module that reads the environment. Everything else asks for
`get_settings()`. Variables use the `LEDGERLY_` prefix; `.env` in the repo root
holds the defaults for the shared staging stack.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="LEDGERLY_", env_file=".env", extra="ignore")

    service_name: str = "ledgerly"
    log_level: str = "INFO"

    # Postgres. The app role can read and write rows; schema changes need the migrator role.
    app_dsn: str = "postgresql://ledgerly_app:ledgerly_app@postgres:5432/ledgerly"
    migrator_dsn: str = "postgresql://ledgerly_migrator:ledgerly_migrator@postgres:5432/ledgerly"
    test_app_dsn: str = "postgresql://ledgerly_app:ledgerly_app@postgres:5432/ledgerly_test"
    test_migrator_dsn: str = (
        "postgresql://ledgerly_migrator:ledgerly_migrator@postgres:5432/ledgerly_test"
    )
    db_acquire_timeout_s: float = 2.0
    db_statement_timeout_ms: int = 2000
    api_pool_max: int = 6
    worker_pool_max: int = 12

    # Redis stream that carries new charges from the API to the worker.
    redis_url: str = "redis://redis:6379/0"
    stream_name: str = "charges.created"
    consumer_group: str = "workers"
    # Idempotency locks (ledgerly/idempotency.py)
    idempotency_lock_ttl_ms: int = 1000
    idempotency_lock_wait_ms: int = 3000
    idempotency_lock_poll_ms: int = 20

    # Worker
    worker_concurrency: int = 12
    worker_metrics_port: int = 9101

    # External payment processor
    processor_url: str = "http://processor:8000"
    processor_timeout_s: float = 1.0

    # Public entry point (load balancer in front of the API replicas)
    public_url: str = "http://proxy:8080"


@lru_cache
def get_settings() -> Settings:
    return Settings()
