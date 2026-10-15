# Task card — INC-2041 (Ledgerly)

**Capability targeted:** debugging a production incident in a multi-service system under load, end to end: reproduce it, find two interacting root causes, fix them without breaking production rules, clean up the money damage the right way, and write it up.

**Environment:** Inspect AI task (`task/ledgerly_incident.py`), Docker Compose sandbox of 11 services. The agent works in `dev` (shell as user `dev`, the repo at `/workspace/ledgerly`, `psql`, `redis-cli`, `make loadtest`, `oncall`, `ledgerlyctl`). No internet, no Docker socket.

## Prompt

The full handoff is `task/prompt.md` (≈300 words). It states the incident, where the evidence is, the tools, the rule to consult on-call before risky actions, and four deliverables: fix the cause(s) so the service holds at the incident's load and at 2×, with one charge per Idempotency-Key and every charge reaching a terminal state; regression tests and a CHANGELOG entry; handle the existing damage; a postmortem from the template. It gives no hint about the root causes.

## Sources of difficulty

1. **Two interacting bugs.** Unbounded, immediate retries of processor timeouts inside a database transaction (holding the customer row lock), and check-then-insert idempotency without a unique constraint. The first also *hides* the second: while the system is collapsing, requests for locked customers fail instead of racing, so duplicates only become obvious after the storm is fixed.
2. **Faults only under load.** Single requests work. The agent must use the load test and the outage evidence.
3. **A red herring.** Redis memory climbs (the stream backlog) and never comes down (the stream is never trimmed). Changing Redis configuration is not a fix and can lose charges.
4. **Masking fixes look like progress.** Bigger pools, longer timeouts, more workers, disabling retries: each changes the symptoms; none survives the hidden 2× replay.
5. **Existing damage × schema constraint.** Duplicates already in the table make `CREATE UNIQUE INDEX CONCURRENTLY` fail until they are dealt with; they must be refunded through the API after approval, never deleted.
6. **Production rules revealed only by asking.** It is business hours: no Postgres restarts, no locking migrations. The agent learns this only by consulting on-call, as the prompt and runbook instruct.
7. **Two replicas.** Any process-local idempotency fix fails.
8. **Repo conventions.** Logging, settings and retries each have one home; schema changes need a new Alembic revision that doesn't lock busy tables.
9. **Deliverable completeness.** Tests, CHANGELOG and a postmortem that gets the mechanisms and the numbers right.

## Grading

Procedural first; an LLM only for the postmortem. Full design in PROJECT.md §6; every check, weight and knowability source in `task/grader/checks.py`.

| Component | Weight | How |
|---|---|---|
| Hidden replay 1× | 0.20 | Seeded traffic (incl. client retries and hedged double requests with the same key) replayed 3× from the agent's end-state DB, measured per key from the charge ids the client received and Paystream's captures. Errors: no success, a returned id with no row under that key, a failure Paystream wouldn't cause, a success without a matching capture. Duplicates: more than one id, row or capture per key. Medians against 1%/3% (errors), 0/2% (non-terminal) and 0 (duplicates); the last two only count while errors ≤ 3%. A run whose retries break the policy (> 10 requests per reference or > 30% retries, from Paystream's counts) gets no error credit. |
| Hidden replay 2× | 0.25 | Same at double the rate. |
| Hidden tests | 0.20 | Grader-owned, in a clean container, one process per test: concurrent same-key requests across two API processes (0.08); bounded retries (0.03); growing, jittered waits (0.03); retry budget (0.02); no row lock or open transaction during the processor call (0.04). |
| Conventions | 0.10 | New non-locking Alembic revision, new regression test, CHANGELOG entry, repo tests pass; −25% per violation (logger, settings, retry bypass, dependency change, edited old migration). |
| Damage | 0.10 | Exactly the duplicate set refunded through the refunds API (Paystream confirms), after on-call approved that count. |
| Communication | 0.05 | Policy consulted before the first DDL/restart; refund approval before the first refund. From timestamps, not an LLM. |
| Postmortem | 0.10 | LLM rubric, six binary anchored criteria (both mechanisms, exact duplicate count, timeline and action items, Redis as a symptom, no wrong cause), ground truth given to the grader, verbatim evidence quotes checked against the document and the criterion; majority of three judgments. |

**Gates** (any failure caps the score at 0.5): in a majority of 2× replays, zero duplicate keys while answering ≥ 97% of requests correctly; no Postgres restart; no locking migration on existing tables; no charge row deleted.

## Measured properties

See `QA_REPORT.md`: determinism, sanity bands, reward-hack probes, fairness across two different reference fixes, knowability of every check, rubric variance, interpretation probes.

## Frontier agent results

One valid run (Codex CLI on `gpt-5.5-2026-04-23`, 3M-token cap): **0.705**. In 7.4 minutes of agent time it fixed both bugs (perfect 1× and 2× replay, all gates passed), with non-locking migration, tests and on-call consulted. It missed retry backoff, jitter and budget, and the cap stopped it before refunds, CHANGELOG and postmortem. The docs that make every check knowable also name both mechanisms, so the task is easier than intended for this agent. Details and fixes in `FAILURE_MODES.md`.

## Known limitations

- The shell command log is bypassable; no score depends on it. Gates use server-side logs (Postgres, supervisors, on-call) and database state.
- The hidden tests import the agent's code, so a targeted attack on the test process is possible in principle. It runs as an unprivileged user with database roles scoped to throwaway databases, after everything else has been read; a tripwire voids the hidden tests if application code imports the test framework or patches the interpreter; the idempotency tests are double-checked against the database by the grader. The replay (0.45 plus a gate) measures what the client was told and what Paystream saw, so it can't be talked into a better result.
- Replay outcomes depend on timing. Thresholds are set from calibration with wide margins (docs/calibration.md), and runs are interleaved and medianed. Calibration was done on a 4-CPU / 6 GiB Docker VM; very different hardware needs recalibration.
- The on-call classifier uses an LLM when configured; its first answer for a question is cached, and a keyword classifier is the fallback. A question it misreads gets a generic answer that lists what it can help with.
- The rubric model (OpenAI `gpt-5.5-2026-04-23`, a reasoning model that ignores temperature and seed) is not deterministic on its own: each postmortem gets three judgments and a criterion counts on a majority, and verdicts are cached by content. The QA kit measures the variance that remains: over 5 runs each on three fixed postmortems, the references were identical and the weak postmortem flipped one criterion once (0.667 → 0.5), i.e. at most 0.017 of a run's total score. That exceeds the kit's strict limit (std ≤ 0.05 allows no flip), so the rubric check is reported as failing and accepted as a known limitation.
