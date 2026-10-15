# 2-minute video — script outline

Audience: people who build or buy RL environments and evals for coding agents. One idea: a grader you can trust, shown by watching it catch a fix that looks right. Then an honest look at what a frontier agent did with the task.

| Time | Screen | Voice-over (one or two sentences) |
|---|---|---|
| 0:00–0:15 | Title card, then `incident/INC-2041/` in a terminal: `jq` over `api.log.jsonl` showing 503s and timeouts | "A payments service went down under load, and some customers were charged twice. We hand a coding agent the on-call pager." |
| 0:15–0:35 | `make dev-up && make loadtest`: per-second lines, errors climbing, pending charges stuck; JSON summary (≈25% errors, ≈40% non-terminal) | "The incident reproduces on demand. Two bugs interact: unbounded retries inside a database transaction, and check-then-insert idempotency." |
| 0:35–0:55 | `probes/hack_bigger_pool/patch.diff` (pools 6 → 32), then `make grade SUBMISSION=probes/hack_bigger_pool`: replay rows red, duplicate gate failed, score 0.10 | "The classic masking fix: bigger connection pools. The grader replays hidden traffic at 1× and 2× from the fix's own end state, and it still collapses." |
| 0:55–1:20 | Browser: `qa/report.html`. Determinism 5/5 identical; 15/15 hack probes under 0.3 (highest 0.10); both references 1.0; 38/38 sources verified; the rubric row in red | "A QA kit proves the grader's properties instead of asserting them. Six of seven checks pass. The seventh, the LLM rubric's run-to-run variance, misses its strict bar by one flip in fifteen runs, and the report says so." |
| 1:20–1:50 | Inspect log viewer: the Codex run on gpt-5.5. Its first message ("two important tripwires…"), the `oncall ask` exchange, `make loadtest` with 0 errors, then the score card: 0.705, replay 1.00 / 1.00 | "A frontier agent fixed both bugs in seven minutes. Its first message names them, because the docs we wrote to make every check knowable also spelled out the answer. That tension is the main lesson, and FAILURE_MODES.md explains how a harder version would keep both." |
| 1:50–2:00 | Repo URL, log viewer URL | "Task, grader, QA kit and the run are open." |

Recording notes
- Pre-record `make loadtest` and `make grade`; speed up waits 4–8× and say so on screen.
- Use the published log viewer, not a local one, so the link in the description matches.
- Keep the terminal at 110 columns; large font.
