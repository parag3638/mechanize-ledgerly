# Task card — INC-2041 (Ledgerly)

**Capability targeted:** debugging a production incident in a multi-service system under load, end to end: reproduce it, find two interacting root causes, fix them without breaking production rules, clean up the money damage the right way, and write it up.

**Environment:** Inspect AI task (`task/ledgerly_incident.py`), Docker Compose sandbox of 11 services. The agent works in `dev` (shell as user `dev`, the repo at `/workspace/ledgerly`, `psql`, `redis-cli`, `make loadtest`, `oncall`, `ledgerlyctl`). No internet, no Docker socket.

## Prompt

The full handoff is `task/prompt.md` (≈300 words). It states the incident, where the evidence is, the tools, the rule to consult on-call before risky actions, and four deliverables: fix the cause(s) so the service holds at the incident's load and at 2×, with one charge per Idempotency-Key and every charge reaching a terminal state; regression tests and a CHANGELOG entry; handle the existing damage; a postmortem from the template. It gives no hint about the root causes.

## Sources of difficulty

1. **Two interacting bugs, the second latent.**
   - **Bug 1:** unbounded, immediate retries of processor timeouts inside a database transaction that holds the customer row lock.
   - **Bug 2:** idempotency rests on a Redis lock (`SET NX PX 500`, released with a plain `DEL`) around the create-charge transaction. A first request that waits on the customer row for longer than the TTL loses the lock. The repeat takes the lock, can't see the uncommitted charge, and inserts a second one.
   - **The trap:** bug 1 triggers bug 2. Once the storm is fixed, requests are fast again and the load test shows no duplicates, but any slow request (a lock, a pause, a slow disk) still gets through. "The duplicates were just a symptom of the storm" is the natural wrong conclusion.
   - **What the docs say:** they state outcomes ("one key maps to one charge … however long the first request takes"; Redis is not authoritative), not mechanisms. A knowability audit fails if a mechanism phrase creeps back into the agent's repo.
2. **Faults only under load.** Single requests work. The agent must use the load test and the outage evidence.
3. **A red herring.** Redis memory climbs (the stream backlog) and never comes down (the stream is never trimmed). Changing Redis configuration is not a fix and can lose charges.
4. **Masking fixes look like progress.** Bigger pools, longer timeouts, more workers, disabling retries: each changes the symptoms; none survives the hidden 2× replay.
5. **Existing damage × schema constraint.** Duplicates already in the table make `CREATE UNIQUE INDEX CONCURRENTLY` fail until they are dealt with; they must be refunded through the API after approval, never deleted.
6. **Production rules revealed only by asking.** It is business hours: no Postgres restarts, no locking migrations. The agent learns this only by consulting on-call, as the prompt and runbook instruct.
7. **Two replicas and a non-authoritative Redis.** Any process-local idempotency fix fails. So does any fix that trusts Redis alone for the guarantee (it loses 0.05, not the gate).
8. **Repo conventions.** Logging, settings and retries each have one home; schema changes need a new Alembic revision that doesn't lock busy tables.
9. **Deliverable completeness.** Tests, CHANGELOG and a postmortem that gets the mechanisms and the numbers right.

## Grading

Procedural first; an LLM only for the postmortem. Full design in PROJECT.md §6; every check, weight and knowability source in `task/grader/checks.py`.

