"""Deterministic behaviour of the mock payment processor.

Every charge reference (the client's Idempotency-Key) falls into one class,
decided by sha256(seed:reference). The class fixes what each attempt does, so a
replay of the same keys against the same seed always meets the same latencies
and errors. Nothing here depends on wall-clock time or randomness.
"""

import hashlib
from dataclasses import dataclass
from enum import StrEnum


class KeyClass(StrEnum):
    FAST = "fast"
    SLOW_ONCE = "slow_once"  # attempt 1 stalls past the client timeout, then fast
    SLOW_TWICE = "slow_twice"  # attempts 1-2 stall, then fast
    TRANSIENT_503 = "transient_503"  # attempt 1 returns 503, then fast
    DECLINED = "declined"  # 402 on every attempt: expected terminal state is failed
    HANG = "hang"  # every attempt stalls, then 504: expected terminal state is failed


# Cumulative shares, in basis points (10_000 = 100%).
_SHARES: tuple[tuple[KeyClass, int], ...] = (
    (KeyClass.HANG, 600),
    (KeyClass.SLOW_ONCE, 300),
    (KeyClass.SLOW_TWICE, 100),
    (KeyClass.TRANSIENT_503, 150),
    (KeyClass.DECLINED, 50),
    (KeyClass.FAST, 8800),
)

SLOW_S = 1.3  # past the 1.0 s client timeout
HANG_S = 5.0
FAST_MIN_S = 0.04
FAST_SPAN_S = 0.08

# Classes whose charge must end `failed` even with a correct client.
EXPECTED_FAILED = frozenset({KeyClass.DECLINED, KeyClass.HANG})


@dataclass(frozen=True)
class Behaviour:
    delay_s: float
    outcome: str  # "ok" | "declined" | "unavailable" (503) | "gateway_timeout" (504)


def _u(seed: str, *parts: object) -> int:
    digest = hashlib.sha256(":".join([seed, *map(str, parts)]).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def classify(seed: str, reference: str) -> KeyClass:
    bucket = _u(seed, "class", reference) % 10_000
    upper = 0
    for key_class, share in _SHARES:
        upper += share
        if bucket < upper:
            return key_class
    return KeyClass.FAST


def behaviour(seed: str, reference: str, attempt: int, hang_enabled: bool = True) -> Behaviour:
    """What the processor does on the `attempt`-th request (1-based) for one charge.

    hang_enabled=False models Paystream after its slow keys recovered (baseline capture only).
    """
    key_class = classify(seed, reference)
    if key_class is KeyClass.HANG and not hang_enabled:
        key_class = KeyClass.FAST
    fast = Behaviour(
        FAST_MIN_S + FAST_SPAN_S * (_u(seed, "lat", reference, attempt) % 1000) / 1000, "ok"
    )
    match key_class:
        case KeyClass.FAST:
            return fast
        case KeyClass.SLOW_ONCE:
            return Behaviour(SLOW_S, "gateway_timeout") if attempt == 1 else fast
        case KeyClass.SLOW_TWICE:
            return Behaviour(SLOW_S, "gateway_timeout") if attempt <= 2 else fast
        case KeyClass.TRANSIENT_503:
            return Behaviour(0.05, "unavailable") if attempt == 1 else fast
        case KeyClass.DECLINED:
            return Behaviour(fast.delay_s, "declined")
        case KeyClass.HANG:
            return Behaviour(HANG_S, "gateway_timeout")
