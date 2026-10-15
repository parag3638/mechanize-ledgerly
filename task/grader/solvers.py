"""Solvers (host side).

apply_submission: replays a submission (patch.diff + optional actions.sh) in the
dev container as the agent's user, so references, probes and real agent runs
are graded by exactly the same scorer.
"""

import asyncio
from pathlib import Path
from typing import Any

from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox

REPO = "/workspace/ledgerly"


@solver
def apply_submission(default_dir: str = "") -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        sub = state.metadata.get("submission_dir") or default_dir
        report: dict[str, Any] = {"submission": sub or "(none: unmodified repo)"}
        if sub:
            d = Path(sub)
            patch = d / "patch.diff"
            if patch.exists() and patch.read_text().strip():
                await sandbox().write_file("/tmp/submission/patch.diff", patch.read_text())
                res = await sandbox().exec(
                    ["git", "apply", "--whitespace=nowarn", "/tmp/submission/patch.diff"],
                    cwd=REPO,
                    user="dev",
                )
                report["patch"] = {"ok": res.success, "stderr": res.stderr[-2000:]}
            actions = d / "actions.sh"
            if actions.exists():
                await sandbox().write_file("/tmp/submission/actions.sh", actions.read_text())
                res = await sandbox().exec(
                    ["bash", "/tmp/submission/actions.sh"],
                    cwd=REPO,
                    user="dev",
                    timeout=1200,
                    timeout_retry=False,
                )
                report["actions"] = {
                    "ok": res.success,
                    "returncode": res.returncode,
                    "stdout": res.stdout[-6000:],
                    "stderr": res.stderr[-3000:],
                }
        await asyncio.sleep(6)  # let the API and worker reload the new code
        state.metadata["submission_report"] = report
        return state

    return solve