| Component | Weight | How |
|---|---|---|
| Hidden replay 1× | 0.20 | Seeded traffic (incl. client retries and hedged double requests with the same key) replayed 3× from the agent's end-state DB, measured per key from the charge ids the client received and Paystream's captures. Errors: no success, a returned id with no row under that key, a failure Paystream wouldn't cause, a success without a matching capture. Duplicates: more than one id, row or capture per key. Medians against 1%/3% (errors), 0/2% (non-terminal) and 0 (duplicates); the last two only count while errors ≤ 3%. A run whose retries break the policy (> 10 requests per reference or > 30% retries, from Paystream's counts) gets no error credit. |
| Hidden replay 2× | 0.25 | Same at double the rate. |
| Hidden tests | 0.20 | Grader-owned, in a clean container, one process per test, against two API processes:<br>- concurrent same-key requests (0.02);<br>- a repeat on the other replica while the first request is held on a locked customer row for 3 s, with sequencing driven by `pg_stat_activity` (0.04, also a gate);<br>- the same, with Redis emptied mid-request (0.05);<br>- bounded retries (0.03), growing jittered waits (0.03), retry budget (0.03).<br>"No transaction open during the processor call" is measured and reported but unscored; the replay scores its consequence. |
| Conventions | 0.10 | New non-locking Alembic revision, new regression test, CHANGELOG entry, repo tests pass; −25% per violation (logger, settings, retry bypass, dependency change, edited old migration). |
| Damage | 0.10 | Exactly the duplicate set refunded through the refunds API (Paystream confirms), after on-call approved that count. |
| Communication | 0.05 | Policy consulted before the first DDL/restart; refund approval before the first refund. From timestamps, not an LLM. |
| Postmortem | 0.10 | LLM rubric, six binary anchored criteria (both mechanisms, exact duplicate count, timeline and action items, Redis as a symptom, no wrong cause), ground truth given to the grader, verbatim evidence quotes checked against the document and the criterion; majority of three judgments. |

**Gates** (any failure caps the score at 0.5):
- in a majority of 2× replays, zero duplicate keys while answering ≥ 97% of requests correctly;
- a slow first request never yields a second charge (hidden test);
- no Postgres restart;
- no locking migration on existing tables;
- no charge row deleted.

## Measured properties

See `QA_REPORT.md`: determinism, sanity bands, reward-hack probes, fairness across two different reference fixes, knowability of every check, rubric variance, interpretation probes.

## Frontier agent results

Codex CLI on `gpt-5.5-2026-04-23`, one valid run per version (details in `FAILURE_MODES.md`):

| Version | Score | Agent time | What decided it |
|---|---|---|---|
| v1 | 0.705 | 7.4 min | Docs named both mechanisms; the 3M-token cap cut it off before refunds and the postmortem |
| v2 | 0.940 | 13.5 min | Found both bugs by code review from its own best-practice priors; finished every deliverable |

- **Missed in both runs:** retry backoff, jitter and budget (−0.06).
- **v2 is still easier than intended for this agent.** To be hard, a planted fault has to look correct under standard practice and be findable only empirically. FAILURE_MODES lists candidates.

## Known limitations

- The shell command log is bypassable; no score depends on it. Gates use server-side logs (Postgres, supervisors, on-call) and database state.
- The hidden tests import the agent's code, so a targeted attack on the test process is possible in principle. It runs as an unprivileged user with database roles scoped to throwaway databases, after everything else has been read; a tripwire voids the hidden tests if application code imports the test framework or patches the interpreter; the idempotency tests are double-checked against the database by the grader. The replay (0.45 plus a gate) measures what the client was told and what Paystream saw, so it can't be talked into a better result.
- Replay outcomes depend on timing. Thresholds are set from calibration with wide margins (docs/calibration.md), and runs are interleaved and medianed. Calibration was done on a 4-CPU / 6 GiB Docker VM; very different hardware needs recalibration.
- The on-call classifier uses an LLM when configured; its first answer for a question is cached, and a keyword classifier is the fallback. A question it misreads gets a generic answer that lists what it can help with.
- The rubric model (OpenAI `gpt-5.5-2026-04-23`, a reasoning model that ignores temperature and seed) is not deterministic on its own: each postmortem gets three judgments and a criterion counts on a majority, and verdicts are cached by content. In v2's QA, 5 runs on each of three fixed postmortems gave identical scores (std 0). v1 once flipped a single criterion in 15 runs.
- The incident has only 2 duplicate charges. With this bug, a duplicate needs a first request that waits longer than the 500 ms lock TTL yet finishes inside the 2 s statement timeout, which bug 1's collapse rarely allows (docs/calibration.md). Grading of the bug doesn't depend on the count.
