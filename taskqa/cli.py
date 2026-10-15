"""taskqa: prove a grader's properties instead of asserting them.

    python -m taskqa run                       # all checks -> QA_REPORT.md, qa/report.html
    python -m taskqa run --checks knowability,hacks --replay-runs 1

Checks
  1 determinism     same submission graded N times -> identical procedural scores
  2 sanity          unmodified ~0, partial fixes in their bands, monotonic partial credit
  3 hacks           every reward-hack probe < 0.3
  4 fairness        both reference solutions >= 0.9
  5 knowability     every check has a source, every quoted source exists
  6 rubric          LLM rubric std dev over K runs on fixed postmortems <= threshold
  7 interpretation  reasonable alternative readings don't score zero / don't lose credit
"""

import argparse
import asyncio
import hashlib
import itertools
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from taskqa import knowability
from taskqa.grading import Graded, grade

ROOT = Path(__file__).resolve().parents[1]
ALL_CHECKS = (
    "knowability",
    "determinism",
    "sanity",
    "hacks",
    "fairness",
    "interpretation",
    "rubric",
)
PROCEDURAL_EXCLUDE = {"postmortem", "rubric_unavailable", "score", "raw"}
HACK_LIMIT = 0.3
FAIR_MIN = 0.9
RUBRIC_MAX_STD = 0.05
RUBRIC_MAX_RANGE = 0.15


@dataclass
class CheckResult:
    name: str
    passed: bool
    summary: str
    rows: list[dict[str, Any]] = field(default_factory=list)


def _probe_dirs(base: Path, prefix: str) -> list[Path]:
    if not base.exists():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir() and p.name.startswith(prefix))


def _expect(d: Path) -> dict[str, Any]:
    f = d / "expect.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _score(g: Graded) -> float:
    return float(g.value.get("score", 0.0))


def check_knowability() -> CheckResult:
    findings = knowability.audit()
    bad = [f for f in findings if not f.ok]
    rows = [
        {
            "check": f.check,
            "source": f.source,
            "quote": f.quote[:90],
            "ok": f.ok,
            "reason": f.reason,
        }
        for f in findings
    ]
    return CheckResult(
        "knowability", not bad, f"{len(findings) - len(bad)}/{len(findings)} sources verified", rows
    )


def check_determinism(ref: Path, n: int, ctx: dict[str, Any]) -> CheckResult:
    graded = grade(
        [("ref_A", ref, i) for i in range(n)], ctx["out"], ctx["replay_runs"], ctx["logs"]
    )
    procedural = [{k: v for k, v in g.value.items() if k not in PROCEDURAL_EXCLUDE} for g in graded]
    infra = [g for g in graded if g.value.get("infra_error")]
    identical = all(p == procedural[0] for p in procedural)
    rows = [
        {
            "run": g.repeat + 1,
            "score": _score(g),
            **{
                k: g.value.get(k)
                for k in ("replay_1x", "replay_2x", "hidden_tests", "conventions", "damage", "comm")
            },
        }
        for g in graded
    ]
    passed = identical and not infra
    summary = f"{n} gradings of reference A: procedural components {'identical' if identical else 'DIFFER'}"
    if infra:
        summary += f"; {len(infra)} infra errors"
    return CheckResult("determinism", passed, summary, rows)


def check_band_probes(
    name: str, probes: list[Path], ctx: dict[str, Any], limit: float | None = None
) -> tuple[CheckResult, dict[str, float]]:
    graded = grade([(p.name, p, 0) for p in probes], ctx["out"], ctx["replay_runs"], ctx["logs"])
    scores: dict[str, float] = {}
    rows = []
    ok = True
    for p, g in zip(probes, graded, strict=True):
        exp = _expect(p)
        lo, hi = exp.get("band", [0.0, 1.0])
        s = _score(g)
        scores[p.name] = s
        good = (lo <= s <= hi) and (limit is None or s < limit)
        ok &= good
        rows.append(
            {
                "probe": p.name,
                "score": round(s, 3),
                "band": f"[{lo}, {hi}]",
                "ok": good,
                "caught_by": ", ".join(exp.get("caught_by", [])),
                "explanation": g.explanation.splitlines()[0] if g.explanation else "",
            }
        )
    return CheckResult(
        name, ok, f"{sum(r['ok'] for r in rows)}/{len(rows)} probes in band", rows
    ), scores


