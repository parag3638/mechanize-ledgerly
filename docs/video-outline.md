# 2-minute video — script outline

Audience: people who build or buy RL environments and evals for coding agents. One idea: a grader you can trust, shown by watching it catch a fix that looks right. Then an honest look at what a frontier agent did with the task.

| Time | Screen | Voice-over (one or two sentences) |
|---|---|---|
| 0:00–0:15 | Title card, then `incident/INC-2041/` in a terminal: `jq` over `api.log.jsonl` showing 503s and timeouts | "A payments service went down under load, and some customers were charged twice. We hand a coding agent the on-call pager." |
| 0:15–0:35 | `make dev-up && make loadtest`: per-second lines, errors climbing, pending charges stuck; JSON summary (≈25% errors, ≈40% non-terminal) | "The incident reproduces on demand. Two bugs interact: unbounded retries inside a database transaction, and an idempotency lock that expires while a slow request is still running." |
| 0:35–0:55 | `probes/hack_bigger_pool/patch.diff` (pools 6 → 32), then `make grade SUBMISSION=probes/hack_bigger_pool`: replay rows red, duplicate gate failed, score 0.10 | "The classic masking fix: bigger connection pools. The grader replays hidden traffic at 1× and 2× from the fix's own end state, and it still collapses." |
| 0:55–1:20 | Browser: `qa/report.html`. 7/7 checks green: determinism 5/5 identical; 15/15 hack probes under 0.3 (highest 0.08); two different reference fixes at 1.0; the retry-only partial capped at 0.5 although every replay is clean; 47/47 sources verified | "A QA kit proves the grader's properties instead of asserting them, including that the fix that cures the outage but not the latent race is caught, even though every replay looks perfect." |
| 1:20–1:50 | Inspect log viewer: v1 run (first message: "two important tripwires…", 0.705), then the v2 run (plan: "a Redis TTL cannot decide money semantics", 0.940) | "Version 1's docs gave the bugs away, so version 2 removed every hint and hid the race. The agent found it anyway, by code review, from what it already knows about good practice. That is the lesson: to be hard, a fault must look correct and be findable only by measurement." |
| 1:50–2:00 | Repo URL, log viewer URL | "Task, grader, QA kit and the runs are open." |

Recording notes
- Pre-record `make loadtest` and `make grade`; speed up waits 4–8× and say so on screen.
- Use the published log viewer, not a local one, so the link in the description matches.
- Keep the terminal at 110 columns; large font.
