"""Replay thresholds: from the measured runs to the replay components and the 2x gate.

Pure functions of the per-run measurements (replay_runner._measure). They run in
the grader container at step 5, and on the host when taskqa re-scores cached
gradings, so a threshold change never needs the runs to be repeated.
"""

import statistics
from typing import Any

ERRORS_FULL = 0.01
# One bound for half error credit, for "serving" (terminal and duplicate credit) and for the
# 2x gate. Calibrated fixes measure 0.0; with retries off, the charges Paystream accepts on
# a second attempt fail (about 4.5% of keys), which must not earn credit.
ERRORS_SERVING = 0.03
NON_TERMINAL_HALF = 0.02


def _band(value: float, full: float, half: float) -> float:
    if value <= full:
        return 1.0
    if value <= half:
        return 0.5
    return 0.0


def score_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Median of each measure over the successful runs, then thresholds."""
    ok = [r for r in runs if not r.get("infra_error")]
    if len(ok) < 2:
        return {"score": 0.0, "infra_error": True, "runs_ok": len(ok)}
    err = statistics.median(r["error_rate"] for r in ok)
    term = statistics.median(r["non_terminal_rate"] for r in ok)
    dups = statistics.median(r["dup_keys"] for r in ok)
    policy_ok = sum(not r["policy_violation"] for r in ok) * 2 > len(ok)
    serving = err <= ERRORS_SERVING
    parts = {
        "errors": _band(err, ERRORS_FULL, ERRORS_SERVING) if policy_ok else 0.0,
        # Like duplicates, "every charge terminal" only means something while the service answers.
        "terminal": _band(term, 0.0, NON_TERMINAL_HALF) if serving else 0.0,
        "duplicates": 1.0 if (dups == 0 and serving) else 0.0,
    }
    score = 0.4 * parts["errors"] + 0.3 * parts["terminal"] + 0.3 * parts["duplicates"]
    return {
        "score": round(score, 4),
        "parts": parts,
        "median_error_rate": err,
        "median_non_terminal_rate": term,
        "median_dup_keys": dups,
        "retry_policy_ok": policy_ok,
        "infra_error": False,
        "runs_ok": len(ok),
    }


def zero_dups_gate(two_x_runs: list[dict[str, Any]]) -> bool:
    """Majority of 2x runs: no duplicate keys while answering enough requests correctly."""
    ok = [r for r in two_x_runs if not r.get("infra_error")]
    clean = sum(r["dup_keys"] == 0 and r["error_rate"] <= ERRORS_SERVING for r in ok)
    return bool(ok) and clean * 2 > len(ok)


def score_all(runs: list[dict[str, Any]]) -> dict[str, Any]:
    by_label = {label: [r for r in runs if r["label"] == label] for label in ("1x", "2x")}
    return {
        "replay.1x": score_runs(by_label["1x"]),
        "replay.2x": score_runs(by_label["2x"]),
        "gate.zero_dups_2x": zero_dups_gate(by_label["2x"]),
    }
