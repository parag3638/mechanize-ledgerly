"""Serialise requests that share an Idempotency-Key across the API replicas.

Merchants retry on timeouts and the mobile SDK can send the same request on two
connections at once, and the two copies may land on different replicas. Both
replicas take the same short-lived Redis lock before looking the key up, so a
repeat waits for the first request to finish and then finds its charge.

Creating a charge takes a few milliseconds, so the lock's TTL only matters when
a replica dies while holding it; it is kept short so a crashed request frees
the key quickly instead of blocking the merchant's retries.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from ledgerly.api.errors import ApiError
from ledgerly.config import get_settings
from ledgerly.log import get_logger

log = get_logger(__name__)

LOCK_PREFIX = "idem:"
SLOW_WAIT_MS = 100  # waits longer than this are logged


@contextmanager
def guard(client: redis.Redis, key: str) -> Iterator[None]:
    """Hold the key's lock for the duration of the block, waiting for it if needed."""
    settings = get_settings()
    name = LOCK_PREFIX + key
    started = time.monotonic()
    deadline = started + settings.idempotency_lock_wait_ms / 1000
    while not client.set(name, "1", nx=True, px=settings.idempotency_lock_ttl_ms):
        if time.monotonic() >= deadline:
            raise ApiError(
                409,
                "idempotency_in_progress",
                "A request with this Idempotency-Key is still in progress. Retry shortly.",
            )
        time.sleep(settings.idempotency_lock_poll_ms / 1000)
    waited_ms = int((time.monotonic() - started) * 1000)
    if waited_ms > SLOW_WAIT_MS:
        log.info(
            "idempotency lock acquired after waiting",
            event="idem_lock_wait",
            idempotency_key=key,
            waited_ms=waited_ms,
        )
    try:
        yield
    finally:
        client.delete(name)