def check_sanity(ctx: dict[str, Any]) -> CheckResult:
    probes = [
        ROOT / "probes" / "unmodified",
        *_probe_dirs(ctx["refs"] / "probes", "partial_"),
        *_probe_dirs(ctx["refs"] / "probes", "policy_"),
    ]
    res, scores = check_band_probes("sanity", probes, ctx)
    ref_a = grade([("ref_A", ctx["refs"] / "A", 0)], ctx["out"], ctx["replay_runs"], ctx["logs"])[0]
    chain = ["unmodified", "partial_idem_only", "partial_retry_only", "partial_both_no_docs"]
    found = [scores.get(c) for c in chain] + [_score(ref_a)]
    values = [v for v in found if v is not None]
    monotonic = len(values) == len(found) and all(
        b - a >= 0.1 for a, b in itertools.pairwise(values)
    )
    ref_ok = _score(ref_a) >= 0.95
    res.rows.append(
        {
            "probe": "ref_A",
            "score": round(_score(ref_a), 3),
            "band": "[0.95, 1]",
            "ok": ref_ok,
            "caught_by": "",
            "explanation": "",
        }
    )
    res.rows.append(
        {
            "probe": "monotonic chain",
            "score": " < ".join(f"{v:.2f}" if v is not None else "?" for v in found),
            "band": "each step >= 0.1",
            "ok": monotonic,
            "caught_by": " < ".join(chain + ["ref_A"]),
            "explanation": "",
        }
    )
    res.passed = res.passed and monotonic and ref_ok
    res.summary += f"; reference A {_score(ref_a):.3f}; monotonic {'yes' if monotonic else 'NO'}"
    return res


def check_hacks(ctx: dict[str, Any]) -> CheckResult:
    probes = _probe_dirs(ROOT / "probes", "hack_") + _probe_dirs(ctx["refs"] / "probes", "hack_")
    res, scores = check_band_probes("hacks", probes, ctx, limit=HACK_LIMIT)
    worst = max(scores.values(), default=0.0)
    res.summary += f"; highest hack score {worst:.3f} (limit < {HACK_LIMIT})"
    return res


def check_fairness(ctx: dict[str, Any]) -> CheckResult:
    refs = [("ref_A", ctx["refs"] / "A", 0), ("ref_B", ctx["refs"] / "B", 0)]
    graded = grade(refs, ctx["out"], ctx["replay_runs"], ctx["logs"])
    rows = [
        {
            "reference": g.name,
            "score": round(_score(g), 3),
            "ok": _score(g) >= FAIR_MIN,
            "explanation": g.explanation.replace("\n", " | "),
        }
        for g in graded
    ]
    return CheckResult(
        "fairness",
        all(r["ok"] for r in rows),
        " / ".join(f"{r['reference']} {r['score']:.3f}" for r in rows) + f" (min {FAIR_MIN})",
        rows,
    )


def check_interpretation(ctx: dict[str, Any]) -> CheckResult:
    probes = _probe_dirs(ctx["refs"] / "probes", "interp_")
    ref_a = _score(
        grade([("ref_A", ctx["refs"] / "A", 0)], ctx["out"], ctx["replay_runs"], ctx["logs"])[0]
    )
    res, scores = check_band_probes("interpretation", probes, ctx)
    for row in res.rows:
        near = scores[row["probe"]] >= ref_a - 0.05
        row["ok"] = row["ok"] and near
        row["band"] += f" and >= ref A - 0.05 ({ref_a - 0.05:.3f})"
    res.passed = all(r["ok"] for r in res.rows) and bool(res.rows)
    res.summary = (
        f"{sum(r['ok'] for r in res.rows)}/{len(res.rows)} alternative readings keep their credit"
    )
    return res


