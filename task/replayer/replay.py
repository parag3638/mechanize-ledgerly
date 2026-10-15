"""Replay a load profile against Ledgerly and measure the outcome.

Used by `make loadtest` in the Ledgerly repo (as tools/replaylib.py) and by the
grader. Client behaviour, identical for both:
- POST /charges with the event's Idempotency-Key; timeout 3 s.
- On a timeout, connection error, 429 or 5xx: wait 0.5 s and retry with the
  same key, up to 3 attempts in total.
- "double" events send the same request twice, a few milliseconds apart.

Outcomes are measured from the database, not from client-side timings:
duplicate keys, charges not in a terminal state after the drain window, and
keys for which the client never got a successful response.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psycopg

CLIENT_TIMEOUT_S = 3.0
CLIENT_ATTEMPTS = 3
CLIENT_RETRY_WAIT_S = 0.5
TERMINAL = ("succeeded", "failed", "refunded")


@dataclass
class KeyOutcome:
    key: str
    ok: bool = False
    status: int | None = None
    attempts: int = 0
    charge_ids: set[str] = field(default_factory=set[str])
    latency_s: float | None = None


@dataclass
class Tally:
    sent: int = 0
    ok: int = 0
    failed: int = 0


async def _post_once(
    client: httpx.AsyncClient, key: str, body: dict[str, Any], out: KeyOutcome, tally: Tally
) -> None:
    started = time.monotonic()
    for attempt in range(1, CLIENT_ATTEMPTS + 1):
        out.attempts += 1
        tally.sent += 1
        try:
            resp = await client.post(
                "/charges", json=body, headers={"Idempotency-Key": key}, timeout=CLIENT_TIMEOUT_S
            )
        except httpx.HTTPError:
            resp = None
        if resp is not None:
            out.status = resp.status_code
            if resp.status_code in (200, 201):
                out.ok = True
                out.charge_ids.add(resp.json()["id"])
                out.latency_s = time.monotonic() - started
                return
            if resp.status_code < 500 and resp.status_code != 429:
                return  # a client error; retrying won't help
        if attempt < CLIENT_ATTEMPTS:
            await asyncio.sleep(CLIENT_RETRY_WAIT_S)


async def _run_event(
    client: httpx.AsyncClient, ev: dict[str, Any], key: str, out: KeyOutcome, tally: Tally
) -> None:
    body = {
        "customer_id": ev["customer"],
        "amount_cents": ev["amount_cents"],
        "currency": ev["currency"],
    }
    if ev["mode"] == "double":

        async def second() -> None:
            await asyncio.sleep(float(ev.get("jitter_ms", 0)) / 1000)
            await _post_once(client, key, body, out, tally)

        await asyncio.gather(_post_once(client, key, body, out, tally), second())
    else:
        await _post_once(client, key, body, out, tally)
    if out.ok:
        tally.ok += 1
    else:
        tally.failed += 1


def _db_counts(dsn: str, prefix: str) -> dict[str, Any]:
    with psycopg.connect(dsn, connect_timeout=5) as conn:
        rows = conn.execute(
            """
            SELECT idempotency_key, status, count(*) FROM charges
            WHERE idempotency_key LIKE %s GROUP BY idempotency_key, status
            """,
            (prefix + "-%",),
        ).fetchall()
    per_key: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for key, status, n in rows:
        per_key[key] = per_key.get(key, 0) + n
        by_status[status] = by_status.get(status, 0) + n
    dup_keys = sum(1 for n in per_key.values() if n > 1)
    dup_rows = sum(n - 1 for n in per_key.values() if n > 1)
    non_terminal = sum(n for s, n in by_status.items() if s not in TERMINAL)
    return {
        "rows": sum(by_status.values()),
        "keys_with_rows": len(per_key),
        "by_status": by_status,
        "dup_keys": dup_keys,
        "dup_rows": dup_rows,
        "non_terminal": non_terminal,
    }


async def _drain(dsn: str, prefix: str, timeout_s: float, quiet: bool) -> float:
    started = time.monotonic()
    while True:
        counts = await asyncio.to_thread(_db_counts, dsn, prefix)
        waited = time.monotonic() - started
        if counts["non_terminal"] == 0 or waited >= timeout_s:
            return waited
        if not quiet:
            print(f"  drain {waited:5.1f}s  non_terminal={counts['non_terminal']}", flush=True)
        await asyncio.sleep(1.0)


async def replay(
    profile: dict[str, Any],
    base_url: str,
    dsn: str,
    prefix: str,
    drain_s: float,
    quiet: bool = False,
    detail: bool = False,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = profile["events"]
    outcomes: dict[str, KeyOutcome] = {}
    tally = Tally()
    limits = httpx.Limits(max_connections=1000, max_keepalive_connections=200)
    loop = asyncio.get_running_loop()
    start = loop.time()

    async def report() -> None:
        while True:
            await asyncio.sleep(1.0)
            print(
                f"  t={loop.time() - start:5.0f}s  keys={len(outcomes):5d}  ok={tally.ok:5d}  "
                f"client_errors={tally.failed:5d}  requests={tally.sent:6d}",
                flush=True,
            )

    reporter = None if quiet else asyncio.create_task(report())
    async with httpx.AsyncClient(base_url=base_url, limits=limits) as client:
        tasks: list[asyncio.Task[None]] = []
        for ev in events:
            delay = start + float(ev["t"]) - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            key = f"{prefix}-{ev['n']:05d}"
            outcomes[key] = KeyOutcome(key)
            tasks.append(asyncio.create_task(_run_event(client, ev, key, outcomes[key], tally)))
        await asyncio.gather(*tasks)
    if reporter is not None:
        reporter.cancel()
    traffic_s = loop.time() - start
    drained_s = await _drain(dsn, prefix, drain_s, quiet)
    counts = _db_counts(dsn, prefix)

    keys = len(outcomes)
    client_errors = sum(1 for o in outcomes.values() if not o.ok)
    latencies = sorted(o.latency_s for o in outcomes.values() if o.latency_s is not None)

    def pct(p: float) -> float | None:
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, int(p * len(latencies)))], 3)

    return {
        "prefix": prefix,
        "profile": profile.get("meta", {}),
        "keys": keys,
        "requests": tally.sent,
        "client_ok": keys - client_errors,
        "client_errors": client_errors,
        "error_rate": round(client_errors / keys, 4) if keys else 0.0,
        "non_terminal_rate": round(counts["non_terminal"] / keys, 4) if keys else 0.0,
        "latency_p50_s": pct(0.50),
        "latency_p95_s": pct(0.95),
        "latency_mean_s": round(statistics.fmean(latencies), 3) if latencies else None,
        "traffic_s": round(traffic_s, 1),
        "drain_s": round(drained_s, 1),
        **counts,
        **(
            {
                "outcomes": {
                    k: {"ok": o.ok, "status": o.status, "charge_ids": sorted(o.charge_ids)}
                    for k, o in outcomes.items()
                }
            }
            if detail
            else {}
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--dsn", required=True, help="Postgres DSN with SELECT on charges")
    parser.add_argument("--prefix", default=f"lt-{int(time.time())}")
    parser.add_argument(
        "--drain", type=float, default=20.0, help="seconds to wait for terminal states"
    )
    parser.add_argument("--out", type=Path, help="write the summary JSON here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    profile = json.loads(args.profile.read_text())
    meta = profile.get("meta", {})
    if not args.quiet:
        print(
            f"replaying {meta.get('events')} charges over {meta.get('duration_s')}s "
            f"({meta.get('rate')}/s) against {args.base_url}, keys {args.prefix}-*",
            flush=True,
        )
    result = asyncio.run(
        replay(profile, args.base_url, args.dsn, args.prefix, args.drain, args.quiet)
    )
    if args.out:
        args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
