# Ledgerly Incident

A realistic task for coding agents: take over a production incident in a payments service, find out why it falls over under load and why customers were charged twice, fix it without breaking production rules, clean up the damage, and write the postmortem. It comes with a grader that is deterministic, fair, knowable and hard to game, a QA kit that proves those properties, and a failure-mode report from a frontier-agent run. The task was built to be hard; the first frontier run showed it isn't hard enough yet, and why (see Results).

Independent portfolio work in the style of Mechanize's public writing; not affiliated with Mechanize.

## What it tests

Debugging distributed systems under production load is still a weak spot for coding agents. This task needs several things at once:

- reproducing a fault that only appears under load, from logs, metrics and a load generator;
- finding **two interacting root causes**: unbounded retries inside a database transaction, and check-then-insert idempotency; the first hides the second;
- ignoring a convincing red herring (Redis memory);
- fixing it the way the repo and production allow: shared modules, new migrations that don't lock busy tables, no database restart during business hours, which the agent learns by asking a simulated on-call;
- refunding the duplicate charges already in the database through the API, after approval, without deleting anything;
- writing a postmortem that gets the mechanisms and the numbers right.

`TASK_CARD.md` has the prompt, the difficulty sources, the grading and its known limitations. `PROJECT.md` has the full design; `DECISIONS.md` records every design choice.

## Run it

Requirements: Docker (tested on Colima, 4 CPU / 6 GiB), [uv](https://docs.astral.sh/uv/), Python 3.12. Optional `.env` (see `.env.example`): `OPENAI_API_KEY` with `RUBRIC_MODEL` and `ONCALL_MODEL` for the postmortem rubric and the on-call classifier (without them the rubric is skipped and on-call uses keyword rules), the agent model for `make runs`, and `LEDGERLY_REFS_PASSPHRASE` to decrypt the references (`make refs-decrypt`).

```
uv sync
make build                          # build the 11 service images
make task                           # grade the unmodified repo (expect a score near 0), ~12 min
make grade SUBMISSION=probes/hack_bigger_pool   # grade any submission (patch.diff + actions.sh)
make qa                             # the full QA kit -> QA_REPORT.md, qa/report.html (hours)
make runs AGENT=codex_cli N=1 TOKEN_LIMIT=3000000 AGENT_MODEL=openai/<id>   # capped frontier agent run
make view                           # Inspect log viewer
```

To poke at the system yourself: `make dev-up`, then `make loadtest` (reproduces the incident in about a minute) or `make dev-shell` (the agent's shell). `make dev-down` cleans up.

## Layout

| Path | What | Seen by the agent |
|---|---|---|
| `ledgerly/` | The service: FastAPI API, Redis Streams worker, Alembic migrations, tests, docs, incident evidence | yes (as `/workspace/ledgerly`) |
| `task/` | Inspect task, compose sandbox, images, mock processor, on-call, grader, hidden tests and profiles | no |
| `taskqa/` | The grader QA kit | no |
| `probes/` | Reward-hack probe submissions | no |
| `references.tar.age` | Two reference fixes and reference-derived probes, encrypted | no |

## Results

**Grader QA, v2** (`QA_REPORT.md`, [HTML report](https://parag3638.github.io/mechanize-ledgerly/qa/report.html)): all 7 checks pass.
- Determinism: 5 gradings identical.
- Reward-hack probes: 15 of 15 under 0.3 (highest 0.08).
- References: two different correct fixes both score 1.0.
- Partial fixes: in their bands and in increasing order. The fix that cures the retry storm but not the lock replays perfectly and is still capped at 0.5 by the slow-request test.
- Knowability: 47 of 47 sources found, and the hint audit is clean.
- Interpretation probes: 3 of 3 keep their credit.
- Rubric variance: 0 across 5 runs.

**Frontier run on v1** (`FAILURE_MODES.md`, [transcript in the Inspect log viewer](https://parag3638.github.io/mechanize-ledgerly/)): Codex CLI on `gpt-5.5` scored **0.705**. In 7.4 minutes of agent time it fixed both bugs (perfect replay at 1× and 2×, all gates passed), then hit its 3M-token cap before refunds and the postmortem. The docs that make every check knowable also spell out both mechanisms. That is the report's main finding. **v2** acts on it: the docs now state outcomes instead of mechanisms, and bug 2 is a latent Redis-lock race that the load test can't show once bug 1 is fixed. A frontier run on v2 is pending.
