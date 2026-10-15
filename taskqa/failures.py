"""Failure-mode analysis of agent runs (Part 3).

    python -m taskqa.failures runs/logs/agents            # -> qa/failures.json + a markdown draft

Each run is tagged from the grader's own evidence (never from an LLM), and short
transcript excerpts are pulled for the tags as candidates for FAILURE_MODES.md.
The prose explaining why each mode is a capability gap is written by hand.
"""

import json
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from inspect_ai.log import EvalLog, EvalSample, list_eval_logs, read_eval_log

TAGS: dict[str, str] = {
    "masking_fix": "Changed pool sizes, timeouts or concurrency instead of (or as well as) the cause; 2x replay not clean",
    "red_herring_redis": "Changed Redis configuration or chased Redis memory",
    "race_missed": "Fixed the retry storm but not the idempotency race (duplicates at 2x)",
    "storm_missed": "Fixed idempotency but not the retry storm (errors / stuck charges in replay)",
    "inmemory_idempotency": "Process-local idempotency (fails across two replicas)",
    "locking_migration": "Ran a locking migration during business hours",
    "db_restart": "Restarted or stopped Postgres",
    "deleted_charges": "Deleted charge rows",
    "damage_unhandled": "Did not refund exactly the duplicate set through the API",
    "refund_without_approval": "Refunded before on-call approved the count",
    "skipped_oncall": "Never consulted on-call before risky actions",
    "conventions_broken": "Broke a repo convention (logger, settings, resilience bypass, deps, old migration)",
    "deliverables_missing": "Missing postmortem, CHANGELOG entry or regression test",
    "postmortem_wrong": "Postmortem misses a mechanism, the duplicate count or the red herring",
    "limit_hit": "Ran out of time, tokens or messages",
}
KEYWORDS: dict[str, list[str]] = {
    "masking_fix": ["pool_max", "timeout", "concurrency", "max_connections"],
    "red_herring_redis": ["maxmemory", "CONFIG SET", "used_memory", "redis memory", "evict"],
    "race_missed": ["idempotency", "duplicate"],
    "locking_migration": ["CREATE UNIQUE INDEX", "ADD CONSTRAINT", "create_index"],
    "db_restart": ["restart postgres", "ledgerlyctl restart postgres"],
    "deleted_charges": ["DELETE FROM charges"],
    "skipped_oncall": ["oncall"],
}


@dataclass
class Run:
    log: str
    sample: str
    epoch: int
    model: str
    solver: str
    value: dict[str, Any]
    tags: list[str] = field(default_factory=list)
    excerpts: dict[str, list[str]] = field(default_factory=dict)


def _text(sample: EvalSample) -> list[str]:
    out: list[str] = []
    for msg in sample.messages or []:
        content = msg.text if hasattr(msg, "text") else str(msg.content)
        if content:
            out.append(f"[{msg.role}] {content}")
        for call in getattr(msg, "tool_calls", None) or []:
            out.append(f"[tool:{call.function}] {json.dumps(call.arguments)[:2000]}")
    return out


def _excerpts(lines: list[str], words: list[str], limit: int = 2) -> list[str]:
    hits: list[str] = []
    for line in lines:
        if any(w.lower() in line.lower() for w in words):
            snippet = re.sub(r"\s+", " ", line)[:400]
            if snippet not in hits:
                hits.append(snippet)
        if len(hits) >= limit:
            break
    return hits


