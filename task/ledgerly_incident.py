"""INC-2041: debug a production incident in Ledgerly under load.

    # grade a submission (no model): references, probes, the unmodified repo
    inspect eval task/ledgerly_incident.py --model mockllm/model -T submissions=probes/unmodified

    # run a frontier agent
    inspect eval task/ledgerly_incident.py --model openai/<id> -T solver=codex_cli

See PROJECT.md for the design and TASK_CARD.md for the grading.
"""

import sys
from pathlib import Path

TASK_DIR = Path(__file__).resolve().parent
REPO_ROOT = TASK_DIR.parent
sys.path.insert(0, str(TASK_DIR))

from grader.scorer import ledgerly_scorer
from grader.solvers import apply_submission
from inspect_ai import Task, task
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.solver import Solver
from inspect_ai.tool import bash, text_editor

PROMPT = (TASK_DIR / "prompt.md").read_text()
COMPOSE = TASK_DIR / "compose.yaml"
# Runs in the dev container after every service (including startup migrations) is healthy:
# the agent's session, and the audit window the grader judges, start here.
SESSION_SETUP = "date -u +%Y-%m-%dT%H:%M:%S.%3NZ > /var/lib/ledgerly/session_start"
AGENT_SYSTEM = (
    "You are the on-call engineer who just took over this incident. Work in /workspace/ledgerly. "
    "You have a shell; there is no internet access."
)


def _agent_solver(name: str, version: str) -> Solver:
    if name == "codex_cli":
        from inspect_swe import codex_cli

        return codex_cli(
            system_prompt=AGENT_SYSTEM,
            cwd="/workspace/ledgerly",
            user="dev",
            web_search="disabled",
            version=version or "auto",
        )
    if name == "claude_code":
        from inspect_swe import claude_code

        return claude_code(
            system_prompt=AGENT_SYSTEM,
            cwd="/workspace/ledgerly",
            user="dev",
            disallowed_tools=["WebSearch", "WebFetch"],
            version=version or "auto",
        )
    if name == "react":
        return react(
            prompt=AGENT_SYSTEM,
            tools=[bash(timeout=600, user="dev"), text_editor(user="dev")],
        )
    raise ValueError(f"unknown solver {name!r}; use apply, codex_cli, claude_code or react")


def _resolve(path: str) -> Path:
    """Submission dirs are relative to the repo root (Inspect runs tasks from task/)."""
    p = Path(path)
    p = p if p.is_absolute() else REPO_ROOT / p
    if not p.is_dir():
        raise FileNotFoundError(f"submission directory not found: {p}")
    return p.resolve()


@task
def ledgerly_incident(
    solver: str = "apply",
    submission: str = "",
    submissions: str | list[str] = "",
    replay_runs: int = 3,
    agent_version: str = "",
    time_limit: int = 3600,
) -> Task:
    """`submissions`: comma-separated submission dirs, one sample each (grading only)."""
    if solver == "apply":
        items = submissions.split(",") if isinstance(submissions, str) else submissions
        dirs = [s.strip() for s in items if s.strip()] or [submission]
        dataset = [
            Sample(
                id=f"{i:02d}-{Path(d).name if d else 'unmodified'}",
                input=PROMPT,
                setup=SESSION_SETUP,
                metadata={"submission_dir": str(_resolve(d)) if d else ""},
            )
            for i, d in enumerate(dirs, start=1)
        ]
        return Task(
            dataset=dataset,
            solver=apply_submission(),
            scorer=ledgerly_scorer(replay_runs),
            sandbox=("docker", str(COMPOSE)),
            fail_on_error=False,
        )
    return Task(
        dataset=[Sample(id="INC-2041", input=PROMPT, setup=SESSION_SETUP)],
        solver=_agent_solver(solver, agent_version),
        scorer=ledgerly_scorer(replay_runs),
        sandbox=("docker", str(COMPOSE)),
        time_limit=time_limit,
        fail_on_error=False,
    )
