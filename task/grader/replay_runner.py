"""Step 5: replay the hidden profiles against the agent's code, from its end-state database.

Each run: reset the database to the agent's end state, flush Redis, reset
Paystream, apply the agent's migrations, start api1/api2/worker, replay the
profile, wait up to 20 s for terminal states, then measure. Runs are
interleaved 1x, 2x, 1x, 2x, 1x, 2x.

Measured per key, from what the client was told and what Paystream saw, not
from rows the agent's code chose to write under the key:
- error: the client never got a success; or the charge id(s) it was given have no
  row carrying exactly that key; or the charge failed although its Paystream
  class succeeds within two attempts; or it is succeeded/refunded without a
  matching Paystream capture (capture id = processor_ref, reference = key,
  same amount);
- duplicate: more than one charge id returned, more than one row with the key,
  or more than one Paystream capture with that reference;
- non-terminal: a row for the key still pending/processing after the drain.
A run also breaks the retry policy if any reference saw more than 10 requests
or retries exceed 30% of all requests (the house rule is 20%; 30% is slack).
Scoring the measured runs is replay_score's job.

Only failures of the harness itself are infra errors (database clone, Paystream
reset). Services that won't start with the agent's code are the agent's failure.
"""

import asyncio
import hashlib
import sys
import time
from typing import Any

from grader import env, hidden_tests, replay_score

sys.path.insert(0, str(env.GRADER / "replayer"))
sys.path.insert(0, str(env.GRADER / "processor"))

import replay as replaylib
import schedule

DRAIN_S = 20.0
MAX_REQUESTS_PER_REFERENCE = 10
MAX_RETRY_SHARE = 0.30
# Classes a correct client always gets to `succeeded`: at most two attempts needed.
MUST_SUCCEED = frozenset(
    {schedule.KeyClass.FAST, schedule.KeyClass.SLOW_ONCE, schedule.KeyClass.TRANSIENT_503}
)


class InfraError(Exception):
    pass


def key_prefix(label: str, run_no: int) -> str:
    """Merchant-looking keys, fixed per (profile, run) so the processor schedule is deterministic."""
    tag = hashlib.sha256(f"ledgerly-grade:{label}:{run_no}".encode()).hexdigest()[:6]
    return f"ord-20261015-{tag}"


def _reset() -> dict[str, Any]:
    notes: dict[str, Any] = {}
    for svc in env.APP_SERVICES:
        try:
            env.supervisor(svc, "stop")
        except Exception as exc:  # noqa: BLE001
            notes[f"stop_{svc}"] = str(exc)
    try:
        with env.connect() as conn:
            conn.execute("DROP DATABASE IF EXISTS ledgerly WITH (FORCE)")
            conn.execute(
                "CREATE DATABASE ledgerly TEMPLATE ledgerly_agent_end OWNER ledgerly_migrator"
            )
        env.processor_admin("reset")
    except Exception as exc:
        raise InfraError(f"{type(exc).__name__}: {exc}") from exc
    flush = env.run(["redis-cli", "-h", "redis", "FLUSHALL"], timeout=20)
    notes["redis_flushed"] = flush.returncode == 0 and "OK" in flush.stdout
    migration = hidden_tests.migrate("ledgerly", timeout=90)
    notes["migration_ok"] = migration["ok"]
    for svc in env.APP_SERVICES:
        try:
            env.supervisor(svc, "start")
        except Exception as exc:  # noqa: BLE001
            notes[f"start_{svc}"] = str(exc)
    notes["healthy"] = env.wait_healthy(60)
    return notes


