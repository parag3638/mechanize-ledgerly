"""Generate a seeded load profile.

    python task/profiles/gen.py --seed 4242 --rate 10 --duration 60 --out task/profiles/public.json

Arrivals are Poisson at `rate` charges/s. Each event is one client request
stream for one Idempotency-Key:
- single: one request (the client retries it on timeout or 5xx, same key)
- double: the client fires the same request twice within 2 milliseconds
  (the mobile SDK hedges on two connections), both with the same key.
"""

import argparse
import json
import random
from pathlib import Path

CUSTOMERS = 40
DOUBLE_SHARE = 0.08


def generate(
    seed: int, rate: float, duration: float, double_share: float = DOUBLE_SHARE
) -> dict[str, object]:
    rng = random.Random(seed)
    events: list[dict[str, object]] = []
    t = 0.0
    n = 0
    while True:
        t += rng.expovariate(rate)
        if t >= duration:
            break
        n += 1
        events.append(
            {
                "t": round(t, 4),
                "n": n,
                "customer": f"cust_{rng.randint(1, CUSTOMERS):03d}",
                "amount_cents": int(rng.lognormvariate(8.0, 0.9)) + 100,
                "currency": "USD",
                "mode": "double" if rng.random() < double_share else "single",
                "jitter_ms": round(rng.uniform(0, 2), 2),
            }
        )
    return {
        "meta": {
            "seed": seed,
            "rate": rate,
            "duration_s": duration,
            "customers": CUSTOMERS,
            "double_share": double_share,
            "events": len(events),
        },
        "events": events,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--rate", type=float, required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--double-share", type=float, default=DOUBLE_SHARE)
    args = parser.parse_args()
    profile = generate(args.seed, args.rate, args.duration, args.double_share)
    args.out.write_text(json.dumps(profile, separators=(",", ":")) + "\n")
    meta = profile["meta"]
    print(f"wrote {args.out}: {meta}")


if __name__ == "__main__":
    main()
