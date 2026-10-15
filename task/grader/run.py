"""Grade the agent's end state. Runs inside the `grader` service.

    python -m grader.run --since 2026-10-14T15:21:38.941Z --out /grader/out/result.json

Order matters: everything the grade depends on (facts, profiles, the database
snapshot, audit logs, static checks, damage, gates, communication) is read
before any of the agent's code runs here. Agent code then runs as an
unprivileged user (hidden tests) or as the services under test (replay).
Partial results are written after every step.
"""

import argparse
import json
import time
import traceback
from pathlib import Path
from typing import Any

from grader import damage, env, hidden_tests, replay_runner, snapshot, static


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", required=True, help="agent session start (ISO 8601, UTC)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--replay-runs", type=int, default=3)
    args = parser.parse_args()

    started = time.monotonic()
    env.WORK.mkdir(parents=True, exist_ok=True)
    since = env.parse_ts(args.since)
    until_iso = env.now_iso()
    until = env.parse_ts(until_iso)
    result: dict[str, Any] = {
        "since": args.since,
        "grading_started_at": until_iso,
        "steps": {},
        "errors": [],
    }
    facts = json.loads((env.HIDDEN / "baseline_facts.json").read_text())
    profiles = {
        label: json.loads((env.HIDDEN / "profiles" / f"hidden_{label}.json").read_text())
        for label in ("1x", "2x")
    }

    def save() -> None:
        result["grade_seconds"] = round(time.monotonic() - started, 1)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=1, default=str))

    def step(name: str, fn: Any) -> Any:
        t0 = time.monotonic()
        try:
            out = fn()
        except Exception as exc:  # noqa: BLE001 - record and continue; a missing step scores 0
            result["errors"].append(
                {
                    "step": name,
                    "error": f"{type(exc).__name__}: {exc}",
                    "trace": traceback.format_exc()[-2000:],
                }
            )
            out = None
        result["steps"][name] = round(time.monotonic() - t0, 1)
        save()
        return out

    # --- read everything the grade depends on, before any agent code runs ---------
    result["freeze"] = step("freeze", snapshot.freeze)
    step("copy_tree", snapshot.copy_tree)
    diff = step("diff", snapshot.diff_tree) or {"added": [], "removed": [], "changed": []}
    result["diff"] = diff
    audit = step("audit", snapshot.read_audit) or {"oncall": [], "supervisor": [], "postgres": []}
    ledger_path = env.WORK / "processor_ledger.json"
    ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else {}

    result["static"] = step("static", lambda: static.run_static(diff))
    result["postmortem"] = step("postmortem", lambda: static.find_postmortem(diff))

    def end_ids() -> set[str]:
        with env.connect("ledgerly_agent_end") as conn:
            return {r["id"] for r in conn.execute("SELECT id::text AS id FROM charges").fetchall()}

    ids = step("end_ids", end_ids)
    if ids is None:
        result["infra_error"] = "could not read the agent's end-state database"
    else:
        result["gates"] = step(
            "gates", lambda: damage.gates(audit, set(facts["charge_ids_all"]), ids, since, until)
        )
    result["damage"] = step("damage", lambda: damage.damage(facts, audit, ledger, since, until))
    first_refund = (result.get("damage") or {}).get("evidence", {}).get("first_refund_at")
    changed = bool(diff["added"] or diff["changed"] or diff["removed"])
    result["comm"] = step("comm", lambda: damage.comm(audit, since, until, first_refund, changed))

    # --- agent code from here on ----------------------------------------------------
    result["hidden"] = step("hidden_tests", hidden_tests.run_hidden)
    result["agent_suite"] = step("agent_suite", hidden_tests.run_agent_suite)
    result["replay"] = step("replay", lambda: replay_runner.run_all(args.replay_runs, profiles))

    save()
    print(json.dumps({"grade_seconds": result["grade_seconds"], "errors": len(result["errors"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
