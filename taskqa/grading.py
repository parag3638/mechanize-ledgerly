"""Grade submissions through the task's own Inspect scorer, with a resumable cache.

A submission is a directory with patch.diff and/or actions.sh (and expect.json
for probes). Results are cached in <out>/scores.jsonl keyed by a hash of the
submission's files, the container-side grader source, the replay run count and
a repeat index, so an interrupted `make qa` resumes where it stopped.

Scoring that happens on the host (replay thresholds, aggregation, the rubric)
is not part of the key: every cached row is re-scored from its raw measurements
when it is read, exactly as the scorer would score them now.
"""

import asyncio
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GRADER_SOURCES = [
    ROOT / "task" / "grader",
    ROOT / "task" / "hidden",
    ROOT / "task" / "compose.yaml",
    ROOT / "task" / "processor",
    ROOT / "task" / "replayer",
    ROOT / "ledgerly",
]
# Pure functions of the grader's raw result; re-applied to cached rows (see rescore).
HOST_SCORING = {
    ROOT / "task" / "grader" / "replay_score.py",
    ROOT / "task" / "grader" / "aggregate.py",
    ROOT / "task" / "grader" / "rubric.py",
}


@dataclass(frozen=True)
class Graded:
    name: str
    repeat: int
    value: dict[str, Any]
    explanation: str
    metadata: dict[str, Any]
    log: str


def _hash_paths(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for root in paths:
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for f in files:
            if "__pycache__" in f.parts or f.suffix in (".pyc",) or ".pytest_cache" in f.parts:
                continue
            if f in HOST_SCORING:
                continue
            h.update(str(f.relative_to(ROOT)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def grader_hash() -> str:
    return _hash_paths(GRADER_SOURCES)


def rescore(row: dict[str, Any]) -> dict[str, Any]:
    """Re-apply the current host-side scoring to a cached grading's raw result.

    The replay components are recomputed from the per-run measurements, the
    rubric is re-run when a rubric model is configured (Inspect caches it by
    content), then everything is aggregated as the scorer does.
    """
    meta = row.get("metadata") or {}
    result = meta.get("grader")
    if not isinstance(result, dict):  # the grader crashed: nothing to re-score
        return row
    sys.path.insert(0, str(ROOT / "task"))
    from grader import aggregate, replay_score, rubric

    result = dict(result)
    replay = result.get("replay")
    if isinstance(replay, dict) and replay.get("runs"):
        result["replay"] = {**replay, **replay_score.score_all(replay["runs"])}
    verdict = meta.get("rubric") or {}
    if rubric.rubric_model_name() is not None:
        facts = json.loads((ROOT / "task" / "hidden" / "baseline_facts.json").read_text())
        text = (result.get("postmortem") or {}).get("text", "")
        verdict = asyncio.run(rubric.score_postmortem(text, facts))
    agg = aggregate.score(result, verdict)
    return {
        **row,
        "value": agg["value"],
        "explanation": aggregate.explanation(agg),
        "metadata": {
            **meta,
            "checks": agg["checks"],
            "violations": agg["violations"],
            "gates": agg["gates"],
            "rubric": verdict,
            "grader": result,
        },
    }


def submission_hash(path: Path) -> str:
    return _hash_paths([path]) if path.exists() and any(path.iterdir()) else "empty"


class Cache:
    def __init__(self, out: Path) -> None:
        self.path = out / "scores.jsonl"
        self.rows: dict[str, dict[str, Any]] = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                row = json.loads(line)
                self.rows[row["key"]] = row

    def key(self, sub: Path, repeat: int, replay_runs: int) -> str:
        return f"{submission_hash(sub)}:{grader_hash()}:{replay_runs}:{repeat}"

    def get(self, key: str) -> dict[str, Any] | None:
        return self.rows.get(key)

    def put(self, key: str, row: dict[str, Any]) -> None:
        row = {"key": key, **row}
        self.rows[key] = row
        with self.path.open("a") as fh:
            fh.write(json.dumps(row, default=str) + "\n")


def grade(
    subs: list[tuple[str, Path, int]], out: Path, replay_runs: int, log_dir: Path
) -> list[Graded]:
    """subs: (name, dir, repeat). Grades what isn't cached, one Inspect eval for the batch."""
    from inspect_ai import eval as inspect_eval

    cache = Cache(out)
    todo = [(n, d, r) for n, d, r in subs if cache.get(cache.key(d, r, replay_runs)) is None]
    if todo:
        logs = inspect_eval(
            os.path.relpath(ROOT / "task" / "ledgerly_incident.py"),  # Inspect globs task specs
            model="mockllm/model",
            task_args={
                "submissions": ",".join(str(d) for _, d, _ in todo),
                "replay_runs": replay_runs,
            },
            max_sandboxes=1,
            log_dir=str(log_dir),
            fail_on_error=False,
        )
        log = logs[0]
        samples = {s.id: s for s in (log.samples or [])}
        for i, (name, d, repeat) in enumerate(todo, start=1):
            sample = samples.get(f"{i:02d}-{d.name}")
            score = next(iter((sample.scores or {}).values()), None) if sample else None
            row = {
                "name": name,
                "repeat": repeat,
                "value": score.value
                if score and isinstance(score.value, dict)
                else {"score": 0.0, "infra_error": True},
                "explanation": (
                    score.explanation
                    if score
                    else f"no score: {sample.error if sample else 'missing'}"
                )
                or "",
                "metadata": score.metadata if score else {},
                "log": log.location,
            }
            cache.put(cache.key(d, repeat, replay_runs), row)
    results: list[Graded] = []
    for name, d, repeat in subs:
        row = cache.get(cache.key(d, repeat, replay_runs))
        assert row is not None
        row = rescore(row)
        results.append(
            Graded(
                name,
                repeat,
                row["value"],
                row["explanation"],
                row.get("metadata") or {},
                row["log"],
            )
        )
    return results