def check_rubric(k: int, ctx: dict[str, Any]) -> CheckResult:
    sys.path.insert(0, str(ROOT / "task"))
    from grader import rubric

    facts = json.loads((ROOT / "task" / "hidden" / "baseline_facts.json").read_text())
    fixtures = sorted((ctx["refs"] / "postmortems").glob("*.md"))
    if rubric.rubric_model_name() is None:
        return CheckResult(
            "rubric", False, "rubric model not configured (set RUBRIC_MODEL and OPENAI_API_KEY)"
        )
    # Paid API calls: reuse the last measurement unless the rubric, fixtures, model or K changed.
    h = hashlib.sha256(f"{rubric.rubric_model_name()}:{k}".encode())
    for src in [ROOT / "task" / "grader" / "rubric.py", *fixtures]:
        h.update(src.read_bytes())
    saved_path = ctx["out"] / "rubric_variance.json"
    try:
        saved = json.loads(saved_path.read_text())
    except (OSError, json.JSONDecodeError):
        saved = {}
    if saved.get("key") == h.hexdigest():
        return CheckResult(**saved["result"])
    rows = []
    ok = True
    for f in fixtures:
        scores: list[float] = []
        for _ in range(k):
            verdict = asyncio.run(rubric.score_postmortem(f.read_text(), facts, cache=False))
            scores.append(float(verdict["score"] or 0.0))
        sd = statistics.pstdev(scores)
        rng = max(scores) - min(scores)
        good = sd <= RUBRIC_MAX_STD and rng <= RUBRIC_MAX_RANGE
        ok &= good
        rows.append(
            {
                "postmortem": f.name,
                "scores": scores,
                "std": round(sd, 4),
                "range": round(rng, 3),
                "ok": good,
            }
        )
    result = CheckResult(
        "rubric",
        ok and bool(rows),
        f"{len(rows)} postmortems x {k} runs; max std {max((r['std'] for r in rows), default=0):.3f} (limit {RUBRIC_MAX_STD})",
        rows,
    )
    saved_path.write_text(json.dumps({"key": h.hexdigest(), "result": asdict(result)}))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taskqa")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--checks", default=",".join(ALL_CHECKS))
    run.add_argument("--n", type=int, default=5, help="determinism repeats")
    run.add_argument("--k", type=int, default=5, help="rubric repeats")
    run.add_argument("--replay-runs", type=int, default=3)
    run.add_argument("--refs", type=Path, default=ROOT / ".refs")
    run.add_argument("--out", type=Path, default=ROOT / "qa")
    args = parser.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    ctx = {
        "out": args.out,
        "refs": args.refs,
        "replay_runs": args.replay_runs,
        "logs": ROOT / "runs" / "logs" / "qa",
    }
    wanted = [c.strip() for c in args.checks.split(",") if c.strip()]
    results: list[CheckResult] = []
    runners = {
        "knowability": lambda: check_knowability(),
        "determinism": lambda: check_determinism(args.refs / "A", args.n, ctx),
        "sanity": lambda: check_sanity(ctx),
        "hacks": lambda: check_hacks(ctx),
        "fairness": lambda: check_fairness(ctx),
        "interpretation": lambda: check_interpretation(ctx),
        "rubric": lambda: check_rubric(args.k, ctx),
    }
    for name in wanted:
        print(f"== {name}", flush=True)
        result = runners[name]()
        print(f"   {'PASS' if result.passed else 'FAIL'}: {result.summary}", flush=True)
        results.append(result)

    from taskqa import report

    (args.out / "results.json").write_text(
        json.dumps([asdict(r) for r in results], indent=1, default=str)
    )
    report.write_markdown(results, ROOT / "QA_REPORT.md", args)
    report.write_html(results, args.out / "report.html")
    print(f"\nwrote QA_REPORT.md and {args.out / 'report.html'}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
