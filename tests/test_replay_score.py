"""Replay thresholds (task/grader/replay_score.py): band edges, serving, policy, gate majority."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "task"))
import pytest
from grader import replay_score as rs


def run(err=0.0, term=0.0, dups=0, pol=False, infra=False, label="1x"):
    return {
        "label": label,
        "error_rate": err,
        "non_terminal_rate": term,
        "dup_keys": dups,
        "policy_violation": pol,
        **({"infra_error": True} if infra else {}),
    }


def three(**kw):
    return [run(**kw) for _ in range(3)]


def parts(runs):
    return rs.score_runs(runs)["parts"]


def test_constants():
    assert (rs.ERRORS_FULL, rs.ERRORS_SERVING, rs.NON_TERMINAL_HALF) == (0.01, 0.03, 0.02)


@pytest.mark.parametrize(
    "err,exp", [(0.0, 1.0), (0.01, 1.0), (0.0101, 0.5), (0.03, 0.5), (0.0301, 0.0)]
)
def test_error_bands(err, exp):
    assert parts(three(err=err))["errors"] == exp


@pytest.mark.parametrize("term,exp", [(0.0, 1.0), (0.0001, 0.5), (0.02, 0.5), (0.0201, 0.0)])
def test_terminal_bands(term, exp):
    assert parts(three(term=term))["terminal"] == exp


def test_terminal_and_dups_zero_when_not_serving():
    p = parts(three(err=0.0301, term=0.0, dups=0))
    assert p["terminal"] == 0.0 and p["duplicates"] == 0.0 and p["errors"] == 0.0


def test_terminal_and_dups_credited_at_serving_edge():
    p = parts(three(err=0.03, term=0.0, dups=0))
    assert p["terminal"] == 1.0 and p["duplicates"] == 1.0


def test_dups_nonzero_median():
    assert parts(three(dups=1))["duplicates"] == 0.0


def test_dups_median_zero_when_minority_dup():
    runs = [run(dups=5), run(), run()]
    assert parts(runs)["duplicates"] == 1.0


def test_policy_violation_majority_zeroes_errors_only():
    runs = [run(pol=True), run(pol=True), run()]
    r = rs.score_runs(runs)
    assert r["retry_policy_ok"] is False and r["parts"]["errors"] == 0.0
    assert r["parts"]["terminal"] == 1.0 and r["score"] == 0.6


def test_policy_violation_minority_ok():
    r = rs.score_runs([run(pol=True), run(), run()])
    assert r["retry_policy_ok"] is True and r["score"] == 1.0


def test_policy_tie_is_violation():
    r = rs.score_runs([run(pol=True), run()])
    assert r["retry_policy_ok"] is False


def test_fewer_than_two_ok_is_infra_error():
    for runs in ([run()], [run(), run(infra=True), run(infra=True)], []):
        r = rs.score_runs(runs)
        assert r["infra_error"] is True and r["score"] == 0.0


def test_infra_runs_excluded_from_median():
    r = rs.score_runs([run(err=0.9, infra=True), run(), run()])
    assert r["infra_error"] is False and r["runs_ok"] == 2 and r["score"] == 1.0


def test_gate_majority():
    two = lambda *rr: [run(label="2x", **k) for k in rr]
    assert rs.zero_dups_gate(two({}, {}, {}))
    assert rs.zero_dups_gate(two({}, {}, {"dups": 3}))
    assert not rs.zero_dups_gate(two({}, {"dups": 1}, {"dups": 1}))
    assert not rs.zero_dups_gate([])


def test_gate_error_edges():
    mk = lambda e: [run(label="2x", err=e) for _ in range(3)]
    assert rs.zero_dups_gate(mk(0.03))
    assert not rs.zero_dups_gate(mk(0.0301))


def test_gate_excludes_infra_runs():
    runs = [
        run(label="2x", infra=True, dups=9),
        run(label="2x", infra=True, dups=9),
        run(label="2x"),
    ]
    assert rs.zero_dups_gate(runs)  # 1 clean of 1 ok
    runs = [run(label="2x", infra=True), run(label="2x", infra=True), run(label="2x", dups=1)]
    assert not rs.zero_dups_gate(runs)
    assert not rs.zero_dups_gate([run(label="2x", infra=True)] * 3)


def test_gate_tie_fails():
    assert not rs.zero_dups_gate([run(label="2x"), run(label="2x", dups=1)])


def test_score_all_shape():
    out = rs.score_all([run(label="1x"), run(label="2x"), run(label="1x"), run(label="2x")])
    assert (
        set(out) == {"replay.1x", "replay.2x", "gate.zero_dups_2x"}
        and out["gate.zero_dups_2x"] is True
    )