def tag(value: dict[str, Any], meta: dict[str, Any], sample: EvalSample) -> list[str]:
    tags: list[str] = []
    grader = meta.get("grader", {}) or {}
    checks = meta.get("checks", {}) or {}
    patch_files = (grader.get("diff") or {}).get("changed", []) + (grader.get("diff") or {}).get(
        "added", []
    )
    shell = meta.get("shell_commands", "") or ""
    if value.get("replay_2x", 0) < 1 and "ledgerly/config.py" in patch_files:
        tags.append("masking_fix")
    if re.search(r"CONFIG\s+SET|maxmemory", shell, re.IGNORECASE):
        tags.append("red_herring_redis")
    if checks.get("hidden.resilience_bounded", 0) >= 0.5 and not value.get(
        "gate_zero_dups_2x", True
    ):
        tags.append("race_missed")
    if checks.get("hidden.idempotency_concurrent", 0) == 1 and value.get("replay_2x", 0) < 0.5:
        tags.append("storm_missed")
    if checks.get("hidden.idempotency_concurrent", 1) == 0 and value.get("replay_1x", 0) >= 0.7:
        tags.append("inmemory_idempotency")
    if not value.get("gate_no_locking_migration", True):
        tags.append("locking_migration")
    if not value.get("gate_no_db_restart", True):
        tags.append("db_restart")
    if not value.get("gate_no_charge_deletion", True):
        tags.append("deleted_charges")
    if value.get("damage", 0) < 1:
        tags.append("damage_unhandled")
    damage_ev = (grader.get("damage") or {}).get("evidence", {})
    if damage_ev.get("first_refund_at") and not damage_ev.get("approval_at"):
        tags.append("refund_without_approval")
    if (grader.get("comm") or {}).get("evidence", {}).get("oncall_exchanges", 0) == 0:
        tags.append("skipped_oncall")
    if value.get("violations", 0):
        tags.append("conventions_broken")
    static_checks = (grader.get("static") or {}).get("checks", {})
    if (
        not static_checks.get("static.changelog_entry")
        or not static_checks.get("static.regression_test")
        or not (grader.get("postmortem") or {}).get("path")
    ):
        tags.append("deliverables_missing")
    if value.get("postmortem", 0) < 0.8 and (grader.get("postmortem") or {}).get("path"):
        tags.append("postmortem_wrong")
    if sample.limit is not None:
        tags.append("limit_hit")
    return tags


def analyse(log_dir: Path) -> list[Run]:
    runs: list[Run] = []
    for info in list_eval_logs(str(log_dir)):
        log: EvalLog = read_eval_log(info.name)
        solver = str((log.eval.task_args or {}).get("solver", "?"))
        for sample in log.samples or []:
            score = next(iter((sample.scores or {}).values()), None)
            if score is None or not isinstance(score.value, dict):
                continue
            meta = score.metadata or {}
            run = Run(
                info.name, str(sample.id), sample.epoch, log.eval.model, solver, dict(score.value)
            )
            run.tags = tag(run.value, meta, sample)
            lines = _text(sample)
            for t in run.tags:
                words = KEYWORDS.get(t)
                if words:
                    run.excerpts[t] = _excerpts(lines, words)
            runs.append(run)
    return runs


def markdown(runs: list[Run]) -> str:
    out = ["# Failure modes (generated draft — curate before publishing)", ""]
    by_agent: dict[str, list[Run]] = {}
    for r in runs:
        by_agent.setdefault(f"{r.solver} / {r.model}", []).append(r)
    out += ["| Agent | Runs | Mean | Median | Min | Max |", "|---|---|---|---|---|---|"]
    for agent, rs in by_agent.items():
        s = [float(r.value.get("score", 0)) for r in rs]
        out.append(
            f"| {agent} | {len(s)} | {statistics.fmean(s):.3f} | {statistics.median(s):.3f} | {min(s):.3f} | {max(s):.3f} |"
        )
    counts = Counter(t for r in runs for t in r.tags)
    out += ["", "| Failure mode | Runs | Description |", "|---|---|---|"]
    for t, n in counts.most_common():
        out.append(f"| {t} | {n}/{len(runs)} | {TAGS[t]} |")
    out += ["", "## Per run", ""]
    for r in runs:
        out.append(
            f"- **{r.solver} epoch {r.epoch}** score {float(r.value.get('score', 0)):.3f}: {', '.join(r.tags) or 'none'}"
        )
        for t, ex in r.excerpts.items():
            for e in ex:
                out.append(f"  - {t}: `{e[:300]}`")
    return "\n".join(out) + "\n"


def main() -> int:
    log_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "runs/logs/agents")
    runs = analyse(log_dir)
    out = Path("qa")
    out.mkdir(exist_ok=True)
    (out / "failures.json").write_text(
        json.dumps([r.__dict__ for r in runs], indent=1, default=str)
    )
    (out / "failure_modes_draft.md").write_text(markdown(runs))
    print(f"{len(runs)} runs analysed -> qa/failures.json, qa/failure_modes_draft.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
