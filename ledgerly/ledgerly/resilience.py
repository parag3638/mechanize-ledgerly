"""Retries for calls to dependencies that fail transiently.

Every retry in Ledgerly goes through `retry`, so behaviour is consistent and
visible: each retry logs `event=retry` and increments `retries_total{fn}`.
"""

import functools
import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from ledgerly.log import get_logger
from ledgerly.metrics import RETRIES

log = get_logger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

# Module-level so tests can replace it and run without real waiting.
sleep = time.sleep


def retry(
    on: tuple[type[BaseException], ...],
    attempts: int = 0,
    delay: float = 0.0,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry the wrapped call when it raises one of `on`.

    attempts: total attempts including the first. 0 means keep trying until the
        call succeeds; processor timeouts are transient, so callers on the charge
        path use the default.
    delay: seconds to wait between attempts.
    """

    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            attempt = 1
            while True:
                try:
                    return fn(*args, **kwargs)
                except on as exc:
                    if attempts and attempt >= attempts:
                        raise
                    RETRIES.labels(fn=fn.__qualname__).inc()
                    log.warning(
                        "retrying after transient error",
                        event="retry",
                        fn=fn.__qualname__,
                        attempt=attempt,
                        error=type(exc).__name__,
                    )
                    attempt += 1
                    if delay:
                        sleep(delay)

        return wrapper

    return decorate