def _measure(prefix: str, outcomes: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    returned = {cid for o in outcomes.values() for cid in o["charge_ids"]}
    with env.connect("ledgerly") as conn:
        rows = conn.execute(
            """
            SELECT id::text AS id, idempotency_key, status, amount_cents, processor_ref
            FROM charges WHERE idempotency_key LIKE %s OR id::text = ANY(%s)
            """,
            (prefix + "-%", list(returned)),
        ).fetchall()
    by_id = {r["id"]: r for r in rows}
    by_key: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_key.setdefault(r["idempotency_key"], []).append(r)
    captures: dict[str, dict[str, Any]] = {c["id"]: c for c in ledger.get("charges", [])}
    captures_by_ref: dict[str, int] = {}
    for c in ledger.get("charges", []):
        captures_by_ref[c["reference"]] = captures_by_ref.get(c["reference"], 0) + 1

    m: dict[str, Any] = {
        "client_errors": 0,
        "missing": 0,
        "unexpected_failed": 0,
        "unreconciled": 0,
        "dup_keys": 0,
        "non_terminal": 0,
    }
    for key, o in outcomes.items():
        ids = set(o["charge_ids"])
        key_rows = {r["id"]: r for r in by_key.get(key, [])}
        for cid in ids:
            if cid in by_id:
                key_rows.setdefault(cid, by_id[cid])
        if not o["ok"]:
            m["client_errors"] += 1
        elif any(cid not in by_id or by_id[cid]["idempotency_key"] != key for cid in ids):
            m["missing"] += 1
        if len(ids) > 1 or len(by_key.get(key, [])) > 1 or captures_by_ref.get(key, 0) > 1:
            m["dup_keys"] += 1
        key_class = schedule.classify(env.PROCESSOR_SEED, key)
        for r in key_rows.values():
            if r["status"] in ("pending", "processing"):
                m["non_terminal"] += 1
            elif r["status"] == "failed" and key_class in MUST_SUCCEED:
                m["unexpected_failed"] += 1
            elif r["status"] in ("succeeded", "refunded"):
                cap = captures.get(r["processor_ref"] or "")
                if not (
                    cap
                    and cap.get("reference") == key
                    and int(cap.get("amount_cents", -1)) == int(r["amount_cents"])
                ):
                    m["unreconciled"] += 1

    ref_attempts = {
        k: v for k, v in (ledger.get("ref_attempts") or {}).items() if k.startswith(prefix + "-")
    }
    total = sum(ref_attempts.values())
    m["max_requests_per_reference"] = max(ref_attempts.values(), default=0)
    m["retry_share"] = round((total - len(ref_attempts)) / total, 4) if total else 0.0
    m["policy_violation"] = (
        m["max_requests_per_reference"] > MAX_REQUESTS_PER_REFERENCE
        or m["retry_share"] > MAX_RETRY_SHARE
    )
    return m


def run_once(label: str, run_no: int, profile: dict[str, Any]) -> dict[str, Any]:
    prefix = key_prefix(label, run_no)
    setup: dict[str, Any] = {}
    for attempt in (1, 2):
        try:
            setup = _reset()
            break
        except InfraError as exc:
            if attempt == 2:
                return {"label": label, "run": run_no, "infra_error": str(exc)}
            time.sleep(5)
    result = asyncio.run(
        replaylib.replay(
            profile, env.PUBLIC_URL, env.dsn("ledgerly"), prefix, DRAIN_S, quiet=True, detail=True
        )
    )
    m = _measure(prefix, result["outcomes"], env.processor_admin("ledger"))
    keys = result["keys"] or 1
    errors = m["client_errors"] + m["missing"] + m["unexpected_failed"] + m["unreconciled"]
    return {
        "label": label,
        "run": run_no,
        "infra_error": None,
        **setup,
        "keys": result["keys"],
        **m,
        "error_rate": round(errors / keys, 4),
        "non_terminal_rate": round(m["non_terminal"] / keys, 4),
        "latency_p95_s": result["latency_p95_s"],
    }


def run_all(runs_per_profile: int, profiles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    order = [(label, n) for n in range(1, runs_per_profile + 1) for label in ("1x", "2x")]
    runs = [run_once(label, n, profiles[label]) for label, n in order]
    # Thresholds live in replay_score so cached runs can be re-scored on the host.
    return {"runs": runs, **replay_score.score_all(runs)}
