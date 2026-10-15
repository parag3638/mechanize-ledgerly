"""The Inspect scorer (host side). Same code path for agent runs and `make grade`.

1. Read the agent's session start from the dev container.
2. Run the procedural grader in the `grader` service (it can reach every service;
   the agent never could) and read its result file.
3. Judge the postmortem with the rubric.
4. Aggregate into Score.value (a flat dict, every component visible).
"""

import json
from pathlib import Path
from typing import Any

from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import TaskState
from inspect_ai.util import sandbox

from grader import aggregate, rubric

FACTS = json.loads(
    (Path(__file__).resolve().parents[1] / "hidden" / "baseline_facts.json").read_text()
)
RESULT_PATH = "/grader/out/result.json"


def _trim(result: dict[str, Any]) -> dict[str, Any]:
    """Kept whole (incl. the postmortem text) so the rubric can be re-run from the log."""
    return dict(result)


@scorer(metrics={"*": [mean()]})
def ledgerly_scorer(replay_runs: int = 3):
    async def score(state: TaskState, target: Target) -> Score:
        session_start = (await sandbox().read_file("/var/lib/ledgerly/session_start")).strip()
        # Nothing the agent left running (background jobs, watchers) may touch the stack while we grade.
        await sandbox().exec(["pkill", "-9", "-u", "dev"], timeout=30)
        run = await sandbox("grader").exec(
            [
                "python",
                "-m",
                "grader.run",
                "--since",
                session_start,
                "--out",
                RESULT_PATH,
                "--replay-runs",
                str(replay_runs),
            ],
            cwd="/grader",
            timeout=1750,
            timeout_retry=False,
        )
        try:
            result = json.loads(await sandbox("grader").read_file(RESULT_PATH))
        except Exception as exc:  # noqa: BLE001 - grader crashed: unscored, with the reason
            return Score(
                value={"score": 0.0, "infra_error": True},
                explanation=f"grader failed: {exc}\n{run.stderr[-2000:]}",
            )
        postmortem = (result.get("postmortem") or {}).get("text", "")
        verdict = await rubric.score_postmortem(postmortem, FACTS)
        agg = aggregate.score(result, verdict)
        try:
            shell_log = await sandbox().read_file("/var/log/ledgerly-shell/commands.log")
        except Exception:  # noqa: BLE001
            shell_log = ""
        return Score(
            value=agg["value"],
            answer=(result.get("postmortem") or {}).get("path"),
            explanation=aggregate.explanation(agg),
            metadata={
                "checks": agg["checks"],
                "violations": agg["violations"],
                "gates": agg["gates"],
                "rubric": verdict,
                "grader": _trim(result),
                "shell_commands": shell_log[-20_000:],
            },
        )

    return score
